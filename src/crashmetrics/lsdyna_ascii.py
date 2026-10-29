"""Readers for LS-DYNA ASCII time-history output (nodout, rcforc, sleout ...).

Each reader returns an `AsciiOutput`: the output times, the entities
(nodes, contacts, sections, airbags ...) in file order, and one array of
shape ``(n_times, n_entities)`` per channel. Channel names follow the
binout variable names (``x_acceleration``, ``x_force``, ``total_moment``
...), so code written for binout data reads the same.

Supported files (`KINDS`):

| File | Content | Entities |
| --- | --- | --- |
| nodout | Nodal displacement, velocity, acceleration, rotation | Nodes |
| rcforc | Contact resultant forces and moments | Contacts (``surfa_*``, ``surfb_*``) |
| sleout | Contact (sliding interface) energies | Contacts; totals in ``totals`` |
| secforc | Section forces, moments, centroid and area | Cross sections |
| rwforc | Rigid wall forces | Rigid walls |
| sbtout | Belt force and length, slip ring slip, retractor pull-out | Belts |
| deforc | Discrete element (spring, damper) forces | Elements |
| jntforc | Joint forces and moments, joint stiffnesses | Joints |
| abstat | Airbag volume, pressure, mass, temperature ... | Airbags, control volumes |
| rbdout | Rigid body motion | Rigid bodies |
| spcforc | Constraint (SPC) reaction forces | Nodes; ``totals`` |
| swforc | Spotweld and constrained weld forces, failure | Welds |

Glstat and matsum have their own readers in `crashmetrics.lsdyna`
(`read_glstat`, `read_matsum`), which feed the energy checks.

The readers parse numbers that touch each other (``1.0E+00-2.0E+00``),
Fortran exponents without the ``E`` (``1.00000-100``) and overflow
fields (``*****``, read as NaN). When a run was restarted and the file
goes back in time, the states after the restart time are replaced by
the restarted ones. Unknown lines are skipped, so labels added by newer
LS-DYNA versions do not break the readers.

Functions:

- `read_ascii`, `parse_ascii`: Any supported file (kind from the file
  name or the content).
- `read_nodout`, `read_rcforc`, `read_sleout`, `read_secforc`,
  `read_rwforc`, `read_sbtout`, `read_deforc`, `read_jntforc`,
  `read_abstat`, `read_rbdout`, `read_spcforc`, `read_swforc`: One file
  type each.
- `read_run`: Every supported file found in a run directory.
- `detect_kind`: The file type from a file name or text.
- `main`: Command-line entry point: ``crashmetrics-ascii PATH ... [--csv DIR]``.
"""

import argparse
import csv
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from crashmetrics.energy_check import normalise_name

__all__ = [
    "KINDS",
    "AsciiOutput",
    "detect_kind",
    "main",
    "parse_ascii",
    "read_abstat",
    "read_ascii",
    "read_deforc",
    "read_jntforc",
    "read_nodout",
    "read_rbdout",
    "read_rcforc",
    "read_run",
    "read_secforc",
    "read_sleout",
    "read_spcforc",
    "read_swforc",
    "read_rwforc",
    "read_sbtout",
]

KINDS = (
    "nodout",
    "rcforc",
    "sleout",
    "secforc",
    "rwforc",
    "sbtout",
    "deforc",
    "jntforc",
    "abstat",
    "rbdout",
    "spcforc",
    "swforc",
)

Key = int


# --- Numbers -----------------------------------------------------------------

# A real number always has a decimal point here; integers (IDs, cycles,
# flags) do not, so they are never mistaken for values. The exponent
# may lack the "E" (Fortran writes 1.00000-100 for 3-digit exponents).
_FLOAT = r"[-+]?(?:\d+\.\d*|\.\d+)(?:[EeDd][-+]?\d+|[-+]\d{2,3}(?![\d.]))?"
_TOKEN = re.compile(
    rf"{_FLOAT}|\*{{3,}}"
    r"|(?<![A-Za-z])[-+]?(?:nan|NaN|NAN|inf|Inf|INF)(?:inity|INITY)?(?![A-Za-z])"
)
_F = rf"({_FLOAT}|\*{{3,}})"


def _value(token: str) -> float:
    """Convert one number token to float (Fortran forms, overflow = NaN)."""
    if token.startswith("*"):
        return float("nan")
    s = token.replace("D", "E").replace("d", "E").replace("e", "E")
    if "E" not in s:
        match = re.fullmatch(r"([-+]?(?:\d+\.\d*|\.\d+))([-+]\d+)", s)
        if match:
            s = f"{match.group(1)}E{match.group(2)}"
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _floats(text: str) -> list[float]:
    """All real numbers in a line, in order."""
    return [_value(t) for t in _TOKEN.findall(text)]


