"""Bonnet clearance: why a headform impact point is red.

A headform point is red for one of two reasons: the head runs out of
space and hits a hard part under the bonnet (bottoming out), or the
bonnet itself is too stiff where it is hit (a hinge, a reinforcement,
the wing edge). This module tells them apart, point by point:

- **Geometry**: `clearance` measures the free space under each impact
  point to the hard parts (engine, strut towers, battery, hinges ...),
  along the headform's path and along the surface normal, for the
  165 mm headform sphere, from a mesh (`crashmetrics.mesh.read_mesh`)
  or any point clouds. `impact_direction` and `HEADFORMS` give the
  Euro NCAP impact directions and headforms.
- **What is needed**: `required_clearance` is the smallest deformation
  space that keeps HIC15 below a target for a given pulse shape (the
  square wave is the physical limit), `clearance_table` for all colour
  limits.
- **What happened**: `head_impact` reads the headform's nodout (CFC 1000
  acceleration, penetration and speed along the impact direction);
  `assess_impact` gives HIC15 and its colour, the first contact peak,
  the deceleration plateau, the deepest penetration, whether and when
  the head bottomed out (from the geometry, from a second peak in the
  pulse, or both), the speed and energy left at that moment, the share
  of the HIC window after it, the extra space that would have stopped
  the head on the plateau, and a diagnosis.
- **The grid**: `assess_grid` assesses all points, prints a text map of
  the grid with the colours and the bottoming points, counts the points
  lost per cause, gives the Euro NCAP head score
  (`crashmetrics.pedestrian.headform_score`), and `compare_grids`
  compares two design loops.

Lengths are in **mm**, times in **ms**, speeds in **m/s**, accelerations
in **g**, for any unit system of the model. `crashmetrics.pedestrian.
synthetic` writes a bonnet, its hard parts and a grid of headform
impacts to try all of this without a solver.
"""

from __future__ import annotations

import csv
import math
import warnings
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics.lsdyna_ascii import AsciiOutput, read_nodout
from crashmetrics.pedestrian.headform import (
    COLOUR_POINTS,
    HeadformScore,
    headform_score,
    hic_colour,
)
from crashmetrics.pedestrian.hic import calculate_hic

__all__ = [
    "COLOUR_LIMITS",
    "DIAGNOSES",
    "HEADFORMS",
    "PULSE_SHAPES",
    "Clearance",
    "GridAssessment",
    "GridComparison",
    "HeadImpact",
    "Headform",
    "ImpactPoint",
    "ImpactAssessment",
    "assess_grid",
    "assess_impact",
    "clearance",
    "clearance_map",
    "clearance_table",
    "compare_grids",
    "head_impact",
    "impact_direction",
    "read_impact_points",
    "required_clearance",
    "surface_normals",
]

FloatArray = NDArray[np.float64]
G = 9.80665

_LENGTH = {"mm-ms-kg": 1.0, "mm-s-t": 1.0, "mm-s-kg": 1.0, "m-s-kg": 1000.0}
"""mm per model length unit."""
_TIME = {"mm-ms-kg": 1.0, "mm-s-t": 1000.0, "mm-s-kg": 1000.0, "m-s-kg": 1000.0}
"""ms per model time unit."""

COLOUR_LIMITS: dict[str, float] = {"green": 650.0, "yellow": 1000.0,
                                   "orange": 1350.0, "brown": 1700.0}
"""Upper HIC15 limit of each colour (Euro NCAP)."""


def _units(unit_system: str) -> tuple[float, float]:
    if unit_system not in _LENGTH:
        raise ValueError(f"Unknown unit_system {unit_system!r}; known: "
                         f"{list(_LENGTH)}.")
    return _LENGTH[unit_system], _TIME[unit_system]


# --- Headforms and directions ---------------------------------------------------


@dataclass(frozen=True)
class Headform:
    """A headform impactor (Euro NCAP, UN GTR 9)."""

    name: str
    mass: float
    """kg."""
    diameter: float
    """mm."""
    angle: float
    """Impact angle to the ground reference plane, degrees."""
    speed: float
    """km/h."""

    @property
    def radius(self) -> float:
        return self.diameter / 2.0

    @property
    def velocity(self) -> float:
        """m/s."""
        return self.speed / 3.6

    @property
    def energy(self) -> float:
        """Impact energy, J."""
        return 0.5 * self.mass * self.velocity ** 2


HEADFORMS: dict[str, Headform] = {
    "child": Headform("child", 3.5, 165.0, 50.0, 40.0),
    "adult": Headform("adult", 4.5, 165.0, 65.0, 40.0),
}
"""Euro NCAP headforms: child 3.5 kg at 50°, adult 4.5 kg at 65°, both
165 mm and 40 km/h."""


def _headform(value: str | Headform) -> Headform:
    if isinstance(value, Headform):
        return value
    try:
        return HEADFORMS[value]
    except KeyError:
        raise ValueError(f"Unknown headform {value!r}; known: {list(HEADFORMS)}.") \
            from None


def _unit(v: ArrayLike, what: str) -> FloatArray:
    a = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(a))
    if a.shape != (3,) or n == 0:
        raise ValueError(f"{what} must be a non-zero 3-vector.")
    return np.asarray(a / n)


