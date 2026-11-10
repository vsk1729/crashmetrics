"""A synthetic bonnet and its headform impacts, for examples and tests.

`bonnet_model` gives a bonnet surface over hard parts (engine, intake
plenum, strut towers, battery, hinges, cowl) and a Euro NCAP-like grid
of impact points every 100 mm; `simulate_grid` impacts every point with
the child (front rows) or adult (rear rows) headform at 40 km/h;
`BonnetRun.write` writes what a real headform study gives:

- ``bonnet.k``: the bonnet outer and the hard parts as shell meshes
  (read with `crashmetrics.mesh.read_mesh`);
- ``impact_points.csv``: the grid points, headform and run folder of
  each (read with `crashmetrics.pedestrian.clearance.read_impact_points`);
- one folder per impact with a ``nodout`` of the headform centre node.

Each impact is a lumped model along the headform's path: the headform
(mass, a stiff skin contact) pushes a local bonnet mass, held by the
bonnet's elastic-plastic bending support (the inner panel). The free
space under the point is measured from the meshes with
`crashmetrics.pedestrian.clearance.clearance`; when the bonnet has used
it up (less the stack of the panels), it lands on the hard part, which
is stiff and crushes at a high force. Stiff zones (latch, hinges, wing
edges) have a higher bending force and more local mass.

`VARIANTS` change one thing with a known effect: the engine 20 mm lower
(the points over the plenum stop being red) and a stiffer bonnet inner
panel (the head stops in less space, but the bonnet itself is now too
stiff). The truth of every impact is kept
(`BonnetRun.truth`) to test the analysis against. The model is for
teaching and testing, not a vehicle simulation; the files say so.

Units of the files: mm, ms, kg.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Hashable
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from crashmetrics.mesh import write_mesh
from crashmetrics.pedestrian.clearance import (
    HEADFORMS,
    Clearance,
    clearance,
    impact_direction,
)
from crashmetrics.synthetic import write_nodout

__all__ = [
    "VARIANTS",
    "BonnetModel",
    "BonnetRun",
    "HardPart",
    "ImpactTruth",
    "StiffZone",
    "bonnet_model",
    "simulate_grid",
]

FloatArray = NDArray[np.float64]
G = 9.80665
_TITLE = "crashmetrics synthetic bonnet (not LS-DYNA output)"


@dataclass(frozen=True)
class HardPart:
    """A hard part under the bonnet: a box (``x``, ``y`` ranges) or a
    vertical cylinder (``centre``, ``radius``), from ``top`` down by
    ``height`` (mm)."""

    part_id: int
    name: str
    top: float
    x: tuple[float, float] = (0.0, 0.0)
    y: tuple[float, float] = (0.0, 0.0)
    centre: tuple[float, float] | None = None
    radius: float = 0.0
    height: float = 80.0
    crush_force: float = 15.0
    """Force at which the part's surface crushes, kN."""
    stiffness: float = 15.0
    """Contact stiffness before it crushes, kN/mm."""

    def mesh(self, size: float = 10.0) -> tuple[FloatArray, list[list[int]]]:
        """Nodes (n, 3) and quads (local indices) of the top and sides."""
        nodes: list[FloatArray] = []
        quads: list[list[int]] = []

        def patch(grid: FloatArray) -> None:
            base = sum(len(n) for n in nodes)
            ni, nj = grid.shape[:2]
            nodes.append(grid.reshape(-1, 3))
            for i in range(ni - 1):
                for j in range(nj - 1):
                    a = base + i * nj + j
                    quads.append([a, a + nj, a + nj + 1, a + 1])

        def steps(a: float, b: float) -> FloatArray:
            return np.linspace(a, b, max(2, int(math.ceil(abs(b - a) / size)) + 1))

        z = steps(self.top - self.height, self.top)
        if self.centre is None:
            xs, ys = steps(*self.x), steps(*self.y)
            gx, gy = np.meshgrid(xs, ys, indexing="ij")
            patch(np.dstack([gx, gy, np.full_like(gx, self.top)]))
            for fixed, run, axis in ((self.x[0], ys, 0), (self.x[1], ys, 0),
                                     (self.y[0], xs, 1), (self.y[1], xs, 1)):
                r, zz = np.meshgrid(run, z, indexing="ij")
                f = np.full_like(r, fixed)
                patch(np.dstack([f, r, zz] if axis == 0 else [r, f, zz]))
        else:
            cx, cy = self.centre
            ang = np.linspace(0.0, 2 * math.pi,
                              max(12, int(2 * math.pi * self.radius / size)) + 1)
            rad = steps(0.0, self.radius)
            rr, aa = np.meshgrid(rad, ang, indexing="ij")
            patch(np.dstack([cx + rr * np.cos(aa), cy + rr * np.sin(aa),
                             np.full_like(rr, self.top)]))
            aa, zz = np.meshgrid(ang, z, indexing="ij")
            patch(np.dstack([cx + self.radius * np.cos(aa),
                             cy + self.radius * np.sin(aa), zz]))
        return np.vstack(nodes), quads

    def lowered(self, dz: float) -> HardPart:
        return replace(self, top=self.top - dz)