# --- Result object -------------------------------------------------------------

@dataclass(frozen=True)
class AsciiOutput:
    """Time histories read from one LS-DYNA ASCII output file.

    Attributes
    ----------
    kind:
        File type, e.g. ``"nodout"``.
    time:
        Output times, in the model's time unit, shape ``(n,)``.
    ids:
        Entity IDs (node, contact, section ...) in the order they first
        appear in the file.
    data:
        Channel name -> array of shape ``(n, len(ids))``; NaN where an
        entity has no value at a time (or the channel does not apply to
        it, e.g. ``belt_force`` of a retractor).
    totals:
        File-level sums printed by LS-DYNA (sleout and spcforc), name ->
        array of shape ``(n,)``.
    names:
        Entity titles from the ``{BEGIN LEGEND}`` block (may be empty).
    title, version:
        First two header lines: the model title and the LS-DYNA version
        line.
    cycle:
        Cycle numbers where the file gives them, else None.
    """

    kind: str
    time: np.ndarray
    ids: tuple[Key, ...]
    data: dict[str, np.ndarray]
    totals: dict[str, np.ndarray] = field(default_factory=dict)
    names: dict[int, str] = field(default_factory=dict)
    title: str = ""
    version: str = ""
    cycle: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.time)

    def __contains__(self, entity: object) -> bool:
        return entity in self.ids

    @property
    def channels(self) -> list[str]:
        """Channel names, in the order they were first read."""
        return list(self.data)

    def index(self, entity: Key) -> int:
        """Column of an entity in the ``data`` arrays."""
        try:
            return self.ids.index(entity)
        except ValueError:
            shown = ", ".join(str(i) for i in self.ids[:20])
            more = " ..." if len(self.ids) > 20 else ""
            raise KeyError(
                f"{self.kind}: no entity {entity!r}; IDs in the file: "
                f"{shown}{more}"
            ) from None

    def channel(self, name: str, entity: Key | None = None) -> np.ndarray:
        """One channel: shape ``(n,)`` for one entity, else ``(n, n_ids)``.

        With ``entity=None`` and a single entity in the file, the 1-D
        history of that entity is returned.
        """
        if name not in self.data:
            raise KeyError(
                f"{self.kind}: no channel {name!r}; channels: "
                f"{', '.join(self.data)}"
            )
        values = self.data[name]
        if entity is None:
            return values[:, 0] if len(self.ids) == 1 else values
        return values[:, self.index(entity)]

    def entity(self, entity: Key) -> dict[str, np.ndarray]:
        """All channels of one entity that have at least one value."""
        column = self.index(entity)
        return {
            name: values[:, column]
            for name, values in self.data.items()
            if not np.all(np.isnan(values[:, column]))
        }

    def magnitude(
        self, channels: Sequence[str], entity: Key | None = None
    ) -> np.ndarray:
        """Resultant of channels, e.g. ``("x_force", "y_force", "z_force")``."""
        parts = [self.channel(name, entity) for name in channels]
        return np.sqrt(sum(np.square(p) for p in parts))

    def name(self, entity: Key) -> str:
        """Title of an entity from the legend ("" if none)."""
        return self.names.get(entity, "")

    def summary(self) -> str:
        """Short text description of the file content."""
        lines = [f"{self.kind}: {self.title}".rstrip(": ")]
        if self.version:
            lines.append(f"  {self.version}")
        if len(self.time):
            lines.append(
                f"  {len(self.time)} states, time {self.time[0]:.6g} to "
                f"{self.time[-1]:.6g}"
            )
        else:
            lines.append("  no states")
        shown = ", ".join(
            f"{i} ({self.names[i]})" if self.names.get(i) else str(i)
            for i in self.ids[:8]
        )
        more = f" ... ({len(self.ids)} in total)" if len(self.ids) > 8 else ""
        lines.append(f"  entities: {shown}{more}")
        lines.append(f"  channels: {', '.join(self.data)}")
        if self.totals:
            lines.append(f"  totals: {', '.join(self.totals)}")
        return "\n".join(lines)

    def to_csv(
        self,
        path: str | Path,
        channels: Sequence[str] | None = None,
        ids: Sequence[Key] | None = None,
    ) -> Path:
        """Write a wide CSV table: time, then one column per channel and entity.

        Columns are named ``channel[id]``; totals are added as
        ``total.name`` when no channel selection is given.
        """
        names = list(channels) if channels is not None else list(self.data)
        entities = list(ids) if ids is not None else list(self.ids)
        columns: list[tuple[str, np.ndarray]] = [("time", self.time)]
        for name in names:
            for entity in entities:
                values = self.channel(name, entity)
                if not np.all(np.isnan(values)):
                    columns.append((f"{name}[{entity}]", values))
        if channels is None:
            columns += [(f"total.{k}", v) for k, v in self.totals.items()]
        path = Path(path)
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([c for c, _ in columns])
            for row in zip(*(v for _, v in columns), strict=True):
                writer.writerow([repr(float(x)) for x in row])
        return path