def impact_direction(headform: str | Headform | float = "child", *,
                     rearward: ArrayLike = (1.0, 0.0, 0.0),
                     up: ArrayLike = (0.0, 0.0, 1.0)) -> FloatArray:
    """Unit vector of the headform's path: rearward and down at the
    headform's angle to the ground (or an angle in degrees).

    ``rearward`` and ``up`` are the vehicle's rearward and upward axes in
    the model (x rearward and z up by default, as in most crash models).
    """
    angle = float(headform) if isinstance(headform, (int, float)) else \
        _headform(headform).angle
    r, u = _unit(rearward, "rearward"), _unit(up, "up")
    if abs(float(r @ u)) > 1e-6:
        raise ValueError("rearward and up must be perpendicular.")
    a = math.radians(angle)
    return np.asarray(math.cos(a) * r - math.sin(a) * u)


# --- Impact points --------------------------------------------------------------


@dataclass(frozen=True)
class ImpactPoint:
    """A grid point: its position, headform and run folder."""

    key: Hashable
    point: tuple[float, float, float]
    headform: str = "child"
    run: str = ""


def _key(text: str) -> Hashable:
    try:
        return int(text)
    except ValueError:
        return text.strip()


def read_impact_points(path: str | Path) -> dict[Hashable, ImpactPoint]:
    """Impact points from a CSV with the columns ``row``, ``column``,
    ``x``, ``y``, ``z`` and optionally ``headform`` (child or adult) and
    ``run`` (the run folder, relative to the CSV). Keys are
    ``(row, column)``, as integers when they are numbers."""
    target = Path(path)
    out: dict[Hashable, ImpactPoint] = {}
    with open(target, newline="") as f:
        reader = csv.DictReader(f)
        need = {"row", "column", "x", "y", "z"}
        have = {c.strip().lower() for c in reader.fieldnames or []}
        if not need <= have:
            raise ValueError(f"{target} needs the columns {sorted(need)}; it has "
                             f"{sorted(have)}.")
        for raw in reader:
            row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
            key = (_key(row["row"]), _key(row["column"]))
            run = row.get("run", "")
            out[key] = ImpactPoint(key, (float(row["x"]), float(row["y"]),
                                         float(row["z"])),
                                   row.get("headform") or "child",
                                   str(target.parent / run) if run else "")
    return out


# --- Geometry -------------------------------------------------------------------


@dataclass(frozen=True)
class Clearance:
    """Free space under one impact point."""

    point: tuple[float, float, float]
    """Impact point on the bonnet, mm."""
    direction: tuple[float, float, float]
    distance: float
    """Travel of the headform along ``direction`` from first contact until
    the sphere touches a hard part, mm (inf: nothing within
    ``max_distance``)."""
    part: str
    """Hard part touched first ('' if none)."""
    contact: tuple[float, float, float] | None
    """The hard-part point touched first, mm."""
    lateral: float
    """Its distance from the line of the headform centre, mm."""
    normal_distance: float = math.nan
    """The same along the inward surface normal (NaN without a surface)."""
    normal_part: str = ""
    centre: tuple[float, float, float] | None = None
    """Headform centre at first contact, mm: ``point + radius * normal``
    with a surface, ``point - radius * direction`` without one."""

    @property
    def free(self) -> bool:
        return math.isinf(self.distance)


def _swept_sphere(c: FloatArray, d: FloatArray, radius: float,
                  clouds: Mapping[str, FloatArray], max_distance: float
                  ) -> tuple[float, str, FloatArray | None, float]:
    """First touch of a sphere of ``radius`` centred at ``c`` moving along
    ``d``: travel u = s - sqrt(R^2 - r^2) for a point at distance s along
    d and r from the line through the centre (0 for a point already inside
    the sphere)."""
    best: tuple[float, str, FloatArray | None, float] = (math.inf, "", None, math.nan)
    r_2 = radius * radius
    for name, q in clouds.items():
        rel = q - c
        s = rel @ d
        dist2 = np.einsum("ij,ij->i", rel, rel)
        r2 = dist2 - s * s
        hit = (r2 <= r_2) & ((s >= 0) | (dist2 < r_2))
        if not np.any(hit):
            continue
        u = np.maximum(s[hit] - np.sqrt(np.maximum(r_2 - r2[hit], 0.0)), 0.0)
        k = int(np.argmin(u))
        if u[k] < best[0] and u[k] <= max_distance:
            best = (float(u[k]), name, q[hit][k],
                    float(math.sqrt(max(r2[hit][k], 0.0))))
    return best


def surface_normals(surface: ArrayLike, points: ArrayLike, *,
                    up: ArrayLike = (0.0, 0.0, 1.0),
                    neighbours: int = 24) -> FloatArray:
    """Outward (upward) unit normals of a surface point cloud at points,
    from a plane fitted to the nearest ``neighbours`` surface points."""
    s = np.asarray(surface, dtype=float)
    pts = np.atleast_2d(np.asarray(points, dtype=float))
    if len(s) < 3:
        raise ValueError("The surface needs 3 or more points.")
    u = _unit(up, "up")
    out = np.empty_like(pts)
    k = min(neighbours, len(s))
    for i, p in enumerate(pts):
        near = s[np.argpartition(np.einsum("ij,ij->i", s - p, s - p), k - 1)[:k]]
        _, _, vt = np.linalg.svd(near - near.mean(axis=0), full_matrices=False)
        n = vt[-1]
        out[i] = n if n @ u >= 0 else -n
    return out