@dataclass(frozen=True)
class StiffZone:
    """A stiffer area of the bonnet (latch, hinge, wing edge)."""

    name: str
    x: tuple[float, float]
    y: tuple[float, float]
    plateau_factor: float
    mass_factor: float = 1.0


@dataclass(frozen=True)
class BonnetModel:
    """A bonnet over hard parts (mm, kg, kN)."""

    name: str
    hard_parts: tuple[HardPart, ...]
    stiff_zones: tuple[StiffZone, ...]
    z_front: float = 770.0
    """Bonnet height at the leading edge (x = 0, y = 0), mm."""
    slope: float = 0.17
    """Rise of the bonnet per mm rearward."""
    crown: float = 70.0
    """Drop from the centre line to y = +-700 mm."""
    length: float = 1100.0
    half_width: float = 700.0
    rows: tuple[int, ...] = tuple(range(1, 11))
    """Grid rows; row r is at x = 100 r mm."""
    columns: tuple[int, ...] = tuple(range(-6, 7))
    """Grid columns; column c is at y = 100 c mm (LH positive)."""
    adult_from_row: int = 6
    """Rows from here on are adult headform points."""
    plateau: float = 2.0
    """Bending (crush) force of the bonnet inner panel, kN."""
    hardening: float = 0.0015
    """Rise of that force per mm of bonnet travel (share)."""
    bonnet_stiffness: float = 0.25
    """Elastic bending stiffness of the bonnet, kN/mm."""
    bonnet_mass: float = 0.45
    """Local bonnet mass the head accelerates, kg."""
    skin_stiffness: float = 0.6
    """Headform skin contact stiffness, kN/mm."""
    skin_damping: float = 0.25
    """Hunt-Crossley damping of the skin contact, s/m: the vinyl skin
    absorbs energy, so the bonnet does not bounce off the head, and the
    damping force grows with the compression (no jump at first touch)."""
    stack: float = 5.0
    """Crushed thickness of bonnet outer and inner, mm."""
    notes: str = ""

    def surface_z(self, x: FloatArray | float, y: FloatArray | float) -> FloatArray:
        return np.asarray(self.z_front + self.slope * np.asarray(x)
                          - self.crown * (np.asarray(y) / self.half_width) ** 2)

    def points(self) -> dict[tuple[int, int], tuple[float, float, float]]:
        """Grid points on the bonnet surface, by (row, column)."""
        out = {}
        for r in self.rows:
            for c in self.columns:
                x, y = 100.0 * r, 100.0 * c
                out[(r, c)] = (x, y, float(self.surface_z(x, y)))
        return out

    def headform(self, key: tuple[int, int]) -> str:
        return "adult" if key[0] >= self.adult_from_row else "child"

    def zone(self, key: tuple[int, int]) -> StiffZone | None:
        x, y = 100.0 * key[0], 100.0 * key[1]
        for z in self.stiff_zones:
            if z.x[0] <= x <= z.x[1] and z.y[0] <= y <= z.y[1]:
                return z
        return None

    def surface_mesh(self, size: float = 20.0) -> tuple[FloatArray, list[list[int]]]:
        xs = np.linspace(0.0, self.length, int(self.length / size) + 1)
        ys = np.linspace(-self.half_width, self.half_width,
                         int(2 * self.half_width / size) + 1)
        gx, gy = np.meshgrid(xs, ys, indexing="ij")
        nodes = np.dstack([gx, gy, self.surface_z(gx, gy)]).reshape(-1, 3)
        nj = len(ys)
        quads = [[i * nj + j, (i + 1) * nj + j, (i + 1) * nj + j + 1, i * nj + j + 1]
                 for i in range(len(xs) - 1) for j in range(nj - 1)]
        return nodes, quads