# --- Building the result ---------------------------------------------------------

class _Builder:
    """Collects states, entity values and totals while a file is parsed."""

    def __init__(self, kind: str, wanted: set[Key] | None, combine: str = "last"):
        self.kind = kind
        self.wanted = wanted
        self.combine = combine
        self.times: list[float] = []
        self.cycles: list[float] = []
        self.states: list[dict[Key, dict[str, float]]] = []
        self.totals: list[dict[str, float]] = []
        self.order: dict[Key, None] = {}
        self.channel_order: dict[str, None] = {}
        self.total_order: dict[str, None] = {}

    def state(self, time: float, cycle: float | None = None, new: bool = False) -> None:
        """Select the state at ``time``; start one if the time is new.

        Consecutive records with the same time share a state (unless
        ``new``). A time below the previous one is a restart: states at
        or after that time are dropped.
        """
        if self.times and not new and time == self.times[-1]:
            return
        if self.times and time <= self.times[-1]:
            keep = int(np.searchsorted(np.asarray(self.times), time, side="left"))
            del self.times[keep:], self.cycles[keep:]
            del self.states[keep:], self.totals[keep:]
        self.times.append(time)
        self.cycles.append(np.nan if cycle is None else float(cycle))
        self.states.append({})
        self.totals.append({})

    def accepts(self, key: Key) -> bool:
        return self.wanted is None or key in self.wanted

    def set(self, key: Key, values: dict[str, float]) -> None:
        if not self.states or not self.accepts(key):
            return
        record = self.states[-1].setdefault(key, {})
        self.order.setdefault(key, None)
        for name, value in values.items():
            self.channel_order.setdefault(name, None)
            if self.combine == "sum" and name in record:
                record[name] += value
            else:
                record[name] = value

    def total(self, values: dict[str, float]) -> None:
        if not self.totals:
            return
        for name, value in values.items():
            self.total_order.setdefault(name, None)
            if self.combine == "sum" and name in self.totals[-1]:
                self.totals[-1][name] += value
            else:
                self.totals[-1][name] = value

    def build(self, header: "_Header") -> AsciiOutput:
        ids = tuple(self.order)
        n = len(self.times)
        data: dict[str, np.ndarray] = {}
        column = {key: j for j, key in enumerate(ids)}
        for name in self.channel_order:
            values = np.full((n, len(ids)), np.nan)
            for i, state in enumerate(self.states):
                for key, record in state.items():
                    if name in record:
                        values[i, column[key]] = record[name]
            data[name] = values
        totals = {
            name: np.array([t.get(name, np.nan) for t in self.totals])
            for name in self.total_order
        }
        cycles = np.array(self.cycles)
        has_cycle = n > 0 and not np.all(np.isnan(cycles))
        return AsciiOutput(
            kind=self.kind,
            time=np.array(self.times, dtype=float),
            ids=ids,
            data=data,
            totals=totals,
            names={k: v for k, v in header.names.items() if v},
            title=header.title,
            version=header.version,
            cycle=cycles if has_cycle else None,
        )


@dataclass
class _Header:
    title: str = ""
    version: str = ""
    names: dict[int, str] = field(default_factory=dict)


def _header(lines: list[str]) -> tuple[_Header, int]:
    """Title, version line and legend; returns the header and the next line."""
    header = _Header()
    start = 0
    if lines and "{BEGIN LEGEND}" not in lines[0]:
        header.title = lines[0].strip()
        start = 1
    if len(lines) > 1 and "ls-dyna" in lines[1].lower():
        header.version = " ".join(lines[1].split())
        start = 2
    for i in range(start, min(len(lines), start + 20)):
        if "{BEGIN LEGEND}" not in lines[i]:
            continue
        j = i + 1
        while j < len(lines) and "{END LEGEND}" not in lines[j]:
            match = re.match(r"\s*(\d+)\s*(.*?)\s*$", lines[j])
            if match:
                header.names[int(match.group(1))] = match.group(2)
            j += 1
        return header, j + 1
    return header, start


# --- Parsers -------------------------------------------------------------------------