def clearance(
    points: Mapping[Hashable, ArrayLike] | ArrayLike,
    hard_parts: Mapping[str, ArrayLike],
    direction: ArrayLike | Mapping[Hashable, ArrayLike],
    *,
    surface: ArrayLike | None = None,
    radius: float = 82.5,
    max_distance: float = 400.0,
    up: ArrayLike = (0.0, 0.0, 1.0),
    unit_system: str = "mm-ms-kg",
) -> dict[Hashable, Clearance]:
    """Free space under impact points to the hard parts.

    Parameters
    ----------
    points:
        Impact points on the bonnet: ``{key: (x, y, z)}`` (keys such as
        grid ``(row, column)``) or an (n, 3) array (keys 0..n-1).
    hard_parts:
        Part name -> its node coordinates (n, 3), for example
        ``{"Engine": mesh.points(401)}``. Give only parts the head
        cannot push away (deformable inner panels are not hard parts).
    direction:
        The headform's path (`impact_direction`), one for all points or
        ``{key: vector}``.
    surface:
        Bonnet surface points. The headform touches the bonnet at the
        impact point with its centre on the surface normal, which on an
        inclined bonnet is not the leading point of the sphere along its
        path; give the surface for the right result there. It also adds
        the clearance along the inward surface normal. Without it the
        headform is assumed to hit the surface head-on.
    radius:
        Headform radius, mm (82.5: the 165 mm Euro NCAP headform).
    max_distance:
        Hard parts farther than this along the path are ignored, mm.
    unit_system:
        Of the coordinates (results in mm).
    """
    length, _ = _units(unit_system)
    if isinstance(points, Mapping):
        keys = list(points)
        pts = np.array([np.asarray(points[k], dtype=float) for k in keys]) * length
    else:
        pts = np.atleast_2d(np.asarray(points, dtype=float)) * length
        keys = list(range(len(pts)))
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError("points must be (n, 3) coordinates.")
    clouds = {name: np.atleast_2d(np.asarray(q, dtype=float)) * length
              for name, q in hard_parts.items()}
    if not clouds:
        raise ValueError("Give at least one hard part.")
    per_point = isinstance(direction, Mapping)
    normals = None
    if surface is not None:
        normals = surface_normals(np.asarray(surface, dtype=float) * length, pts, up=up)
    out: dict[Hashable, Clearance] = {}
    for i, key in enumerate(keys):
        d = _unit(direction[key] if per_point else direction,  # type: ignore[index]
                  "direction")
        # The headform touches the bonnet at the point, where the surface
        # normal points to its centre; without a surface, head-on.
        c = pts[i] + radius * normals[i] if normals is not None else pts[i] - radius * d
        u, part, hit, lateral = _swept_sphere(c, d, radius, clouds, max_distance)
        nd, npart = math.nan, ""
        if normals is not None:
            nd, npart, _, _ = _swept_sphere(c, -normals[i], radius, clouds,
                                            max_distance)
        out[key] = Clearance(tuple(pts[i]), tuple(d), u, part,  # type: ignore[arg-type]
                             None if hit is None else tuple(hit), lateral, nd, npart,
                             tuple(float(v) for v in c))  # type: ignore[arg-type]
    return out


def clearance_map(clearances: Mapping[Hashable, Clearance], *,
                  needed: float | None = None, normal: bool = False) -> str:
    """Text map of the free space (mm) of a (row, column) grid: ``-`` for
    no hard part within reach, ``!`` after points with less than
    ``needed`` mm (`required_clearance` plus the stack, say). ``normal``
    maps the clearance along the surface normal instead."""
    keys = [k for k in clearances if isinstance(k, tuple) and len(k) == 2]
    if not keys:
        raise ValueError("clearance_map() needs (row, column) keys.")
    rows = sorted({k[0] for k in keys})
    cols = sorted({k[1] for k in keys})
    lines = ["row  " + "".join(f"{c:>5}" for c in cols)]
    for r in rows:
        cells = []
        for c in cols:
            item = clearances.get((r, c))
            if item is None:
                cells.append("    .")
                continue
            value = item.normal_distance if normal else item.distance
            if not math.isfinite(value):
                cells.append("    -")
            else:
                flag = "!" if needed is not None and value < needed else " "
                cells.append(f"{value:4.0f}{flag}")
        lines.append(f"{r:>3}  " + "".join(cells))
    what = "along the surface normal" if normal else "along the impact direction"
    lines.append(f"Free space {what}, mm;  -: no hard part within reach"
                 + (f";  !: less than {needed:g} mm" if needed is not None else ""))
    return "\n".join(lines)


# --- Deformation space needed ---------------------------------------------------


