"""Edit a deck and write it back, for design loops and DOE variants.

Every edit changes only the fields it names, in their own format (fixed,
long or comma), and leaves every other line, comment and include file
as it was; `Deck.write` writes the files back. Typical edits:

- `set_parameter`: a ``*PARAMETER`` value (the usual way a DOE variable
  enters a deck);
- `set_thickness`, `set_material`, `set_section`: a part's properties
  (a section shared with other parts is changed for all of them, or
  copied for this part only);
- `set_end_time`, `set_mass_scaling`, `set_initial_velocity`;
- `set_output`, `add_history_nodes`, `prepare_outputs` (adds what
  `crashmetrics.deck.output_requirements` finds missing).

`write_variants` writes one deck per row of a design (for example from
`crashmetrics.doe.latin_hypercube`), each read fresh from the original
files, with a CSV of the values.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from crashmetrics.deck._fields import format_value, replace_field
from crashmetrics.deck.bulk import record_id
from crashmetrics.deck.cards import Record
from crashmetrics.deck.loadcase import load_case, output_requirements
from crashmetrics.deck.reader import Block, Deck, read_deck

__all__ = [
    "add_history_nodes",
    "part_card",
    "prepare_outputs",
    "set_end_time",
    "set_initial_velocity",
    "set_mass_scaling",
    "set_material",
    "set_output",
    "set_parameter",
    "set_section",
    "set_thickness",
    "write_variants",
]


def _f(v: float, width: int = 10) -> str:
    return format_value(v, width, "f")


def _i(v: int, width: int = 10) -> str:
    return format_value(v, width, "i")


def set_parameter(deck: Deck, name: str, value: float | int | str) -> None:
    """Change a ``*PARAMETER`` value (or an expression's text, given as a
    string); fields that use it read the new value."""
    key = name.lower().lstrip("&")
    p = deck.parameters.get(key)
    if p is None:
        locals_ = [q for (_, n), q in deck.local_parameters.items() if n == key]
        if len(locals_) != 1:
            raise KeyError(
                f"Parameter {name!r} is not defined"
                + (" (or defined locally in several files)" if locals_ else "")
                + f"; defined: {sorted(deck.parameters)[:20]}."
            )
        p = locals_[0]
    if p.slot is None:
        raise ValueError(f"Parameter {name!r} cannot be edited.")
    line_no, slot = p.slot
    if p.expression:
        if not isinstance(value, str):
            raise ValueError(
                f"{name} is an expression ({p.expression!r}); give the new "
                "expression as text."
            )
        text = value.ljust(slot.width) if not slot.comma else value
    else:
        kind = {"I": "i", "C": "s", "R": "f"}[p.kind]
        text = format_value(value, slot.width if not slot.comma else 20, kind)
    p.block.set_line(line_no, replace_field(p.block.lines[line_no], slot, text))
    deck.refresh()


def part_card(deck: Deck, part: int) -> Record:
    """The ``*PART`` record of a part ID."""
    for r in deck.records("PART*"):
        if (
            r.block.family in ("PART", "PART_COMPOSITE")
            and record_id(r, "pid", "part") == part
        ):
            return r
    raise KeyError(f"No *PART {part}.")


def _section(deck: Deck, secid: int) -> Record:
    for r in deck.records("SECTION_*"):
        if record_id(r, "secid", "section") == secid:
            return r
    raise KeyError(f"No section {secid}.")


def _users(deck: Deck, secid: int) -> list[int]:
    return [
        record_id(r, "pid", "part")
        for r in deck.records("PART*")
        if r.block.family == "PART" and record_id(r, "secid", "section") == secid
    ]


def set_thickness(
    deck: Deck, part: int, thickness: float, *, shared: str = "error"
) -> int:
    """Set the shell thickness of a part (T1 to T4 of its
    ``*SECTION_SHELL``). If other parts use the section: ``shared="error"``
    raises, ``"all"`` changes it for all of them, ``"copy"`` gives this
    part its own copy of the section (a new section ID, returned)."""
    pr = part_card(deck, part)
    secid = record_id(pr, "secid", "section")
    sec = _section(deck, secid)
    if sec.block.subtype != "SHELL":
        raise ValueError(
            f"Part {part} has a *SECTION_{sec.block.subtype}, not a shell section."
        )
    others = [p for p in _users(deck, secid) if p != part]
    if others and shared == "error":
        raise ValueError(
            f"Section {secid} is also used by parts {others[:10]}; pass "
            "shared='all' or shared='copy'."
        )
    if others and shared == "copy":
        new_id = (
            max(record_id(r, "secid", "section") for r in deck.records("SECTION_*")) + 1
        )
        new_id -= secid - sec.get("secid")  # file's own numbering
        lines = list(sec.block.lines)
        block = sec.block.file.insert("\n".join(lines), before=None)
        rec = block.records()[sec.index]
        rec.set("secid", new_id)
        for k in ("t1", "t2", "t3", "t4"):
            rec.set(k, thickness)
        part_card(deck, part).set("secid", new_id)
        return int(record_id(rec, "secid", "section"))
    if shared not in ("error", "all", "copy"):
        raise ValueError("shared must be 'error', 'all' or 'copy'.")
    for k in ("t1", "t2", "t3", "t4"):
        _section(deck, secid).set(k, thickness)
    return secid


def set_material(deck: Deck, part: int, material: int) -> None:
    """Give a part another material (the material must exist)."""
    if not any(
        record_id(r, "mid", "material") == material
        for r in deck.records("MAT_*")
        if r.block.family == "MAT"
    ):
        raise KeyError(f"No material {material}.")
    pr = part_card(deck, part)
    pr.set("mid", material - (record_id(pr, "mid", "material") - pr.get("mid", 0)))


def set_section(deck: Deck, part: int, section: int) -> None:
    """Give a part another section (the section must exist)."""
    _section(deck, section)
    pr = part_card(deck, part)
    pr.set("secid", section - (record_id(pr, "secid", "section") - pr.get("secid", 0)))


def _single(deck: Deck, keyword: str, fields: str, values: Mapping[str, Any]) -> Record:
    """The record of a single control keyword, added to the main file if
    the deck has none."""
    recs = list(deck.records(keyword))
    if recs:
        return recs[0]
    names = fields.split()
    line = "".join(
        _f(values.get(n, 0.0)) if not n.endswith(":i") else _i(values.get(n[:-2], 0))
        for n in names
    )
    block = deck.main.insert(f"*{keyword}\n{line}")
    return block.records()[0]


def set_end_time(deck: Deck, end_time: float) -> None:
    """``*CONTROL_TERMINATION`` ENDTIM (model time units; added if missing)."""
    r = _single(deck, "CONTROL_TERMINATION", "endtim", {"endtim": end_time})
    r.set("endtim", end_time)


def set_mass_scaling(deck: Deck, dt2ms: float, tssfac: float | None = None) -> None:
    """``*CONTROL_TIMESTEP`` DT2MS (negative: mass added only where the
    time step is below TSSFAC x |DT2MS|) and optionally TSSFAC."""
    r = _single(deck, "CONTROL_TIMESTEP", "dtinit tssfac", {"tssfac": tssfac or 0.9})
    r.set("dt2ms", dt2ms)
    if tssfac is not None:
        r.set("tssfac", tssfac)


def set_initial_velocity(
    deck: Deck,
    velocity: Sequence[float] | None = None,
    *,
    speed: float | None = None,
    which: int | None = None,
) -> int:
    """Set the initial velocity of ``*INITIAL_VELOCITY_GENERATION``,
    ``*INITIAL_VELOCITY`` or ``*INITIAL_VELOCITY_RIGID_BODY`` cards: the
    components, or only the ``speed`` (model units) in the same direction.
    ``which``: index of the card (all cards by default). Returns the
    number of cards changed."""
    if (velocity is None) == (speed is None):
        raise ValueError("Give velocity or speed.")
    recs = [r for r in deck.records("INITIAL_VELOCITY*") if "vx" in r]
    if which is not None:
        recs = [recs[which]]
    if not recs:
        raise KeyError("The deck has no initial velocity card.")
    for r in recs:
        if velocity is not None:
            new = list(velocity)
        else:
            v = [r.get("vx", 0.0), r.get("vy", 0.0), r.get("vz", 0.0)]
            n = math.sqrt(sum(x * x for x in v))
            if n == 0:
                raise ValueError(
                    f"{r.block.where()}: the velocity is zero, give the components."
                )
            new = [x / n * speed for x in v]  # type: ignore[operator]
        for k, x in zip(("vx", "vy", "vz"), new):
            r.set(k, x)
    return len(recs)


def set_output(deck: Deck, name: str, dt: float, *, binary: int | None = None) -> Block:
    """Write an ASCII output (``GLSTAT``, ``NODOUT`` ...) every ``dt``
    (model time units); ``binary`` 1 ASCII, 2 binout, 3 both. Added to
    the main file if missing."""
    key = name.upper().replace("*DATABASE_", "")
    for b in deck.find(f"DATABASE_{key}"):
        r = b.records()[0]
        r.set("dt", dt)
        if binary is not None:
            r.set("binary", binary)
        return b
    line = _f(dt) + (_i(binary) if binary is not None else "")
    return deck.main.insert(f"*DATABASE_{key}\n{line}")


def add_history_nodes(deck: Deck, nodes: Iterable[int]) -> Block:
    """Add a ``*DATABASE_HISTORY_NODE`` with these nodes (to the main file)."""
    ids = [int(n) for n in nodes]
    if not ids:
        raise ValueError("Give at least one node.")
    lines = ["".join(_i(n) for n in ids[i : i + 8]) for i in range(0, len(ids), 8)]
    return deck.main.insert("*DATABASE_HISTORY_NODE\n" + "\n".join(lines))


def prepare_outputs(
    deck: Deck,
    analyses: Sequence[str],
    dt: float,
    *,
    node_dt: float | None = None,
    energy: bool = True,
    unit_system: str | None = None,
) -> list[str]:
    """Add the outputs and energy settings `output_requirements` finds
    missing for these analyses (every ``dt``; nodout every ``node_dt``,
    model time units). Cross sections and history nodes are not made up;
    they stay as findings. Returns what was changed."""
    sheet = output_requirements(deck, analyses, unit_system=unit_system)
    done: list[str] = []
    for c in sheet.checks:
        if c.status == "PASS":
            continue
        name = c.name.split()[0].upper()
        if c.name == "control_energy" or c.name.startswith("control_energy"):
            if energy:
                r = _single(
                    deck,
                    "CONTROL_ENERGY",
                    "hgen:i rwen:i slnten:i rylen:i",
                    {"hgen": 2, "rwen": 2, "slnten": 2, "rylen": 2},
                )
                for k in ("hgen", "rwen", "slnten"):
                    if r.get(k) != 2:
                        r.set(k, 2)
                done.append("CONTROL_ENERGY: HGEN, RWEN, SLNTEN 2")
        elif name == "NODOUT" and "sampling" in c.name:
            if node_dt is not None:
                set_output(deck, "NODOUT", node_dt)
                done.append(f"NODOUT every {node_dt:g}")
        elif c.status == "FAIL" and name in (
            "GLSTAT",
            "MATSUM",
            "SLEOUT",
            "SECFORC",
            "SWFORC",
            "NODOUT",
            "RCFORC",
            "RWFORC",
        ):
            interval = node_dt if (name == "NODOUT" and node_dt) else dt
            set_output(deck, name, interval, binary=1 if name else None)
            done.append(f"{name} every {interval:g}")
        elif c.status == "WARN" and "binout only" in c.value:
            set_output(
                deck,
                name,
                next(o.dt for o in load_case(deck).outputs.values() if o.name == name),
                binary=3,
            )
            done.append(f"{name}: BINARY 3")
    return list(dict.fromkeys(done))


def write_variants(
    deck: Deck | str | Path,
    design: Any,
    folder: str | Path,
    *,
    setters: Mapping[str, Callable[[Deck, float], None]] | None = None,
    name: str = "run_{:03d}",
) -> Path:
    """One deck per design row in ``folder/run_001``, ``run_002`` ...

    ``design``: a `crashmetrics.doe.Design` or (names, rows). A variable
    with a setter in ``setters`` (``lambda deck, value: ...``) is applied
    with it, any other must be a ``*PARAMETER`` of the deck. Each variant
    is read fresh from the original files. Writes ``design.csv`` (run
    folder and values) and returns its path.
    """
    source = deck.main.path if isinstance(deck, Deck) else Path(deck)
    if isinstance(deck, Deck) and any(f.modified for f in deck.files):
        raise ValueError(
            "The deck has unsaved edits; write it first, or give the path."
        )
    names, rows = (design.names, design.values) if hasattr(design, "names") else design
    names = list(names)
    setters = dict(setters or {})
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    table = out / "design.csv"
    with open(table, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["run", *names])
        for i, row in enumerate(rows, 1):
            d = read_deck(source)
            for var, value in zip(names, row):
                if var in setters:
                    setters[var](d, float(value))
                else:
                    set_parameter(d, var, float(value))
            run = name.format(i)
            d.write(out / run)
            w.writerow([run, *[f"{float(v):.10g}" for v in row]])
    return table