_NODOUT_NAMES = {
    "x-disp": "x_displacement", "y-disp": "y_displacement", "z-disp": "z_displacement",
    "x-vel": "x_velocity", "y-vel": "y_velocity", "z-vel": "z_velocity",
    "x-accl": "x_acceleration", "y-accl": "y_acceleration", "z-accl": "z_acceleration",
    "x-coor": "x_coordinate", "y-coor": "y_coordinate", "z-coor": "z_coordinate",
    "x-rot": "rx_displacement", "y-rot": "ry_displacement", "z-rot": "rz_displacement",
    "x-rot vel": "rx_velocity", "y-rot vel": "ry_velocity", "z-rot vel": "rz_velocity",
    "x-rot acc": "rx_acceleration", "y-rot acc": "ry_acceleration",
    "z-rot acc": "rz_acceleration",
}
_NODOUT_STATE = re.compile(
    rf"n\s?o\s?d\s?a\s?l\s+p\s?r\s?i\s?n\s?t\s+o\s?u\s?t.*?s\s?t\s?e\s?p\s+(\d+)"
    rf".*?at\s+time\s*{_F}"
)
_ID_LINE = re.compile(r"^\s*(\d+)(?=\s|[-+])(.*)$")


def _parse_nodout(lines: list[str], b: _Builder) -> None:
    names: list[str] = []
    for line in lines:
        state = _NODOUT_STATE.search(line)
        if state:
            b.state(_value(state.group(2)), int(state.group(1)))
            names = []
            continue
        if "nodal point" in line:
            labels = re.split(r"\s{2,}", line.split("nodal point", 1)[1].strip())
            names = [_NODOUT_NAMES.get(lab, normalise_name(lab)) for lab in labels]
            continue
        if not names:
            continue
        match = _ID_LINE.match(line)
        if not match:
            continue
        key = int(match.group(1))
        if not b.accepts(key):
            continue
        values = _floats(match.group(2))
        if values:
            b.set(key, dict(zip(names, values, strict=False)))


_RCFORC_LINE = re.compile(r"^\s*(slave|master|surfa|surfb)\s+(\d+)\s+(.*)$", re.I)
_PAIR = re.compile(rf"([A-Za-z][A-Za-z_]*)\s*=?\s*{_F}")
_RCFORC_NAMES = {
    "x": "x_force", "y": "y_force", "z": "z_force", "mass": "mass",
    "mx": "x_moment", "my": "y_moment", "mz": "z_moment",
}
_SIDE = {"slave": "surfa", "surfa": "surfa", "master": "surfb", "surfb": "surfb"}


def _parse_rcforc(lines: list[str], b: _Builder) -> None:
    for line in lines:
        match = _RCFORC_LINE.match(line)
        if not match:
            continue
        side = _SIDE[match.group(1).lower()]
        key = int(match.group(2))
        pairs = {k.lower(): _value(v) for k, v in _PAIR.findall(match.group(3))}
        if "time" not in pairs:
            continue
        b.state(pairs.pop("time"))
        b.set(key, {
            f"{side}_{_RCFORC_NAMES.get(k, normalise_name(k))}": v
            for k, v in pairs.items()
        })


_SLEOUT_STATE = re.compile(
    rf"contact\s+interface\s+energy\s+file.*?time\s*=\s*{_F}", re.I
)
_SLEOUT_CYCLE = re.compile(r"cycle\s*=\s*(\d+)")
_SLEOUT_TOTALS = (
    (re.compile(rf"total\s+(?:slave|surfa)\s+side\s*=\s*{_F}", re.I), "surfa_energy"),
    (re.compile(rf"total\s+(?:mastr|master|surfb)\s+side\s*=\s*{_F}", re.I),
     "surfb_energy"),
    (re.compile(rf"total\s+energy\s*=\s*{_F}", re.I), "total_energy"),
    (re.compile(rf"friction\s+energy\s*=\s*{_F}", re.I), "friction_energy"),
)


def _parse_sleout(lines: list[str], b: _Builder) -> None:
    for line in lines:
        state = _SLEOUT_STATE.search(line)
        if state:
            b.state(_value(state.group(1)), new=True)
            continue
        cycle = _SLEOUT_CYCLE.search(line)
        if cycle and b.cycles:
            b.cycles[-1] = float(cycle.group(1))
            continue
        total = next(((name, m) for rx, name in _SLEOUT_TOTALS
                      if (m := rx.search(line))), None)
        if total:
            b.total({total[0]: _value(total[1].group(1))})
            continue
        match = _ID_LINE.match(line)
        if match:
            values = _floats(match.group(2))
            if len(values) >= 3:
                b.set(int(match.group(1)), {
                    "surfa_energy": values[0],
                    "surfb_energy": values[1],
                    "friction_energy": values[2],
                })