PULSE_SHAPES: dict[str, Callable[[FloatArray], FloatArray]] = {
    "square": lambda t: np.ones_like(t),
    "half_sine": lambda t: np.sin(np.pi * t),
    "triangle": lambda t: 1.0 - np.abs(2.0 * t - 1.0),
    "rising": lambda t: t,
    "falling": lambda t: 1.0 - t,
}
"""Deceleration pulse shapes over the stopping time (0 to 1). The square
wave stops the head in the least space for a HIC; real bonnet pulses
need more."""


def _hic_of_shape(g: FloatArray, tau: FloatArray, scale_g: float, duration_s: float,
                  window_s: float) -> float:
    """HIC of a(t) = scale_g * g(t / T) with T = duration_s, window limited."""
    cum = np.concatenate(([0.0], np.cumsum(0.5 * (g[1:] + g[:-1]) * np.diff(tau))))
    best = 0.0
    for i in range(len(tau) - 1):
        dt = (tau[i + 1:] - tau[i]) * duration_s
        ok = dt <= window_s + 1e-15
        if not np.any(ok):
            continue
        mean = (cum[i + 1:][ok] - cum[i]) / (tau[i + 1:][ok] - tau[i])
        best = max(best, float(np.max((scale_g * mean) ** 2.5 * dt[ok])))
    return best


def required_clearance(hic: float, *, speed: float = 40.0, shape: str = "half_sine",
                       window_ms: float = 15.0) -> float:
    """Smallest stopping distance (mm) that keeps HIC15 at ``hic`` for a
    head at ``speed`` (km/h) stopped by a pulse of ``shape``
    (`PULSE_SHAPES`).

    The pulse is scaled in time and level until it stops the head and
    gives exactly that HIC; its stopping distance is returned. The
    square wave gives the physical lower limit (about 68 mm for HIC 1000
    at 40 km/h). Add the crushed thickness of the bonnet and the
    headform skin to compare with the geometric clearance.
    """
    if hic <= 0 or speed <= 0:
        raise ValueError("hic and speed must be positive.")
    try:
        shape_fn = PULSE_SHAPES[shape]
    except KeyError:
        raise ValueError(f"Unknown shape {shape!r}; known: {list(PULSE_SHAPES)}.") \
            from None
    tau = np.linspace(0.0, 1.0, 241)
    g = np.maximum(shape_fn(tau), 0.0)
    area = float(np.sum(0.5 * (g[1:] + g[:-1]) * np.diff(tau)))
    v0 = speed / 3.6
    window = window_ms / 1000.0

    def hic_for(duration: float) -> float:
        level = v0 / (G * duration * area)           # g
        return _hic_of_shape(g, tau, level, duration, window)

    lo, hi = 1e-4, 1.0                                 # s
    for _ in range(60):                               # HIC falls as T grows
        mid = math.sqrt(lo * hi)
        if hic_for(mid) > hic:
            lo = mid
        else:
            hi = mid
    duration = math.sqrt(lo * hi)
    cum = np.concatenate(([0.0], np.cumsum(0.5 * (g[1:] + g[:-1]) * np.diff(tau))))
    remaining = 1.0 - cum / area                       # v / v0 over the pulse
    travel = float(np.sum(0.5 * (remaining[1:] + remaining[:-1]) * np.diff(tau)))
    return 1000.0 * v0 * duration * travel


def clearance_table(*, speed: float = 40.0,
                    shapes: Sequence[str] = ("square", "half_sine", "triangle"),
                    limits: Mapping[str, float] | None = None) -> str:
    """Markdown table: deformation space needed (mm) to stay within each
    colour limit, per pulse shape."""
    lim = dict(limits or COLOUR_LIMITS)
    lines = [f"Deformation space needed at {speed:g} km/h, mm:", "",
             "| HIC15 limit | " + " | ".join(shapes) + " |",
             "| --- |" + " --- |" * len(shapes)]
    for colour, value in lim.items():
        cells = [f"{required_clearance(value, speed=speed, shape=s):.0f}"
                 for s in shapes]
        lines.append(f"| {value:g} ({colour}) | " + " | ".join(cells) + " |")
    return "\n".join(lines)


# --- One impact -----------------------------------------------------------------


@dataclass(frozen=True)
class HeadImpact:
    """Headform motion of one impact (mm, ms, m/s, g)."""

    name: str
    time: FloatArray
    """ms."""
    acceleration: FloatArray
    """Resultant, g (CFC 1000 unless ``cfc`` was None)."""
    penetration: FloatArray
    """Travel along the impact direction from first contact, mm."""
    velocity: FloatArray
    """Speed along the impact direction, m/s (negative: rebound)."""
    headform: Headform
    direction: tuple[float, float, float]
    contact_time: float
    """ms of first contact (unfiltered acceleration reaches ``contact_g``)."""
    cfc: float | None = 1000.0
    source: str = ""


