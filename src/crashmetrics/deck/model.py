"""Model tables of a deck: parts, mass, centre of gravity, time step.

`model_summary` lists every part with its elements, section (type,
formulation, thickness), material (type, density, rigid), mass and
centre of gravity, from the mesh and the cards, before any run:

- **Shells**: area times thickness (``*ELEMENT_SHELL_THICKNESS`` values,
  else the section's) times density; ``*PART_COMPOSITE`` layers summed.
- **Solids and thick shells**: volume times density. For the
  under-integrated formulations (ELFORM 1 and the like) the one-point
  volume the solver uses (8 x the Jacobian at the centre), else the
  exact volume; degenerate hexahedra (tetrahedra, wedges) included.
- **Beams**: length times the section area (``A``, or rectangular and
  tubular cross-sections from TS and TT).
- **Lumped masses**: ``*ELEMENT_MASS`` (by its part ID, else listed as
  lumped), ``*ELEMENT_MASS_PART`` (added or final mass of a part or part
  set), ``*ELEMENT_INERTIA``; ``*PART_INERTIA`` replaces a rigid part's
  mass and centre.

`time_steps` estimates each element's explicit time step as LS-DYNA
does for shells, solids and beams (characteristic length over sound
speed, times TSSFAC), lists the smallest, and, with mass scaling
(negative DT2MS), the mass it would add.

Masses are in the model's mass unit; `unit_system` (given, from
``*CONTROL_UNITS``, or guessed from the materials) converts to kg and ms.
"""

from __future__ import annotations

import csv
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from crashmetrics.deck.bulk import (
    _file_offset,
    elements,
    mass_elements,
    nodes,
    record_id,
    sets,
)
from crashmetrics.deck.cards import MATERIAL_NAMES, Record
from crashmetrics.deck.reader import Deck

__all__ = [
    "UNIT_SYSTEMS",
    "ElementTimeStep",
    "ModelSummary",
    "PartInfo",
    "TimeStepEstimate",
    "guess_units",
    "model_summary",
    "time_steps",
]

FloatArray = NDArray[np.float64]

UNIT_SYSTEMS: dict[str, tuple[float, float, float]] = {
    "mm-ms-kg": (1.0, 1.0, 1.0),
    "mm-s-t": (1.0, 1000.0, 1000.0),
    "mm-s-kg": (1.0, 1000.0, 1.0),
    "m-s-kg": (1000.0, 1000.0, 1.0),
}
"""Unit system -> factors to mm, ms and kg (length, time, mass)."""

_HEX_FACES = (
    (0, 3, 2, 1),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)


# --- Geometry -----------------------------------------------------------------