def _parse_secforc(lines: list[str], b: _Builder) -> None:
    key: int | None = None
    step = 0
    for line in lines:
        if "line#" in line:
            continue
        values = _floats(line)
        match = _ID_LINE.match(line)
        if match and len(values) == 5 and step == 0:
            key = int(match.group(1))
            b.state(values[0])
            b.set(key, dict(zip(
                ("x_force", "y_force", "z_force", "total_force"), values[1:],
                strict=True)))
            step = 1
        elif key is not None and step and len(values) == 4:
            names = (("x_moment", "y_moment", "z_moment", "total_moment") if step == 1
                     else ("x_centroid", "y_centroid", "z_centroid", "area"))
            b.set(key, dict(zip(names, values, strict=True)))
            step = 0 if step == 2 else 2
        elif not line.strip():
            continue
        else:
            step = 0


_RWFORC_LINE = re.compile(rf"^\s*{_F}\s+(\d+)\s*{_F}\s*{_F}\s*{_F}\s*{_F}\s*$")


def _parse_rwforc(lines: list[str], b: _Builder) -> None:
    for line in lines:
        match = _RWFORC_LINE.match(line)
        if match:
            b.state(_value(match.group(1)))
            b.set(int(match.group(2)), dict(zip(
                ("normal_force", "x_force", "y_force", "z_force"),
                (_value(match.group(i)) for i in range(3, 7)), strict=True)))


_DOTS = re.compile(
    rf"^\s*(?P<label>\S.*?)\s*\.{{2,}}\s*(?P<value>{_FLOAT}|\*{{3,}}|\d+)"
)


def _dot_line(line: str) -> tuple[str, str] | None:
    match = _DOTS.match(line)
    return (match.group("label"), match.group("value")) if match else None


def _parse_dotted(
    lines: list[str],
    b: _Builder,
    entities: dict[str, str],
    names: Callable[[str, str], str] | None = None,
) -> None:
    """Parse ``label....... value`` files (deforc, jntforc, sbtout).

    ``entities`` maps an entity-ID label (normalised) to a context name;
    ``names(context, label)`` gives the channel name of a value label.
    """
    key: int | None = None
    context = ""
    for line in lines:
        item = _dot_line(line)
        if item is None:
            continue
        label = normalise_name(item[0])
        if label == "time":
            b.state(_value(item[1]), new=True)
            key = None
            continue
        if label in entities:
            key = int(item[1]) if item[1].isdigit() else int(_value(item[1]))
            context = entities[label]
            continue
        if key is None:
            continue
        channel = names(context, label) if names else label
        b.set(key, {channel: _value(item[1])})


_SBTOUT_NAMES = {
    ("belt", "force"): "belt_force",
    ("belt", "current_length"): "belt_length",
    ("ring", "total_slip_from_side_1_to"): "ring_slip",
    ("retractor", "pull_out_to_date"): "retractor_pull_out",
    ("retractor", "force_in_attached_element"): "retractor_force",
}


def _parse_sbtout(lines: list[str], b: _Builder) -> None:
    _parse_dotted(
        lines, b,
        {"seat_belt_number": "belt", "slip_ring_number": "ring",
         "retractor_number": "retractor"},
        lambda context, label: _SBTOUT_NAMES.get(
            (context, label), f"{context}_{label}"
        ),
    )


def _parse_deforc(lines: list[str], b: _Builder) -> None:
    _parse_dotted(lines, b, {"spring_damper_number": "element"})


def _parse_jntforc(lines: list[str], b: _Builder) -> None:
    _parse_dotted(
        lines, b, {"joint_id": "joint", "joint_stiffness_id_number": "stiffness"}
    )


_ABSTAT_NAMES = (
    "volume", "pressure", "internal_energy", "dm_dt_in", "density", "dm_dt_out",
    "total_mass", "gas_temp", "surface_area", "reaction", "dm_dt_outp", "dm_dt_outv",
)
_ABSTAT_LINE = re.compile(rf"^\s*{_F}\s+(\d+)\s+(.*)$")


def _parse_abstat(lines: list[str], b: _Builder) -> None:
    for line in lines:
        match = _ABSTAT_LINE.match(line)
        if not match:
            continue
        values = _floats(match.group(3))
        if len(values) < 4:
            continue
        b.state(_value(match.group(1)))
        b.set(int(match.group(2)), dict(zip(_ABSTAT_NAMES, values, strict=False)))


_RBDOUT_STATE = re.compile(
    rf"r\s?i\s?g\s?i\s?d\s+b\s?o\s?d\s?y\s+m\s?o\s?t\s?i\s?o\s?n.*?cycle\s*=\s*(\d+)"
    rf"\s+time\s*=\s*{_F}"
)
_RBDOUT_BODY = re.compile(r"^\s*(?:nodal\s+)?rigid\s+body\s+(\d+)\s*$")
_RBDOUT_ROWS = {
    "displacements": ("dx", "dy", "dz", "rdx", "rdy", "rdz"),
    "velocities": ("vx", "vy", "vz", "rvx", "rvy", "rvz"),
    "accelerations": ("ax", "ay", "az", "rax", "ray", "raz"),
}