def head_impact(
    source: str | Path | AsciiOutput,
    *,
    node: int | None = None,
    direction: ArrayLike | None = None,
    headform: str | Headform = "child",
    unit_system: str = "mm-ms-kg",
    cfc: float | None = 1000.0,
    contact_g: float = 2.0,
    name: str | None = None,
) -> HeadImpact:
    """The headform's motion from nodout.

    Parameters
    ----------
    source:
        A nodout file, a run folder with one, or an `AsciiOutput`.
    node:
        The headform's centre of gravity node; the only (or first) node
        of the file by default.
    direction:
        Impact direction; `impact_direction(headform)` by default.
    headform:
        ``"child"``, ``"adult"`` or a `Headform`.
    cfc:
        SAE J211 class for the acceleration (Euro NCAP: 1000); None for
        none. Unevenly spaced output is resampled first.
    contact_g:
        First contact: the unfiltered acceleration first reaches this, g.
        The penetration is measured from then.
    """
    hf = _headform(headform)
    length, tk = _units(unit_system)
    if isinstance(source, AsciiOutput):
        out, label, src = source, name or "impact", ""
    else:
        path = Path(source)
        if path.is_dir():
            found = [p for p in (path / "nodout", path / "NODOUT") if p.is_file()]
            found += sorted(p for p in path.iterdir()
                            if p.name.lower().endswith(".nodout"))
            if not found:
                raise FileNotFoundError(f"No nodout in {path}.")
            path = found[0]
        out, label, src = read_nodout(path), name or path.parent.name, str(path)
    need = [f"{a}_{q}" for q in ("displacement", "velocity", "acceleration")
            for a in "xyz"]
    missing = [c for c in need if c not in out.data]
    if missing:
        raise ValueError(f"nodout lacks {missing}; output displacements, velocities "
                         "and accelerations of the headform node.")
    col = out.index(node) if node is not None else 0
    d = _unit(direction, "direction") if direction is not None else impact_direction(hf)
    t = out.time * tk
    disp = np.column_stack([out.data[f"{a}_displacement"][:, col] for a in "xyz"])
    vel = np.column_stack([out.data[f"{a}_velocity"][:, col] for a in "xyz"])
    acc = np.column_stack([out.data[f"{a}_acceleration"][:, col] for a in "xyz"])
    disp = np.nan_to_num(disp) * length                         # mm
    vel = np.nan_to_num(vel) * length / tk                      # mm/ms = m/s
    acc = np.nan_to_num(acc) * length / tk ** 2 * 1000.0 / G    # mm/ms^2 -> g
    step = np.diff(t)
    if cfc is not None and len(t) > 2:
        from crashmetrics.signals import cfc_filter
        if np.ptp(step) > 1e-6 * float(np.median(step)):
            grid = np.arange(t[0], t[-1] + 0.5 * float(np.median(step)),
                             float(np.median(step)))
            disp, vel, acc = (np.column_stack([np.interp(grid, t, a[:, k])
                                               for k in range(3)])
                              for a in (disp, vel, acc))
            t = grid
    raw = np.linalg.norm(acc, axis=1)
    if cfc is not None and len(t) > 2:
        acc = np.column_stack([cfc_filter(t / 1000.0, acc[:, k], cfc)
                               for k in range(3)])
    resultant = np.linalg.norm(acc, axis=1)
    along = disp @ d
    # First contact from the unfiltered signal: the phaseless CFC filter
    # spreads the onset to before the contact.
    started = np.flatnonzero(raw >= contact_g)
    t0 = float(t[0])
    if len(started):
        k = int(started[0])
        t0 = float(t[k]) if k == 0 else float(np.interp(
            contact_g, raw[k - 1:k + 1], t[k - 1:k + 1]))
    return HeadImpact(label, t, resultant, along - float(np.interp(t0, t, along)),
                      vel @ d, hf, tuple(d), t0, cfc, src)  # type: ignore[arg-type]


DIAGNOSES: dict[str, str] = {
    "ok": "within the target colour",
    "bottoming": "the head bottoms out on a hard part, which sets the HIC",
    "light_bottoming": "the head touches a hard part, but the HIC is within the "
                       "target",
    "first_peak": "the first contact peak sets the HIC (its HIC alone is 70 % or "
                  "more of the total): the bonnet is locally heavy or stiff in "
                  "contact (reinforcement, latch, hinge, edge)",
    "stiff": "the deceleration plateau sets the HIC without reaching a hard part: "
             "the bonnet structure is too stiff in bending",
}
"""Diagnosis codes of `assess_impact`."""


@dataclass(frozen=True)
class ImpactAssessment:
    """What happened in one headform impact (mm, ms, m/s, g, J)."""

    name: str
    hic: float
    hic_window: tuple[float, float]
    """ms."""
    colour: str
    peak: float
    """Highest acceleration, g."""
    peak_time: float
    first_peak: float
    """The first contact peak, g."""
    first_peak_time: float
    plateau: float
    """Mean acceleration from the first peak to bottoming (or to the
    deepest penetration), g."""
    penetration: float
    """Deepest travel along the impact direction, mm."""
    penetration_time: float
    clearance: float
    """Geometric clearance, mm (NaN if not given)."""
    margin: float
    """Space left at the deepest penetration: ``clearance - stack + skin -
    penetration``, mm (negative: used up)."""
    part: str
    """Hard part under the point (from the clearance)."""
    bottoming: bool
    bottoming_time: float
    """ms, NaN without bottoming."""
    bottoming_source: str
    """``"geometry"``, ``"pulse"``, ``"both"`` or ``""``."""
    residual_speed: float
    """Speed along the impact direction when bottoming, m/s."""
    residual_energy: float
    """Headform energy left when bottoming, J (share of the impact energy
    in ``residual_share``)."""
    residual_share: float
    extra_space: float
    """Space that would have stopped the residual speed on the plateau, mm."""
    hic_share_after: float
    """Share of the HIC window's velocity change after bottoming (0 to 1)."""
    diagnosis: str
    """A key of `DIAGNOSES`."""
    reason: str

    @property
    def points(self) -> float:
        """Euro NCAP points of the colour (1 green to 0 red)."""
        return COLOUR_POINTS[self.colour]


