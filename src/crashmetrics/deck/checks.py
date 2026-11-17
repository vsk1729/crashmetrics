"""Deck checks before a run: references, duplicates, coverage.

`check_deck` reads a deck once and gives a sheet of checks, each PASS,
FAIL, WARN or INFO, with the items concerned and where they are:

- **Reading**: include files not found or circular, parameters used but
  not defined, fields that could not be read.
- **IDs**: duplicate IDs (nodes, elements of each kind, parts, sections,
  materials, sets, curves ...), including clashes between include files.
- **References**: every ID a card refers to exists (elements to parts and
  nodes, parts to sections, materials and hourglass cards, sets to their
  members, contacts to their sets or parts, outputs, boundary
  conditions, initial velocities and loads to theirs, materials to their
  curves).
- **Model**: parts without elements, shells without thickness, parts
  without density, degenerate elements, nodes not used by anything.
- **Contacts and welds**: deformable parts in no contact; spot weld
  elements without a tied or spot weld contact.
- **Time step**: the smallest estimated time step, and the mass that
  mass scaling would add (`crashmetrics.deck.model.time_steps`).
- **Unused**: sections, materials, curves and sets nothing refers to;
  keywords not interpreted here (kept unchanged).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from crashmetrics.deck.bulk import (
    _file_offset,
    curves,
    elements,
    mass_elements,
    nodes,
    record_id,
    sets,
)
from crashmetrics.deck.cards import Record, references
from crashmetrics.deck.model import (
    UNIT_SYSTEMS,
    _materials,
    _parts,
    _shell_geometry,
    _solid_geometry,
    model_summary,
    time_steps,
)
from crashmetrics.deck.reader import Deck

__all__ = ["DeckCheck", "DeckSheet", "check_deck"]

_ICON = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "INFO": "ℹ️"}

_SURFACE = {
    0: "set_segment",
    1: "set_shell",
    2: "set_part",
    3: "part",
    4: "set_node",
    6: "set_part",
}
"""Contact SSTYP / MSTYP -> what SSID / MSID is (5: all parts)."""
_IVG = {1: "set_part", 2: "part", 3: "set_node"}

_NAMES = {
    "node": "nodes",
    "shell": "shell elements",
    "solid": "solid elements",
    "beam": "beam elements",
    "tshell": "thick shells",
    "discrete": "discrete elements",
    "seatbelt": "seatbelt elements",
    "part": "parts",
    "section": "sections",
    "material": "materials",
    "eos": "equations of state",
    "hourglass": "hourglass cards",
    "curve": "curves and tables",
    "coord": "coordinate systems",
    "vector": "vectors",
    "box": "boxes",
    "transform": "transformations",
    "contact": "contacts",
    "thmat": "thermal materials",
}


def _name(ns: str) -> str:
    if ns.startswith("set_"):
        return f"{ns[4:]} sets"
    return _NAMES.get(ns, ns)


@dataclass(frozen=True)
class DeckCheck:
    group: str
    name: str
    status: str
    """``PASS``, ``FAIL``, ``WARN`` or ``INFO``."""
    value: str
    items: tuple[str, ...] = ()
    """The items concerned, with where they are (file:line)."""

    def line(self, max_items: int = 5) -> str:
        head = (
            f"{_ICON[self.status]} {self.status:4} {self.group} / {self.name}: "
            f"{self.value}"
        )
        more = [f"      {x}" for x in self.items[:max_items]]
        if len(self.items) > max_items:
            more.append(f"      ... {len(self.items) - max_items} more")
        return "\n".join([head] + more)


@dataclass(frozen=True)
class DeckSheet:
    deck: str
    checks: tuple[DeckCheck, ...]

    @property
    def failures(self) -> tuple[DeckCheck, ...]:
        return tuple(c for c in self.checks if c.status == "FAIL")

    @property
    def warnings(self) -> tuple[DeckCheck, ...]:
        return tuple(c for c in self.checks if c.status == "WARN")

    @property
    def passed(self) -> bool:
        return not self.failures

    def summary(self, max_items: int = 5, show_pass: bool = False) -> str:
        n = {s: sum(c.status == s for c in self.checks) for s in _ICON}
        head = (
            f"{self.deck}: {'PASSED' if self.passed else 'FAILED'} "
            f"({n['FAIL']} failed, {n['WARN']} warnings, {n['PASS']} passed, "
            f"{n['INFO']} info)"
        )
        body = [
            c.line(max_items) for c in self.checks if show_pass or c.status != "PASS"
        ]
        return "\n".join([head] + body)

    def table(self) -> str:
        lines = ["| | Group | Check | Result |", "| --- | --- | --- | --- |"]
        for c in self.checks:
            items = "; ".join(c.items[:3]) + (" ..." if len(c.items) > 3 else "")
            lines.append(
                f"| {_ICON[c.status]} | {c.group} | {c.name} | {c.value}"
                + (f" ({items})" if items else "")
                + " |"
            )
        return "\n".join(lines)


# --- Index of IDs -------------------------------------------------------------


class _Index:
    def __init__(self) -> None:
        self.defs: dict[str, dict[int, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self.refs: dict[str, dict[int, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )

    def define(self, ns: str, i: int, where: str) -> None:
        self.defs[ns][int(i)].append(where)

    def refer(self, ns: str, i: int, where: str) -> None:
        if ns and int(i) > 0:
            self.refs[ns][int(i)].append(where)


def _index(deck: Deck) -> _Index:
    ix = _Index()
    nd = nodes(deck)
    for i, f in zip(nd.ids.tolist(), nd.files):
        ix.define("node", i, f)
    for kind, e in elements(deck).items():
        for eid, pid, ns, f in zip(
            e.ids.tolist(), e.parts.tolist(), e.nodes.tolist(), e.files
        ):
            ix.define(kind, eid, f)
            ix.refer("part", pid, f"{kind} {eid} ({f})")
            for n in ns:
                if n:
                    ix.refer("node", n, f"{kind} {eid} ({f})")
    for (kind, sid), s in sets(deck).items():
        for w in s.where.split("; "):
            ix.define("set_" + kind, sid, w)
        member = "node" if kind == "segment" else kind
        for m in s.members if not s.add else []:
            ix.refer(member, m, f"{kind} set {sid} ({s.where.split('; ')[0]})")
        for a in s.add:
            ix.refer("set_" + kind, a, f"{kind} set {sid} ({s.where})")
    for kind, sid, where in deck.cache.get("set_duplicates", []):
        ix.defs["set_" + kind][sid] = sorted(set(ix.defs["set_" + kind][sid] + [where]))
    for cid, c in curves(deck).items():
        ix.define("curve", cid, c.where)
    for cid, where in deck.cache.get("curve_duplicates", []):
        ix.define("curve", cid, where)
    for me in mass_elements(deck):
        if me.kind == "node":
            ix.refer("node", me.target, f"mass element {me.id} ({me.where})")
        elif me.kind == "node_set":
            ix.refer("set_node", me.target, f"mass element {me.id} ({me.where})")
        elif me.kind in ("part", "part_set"):
            ix.refer(
                "part" if me.kind == "part" else "set_part",
                me.target,
                f"*ELEMENT_MASS_PART ({me.where})",
            )
    for b in deck.blocks:
        if b.spec is None:
            continue
        sp = b.spec
        for rec in b.records():
            where = b.where(rec.title_line if rec.title_line > 0 else 0)
            ns, key = sp.defines
            if ns and key in rec:
                ix.define(ns, record_id(rec, key, ns), where)
            for fname, ref in references(sp):
                if fname in rec and ref:
                    ix.refer(ref, record_id(rec, fname, ref), f"*{b.keyword} ({where})")
            for row in rec.rows:
                for rf in sp.rows:
                    if rf.ref and rf.name in row and row[rf.name]:
                        ix.refer(
                            rf.ref,
                            int(row[rf.name]) + _file_offset(b.file, rf.ref),
                            f"*{b.keyword} ({where})",
                        )
            _dynamic(ix, b.family, b.subtype, rec, where)
    return ix


def _dynamic(ix: _Index, family: str, subtype: str, rec: Record, where: str) -> None:
    kw = f"*{rec.block.keyword} ({where})"
    if family == "CONTACT":
        for side in ("s", "m"):
            typ = int(rec.get(f"{side}styp", 0))
            i = int(rec.get(f"{side}sid", 0))
            ns = _SURFACE.get(typ)
            if ns and i > 0:
                ix.refer(ns, i + _file_offset(rec.block.file, ns), kw)
    elif family == "INITIAL" and subtype == "VELOCITY_GENERATION":
        ns = _IVG.get(int(rec.get("styp", 0)))
        if ns and rec.get("id", 0) > 0:
            ix.refer(ns, record_id(rec, "id", ns), kw)


# --- Checks -------------------------------------------------------------------


def _items(d: dict[int, list[str]], limit: int = 50) -> tuple[str, ...]:
    out = []
    for i, where in list(d.items())[:limit]:
        w = sorted(set(where))
        out.append(
            f"{i}: {', '.join(w[:3])}" + (f" (+{len(w) - 3})" if len(w) > 3 else "")
        )
    return tuple(out)


def check_deck(
    deck: Deck, *, unit_system: str | None = None, mass_scaling_limit: float = 5.0
) -> DeckSheet:
    """Check a deck before running it (see the module notes).

    ``mass_scaling_limit``: added mass that mass scaling would add, % of
    the model mass, above which the time step check warns.
    """
    checks: list[DeckCheck] = []
    add = checks.append

    # Reading
    ix = _index(deck)
    notes = list(dict.fromkeys(deck.notes))
    inc = [
        n
        for n in notes
        if "include" in n.lower() and ("not found" in n or "circular" in n)
    ]
    par = [
        n
        for n in notes
        if "parameter" in n and ("not defined" in n or "undefined" in n)
    ]
    other = [n for n in notes if n not in inc and n not in par]
    add(
        DeckCheck(
            "Reading",
            "Include files",
            "FAIL" if inc else "PASS",
            f"{len(deck.files)} files read" + (f", {len(inc)} problems" if inc else ""),
            tuple(inc),
        )
    )
    add(
        DeckCheck(
            "Reading",
            "Parameters",
            "FAIL" if par else "PASS",
            f"{len(deck.parameters) + len(deck.local_parameters)} defined"
            + (f", {len(par)} problems" if par else ""),
            tuple(par),
        )
    )
    if other:
        add(
            DeckCheck(
                "Reading", "Other reading notes", "WARN", f"{len(other)}", tuple(other)
            )
        )

    # Duplicates
    dups = []
    for ns, d in ix.defs.items():
        multi = {i: w for i, w in d.items() if len(w) > 1}
        if multi:
            dups.append(
                DeckCheck(
                    "IDs",
                    f"Duplicate {_name(ns)}",
                    "FAIL",
                    f"{len(multi)} IDs defined more than once",
                    _items(multi),
                )
            )
    checks.extend(dups or [DeckCheck("IDs", "Duplicate IDs", "PASS", "none")])

    # Missing references
    missing = []
    for ns, d in ix.refs.items():
        known = ix.defs.get(ns, {})
        miss = {i: w for i, w in d.items() if i not in known}
        if ns.startswith("set_") and miss:  # unresolved set kinds are known
            miss = {i: w for i, w in miss.items() if (ns[4:], i) not in sets(deck)}
        if miss:
            missing.append(
                DeckCheck(
                    "References",
                    f"Missing {_name(ns)}",
                    "FAIL",
                    f"{len(miss)} IDs referred to but not defined",
                    _items(miss),
                )
            )
    checks.extend(
        missing
        or [
            DeckCheck(
                "References", "All references", "PASS", "every referred ID is defined"
            )
        ]
    )

    # Model
    summary = model_summary(deck, unit_system)
    no_el = [p for p in summary.parts if not p.elements and p.note == ""]
    add(
        DeckCheck(
            "Model",
            "Parts without elements",
            "WARN" if no_el else "PASS",
            f"{len(no_el)}" if no_el else "none",
            tuple(f"{p.id} {p.title} ({p.file})" for p in no_el),
        )
    )
    shells0 = [
        p
        for p in summary.parts
        if p.elements.get("shell")
        and p.section_type == "SHELL"
        and (p.thickness == 0 or math.isnan(p.thickness))
        and not p.mass
    ]
    add(
        DeckCheck(
            "Model",
            "Shell thickness",
            "FAIL" if shells0 else "PASS",
            f"{len(shells0)} shell parts without thickness" if shells0 else "all set",
            tuple(f"{p.id} {p.title}" for p in shells0),
        )
    )
    dens = [
        p
        for p in summary.parts
        if any(p.elements.get(k) for k in ("shell", "solid", "tshell", "beam"))
        and (not p.density or math.isnan(p.density))
    ]
    add(
        DeckCheck(
            "Model",
            "Density",
            "FAIL" if dens else "PASS",
            f"{len(dens)} parts without density" if dens else "all set",
            tuple(f"{p.id} {p.title}: material {p.material or 'none'}" for p in dens),
        )
    )
    add(*_degenerate(deck))
    used = set(ix.refs.get("node", {}))
    free = [i for i in ix.defs.get("node", {}) if i not in used]
    add(
        DeckCheck(
            "Model",
            "Free nodes",
            "INFO" if free else "PASS",
            f"{len(free)} nodes not used by any element, set, mass or card"
            if free
            else "none",
            tuple(str(i) for i in free[:50]),
        )
    )

    # Contacts and welds
    checks.extend(_contacts(deck, ix, summary))

    # Time step
    ts = time_steps(deck, unit_system=unit_system or summary.unit_system)
    if ts.smallest:
        t = UNIT_SYSTEMS[ts.unit_system][1] if ts.unit_system else 1.0
        unit = "ms" if ts.unit_system else "model time units"
        e = ts.smallest[0]
        add(
            DeckCheck(
                "Time step",
                "Smallest estimated time step",
                "INFO",
                f"{e.dt * t:.4g} {unit} ({e.kind} {e.id}, part {e.part})",
                tuple(
                    f"{x.kind} {x.id} part {x.part}: {x.dt * t:.4g} {unit}"
                    for x in ts.smallest[:10]
                ),
            )
        )
        if ts.dt2ms < 0 and ts.model_mass:
            share = 100 * ts.added_mass / ts.model_mass
            add(
                DeckCheck(
                    "Time step",
                    "Mass scaling",
                    "WARN" if share > mass_scaling_limit else "PASS",
                    f"about {share:.2f} % added mass (limit {mass_scaling_limit:g} %)",
                )
            )
    if ts.skipped:
        add(
            DeckCheck(
                "Time step",
                "Not estimated",
                "INFO",
                ", ".join(f"{n} {r}" for r, n in ts.skipped.items()),
            )
        )

    # Unused definitions and unknown keywords
    for ns in (
        "section",
        "material",
        "hourglass",
        "curve",
        "set_part",
        "set_node",
        "set_segment",
        "set_shell",
        "set_solid",
    ):
        d = ix.defs.get(ns, {})
        unused = {i: w for i, w in d.items() if i not in ix.refs.get(ns, {})}
        if unused:
            add(
                DeckCheck(
                    "Unused",
                    f"Unused {_name(ns)}",
                    "INFO",
                    f"{len(unused)}",
                    _items(unused),
                )
            )
    unknown = deck.info.unknown
    if unknown:
        add(
            DeckCheck(
                "Keywords",
                "Not interpreted (kept unchanged)",
                "INFO",
                f"{len(unknown)} keyword types",
                tuple(unknown),
            )
        )
    return DeckSheet(deck.main.name, tuple(checks))


def _degenerate(deck: Deck) -> Iterator[DeckCheck]:
    nd = nodes(deck)
    bad: list[str] = []
    for kind, e in elements(deck).items():
        idx = nd.index(e.nodes.ravel()).reshape(e.nodes.shape)
        ok = ~np.any((idx < 0) & (e.nodes > 0), axis=1)
        if kind == "shell":
            ii = idx[ok, :4].copy()
            ii[:, 3] = np.where(e.nodes[ok, 3] > 0, ii[:, 3], ii[:, 2])
            area = _shell_geometry(nd.xyz[ii])[0]
            for eid in e.ids[ok][area <= 0]:
                bad.append(f"shell {eid}: zero area")
        elif kind in ("solid", "tshell"):
            ii = idx[ok]
            ii = np.where(e.nodes[ok] > 0, ii, ii[:, 3:4])
            vol = _solid_geometry(nd.xyz[ii])[0]
            for eid in e.ids[ok][vol == 0]:
                bad.append(f"{kind} {eid}: zero volume")
            for eid in e.ids[ok][vol < 0]:
                bad.append(f"{kind} {eid}: negative volume (node order)")
    yield DeckCheck(
        "Model",
        "Degenerate elements",
        "FAIL" if bad else "PASS",
        f"{len(bad)}" if bad else "none",
        tuple(bad[:50]),
    )


def _contacts(deck: Deck, ix: _Index, summary: object) -> list[DeckCheck]:
    out = []
    recs = list(deck.records("CONTACT_*"))
    unread = [b for b in deck.find("CONTACT_*") if b.spec is None]
    parts_by_set = {sid: s.members for (k, sid), s in sets(deck).items() if k == "part"}
    covered: set[int] = set()
    every = False
    unknown_cover = bool(unread)
    for r in recs:
        for side in ("s", "m"):
            typ = int(r.get(f"{side}styp", 0))
            i = int(r.get(f"{side}sid", 0))
            if typ == 5 or (side == "s" and typ == 2 and i == 0):
                every = True
            elif typ == 3:
                covered.add(i)
            elif typ in (2, 6):
                covered.update(parts_by_set.get(i, []))
            elif i > 0:
                unknown_cover = True
    deformable = [
        p
        for p in summary.parts  # type: ignore[attr-defined]
        if any(p.elements.get(k) for k in ("shell", "solid", "tshell")) and not p.rigid
    ]
    if not recs and not unread:
        out.append(DeckCheck("Contacts", "Contacts", "WARN", "no contact defined"))
    elif every:
        out.append(
            DeckCheck(
                "Contacts", "Parts in a contact", "PASS", "a contact includes all parts"
            )
        )
    else:
        outside = [p for p in deformable if p.id not in covered]
        status = "PASS" if not outside else ("INFO" if unknown_cover else "WARN")
        note = (
            " (some contacts use segment, node or element sets, not checked)"
            if unknown_cover and outside
            else ""
        )
        out.append(
            DeckCheck(
                "Contacts",
                "Parts in a contact",
                status,
                (
                    f"{len(outside)} deformable parts in no contact{note}"
                    if outside
                    else "every deformable part is in a contact"
                ),
                tuple(f"{p.id} {p.title}" for p in outside),
            )
        )
    mats = _materials(deck)
    parts = _parts(deck)
    weld_parts = [
        pid
        for pid, r in parts.items()
        if (m := mats.get(record_id(r, "mid", "material"))) is not None
        and m.block.subtype == "100"
    ]
    welds = sum(
        int(np.isin(e.parts, weld_parts).sum()) for e in elements(deck).values()
    )
    cons = sum(len(b.records()) for b in deck.find("CONSTRAINED_SPOTWELD*"))
    if welds or cons:
        tied = [
            r
            for r in recs
            if "SPOTWELD" in r.block.subtype or "TIED" in r.block.subtype
        ]
        status = "PASS" if (tied or not welds) else "WARN"
        out.append(
            DeckCheck(
                "Contacts",
                "Spot welds",
                status,
                f"{welds} spot weld elements, {cons} constrained spot welds, "
                f"{len(tied)} tied or spot weld contacts"
                + ("" if status == "PASS" else ": weld elements need one"),
            )
        )
    return out