def _parse_rbdout(lines: list[str], b: _Builder) -> None:
    key: int | None = None
    frame = "global"
    for line in lines:
        state = _RBDOUT_STATE.search(line)
        if state:
            b.state(_value(state.group(2)), int(state.group(1)), new=True)
            key = None
            continue
        body = _RBDOUT_BODY.match(line)
        if body:
            key = int(body.group(1))
            frame = "global"
            continue
        if key is None:
            continue
        lowered = line.strip().lower()
        if lowered.startswith(("output in principal", "output in local")):
            frame = "local"
            continue
        if ":" in lowered:
            label, rest = lowered.split(":", 1)
            label = label.strip()
            values = _floats(rest)
            if label == "coordinates":
                b.set(key, dict(zip(("global_x", "global_y", "global_z"), values,
                                    strict=False)))
            elif label in _RBDOUT_ROWS:
                b.set(key, {f"{frame}_{n}": v for n, v in
                            zip(_RBDOUT_ROWS[label], values, strict=False)})
            continue
        row = re.match(r"\s*row\s+([123])\b(.*)$", lowered)
        if row:
            r = row.group(1)
            b.set(key, {f"dircos_{r}{c}": v for c, v in
                        zip("123", _floats(row.group(2)), strict=False)})


_SPC_STATE = re.compile(rf"output\s+at\s+time\s*=\s*{_F}")
_SPC_NODE = re.compile(
    rf"node\s*=\s*(\d+)\s+local\s+x,y,z\s+(forces|moments)\s*=\s*{_F}\s*{_F}\s*{_F}",
    re.I,
)
_SPC_TOTAL = re.compile(rf"(force|moment)\s+resultants\s*=\s*{_F}\s*{_F}\s*{_F}", re.I)


def _parse_spcforc(lines: list[str], b: _Builder) -> None:
    for line in lines:
        state = _SPC_STATE.search(line)
        if state:
            b.state(_value(state.group(1)), new=True)
            continue
        node = _SPC_NODE.search(line)
        if node:
            kind = "force" if node.group(2).lower() == "forces" else "moment"
            b.set(int(node.group(1)), {
                f"{axis}_{kind}": _value(node.group(i))
                for axis, i in (("x", 3), ("y", 4), ("z", 5))
            })
            continue
        total = _SPC_TOTAL.search(line)
        if total:
            kind = total.group(1).lower()
            b.total({f"{axis}_{kind}": _value(total.group(i))
                     for axis, i in (("x", 2), ("y", 3), ("z", 4))})


_SWFORC_LINE = re.compile(
    rf"^\s*(\d+)\s*{_F}\s*{_F}\s*{_F}\s+(failure|{_FLOAT})\s+(.*?)\s+ID\s+(\d+)(.*)$"
)
_SWFORC_TRAILING = ("length", "resultant_moment", "torsion")


def _parse_swforc(lines: list[str], b: _Builder) -> None:
    for line in lines:
        match = _SWFORC_LINE.match(line)
        if not match:
            continue
        flag = match.group(5)
        values = {
            "axial": _value(match.group(2)),
            "shear": _value(match.group(3)),
            "failure": 1.0 if flag == "failure" else _value(flag),
        }
        element = " ".join(match.group(6).split()).lower()
        rest = match.group(8)
        failed_at = re.search(rf"failure\s+time\s*=\s*{_F}", rest)
        if failed_at:
            values["failure_time"] = _value(failed_at.group(1))
        elif element.startswith("spotweld"):
            # beam, solid and assembly welds print length, resultant
            # moment and torsion in this order (fcmx/t= extras ignored)
            numbers = _floats(rest.split("fcmx", 1)[0])
            values.update(zip(_SWFORC_TRAILING, numbers, strict=False))
        b.state(_value(match.group(4)))
        b.set(int(match.group(7)), values)


_PARSERS: dict[str, tuple[Callable[[list[str], _Builder], None], str]] = {
    "nodout": (_parse_nodout, "last"),
    "rcforc": (_parse_rcforc, "last"),
    "sleout": (_parse_sleout, "last"),
    "secforc": (_parse_secforc, "last"),
    "rwforc": (_parse_rwforc, "last"),
    "sbtout": (_parse_sbtout, "last"),
    "deforc": (_parse_deforc, "last"),
    "jntforc": (_parse_jntforc, "last"),
    "abstat": (_parse_abstat, "last"),
    "rbdout": (_parse_rbdout, "last"),
    "spcforc": (_parse_spcforc, "sum"),
    "swforc": (_parse_swforc, "last"),
}