def _reference() -> BonnetModel:
    def strut(pid: int, name: str, y: float) -> HardPart:
        return HardPart(pid, name, 780.0, centre=(400.0, y), radius=80.0, height=150.0,
                        crush_force=15.0, stiffness=12.0)

    parts = (
        HardPart(401, "Engine", 750.0, x=(300.0, 720.0), y=(-300.0, 260.0),
                 height=120.0, crush_force=12.0, stiffness=10.0),
        HardPart(402, "Intake plenum", 770.0, x=(230.0, 330.0), y=(-260.0, 120.0),
                 height=80.0, crush_force=12.0, stiffness=10.0),
        strut(403, "Strut tower LH", 540.0),
        strut(404, "Strut tower RH", -540.0),
        HardPart(405, "Battery", 745.0, x=(150.0, 320.0), y=(280.0, 440.0),
                 height=180.0, crush_force=14.0, stiffness=12.0),
        HardPart(406, "Hinge LH", 920.0, x=(980.0, 1060.0), y=(560.0, 650.0),
                 height=60.0, crush_force=20.0, stiffness=20.0),
        HardPart(407, "Hinge RH", 920.0, x=(980.0, 1060.0), y=(-650.0, -560.0),
                 height=60.0, crush_force=20.0, stiffness=20.0),
        HardPart(408, "Cowl", 890.0, x=(1060.0, 1140.0), y=(-650.0, 650.0),
                 height=60.0, crush_force=12.0, stiffness=12.0),
    )
    zones = (
        StiffZone("latch", (0.0, 150.0), (-150.0, 150.0), 1.3, 3.0),
        StiffZone("hinge LH", (950.0, 1100.0), (500.0, 700.0), 2.4, 1.5),
        StiffZone("hinge RH", (950.0, 1100.0), (-700.0, -500.0), 2.4, 1.5),
        StiffZone("wing edge LH", (0.0, 1100.0), (600.0, 700.0), 1.5, 1.3),
        StiffZone("wing edge RH", (0.0, 1100.0), (-700.0, -600.0), 1.5, 1.3),
    )
    return BonnetModel("baseline", parts, zones, notes="Reference bonnet")


def _variant(name: str) -> BonnetModel:
    base = _reference()
    if name == "baseline":
        return base
    if name == "lower_engine":
        parts = tuple(p.lowered(20.0) if p.name in ("Engine", "Intake plenum") else p
                      for p in base.hard_parts)
        return replace(base, name=name, hard_parts=parts,
                       notes="Engine and intake plenum 20 mm lower")
    if name == "stiff_inner":
        return replace(base, name=name, plateau=base.plateau * 1.4,
                       notes="Bonnet inner panel 40 % stiffer")
    raise ValueError(f"Unknown variant {name!r}; known: {list(VARIANTS)}.")


VARIANTS: dict[str, str] = {
    "baseline": "Reference bonnet: the head bottoms out on the intake plenum, the "
                "strut towers, the battery, the hinges and the cowl; the latch "
                "and the wing edges are stiff",
    "lower_engine": "Engine and plenum 20 mm lower: the plenum points go from red "
                    "to brown, orange or yellow",
    "stiff_inner": "Inner panel 40 % stiffer: the head stops in less space, but "
                   "the bonnet itself is now too stiff and the score drops",
}
"""Variants of `bonnet_model` and what the analysis should find."""