def _peaks(a: FloatArray) -> NDArray[np.intp]:
    inner = np.flatnonzero((a[1:-1] > a[:-2]) & (a[1:-1] >= a[2:])) + 1
    return np.asarray(inner)


def assess_impact(
    impact: HeadImpact,
    clearance: Clearance | float | None = None,
    *,
    stack: float = 5.0,
    skin: float = 3.0,
    rise: float = 1.25,
    first_fraction: float = 0.3,
    target: str = "yellow",
    window_ms: float = 15.0,
) -> ImpactAssessment:
    """HIC, bottoming out and its cause for one impact.

    Parameters
    ----------
    impact:
        From `head_impact`.
    clearance:
        A `Clearance` (its distance and hard part) or a distance in mm.
    stack:
        Crushed thickness of the bonnet outer and inner panels between
        the head and the hard part, mm.
    skin:
        Compression of the headform skin under the bonnet load, mm: the
        head centre travels this much more than the bonnet. The head
        bottoms out when its penetration reaches ``clearance - stack +
        skin``.
    rise:
        Pulse test: a later peak at least ``rise`` times the first
        contact peak after a dip marks bottoming out.
    first_fraction:
        The first contact peak is the first local peak above this
        fraction of the highest acceleration.
    target:
        Colour the point should reach; worse colours get a cause.
    """
    t, a, x, v = impact.time, impact.acceleration, impact.penetration, impact.velocity
    hic = calculate_hic(t / 1000.0, a, window_ms=window_ms)
    colour = hic_colour(hic.value)
    k_peak = int(np.argmax(a))
    peaks = _peaks(a)
    big = [int(k) for k in peaks if a[k] >= first_fraction * a[k_peak]]
    k1 = big[0] if big else k_peak
    k_pen = int(np.argmax(x))
    # Bottoming from the pulse: a later, higher peak after a dip.
    pulse_time = math.nan
    if k_peak > k1 and a[k_peak] >= rise * a[k1]:
        k_dip = k1 + int(np.argmin(a[k1:k_peak + 1]))
        level = a[k_dip] + 0.2 * (a[k_peak] - a[k_dip])
        rising = np.flatnonzero(a[k_dip:k_peak + 1] <= level)
        pulse_time = float(t[k_dip + int(rising[-1])])
    # Bottoming from the geometry.
    gap, part = math.nan, ""
    if isinstance(clearance, Clearance):
        gap, part = clearance.distance, clearance.part
    elif clearance is not None:
        gap = float(clearance)
    geo_time = math.nan
    if math.isfinite(gap):
        limit = gap - stack + skin
        reach = np.flatnonzero(x >= limit)
        if len(reach):
            k = int(reach[0])
            geo_time = float(t[k]) if k == 0 else float(np.interp(
                limit, x[k - 1:k + 1], t[k - 1:k + 1]))
    sources = [s for s, tt in (("geometry", geo_time), ("pulse", pulse_time))
               if math.isfinite(tt)]
    bottoming = bool(sources)
    when = geo_time if math.isfinite(geo_time) else pulse_time
    source = "both" if len(sources) == 2 else (sources[0] if sources else "")
    end = when if bottoming else float(t[k_pen])
    span = (t > t[k1]) & (t <= end)
    plateau = float(np.mean(a[span])) if np.any(span) else float(a[k1])
    hf = impact.headform
    v_res = float(np.interp(when, t, v)) if bottoming else 0.0
    e_res = 0.5 * hf.mass * max(v_res, 0.0) ** 2
    extra = (1000.0 * max(v_res, 0.0) ** 2 / (2.0 * plateau * G)
             if bottoming and plateau > 0 else 0.0)
    share = 0.0
    t1, t2 = hic.start_time_ms, hic.end_time_ms
    if bottoming:
        inside = (t >= t1) & (t <= t2)
        if np.count_nonzero(inside) > 1:
            ti, ai = t[inside], a[inside]
            pieces = 0.5 * (ai[1:] + ai[:-1]) * np.diff(ti)
            total = float(np.sum(pieces))
            part_after = float(np.sum(pieces[ti[1:] > when]))
            share = part_after / total if total > 0 else 0.0
    margin = gap - stack + skin - float(x[k_pen]) if math.isfinite(gap) else math.nan
    # HIC of the first contact phase alone: up to where the acceleration
    # falls back to the plateau after the first peak.
    after1 = np.flatnonzero(a[k1:] <= plateau)
    k_end1 = k1 + int(after1[0]) if len(after1) else len(t) - 1
    first_hic = 0.0
    if k_end1 > 1:
        with warnings.catch_warnings():         # a phase shorter than 15 ms
            warnings.simplefilter("ignore", UserWarning)
            first_hic = calculate_hic(t[:k_end1 + 1] / 1000.0, a[:k_end1 + 1],
                                      window_ms=window_ms).value
    order = list(COLOUR_LIMITS) + ["red"]
    worse = order.index(colour) > order.index(target)
    where = f" on {part}" if part else ""
    if bottoming and worse and share >= 0.25:
        diagnosis = "bottoming"
        reason = (f"bottoms out{where} at {when:.1f} ms with {v_res:.1f} m/s left "
                  f"({100 * e_res / hf.energy:.0f} % of the energy); about "
                  f"{extra:.0f} mm more space needed")
    elif bottoming and not worse:
        diagnosis = "light_bottoming"
        reason = (f"touches{where or ' a hard part'} at {when:.1f} ms with "
                  f"{v_res:.1f} m/s left")
    elif worse and first_hic >= 0.7 * hic.value:
        diagnosis = "first_peak"
        reason = (f"first contact peak {a[k1]:.0f} g at {t[k1]:.1f} ms gives "
                  f"HIC {first_hic:.0f} on its own; "
                  + (f"{margin:.0f} mm of space left" if math.isfinite(margin)
                     and margin > 0 else "no hard part reached in the HIC window"))
    elif worse:
        diagnosis = "stiff"
        used = (f"; {x[k_pen]:.0f} of {gap - stack + skin:.0f} mm used"
                if math.isfinite(gap) else "")
        reason = (f"plateau {plateau:.0f} g"
                  + (" (a late, light touch of a hard part)" if bottoming
                     else " without reaching a hard part") + used)
    else:
        diagnosis, reason = "ok", f"{colour}" + (
            f", {margin:.0f} mm of space left" if math.isfinite(margin) else "")
    return ImpactAssessment(
        impact.name, hic.value, (t1, t2), colour, float(a[k_peak]), float(t[k_peak]),
        float(a[k1]), float(t[k1]), plateau, float(x[k_pen]), float(t[k_pen]), gap,
        margin, part, bottoming, when if bottoming else math.nan, source, v_res,
        e_res, e_res / hf.energy, extra, share, diagnosis, reason)