_SIGNATURES = (
    ("nodout", re.compile(r"n\s?o\s?d\s?a\s?l\s+p\s?r\s?i\s?n\s?t\s+o\s?u\s?t")),
    ("sleout", re.compile(r"contact\s+interface\s+energy\s+file", re.I)),
    ("secforc", re.compile(r"line#1\s+section#")),
    ("rwforc", re.compile(r"wall#\s+normal-force")),
    ("sbtout", re.compile(r"S E A T B E L T|seat belt number\.", re.I)),
    ("deforc", re.compile(r"spring/damper number\.")),
    ("jntforc", re.compile(r"joint ID\.|joint stiffness id number\.")),
    ("abstat", re.compile(r"airbag/cv #")),
    ("rbdout", re.compile(
        r"r\s?i\s?g\s?i\s?d\s+b\s?o\s?d\s?y\s+m\s?o\s?t\s?i\s?o\s?n")),
    ("spcforc", re.compile(r"single point constraint forces|local x,y,z forces")),
    ("swforc", re.compile(r"constraint #\s+axial")),
    ("rcforc", re.compile(r"^\s*(slave|master|SURFA|SURFB)\s+\d+\s+time", re.M)),
)


def detect_kind(name: str | Path | None = None, text: str | None = None) -> str:
    """The file type: from the file name (e.g. ``nodout``, ``run1.rcforc``)
    or, failing that, from the text."""
    if name is not None:
        parts = re.split(r"[._\-]", Path(name).name.lower())
        for part in parts:
            if part in KINDS:
                return part
    if text is not None:
        sample = text[:200_000]
        for kind, pattern in _SIGNATURES:
            if pattern.search(sample):
                return kind
    raise ValueError(
        f"Cannot tell the LS-DYNA ASCII file type of {name or 'the text'}; "
        f"pass kind= (one of {', '.join(KINDS)})."
    )


def parse_ascii(
    text: str,
    kind: str | None = None,
    ids: Iterable[Key] | None = None,
) -> AsciiOutput:
    """Parse the text of an LS-DYNA ASCII output file.

    Parameters
    ----------
    text:
        File content.
    kind:
        File type (see `KINDS`); detected from the text if None.
    ids:
        Read only these entities (faster for large nodout files).
    """
    kind = kind.lower() if kind else detect_kind(text=text)
    if kind not in _PARSERS:
        raise ValueError(
            f"Unsupported file type {kind!r}; supported: {', '.join(KINDS)}"
        )
    parser, combine = _PARSERS[kind]
    lines = text.splitlines()
    header, start = _header(lines)
    builder = _Builder(kind, None if ids is None else set(ids), combine)
    parser(lines[start:], builder)
    return builder.build(header)


def read_ascii(
    path: str | Path,
    kind: str | None = None,
    ids: Iterable[Key] | None = None,
) -> AsciiOutput:
    """Read an LS-DYNA ASCII output file.

    The type comes from ``kind``, else from the file name, else from the
    content; ``ids`` limits the entities read.
    """
    path = Path(path)
    text = path.read_text(errors="replace")
    if kind is None:
        kind = detect_kind(path, text)
    return parse_ascii(text, kind, ids)


def read_nodout(path: str | Path, ids: Iterable[Key] | None = None) -> AsciiOutput:
    """Read an LS-DYNA ``nodout`` file: nodal time histories.

    ``ids`` limits the entities read.
    """
    return read_ascii(path, "nodout", ids)


def read_rcforc(path: str | Path, ids: Iterable[Key] | None = None) -> AsciiOutput:
    """Read an LS-DYNA ``rcforc`` file: contact resultant forces.

    ``ids`` limits the entities read.
    """
    return read_ascii(path, "rcforc", ids)


def read_sleout(path: str | Path, ids: Iterable[Key] | None = None) -> AsciiOutput:
    """Read an LS-DYNA ``sleout`` file: contact energies (totals in ``totals``).

    ``ids`` limits the entities read.
    """
    return read_ascii(path, "sleout", ids)


def read_secforc(path: str | Path, ids: Iterable[Key] | None = None) -> AsciiOutput:
    """Read an LS-DYNA ``secforc`` file: cross-section forces and moments.

    ``ids`` limits the entities read.
    """
    return read_ascii(path, "secforc", ids)


def read_rwforc(path: str | Path, ids: Iterable[Key] | None = None) -> AsciiOutput:
    """Read an LS-DYNA ``rwforc`` file: rigid wall forces.

    ``ids`` limits the entities read.
    """
    return read_ascii(path, "rwforc", ids)