def bonnet_model(variant: str = "baseline") -> BonnetModel:
    """The reference bonnet or one of `VARIANTS`."""
    return _variant(variant)


@dataclass(frozen=True)
class ImpactTruth:
    """What the lumped model did at one point (mm, ms, m/s, J)."""

    clearance: float
    part: str
    bottoming_time: float
    """When the bonnet landed on the hard part, ms after the start (NaN:
    never)."""
    residual_speed: float
    """Head speed then, m/s."""
    max_hard_force: float
    """Highest hard-part force, kN."""


@dataclass
class BonnetRun:
    """Impacts of all grid points of a `BonnetModel` (mm, ms)."""

    model: BonnetModel
    time: FloatArray
    """Output times, ms."""
    keys: list[tuple[int, int]]
    points: dict[tuple[int, int], tuple[float, float, float]]
    directions: dict[tuple[int, int], FloatArray]
    clearances: dict[Hashable, Clearance]
    travel: FloatArray
    """(time, point): head travel along its path from first contact
    (negative before it), mm."""
    speed: FloatArray
    """(time, point): m/s along the path."""
    acceleration: FloatArray
    """(time, point): deceleration, g."""
    truth: dict[tuple[int, int], ImpactTruth] = field(default_factory=dict)

    @staticmethod
    def folder(key: tuple[int, int]) -> str:
        return f"r{key[0]:02d}_c{key[1]:+d}"

    def write(self, folder: str | Path) -> Path:
        """Write ``bonnet.k``, ``impact_points.csv`` and a nodout per point."""
        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        m = self.model
        nodes, shells, names = [], {}, {100: "Bonnet outer"}
        xyz, quads = m.surface_mesh()
        offset, eid = 1, 1
        for pid, (n, q) in [(100, (xyz, quads))] + [(p.part_id, p.mesh())
                                                    for p in m.hard_parts]:
            nodes.append(n)
            for quad in q:
                shells[eid] = (pid, [offset + k for k in quad])
                eid += 1
            offset += len(n)
        names.update({p.part_id: p.name for p in m.hard_parts})
        allnodes = np.vstack(nodes)
        write_mesh(root / "bonnet.k", np.arange(1, len(allnodes) + 1), allnodes,
                   shells, names, title=f"{_TITLE}: {m.name}")
        with open(root / "impact_points.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["row", "column", "x", "y", "z", "headform", "run"])
            for k in self.keys:
                x, y, z = self.points[k]
                w.writerow([k[0], k[1], f"{x:.1f}", f"{y:.1f}", f"{z:.2f}",
                            m.headform(k), self.folder(k)])
        for j, k in enumerate(self.keys):
            d = self.directions[k]
            centre = np.asarray(self.clearances[k].centre)   # at first contact
            disp = (self.travel[:, j] - self.travel[0, j])[:, None] * d     # mm
            coords = centre + self.travel[:, j, None] * d
            vel = self.speed[:, j, None] * d                   # mm/ms
            acc = -self.acceleration[:, j, None] * d * G / 1000.0   # mm/ms^2
            run = root / self.folder(k)
            run.mkdir(exist_ok=True)
            write_nodout(run / "nodout", self.time, [1], disp[:, None], vel[:, None],
                         acc[:, None], coords[:, None],
                         names={1: "Headform CG"},
                         title=f"{_TITLE}: {m.name} {self.folder(k)}")
        return root


def simulate_grid(model: BonnetModel, *, duration: float = 16.0,
                  pre_contact: float = 1.0, output_step: float = 0.1,
                  step: float = 0.004) -> BonnetRun:
    """Impact every grid point (child or adult headform at 40 km/h).

    The head starts ``pre_contact`` ms before touching the bonnet; output
    every ``output_step`` ms (10 kHz). Times in ms.
    """
    pts = model.points()
    keys = list(pts)
    dirs = {k: impact_direction(model.headform(k)) for k in keys}
    hard = {p.name: p.mesh()[0] for p in model.hard_parts}
    surface, _ = model.surface_mesh()
    gaps = clearance(pts, hard, dirs, surface=surface)   # type: ignore[arg-type]
    by_name = {p.name: p for p in model.hard_parts}
    n = len(keys)
    hf = [HEADFORMS[model.headform(k)] for k in keys]
    m_h = np.array([h.mass for h in hf])
    v0 = np.array([h.velocity for h in hf])
    zones = [model.zone(k) for k in keys]
    f_y = np.array([model.plateau * (z.plateau_factor if z else 1.0) for z in zones])
    m_b = np.array([model.bonnet_mass * (z.mass_factor if z else 1.0) for z in zones])
    gap = np.array([gaps[k].distance - model.stack for k in keys])    # mm
    gap = np.where(np.isfinite(gap), np.maximum(gap, 0.5), 1e9)
    k_h = np.array([by_name[gaps[k].part].stiffness if gaps[k].part else 1.0
                    for k in keys])
    f_cr = np.array([by_name[gaps[k].part].crush_force if gaps[k].part else 1.0
                     for k in keys])
    k_b, k_c = model.bonnet_stiffness, model.skin_stiffness
    # Units mm, ms, kg: force kN, speed mm/ms = m/s, F/m in mm/ms^2.
    damp = 2 * 0.15 * np.sqrt(k_b * m_b)          # kN ms/mm
    lam = 1.5 * model.skin_damping * k_c              # kN ms/mm^2
    xh = -v0 * pre_contact
    vh = v0.copy()
    xb = np.zeros(n)
    vb = np.zeros(n)
    xp = np.zeros(n)
    xhp = np.zeros(n)
    t_bottom = np.full(n, math.nan)
    v_bottom = np.zeros(n)
    f_hmax = np.zeros(n)
    steps = int(round((duration + pre_contact) / step))
    every = int(round(output_step / step))
    rec_t, rec_x, rec_v, rec_a = [], [], [], []
    for i in range(steps + 1):
        delta = xh - xb
        fc = np.where(delta > 0, np.maximum(
            delta * (k_c + lam * (vh - vb)), 0.0), 0.0)
        limit = f_y * (1.0 + model.hardening * np.maximum(xb, 0.0))
        fb = k_b * (xb - xp)
        over = fb > limit
        xp = np.where(over, xb - limit / k_b, xp)
        under = fb < -limit
        xp = np.where(under, xb + limit / k_b, xp)
        fb = np.clip(fb, -limit, limit) + damp * vb
        pen = xb - gap - xhp
        fh = np.where(pen > 0, k_h * pen, 0.0)
        crush = fh > f_cr
        xhp = np.where(crush, xb - gap - f_cr / k_h, xhp)
        fh = np.minimum(fh, f_cr)
        new = (fh > 0) & np.isnan(t_bottom)
        t_bottom = np.where(new, i * step, t_bottom)
        v_bottom = np.where(new, vh, v_bottom)
        f_hmax = np.maximum(f_hmax, fh)
        if i % every == 0:
            rec_t.append(i * step)
            rec_x.append(xh.copy())
            rec_v.append(vh.copy())
            rec_a.append(fc / m_h * 1000.0 / G)
        ah = -fc / m_h            # kN / kg = mm/ms^2
        ab = (fc - fb - fh) / m_b
        vh = vh + ah * step
        vb = vb + ab * step
        xh = xh + vh * step
        xb = xb + vb * step
    truth = {k: ImpactTruth(gaps[k].distance, gaps[k].part, float(t_bottom[j]),
                            float(v_bottom[j]), float(f_hmax[j]))
             for j, k in enumerate(keys)}
    return BonnetRun(model, np.array(rec_t), keys, pts, dirs, gaps,
                     np.array(rec_x), np.array(rec_v), np.array(rec_a), truth)