def _shell_geometry(
    p: FloatArray,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """Area, centroid, longest side and longest diagonal of shells
    (p: n x 4 x 3; triangles repeat node 3 as node 4)."""
    a, b, c, d = p[:, 0], p[:, 1], p[:, 2], p[:, 3]
    t1 = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    t2 = 0.5 * np.linalg.norm(np.cross(c - a, d - a), axis=1)
    area = t1 + t2
    cen = np.where(
        area[:, None] > 0,
        ((a + b + c) / 3 * t1[:, None] + (a + c + d) / 3 * t2[:, None])
        / np.where(area > 0, area, 1)[:, None],
        (a + b + c + d) / 4,
    )
    sides = np.stack(
        [
            np.linalg.norm(b - a, axis=1),
            np.linalg.norm(c - b, axis=1),
            np.linalg.norm(d - c, axis=1),
            np.linalg.norm(a - d, axis=1),
        ],
        axis=1,
    )
    diag = np.maximum(np.linalg.norm(c - a, axis=1), np.linalg.norm(d - b, axis=1))
    return area, cen, sides.max(axis=1), diag


_XI = np.array(
    [
        [-1, -1, -1],
        [1, -1, -1],
        [1, 1, -1],
        [-1, 1, -1],
        [-1, -1, 1],
        [1, -1, 1],
        [1, 1, 1],
        [-1, 1, 1],
    ],
    dtype=float,
)
_GAUSS = [(a, b, c) for a in (-1, 1) for b in (-1, 1) for c in (-1, 1)]


def _jacobian_det(p: FloatArray, r: float, s: float, t: float) -> FloatArray:
    """det J of the trilinear map of 8-node solids at (r, s, t)."""
    dn = (
        np.stack(
            [
                _XI[:, 0] * (1 + _XI[:, 1] * s) * (1 + _XI[:, 2] * t),
                _XI[:, 1] * (1 + _XI[:, 0] * r) * (1 + _XI[:, 2] * t),
                _XI[:, 2] * (1 + _XI[:, 0] * r) * (1 + _XI[:, 1] * s),
            ],
            axis=1,
        )
        / 8
    )
    return np.asarray(np.linalg.det(np.einsum("ka,nkb->nab", dn, p)))


def _solid_geometry(
    p: FloatArray, one_point: NDArray[np.bool_] | None = None
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Volume, centroid and largest face area of 8-node solids.

    Hexahedra and wedges: the exact volume of the trilinear element (2 x 2
    x 2 Gauss points), or, where ``one_point`` is set (under-integrated
    formulations), 8 det J at the centre with the centroid at the mean
    of the nodes, as the solver computes their mass. Tetrahedra (four
    distinct nodes): the exact volume."""
    n = len(p)
    g = 1 / math.sqrt(3)
    vol = np.zeros(n)
    mom = np.zeros((n, 3))
    for a, b, c in _GAUSS:
        w = _jacobian_det(p, a * g, b * g, c * g)
        shape = (
            (1 + _XI[:, 0] * a * g)
            * (1 + _XI[:, 1] * b * g)
            * (1 + _XI[:, 2] * c * g)
            / 8
        )
        vol += w
        mom += w[:, None] * np.einsum("k,nkb->nb", shape, p)
    cen = np.where(
        np.abs(vol)[:, None] > 0,
        mom / np.where(vol != 0, vol, 1)[:, None],
        p.mean(axis=1),
    )
    if one_point is not None and one_point.any():
        v1 = 8 * _jacobian_det(p[one_point], 0.0, 0.0, 0.0)
        vol[one_point] = v1
        cen[one_point] = p[one_point].mean(axis=1)
    amax = np.zeros(n)
    for face in _HEX_FACES:
        q = p[:, face]
        fa = 0.5 * np.linalg.norm(
            np.cross(q[:, 1] - q[:, 0], q[:, 2] - q[:, 0]), axis=1
        ) + 0.5 * np.linalg.norm(np.cross(q[:, 2] - q[:, 0], q[:, 3] - q[:, 0]), axis=1)
        amax = np.maximum(amax, fa)
    for i in range(n):  # tetrahedra: exact
        u: list[FloatArray] = []
        for row in p[i]:
            if not any(np.array_equal(row, x) for x in u):
                u.append(row)
        if len(u) == 4:
            vol[i] = abs(np.dot(u[1] - u[0], np.cross(u[2] - u[0], u[3] - u[0]))) / 6
            cen[i] = np.mean(u, axis=0)
    return vol, cen, amax


_ONE_POINT = {0, 1, 10, 13, 15, 16, -1, -2}
"""Solid formulations whose mass uses the one-point volume (ELFORM 1, the
default, verified against a solver's mass table; the other
under-integrated ones assumed alike)."""


# --- Units --------------------------------------------------------------------


def guess_units(deck: Deck) -> str | None:
    """The unit system from ``*CONTROL_UNITS``, else the one most
    materials' density and Young's modulus agree with (None if unclear)."""
    for rec in deck.records("CONTROL_UNITS"):
        length = str(rec.get("length", "")).lower()
        time = str(rec.get("time", "")).lower()
        mass = str(rec.get("mass", "")).lower()
        key = f"{length}-{time}-{'t' if mass in ('ton', 'tonne', 'mtrc_ton') else mass}"
        if key in UNIT_SYSTEMS:
            return key
    from crashmetrics.materials.keyword import guess_unit_system

    votes: Counter[str] = Counter()
    for rec in deck.records("MAT_*"):
        ro, e = rec.get("ro", 0.0), rec.get("e", 0.0)
        if rec.block.family == "MAT" and ro and e:
            us = guess_unit_system(ro, e)
            if us:
                votes[us] += 1
    return votes.most_common(1)[0][0] if votes else None


# --- Parts and mass -----------------------------------------------------------


@dataclass(frozen=True)
class PartInfo:
    id: int
    title: str
    elements: dict[str, int]
    """Element kind -> count."""
    section: int
    section_type: str
    elform: int
    thickness: float
    """Shell thickness (model units; NaN for other parts)."""
    material: int
    material_type: str
    density: float
    rigid: bool
    mass: float
    """Model mass unit."""
    cg: tuple[float, float, float]
    file: str
    note: str = ""

    @property
    def kind(self) -> str:
        return (
            max(self.elements, key=self.elements.__getitem__) if self.elements else ""
        )


@dataclass(frozen=True)
class ModelSummary:
    parts: tuple[PartInfo, ...]
    lumped_mass: float
    """Mass elements without a part."""
    total_mass: float
    cg: tuple[float, float, float]
    nodes: int
    elements: dict[str, int]
    unit_system: str | None
    notes: tuple[str, ...] = ()

    @property
    def mass_kg(self) -> float:
        """Total mass in kg (NaN without a unit system)."""
        if self.unit_system is None:
            return math.nan
        return self.total_mass * UNIT_SYSTEMS[self.unit_system][2]

    def part(self, pid: int) -> PartInfo:
        for p in self.parts:
            if p.id == pid:
                return p
        raise KeyError(f"No part {pid}.")

    def table(self, top: int | None = None, by: str = "mass") -> str:
        """Markdown table of the parts (heaviest first by default)."""
        unit = "(kg)" if self.unit_system else "(model units)"
        f = UNIT_SYSTEMS[self.unit_system][2] if self.unit_system else 1.0
        rows = (
            sorted(self.parts, key=lambda p: -p.mass)
            if by == "mass"
            else list(self.parts)
        )
        lines = [
            "| Part | Title | Elements | Section | t | Material | Density | "
            f"Mass {unit} |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for p in rows[:top] if top else rows:
            el = ", ".join(f"{n} {k}" for k, n in p.elements.items())
            t = "" if math.isnan(p.thickness) else f"{p.thickness:g}"
            mat = f"{p.material} {p.material_type}" + (" (rigid)" if p.rigid else "")
            lines.append(
                f"| {p.id} | {p.title} | {el} | {p.section} {p.section_type} "
                f"{p.elform or ''} | {t} | {mat} | {p.density:.4g} | "
                f"{p.mass * f:.4g} |"
            )
        return "\n".join(lines)

    def summary(self) -> str:
        unit = self.unit_system or "model units"
        kg = f" ({self.mass_kg:.4g} kg)" if self.unit_system else ""
        el = ", ".join(f"{n} {k}" for k, n in self.elements.items()) or "no elements"
        lines = [
            f"{len(self.parts)} parts, {self.nodes} nodes, {el}",
            f"Total mass {self.total_mass:.6g}{kg}, centre of gravity "
            f"({self.cg[0]:.4g}, {self.cg[1]:.4g}, {self.cg[2]:.4g}) [{unit}]",
        ]
        if self.lumped_mass:
            lines.append(
                f"  of which lumped masses without a part: {self.lumped_mass:.6g}"
            )
        lines += [f"Note: {n}" for n in self.notes]
        return "\n".join(lines)

    def to_csv(self, path: str | Path) -> Path:
        target = Path(path)
        with open(target, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(
                [
                    "part",
                    "title",
                    "elements",
                    "section",
                    "section_type",
                    "elform",
                    "thickness",
                    "material",
                    "material_type",
                    "density",
                    "rigid",
                    "mass",
                    "cg_x",
                    "cg_y",
                    "cg_z",
                    "file",
                ]
            )
            for p in self.parts:
                w.writerow(
                    [
                        p.id,
                        p.title,
                        sum(p.elements.values()),
                        p.section,
                        p.section_type,
                        p.elform,
                        p.thickness,
                        p.material,
                        p.material_type,
                        p.density,
                        int(p.rigid),
                        p.mass,
                        *p.cg,
                        p.file,
                    ]
                )
        return target


def _first(records: list[Record], key: str, namespace: str) -> dict[int, Record]:
    """Records by their ID (with include offsets); the first definition wins."""
    out: dict[int, Record] = {}
    for r in records:
        if key in r:
            out.setdefault(record_id(r, key, namespace), r)
    return out


def _sections(deck: Deck) -> dict[int, Record]:
    return _first(list(deck.records("SECTION_*")), "secid", "section")


def _materials(deck: Deck) -> dict[int, Record]:
    return _first(
        [r for r in deck.records("MAT_*") if r.block.family == "MAT"], "mid", "material"
    )


def _parts(deck: Deck) -> dict[int, Record]:
    return _first(
        [
            r
            for r in deck.records("PART*")
            if r.block.family in ("PART", "PART_COMPOSITE")
        ],
        "pid",
        "part",
    )


def _offset(rec: Record, namespace: str) -> int:
    return _file_offset(rec.block.file, namespace)


def _sec(part: Record | None, secs: dict[int, Record]) -> Record | None:
    return secs.get(record_id(part, "secid", "section")) if part is not None else None


def _mat(part: Record | None, mats: dict[int, Record]) -> Record | None:
    return mats.get(record_id(part, "mid", "material")) if part is not None else None


def _shell_thickness(sec: Record | None) -> float:
    if sec is None or sec.block.subtype not in ("SHELL",):
        return math.nan
    ts = [sec.get(f"t{i}", 0.0) for i in range(1, 5)]
    pos = [t for t in ts if t > 0]
    return float(np.mean(pos)) if pos else 0.0


def _beam_area(sec: Record | None) -> float:
    """Cross-section area of a beam section (NaN if not known here)."""
    if sec is None or sec.block.subtype != "BEAM":
        return math.nan
    g = sec.get("geometry", [])
    g = list(g) + [0.0] * (8 - len(g))
    elform, cst = sec.get("elform", 1) or 1, sec.get("cst", 0)
    if elform in (2, 3, 12, 13):
        return float(g[0])
    if elform in (1, 4, 5, 9, 11, 14):
        ts = np.mean([v for v in g[0:2] if v > 0] or [0.0])
        tt = np.mean([v for v in g[2:4] if v > 0] or [0.0])
        if cst == 0:
            return float(ts * tt)
        if cst == 1:
            return float(math.pi / 4 * (ts**2 - tt**2))
    return math.nan


def _elform(part_recs: dict[int, Record], secs: dict[int, Record], pid: int) -> int:
    sec = _sec(part_recs.get(pid), secs)
    return int(sec.get("elform", 1) or 1) if sec is not None else 1


def _material_type(mat: Record | None) -> str:
    if mat is None:
        return ""
    sub = mat.block.subtype
    return f"{sub} {MATERIAL_NAMES[sub]}" if sub in MATERIAL_NAMES else sub


def model_summary(deck: Deck, unit_system: str | None = None) -> ModelSummary:
    """Parts, mass and centre of gravity of a deck (see the module notes)."""
    us = unit_system or guess_units(deck)
    if us is not None and us not in UNIT_SYSTEMS:
        raise ValueError(f"Unknown unit_system {us!r}; known: {list(UNIT_SYSTEMS)}.")
    nd = nodes(deck)
    els = elements(deck)
    secs = _sections(deck)
    mats = _materials(deck)
    part_recs = _parts(deck)
    notes: list[str] = []
    mass: dict[int, float] = {}
    mom: dict[int, FloatArray] = {}
    count: dict[int, Counter[str]] = {}

    def add(pids: NDArray[np.int64], m: FloatArray, c: FloatArray) -> None:
        ok = np.isfinite(m)
        for pid in np.unique(pids):
            sel = (pids == pid) & ok
            mass[int(pid)] = mass.get(int(pid), 0.0) + float(m[sel].sum())
            mom[int(pid)] = mom.get(int(pid), np.zeros(3)) + (
                m[sel, None] * c[sel]
            ).sum(axis=0)

    def density(pid: int) -> float:
        m = _mat(part_recs.get(pid), mats)
        return float(m.get("ro", math.nan)) if m is not None else math.nan

    for kind, e in els.items():
        for pid, n in zip(*np.unique(e.parts, return_counts=True)):
            count.setdefault(int(pid), Counter())[kind] += int(n)
        idx = nd.index(e.nodes.ravel()).reshape(e.nodes.shape)
        used = e.nodes > 0
        bad = np.any((idx < 0) & used, axis=1)
        if bad.any():
            notes.append(
                f"{int(bad.sum())} {kind} elements have nodes that are not defined; "
                "left out of the mass."
            )
        ok = ~bad
        if not ok.any():
            continue
        e_parts = e.parts[ok]
        rho = np.array([density(int(p)) for p in e_parts])
        if kind == "shell":
            nn = e.nodes[ok, :4]
            ii = idx[ok, :4].copy()
            ii[:, 3] = np.where(nn[:, 3] > 0, ii[:, 3], ii[:, 2])
            area, cen, _, _ = _shell_geometry(nd.xyz[ii])
            t = e.thickness[ok].copy()
            for j, pid in enumerate(e_parts):
                if math.isnan(t[j]):
                    r = part_recs.get(int(pid))
                    if r is not None and r.block.family == "PART_COMPOSITE":
                        moff = _offset(r, "material")
                        layers = [
                            (
                                row.get(f"mid{k}", 0) + moff
                                if row.get(f"mid{k}", 0)
                                else 0,
                                row.get(f"thick{k}", 0.0),
                            )
                            for row in r.rows
                            for k in (1, 2)
                        ]
                        t[j] = sum(th for _, th in layers)
                        rho[j] = (
                            (
                                sum(
                                    th * float(mats[m].get("ro", 0.0))
                                    for m, th in layers
                                    if m in mats
                                )
                                / t[j]
                            )
                            if t[j]
                            else math.nan
                        )
                    else:
                        t[j] = _shell_thickness(_sec(r, secs))
            add(e_parts, area * t * rho, cen)
        elif kind in ("solid", "tshell"):
            ii = idx[ok]
            ii = np.where(e.nodes[ok] > 0, ii, ii[:, 3:4])
            onept = np.array(
                [_elform(part_recs, secs, int(p)) in _ONE_POINT for p in e_parts]
            )
            vol, cen, _ = _solid_geometry(
                nd.xyz[ii], onept if kind == "solid" else None
            )
            add(e_parts, np.abs(vol) * rho, cen)
        elif kind == "beam":
            ii = idx[ok, :2]
            p1, p2 = nd.xyz[ii[:, 0]], nd.xyz[ii[:, 1]]
            length = np.linalg.norm(p2 - p1, axis=1)
            area = np.array(
                [_beam_area(_sec(part_recs.get(int(p)), secs)) for p in e_parts]
            )
            if np.isnan(area).any():
                notes.append(
                    f"{int(np.isnan(area).sum())} beams have a section whose area "
                    "is not known here; their mass is left out."
                )
            add(e_parts, length * area * rho, (p1 + p2) / 2)

    lumped, lumped_mom = 0.0, np.zeros(3)
    for me in mass_elements(deck):
        if me.kind == "node":
            i = nd.index([me.target])[0]
            if i < 0:
                notes.append(f"Mass element {me.id} at undefined node {me.target}.")
                continue
            if me.part > 0:
                mass[me.part] = mass.get(me.part, 0.0) + me.mass
                mom[me.part] = mom.get(me.part, np.zeros(3)) + me.mass * nd.xyz[i]
            else:
                lumped += me.mass
                lumped_mom += me.mass * nd.xyz[i]
        elif me.kind == "node_set":
            s = sets(deck).get(("node", me.target))
            if s is None or not s.members:
                notes.append(f"Mass element {me.id}: node set {me.target} not found.")
                continue
            ii = nd.index(s.members)
            ii = ii[ii >= 0]
            lumped += me.mass * len(ii)
            lumped_mom += me.mass * nd.xyz[ii].sum(axis=0)
        elif me.kind in ("part", "part_set"):
            pids = (
                [me.target]
                if me.kind == "part"
                else (
                    sets(deck).get(("part", me.target)).members  # type: ignore[union-attr]
                    if ("part", me.target) in sets(deck)
                    else []
                )
            )
            if not pids:
                notes.append(f"*ELEMENT_MASS_PART_SET {me.target}: set not found.")
            total = sum(mass.get(p, 0.0) for p in pids)
            for p in pids:
                share = mass.get(p, 0.0) / total if total else 1.0 / len(pids)
                c = mom.get(p, np.zeros(3)) / mass[p] if mass.get(p) else np.zeros(3)
                new = (
                    me.final_mass * share
                    if me.final_mass > 0
                    else mass.get(p, 0.0) + me.mass * share
                )
                mass[p] = new
                mom[p] = c * new
        elif me.kind == "inertia":
            i = nd.index([me.target])[0]
            if i >= 0:
                lumped += me.mass
                lumped_mom += me.mass * nd.xyz[i]

    for pid, r in part_recs.items():
        if "INERTIA" in r.block.options and r.get("tm", 0.0) > 0:
            mass[pid] = float(r["tm"])
            mom[pid] = float(r["tm"]) * np.array(
                [r.get("xc", 0.0), r.get("yc", 0.0), r.get("zc", 0.0)]
            )

    parts = []
    for pid in sorted(set(part_recs) | set(count) | set(mass)):
        r = part_recs.get(pid)
        sec, mat = _sec(r, secs), _mat(r, mats)
        m = mass.get(pid, 0.0)
        cv = mom.get(pid, np.zeros(3)) / m if m else np.full(3, np.nan)
        centre = (float(cv[0]), float(cv[1]), float(cv[2]))
        if r is not None and r.block.family == "PART_COMPOSITE":
            th = sum(row.get(f"thick{k}", 0.0) for row in r.rows for k in (1, 2))
            stype = "COMPOSITE"
        else:
            th = _shell_thickness(sec)
            stype = sec.block.subtype if sec is not None else ""
        parts.append(
            PartInfo(
                pid,
                r.title if r is not None else "",
                dict(count.get(pid, {})),
                record_id(r, "secid", "section") if r is not None else 0,
                stype,
                sec.get("elform", 0) if sec is not None else 0,
                th,
                record_id(r, "mid", "material") if r is not None else 0,
                _material_type(mat),
                float(mat.get("ro", math.nan)) if mat is not None else math.nan,
                mat is not None and mat.block.subtype == "020",
                m,
                centre,
                r.block.file.name if r is not None else "",
                "" if r is not None else "no *PART card",
            )
        )
    total = sum(mass.values()) + lumped
    tmom = sum((mom[p] for p in mom), np.zeros(3)) + lumped_mom
    cgv = tmom / total if total else np.full(3, np.nan)
    cg = (float(cgv[0]), float(cgv[1]), float(cgv[2]))
    return ModelSummary(
        tuple(parts),
        lumped,
        total,
        cg,
        len(nd.ids),
        {k: len(v.ids) for k, v in els.items()},
        us,
        tuple(dict.fromkeys(notes)),
    )


# --- Time step ----------------------------------------------------------------


@dataclass(frozen=True)
class ElementTimeStep:
    kind: str
    id: int
    part: int
    dt: float
    """Model time unit, with TSSFAC."""
    length: float
    """Characteristic length."""


@dataclass(frozen=True)
class TimeStepEstimate:
    smallest: tuple[ElementTimeStep, ...]
    by_part: dict[int, float]
    tssfac: float
    dt2ms: float
    added_mass: float
    """Mass that mass scaling would add (model units; 0 without it)."""
    model_mass: float
    skipped: dict[str, int] = field(default_factory=dict)
    """Reason -> number of elements without an estimate (rigid, no elastic
    constants known here, ...)."""
    unit_system: str | None = None

    @property
    def dt(self) -> float:
        """Smallest estimated time step (model units)."""
        return self.smallest[0].dt if self.smallest else math.nan

    def summary(self, top: int = 5) -> str:
        t = UNIT_SYSTEMS[self.unit_system][1] if self.unit_system else 1.0
        unit = "ms" if self.unit_system else "model time"
        lines = [
            f"Smallest estimated time step {self.dt * t:.4g} {unit} "
            f"(TSSFAC {self.tssfac:g})"
        ]
        lines += [
            f"  {e.kind} {e.id} (part {e.part}): {e.dt * t:.4g} {unit}, length "
            f"{e.length:.3g}"
            for e in self.smallest[:top]
        ]
        if self.dt2ms < 0:
            share = (
                100 * self.added_mass / self.model_mass if self.model_mass else math.nan
            )
            lines.append(
                f"Mass scaling to {abs(self.dt2ms) * self.tssfac * t:.4g} {unit} would "
                f"add about {self.added_mass:.4g} ({share:.2f} % of the model)"
            )
        for reason, n in self.skipped.items():
            lines.append(f"  {n} elements not estimated: {reason}")
        return "\n".join(lines)


def _elastic(mat: Record | None) -> tuple[float, float, float] | None:
    if mat is None:
        return None
    e, pr, ro = mat.get("e"), mat.get("pr"), mat.get("ro")
    if not e or not ro or e <= 0 or ro <= 0:
        return None
    return float(e), float(pr or 0.0), float(ro)


def time_steps(
    deck: Deck, top: int = 20, unit_system: str | None = None
) -> TimeStepEstimate:
    """Estimated explicit time step of every shell, solid, thick shell and
    beam (see the module notes): characteristic length over sound speed,
    times TSSFAC. Shells (ISDO 0): area over the longest side (twice
    that for triangles); ISDO 1: over the longest diagonal. Solids: volume
    over the largest face (three times that for tetrahedra). Beams: the
    length. Rigid parts and materials without E, PR in their first card
    are skipped."""
    ctrl = next(iter(deck.records("CONTROL_TIMESTEP")), None)
    tssfac = (ctrl.get("tssfac") if ctrl is not None else 0.0) or 0.9
    isdo = ctrl.get("isdo", 0) if ctrl is not None else 0
    dt2ms = ctrl.get("dt2ms", 0.0) if ctrl is not None else 0.0
    nd = nodes(deck)
    els = elements(deck)
    mats = _materials(deck)
    part_recs = _parts(deck)
    secs = _sections(deck)
    skipped: Counter[str] = Counter()
    rows: list[
        tuple[float, str, int, int, float, float]
    ] = []  # dt, kind, id, part, L, mass

    for kind, e in els.items():
        if kind not in ("shell", "solid", "tshell", "beam"):
            continue
        idx = nd.index(e.nodes.ravel()).reshape(e.nodes.shape)
        props: dict[int, Any] = {}
        for pid in np.unique(e.parts):
            mat = _mat(part_recs.get(int(pid)), mats)
            if mat is not None and mat.block.subtype == "020":
                props[int(pid)] = "rigid"
            else:
                props[int(pid)] = _elastic(mat) or "no elastic constants"
        ok = np.array([not isinstance(props[int(p)], str) for p in e.parts])
        for p, n in Counter(e.parts[~ok].tolist()).items():
            skipped[f"{props[int(p)]} ({kind})"] += n
        ok &= ~np.any((idx < 0) & (e.nodes > 0), axis=1)
        if not ok.any():
            continue
        ep = e.parts[ok]
        E = np.array([props[int(p)][0] for p in ep])  # type: ignore[index]
        nu = np.array([props[int(p)][1] for p in ep])  # type: ignore[index]
        ro = np.array([props[int(p)][2] for p in ep])  # type: ignore[index]
        if kind == "shell":
            nn = e.nodes[ok, :4]
            ii = idx[ok, :4].copy()
            tri = nn[:, 3] == 0
            tri |= nn[:, 3] == nn[:, 2]
            ii[:, 3] = np.where(nn[:, 3] > 0, ii[:, 3], ii[:, 2])
            area, _, side, diag = _shell_geometry(nd.xyz[ii])
            base = diag if isdo == 1 else side
            length = np.where(tri, 2.0, 1.0) * area / base
            c = np.sqrt(E / (ro * (1 - nu**2)))
            t = np.array(
                [_shell_thickness(_sec(part_recs.get(int(p)), secs)) for p in ep]
            )
            mass = area * np.nan_to_num(t) * ro
        elif kind in ("solid", "tshell"):
            ii = idx[ok]
            nn = e.nodes[ok]
            ii = np.where(nn > 0, ii, ii[:, 3:4])
            onept = np.array(
                [_elform(part_recs, secs, int(p)) in _ONE_POINT for p in ep]
            )
            vol, _, amax = _solid_geometry(
                nd.xyz[ii], onept if kind == "solid" else None
            )
            unique = np.array([len(set(r.tolist())) for r in nn])
            length = np.abs(vol) / amax * np.where(unique == 4, 3.0, 1.0)
            c = np.sqrt(E * (1 - nu) / ((1 + nu) * (1 - 2 * nu) * ro))
            mass = np.abs(vol) * ro
        else:
            ii = idx[ok, :2]
            length = np.linalg.norm(nd.xyz[ii[:, 1]] - nd.xyz[ii[:, 0]], axis=1)
            c = np.sqrt(E / ro)
            area = np.array([_beam_area(_sec(part_recs.get(int(p)), secs)) for p in ep])
            mass = length * np.nan_to_num(area) * ro
        dt = tssfac * length / c
        for v, eid, pid, L, m in zip(dt, e.ids[ok], ep, length, mass):
            rows.append((float(v), kind, int(eid), int(pid), float(L), float(m)))
    rows.sort(key=lambda r: r[0])
    by_part: dict[int, float] = {}
    for v, _, _, pid, _, _ in rows:
        by_part.setdefault(pid, v)
    added = 0.0
    if dt2ms < 0:
        target = abs(dt2ms) * tssfac
        added = sum(
            m * ((target / v) ** 2 - 1) for v, _, _, _, _, m in rows if 0 < v < target
        )
    model_mass = model_summary(deck, unit_system).total_mass if dt2ms < 0 else 0.0
    return TimeStepEstimate(
        tuple(ElementTimeStep(k, i, p, v, L) for v, k, i, p, L, _ in rows[:top]),
        by_part,
        float(tssfac),
        float(dt2ms),
        float(added),
        model_mass,
        dict(skipped),
        unit_system or guess_units(deck),
    )