def read_sbtout(path: str | Path, ids: Iterable[Key] | None = None) -> AsciiOutput:
    """Read an LS-DYNA ``sbtout`` file: seatbelt, slip ring and retractor output.

    ``ids`` limits the entities read.
    """
    return read_ascii(path, "sbtout", ids)


def read_deforc(path: str | Path, ids: Iterable[Key] | None = None) -> AsciiOutput:
    """Read an LS-DYNA ``deforc`` file: discrete element (spring and damper) forces.

    ``ids`` limits the entities read.
    """
    return read_ascii(path, "deforc", ids)


def read_jntforc(path: str | Path, ids: Iterable[Key] | None = None) -> AsciiOutput:
    """Read an LS-DYNA ``jntforc`` file: joint forces and joint stiffness output.

    ``ids`` limits the entities read.
    """
    return read_ascii(path, "jntforc", ids)


def read_abstat(path: str | Path, ids: Iterable[Key] | None = None) -> AsciiOutput:
    """Read an LS-DYNA ``abstat`` file: airbag and control volume statistics.

    ``ids`` limits the entities read.
    """
    return read_ascii(path, "abstat", ids)


def read_rbdout(path: str | Path, ids: Iterable[Key] | None = None) -> AsciiOutput:
    """Read an LS-DYNA ``rbdout`` file: rigid body motion.

    ``ids`` limits the entities read.
    """
    return read_ascii(path, "rbdout", ids)


def read_spcforc(path: str | Path, ids: Iterable[Key] | None = None) -> AsciiOutput:
    """Read an LS-DYNA ``spcforc`` file: constraint (SPC) reaction forces.

    ``ids`` limits the entities read.
    """
    return read_ascii(path, "spcforc", ids)


def read_swforc(path: str | Path, ids: Iterable[Key] | None = None) -> AsciiOutput:
    """Read an LS-DYNA ``swforc`` file: spotweld and constrained weld forces.

    ``ids`` limits the entities read.
    """
    return read_ascii(path, "swforc", ids)


def read_run(
    directory: str | Path,
    kinds: Iterable[str] | None = None,
    skip_errors: bool = False,
) -> dict[str, AsciiOutput]:
    """Read every supported ASCII file in a run directory.

    Files are found by name (``nodout`` or ``NODOUT``; a job-ID prefix
    such as ``run1.nodout`` also works). Files without any state (an
    empty output request) are left out.

    Parameters
    ----------
    directory:
        Run directory.
    kinds:
        File types to read (default: all of `KINDS`).
    skip_errors:
        Leave out files that cannot be read instead of raising.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"{directory} is not a directory.")
    wanted = [k.lower() for k in (kinds or KINDS)]
    found: dict[str, Path] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        try:
            kind = detect_kind(path)
        except ValueError:
            continue
        if kind in wanted and kind not in found:
            found[kind] = path
    results: dict[str, AsciiOutput] = {}
    for kind in wanted:
        if kind not in found:
            continue
        try:
            output = read_ascii(found[kind], kind)
        except (OSError, ValueError) as error:
            if skip_errors:
                continue
            raise ValueError(f"{found[kind]}: {error}") from error
        if len(output):
            results[kind] = output
    return results


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``crashmetrics-ascii``: summarise ASCII files, optionally as CSV.

    Exit code 0 = all read, 2 = a file or directory could not be read.
    """
    parser = argparse.ArgumentParser(
        prog="crashmetrics-ascii",
        description="Read LS-DYNA ASCII output (nodout, rcforc, sleout, ...) "
                    "and print a summary or write CSV tables.",
    )
    parser.add_argument("paths", nargs="+", help="run directories or ASCII files")
    parser.add_argument("--kind", choices=KINDS, help="file type (single files)")
    parser.add_argument("--csv", metavar="DIR",
                        help="write one CSV table per file into DIR")
    args = parser.parse_args(argv)

    out_dir = Path(args.csv) if args.csv else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
    exit_code = 0
    for item in args.paths:
        path = Path(item)
        try:
            if path.is_dir():
                outputs = read_run(path, [args.kind] if args.kind else None)
                if not outputs:
                    print(f"== {path}: no supported ASCII files with data")
            else:
                outputs = {"": read_ascii(path, args.kind)}
        except (OSError, ValueError) as error:
            print(f"ERROR: {path}: {error}")
            exit_code = 2
            continue
        for output in outputs.values():
            print(f"== {path}" + (f" ({output.kind})" if path.is_dir() else ""))
            print(output.summary())
            if out_dir is not None:
                stem = path.name if path.is_dir() else path.stem or path.name
                target = out_dir / f"{stem}_{output.kind}.csv"
                output.to_csv(target)
                print(f"  -> {target}")
            print()
    return exit_code