# --- The grid -------------------------------------------------------------------

_LETTER = {"green": "G", "yellow": "Y", "orange": "O", "brown": "B", "red": "R"}


@dataclass(frozen=True)
class GridAssessment:
    """All impact points of a grid."""

    points: dict[Hashable, ImpactAssessment]
    protocol: str = "euroncap_2026"
    notes: tuple[str, ...] = field(default_factory=tuple)

    def colours(self) -> dict[str, int]:
        out = dict.fromkeys(_LETTER, 0)
        for p in self.points.values():
            out[p.colour] += 1
        return out

    def diagnoses(self) -> dict[str, int]:
        out = dict.fromkeys(DIAGNOSES, 0)
        for p in self.points.values():
            out[p.diagnosis] += 1
        return out

    def lost_points(self) -> dict[str, float]:
        """Grid points lost to each cause (1 per point minus its colour's
        points)."""
        out = dict.fromkeys(DIAGNOSES, 0.0)
        for p in self.points.values():
            out[p.diagnosis] += 1.0 - p.points
        return out

    def score(self, **kwargs: object) -> HeadformScore:
        """Euro NCAP head score of the predicted HIC15 values
        (`headform_score`; keyword arguments are passed on)."""
        grid = {k: p.hic for k, p in self.points.items()}
        return headform_score(grid, protocol=self.protocol, **kwargs)  # type: ignore[arg-type]

    def map(self) -> str:
        """Text map of a (row, column) grid: colour letter (G Y O B R), with
        ``*`` for bottoming and ``^`` for a first-peak or stiff point."""
        keys = [k for k in self.points if isinstance(k, tuple) and len(k) == 2]
        if not keys:
            raise ValueError("map() needs (row, column) keys.")
        rows = sorted({k[0] for k in keys})
        cols = sorted({k[1] for k in keys})
        mark = {"bottoming": "*", "light_bottoming": "*", "first_peak": "^",
                "stiff": "^", "ok": " "}
        lines = ["row  " + "".join(f"{c:>4}" for c in cols)]
        for r in rows:
            cells = []
            for c in cols:
                p = self.points.get((r, c))
                cells.append("   ." if p is None else
                             f"  {_LETTER[p.colour]}{mark[p.diagnosis]}")
            lines.append(f"{r:>3}  " + "".join(cells))
        lines.append("G Y O B R: colour;  *: bottoms out;  ^: stiff bonnet "
                     "(first peak or plateau)")
        return "\n".join(lines)

    def table(self, top: int | None = 15, worst_first: bool = True) -> str:
        """Markdown table of the points, worst first."""
        items = sorted(self.points.items(), key=lambda kv: -kv[1].hic) if worst_first \
            else list(self.points.items())
        lines = ["| Point | HIC15 | Colour | Penetration mm | Clearance mm | "
                 "Bottoms out | Cause |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for key, p in items[:top] if top else items:
            gap = "-" if not math.isfinite(p.clearance) else f"{p.clearance:.0f}"
            bottom = (f"{p.bottoming_time:.1f} ms, {p.residual_speed:.1f} m/s"
                      if p.bottoming else "no")
            lines.append(f"| {key} | {p.hic:.0f} | {p.colour} | {p.penetration:.0f} | "
                         f"{gap} | {bottom} | {p.reason} |")
        return "\n".join(lines)

    def to_csv(self, path: str | Path) -> Path:
        """All points, one row each (for Excel or a dashboard)."""
        cols = ["point", "hic", "colour", "points", "diagnosis", "part",
                "penetration_mm", "clearance_mm", "margin_mm", "first_peak_g",
                "plateau_g", "peak_g", "bottoming", "bottoming_time_ms",
                "bottoming_source", "residual_speed_ms", "residual_energy_j",
                "extra_space_mm", "hic_share_after", "reason"]
        target = Path(path)
        with open(target, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for key, p in self.points.items():
                w.writerow([key, f"{p.hic:.1f}", p.colour, p.points, p.diagnosis,
                            p.part, f"{p.penetration:.1f}", f"{p.clearance:.1f}",
                            f"{p.margin:.1f}", f"{p.first_peak:.1f}",
                            f"{p.plateau:.1f}", f"{p.peak:.1f}", int(p.bottoming),
                            f"{p.bottoming_time:.2f}", p.bottoming_source,
                            f"{p.residual_speed:.2f}", f"{p.residual_energy:.1f}",
                            f"{p.extra_space:.1f}", f"{p.hic_share_after:.2f}",
                            p.reason])
        return target

    def summary(self) -> str:
        c, d, lost = self.colours(), self.diagnoses(), self.lost_points()
        n = len(self.points)
        score = self.score()
        lines = [f"{n} impact points: " + ", ".join(f"{v} {k}" for k, v in c.items()
                                                       if v),
                 f"Head score {score.score:.2f} of {score.max_score:g} "
                 f"({score.percentage:.1f} %, {score.protocol})"]
        lines += [f"  {k}: {d[k]} points, {lost[k]:.2f} grid points lost"
                  for k in DIAGNOSES if d[k] and k != "ok"]
        lines += [f"Note: {x}" for x in self.notes]
        return "\n".join(lines)


def assess_grid(
    impacts: Mapping[Hashable, HeadImpact],
    clearances: Mapping[Hashable, Clearance | float] | None = None,
    *,
    protocol: str = "euroncap_2026",
    **kwargs: float | str,
) -> GridAssessment:
    """`assess_impact` for every point of a grid (keyword arguments are
    passed on); ``clearances`` by the same keys."""
    notes = []
    gaps = clearances or {}
    missing = [k for k in impacts if gaps and k not in gaps]
    if missing:
        notes.append(f"{len(missing)} points have no clearance (first: {missing[:3]})")
    points = {k: assess_impact(imp, gaps.get(k), **kwargs)  # type: ignore[arg-type]
              for k, imp in impacts.items()}
    return GridAssessment(points, protocol, tuple(notes))


@dataclass(frozen=True)
class GridComparison:
    """Two design loops of the same grid."""

    baseline: str
    variant: str
    changes: tuple[tuple[Hashable, str, str, float, float], ...]
    """(point, colour before, colour after, HIC before, HIC after) of the
    points whose colour changed, most improved first."""
    score: tuple[float, float]
    grid_points: tuple[float, float]
    """Sum of colour points before and after."""
    no_longer_bottoming: tuple[Hashable, ...]
    new_bottoming: tuple[Hashable, ...]

    def summary(self, top: int = 10) -> str:
        a, b = self.score
        lines = [f"{self.variant} against {self.baseline}: head score {a:.2f} -> "
                 f"{b:.2f} ({b - a:+.2f}); grid points {self.grid_points[0]:.2f} -> "
                 f"{self.grid_points[1]:.2f}",
                 f"  {len(self.no_longer_bottoming)} points no longer bottom out, "
                 f"{len(self.new_bottoming)} start to",
                 f"  {len(self.changes)} points change colour:"]
        lines += [f"    {k}: {c0} -> {c1} (HIC {h0:.0f} -> {h1:.0f})"
                  for k, c0, c1, h0, h1 in self.changes[:top]]
        if len(self.changes) > top:
            lines.append(f"    ... {len(self.changes) - top} more")
        return "\n".join(lines)


def compare_grids(baseline: GridAssessment, variant: GridAssessment, *,
                  names: tuple[str, str] = ("baseline", "variant")) -> GridComparison:
    """Colour, score and bottoming changes between two grids (same keys)."""
    common = [k for k in baseline.points if k in variant.points]
    changed = [(k, baseline.points[k].colour, variant.points[k].colour,
                baseline.points[k].hic, variant.points[k].hic) for k in common
               if baseline.points[k].colour != variant.points[k].colour]
    changed.sort(key=lambda r: COLOUR_POINTS[r[1]] - COLOUR_POINTS[r[2]])
    return GridComparison(
        names[0], names[1], tuple(changed),
        (baseline.score().score, variant.score().score),
        (sum(baseline.points[k].points for k in common),
         sum(variant.points[k].points for k in common)),
        tuple(k for k in common if baseline.points[k].bottoming
              and not variant.points[k].bottoming),
        tuple(k for k in common if variant.points[k].bottoming
              and not baseline.points[k].bottoming))
