"""Synthetic LS-DYNA-style crash output for examples, tests and teaching.

A lumped full-width frontal crash against a rigid wall, small enough to
run in a fraction of a second and detailed enough to show what load-path
analysis looks for:

- **Load paths** (`LoadPath`) in parallel: upper (shotgun) rails, main
  rails, lower (subframe) path, each a chain of crushable parts
  (`CrushElement`) behind an elastic spring and an optional gap before
  contact.
- **Crushing**: a part crushes at its strength (mean force with an
  initial peak and folding waves); in a chain the weakest part crushes
  first, so a weak rear part crushes before a strong front one, as in a
  real structure with a wrong crush sequence.
- **Vehicle**: one mass at an initial speed; forces stop it, the elastic
  energy gives a small rebound.

- **Spot welds** (`WeldLine`): lines of welds on the flanges of a part
  carry a share of the path force as shear and, as the part folds, a
  peel (axial) force. A weld fails when ``(axial / Sn)^2 + (shear /
  Ss)^2`` reaches 1; its neighbours take part of its load, and the part
  loses strength as its welds fail.

`frontal_model` gives a reference car and variants with known causes
(`VARIANTS`); `simulate` runs it; `FrontalRun.write` writes ``matsum``
(part energies), ``secforc`` (section forces) and ``swforc`` (spot weld
forces) in the LS-DYNA ASCII format, so every reader and analysis of
crashmetrics can be tried without a solver. `write_matsum`,
`write_secforc` and `write_swforc` write any data in those formats.

Units: mm, ms, kg (force kN, energy J = kN mm). The model is a teaching
model, not a vehicle simulation; the files say so in their header.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics.energy_check import PartEnergies
from crashmetrics.lsdyna_ascii import AsciiOutput

__all__ = [
    "VARIANTS",
    "CrushElement",
    "FrontalModel",
    "FrontalRun",
    "LoadPath",
    "Section",
    "WeldLine",
    "frontal_model",
    "simulate",
    "write_matsum",
    "write_secforc",
    "write_swforc",
]

FloatArray = NDArray[np.float64]

_VERSION_LINE = ("                    crashmetrics synthetic model "
                 "(not LS-DYNA output)")


# --- Model ---------------------------------------------------------------------


@dataclass(frozen=True)
class CrushElement:
    """A crushable part in a load path.

    The crushing force is ``mean_force`` times a factor: falling linearly
    from ``initial_peak`` to 1 over the first ``peak_length`` of crush
    (the force to start the first fold), then ``1 + fold_amplitude
    sin(2 pi s / fold_length)`` (progressive folding).
    """

    part_id: int
    name: str
    mean_force: float
    """kN."""
    length: float
    """Crush length available, mm."""
    initial_peak: float = 1.0
    peak_length: float = 6.0
    fold_length: float = 0.0
    """mm; 0 for no folding waves."""
    fold_amplitude: float = 0.0
    mass: float = 1.0
    """kg (moves with the vehicle)."""
    hourglass: float = 0.0
    """Share of the crush energy reported as hourglass energy."""

    def strength(self, crush: float) -> float:
        """Force needed to crush further after ``crush`` mm, kN."""
        if crush < self.peak_length:
            return self.mean_force * (self.initial_peak - (self.initial_peak - 1.0)
                                      * crush / self.peak_length)
        wave = (math.sin(2.0 * math.pi * (crush - self.peak_length) / self.fold_length)
                if self.fold_length > 0 else 0.0)
        return self.mean_force * (1.0 + self.fold_amplitude * wave)


@dataclass(frozen=True)
class Section:
    """A cross-section through a load path (``*DATABASE_CROSS_SECTION``).

    It carries the path force (the parts of a chain are in series), in
    the direction ``direction`` (its sign is the section normal: a
    negative x means compression is written as negative x force).
    """

    section_id: int
    name: str
    direction: tuple[float, float, float] = (-1.0, 0.0, 0.0)
    share: float = 1.0
    """Share of the path force through this section."""
    mass_ahead: float = 0.0
    """kg between the wall and the section: decelerating it takes part of
    the path force, so sections further back carry slightly less."""
    centroid: tuple[float, float, float] = (0.0, 0.0, 0.0)
    area: float = 800.0


@dataclass(frozen=True)
class WeldLine:
    """A line of spot welds on the flanges of one part of a load path.

    The line carries ``shear_share`` of the path force as shear, more on
    the welds at the front (``gradient``); each weld also gets a peel
    (axial) force of ``peel`` times its shear force times the crushed
    fraction of the part. A weld fails when ``(axial / axial_strength)^2
    + (shear / shear_strength)^2 >= 1``; the welds left take
    ``redistribution`` of the lost share, and the part loses
    ``strength_loss`` of its strength when all its welds have failed.
    """

    name: str
    part_id: int
    first_id: int
    count: int
    shear_share: float
    shear_strength: float
    """kN."""
    axial_strength: float
    """kN."""
    peel: float = 0.5
    gradient: float = 0.3
    """First weld ``1 + gradient`` times the mean load, last ``1 - gradient``."""
    redistribution: float = 0.4
    strength_loss: float = 0.45
    length: float = 1.2
    """Weld length written to swforc, mm."""

    @property
    def ids(self) -> range:
        """Weld IDs, front to rear."""
        return range(self.first_id, self.first_id + self.count)


@dataclass(frozen=True)
class LoadPath:
    """Parts in series, front to rear, reached after ``gap`` mm of crush."""

    name: str
    elements: tuple[CrushElement, ...]
    gap: float = 0.0
    stiffness: float = 50.0
    """Elastic stiffness of the path, kN/mm."""
    sections: tuple[Section, ...] = ()
    welds: tuple[WeldLine, ...] = ()


@dataclass(frozen=True)
class FrontalModel:
    """A vehicle mass on parallel load paths, against a rigid wall."""

    name: str
    paths: tuple[LoadPath, ...]
    mass: float = 1500.0
    """Total mass, kg (crushable parts included)."""
    speed: float = 56.0
    """km/h."""
    body_part: tuple[int, str] = (200, "Body and rest of vehicle")

    def replace_element(self, part_id: int, path: str | None = None,
                        **changes: Any) -> FrontalModel:
        """A copy with one part changed (in every path, or only ``path``)."""
        paths = []
        found = False
        for p in self.paths:
            elements = []
            for e in p.elements:
                if e.part_id == part_id and (path is None or p.name == path):
                    e = replace(e, **changes)
                    found = True
                elements.append(e)
            paths.append(replace(p, elements=tuple(elements)))
        if not found:
            raise ValueError(f"No part {part_id} in the model.")
        return replace(self, paths=tuple(paths))

    def replace_welds(self, name: str, **changes: Any) -> FrontalModel:
        """A copy with one weld line (by name) changed."""
        paths = []
        found = False
        for p in self.paths:
            lines = []
            for w in p.welds:
                if w.name == name:
                    w = replace(w, **changes)
                    found = True
                lines.append(w)
            paths.append(replace(p, welds=tuple(lines)))
        if not found:
            raise ValueError(f"No weld line {name!r} in the model.")
        return replace(self, paths=tuple(paths))

    def weld_groups(self) -> dict[str, range]:
        """Weld line name -> its weld IDs (swforc has no titles)."""
        return {w.name: w.ids for p in self.paths for w in p.welds}

    def without_paths(self, *names: str) -> FrontalModel:
        """A copy without the named load paths."""
        unknown = set(names) - {p.name for p in self.paths}
        if unknown:
            raise ValueError(f"Unknown paths {sorted(unknown)}.")
        return replace(self, paths=tuple(p for p in self.paths if p.name not in names))


def _reference_car() -> FrontalModel:
    def side(s: str, sign: float) -> list[LoadPath]:
        y = 450.0 * sign
        lh = s == "LH"
        bumper = CrushElement(100, "Bumper beam", 45.0, 40.0, 1.0, mass=3.0,
                              hourglass=0.01)
        crash_box = CrushElement(110 if lh else 111, f"Crash box {s}", 95.0, 160.0,
                                 1.45, 6.0, 30.0, 0.25, 1.5, 0.03)
        front_rail = CrushElement(120 if lh else 121, f"Front rail {s}", 150.0,
                                  220.0, 1.25, 8.0, 50.0, 0.15, 6.0, 0.02)
        rear_rail = CrushElement(130 if lh else 131, f"Rear rail {s}", 230.0, 150.0,
                                 1.2, 8.0, 60.0, 0.1, 8.0, 0.02)
        upper = CrushElement(140 if lh else 141, f"Upper rail {s}", 45.0, 520.0, 1.3,
                             6.0, 40.0, 0.2, 4.0, 0.02)
        extension = CrushElement(150 if lh else 151, f"Subframe extension {s}", 35.0,
                                 140.0, 1.4, 6.0, 35.0, 0.2, 1.0, 0.03)
        subframe = CrushElement(152, "Subframe", 80.0, 380.0, 1.2, 8.0, 50.0, 0.1,
                                8.0, 0.02)
        k = 1 if lh else 2
        return [
            LoadPath(f"main {s}", (bumper, crash_box, front_rail, rear_rail), 0.0,
                     60.0, (
                         Section(10 + k, f"Crash box {s}", (-1.0, 0.02 * sign, -0.03),
                                 mass_ahead=1.5, centroid=(-150.0, y, 450.0),
                                 area=950.0),
                         Section(12 + k, f"Front rail {s}", (-1.0, 0.04 * sign, -0.05),
                                 mass_ahead=3.0, centroid=(250.0, y, 430.0),
                                 area=1250.0),
                         Section(14 + k, f"Rear rail {s}", (-0.98, 0.05 * sign, -0.2),
                                 mass_ahead=9.0, centroid=(800.0, y, 300.0),
                                 area=1500.0)),
                     (WeldLine(f"Crash box {s} flange", crash_box.part_id,
                               crash_box.part_id * 1000 + 1, 8, 0.20, 12.0, 9.0,
                               peel=0.45),
                      WeldLine(f"Front rail {s} flange", front_rail.part_id,
                               front_rail.part_id * 1000 + 1, 14, 0.30, 14.0, 11.0,
                               peel=0.75),
                      WeldLine(f"Rear rail {s} flange", rear_rail.part_id,
                               rear_rail.part_id * 1000 + 1, 10, 0.22, 13.0, 9.0,
                               peel=0.6))),
            LoadPath(f"upper {s}", (upper,), 60.0, 15.0, (
                # Section normal points rearwards: compression is +x here.
                Section(20 + k, f"Upper rail {s}", (1.0, -0.06 * sign, 0.1),
                        centroid=(150.0, y * 1.25, 750.0), area=600.0),),
                     (WeldLine(f"Upper rail {s} flange", upper.part_id,
                               upper.part_id * 1000 + 1, 10, 0.5, 6.0, 4.5,
                               peel=0.6),)),
            LoadPath(f"lower {s}", (extension, subframe), 90.0, 30.0, (
                Section(30 + k, f"Subframe extension {s}", (-1.0, 0.0, 0.04),
                        centroid=(-100.0, y * 0.8, 250.0), area=700.0),)),
        ]

    return FrontalModel("reference car", tuple(side("LH", 1.0) + side("RH", -1.0)))


def _variant(name: str) -> FrontalModel:
    car = _reference_car()
    if name == "baseline":
        return car
    if name == "weak_front_rail_lh":
        # Thinner LH front rail: weaker than the crash box in front of it.
        return replace(car.replace_element(120, mean_force=80.0), name=name)
    if name == "no_lower_path":
        return replace(car.without_paths("lower LH", "lower RH"), name=name)
    if name == "weak_welds_front_rail_lh":
        return replace(car.replace_welds("Front rail LH flange", shear_strength=5.0,
                                         axial_strength=4.0), name=name)
    raise ValueError(f"Unknown variant {name!r}; known: {list(VARIANTS)}.")


VARIANTS: dict[str, str] = {
    "baseline": "Reference car: bumper, crash boxes, front and rear rails; upper "
                "rails; subframe extensions and subframe",
    "weak_front_rail_lh": "LH front rail 80 kN instead of 150 kN: it crushes before "
                          "the LH crash box (wrong crush sequence)",
    "no_lower_path": "Subframe extensions and subframe removed: the upper and main "
                     "paths take the load, the rear rails crush",
    "weak_welds_front_rail_lh": "LH front rail flange welds at 40 % strength: they "
                                "unzip while the rail crushes, and the rail "
                                "loses strength",
}
"""Variants of `frontal_model` and what changes."""


def frontal_model(variant: str = "baseline", *, mass: float = 1500.0,
                  speed: float = 56.0) -> FrontalModel:
    """The reference car (`VARIANTS` for the variants)."""
    return replace(_variant(variant), mass=mass, speed=speed)


# --- Simulation ----------------------------------------------------------------


@dataclass(frozen=True)
class FrontalRun:
    """Result of `simulate`: histories at every integration step."""

    model: FrontalModel
    time: FloatArray
    """ms."""
    displacement: FloatArray
    """Vehicle displacement (crush at the wall), mm."""
    velocity: FloatArray
    """mm/ms (= m/s)."""
    path_force: dict[str, FloatArray]
    """Force of each load path, kN (compression positive)."""
    crush: dict[tuple[str, int], FloatArray]
    """(path, part ID) -> crush of that part in that path, mm."""
    plastic_energy: dict[tuple[str, int], FloatArray]
    """(path, part ID) -> crush energy, J."""
    notes: tuple[str, ...] = ()
    meta: dict[str, object] = field(default_factory=dict)
    weld_time: FloatArray = field(default_factory=lambda: np.zeros(0))
    """Times of the weld histories, ms."""
    weld_ids: tuple[int, ...] = ()
    weld_axial: FloatArray = field(default_factory=lambda: np.zeros((0, 0)))
    """(time, weld), kN (tension positive)."""
    weld_shear: FloatArray = field(default_factory=lambda: np.zeros((0, 0)))
    weld_failure_time: FloatArray = field(default_factory=lambda: np.zeros(0))
    """ms per weld, NaN if it holds."""

    # Derived histories --------------------------------------------------------
    @property
    def wall_force(self) -> FloatArray:
        """Total force on the rigid wall, kN."""
        return np.asarray(sum(self.path_force.values()), dtype=float)

    @property
    def deceleration(self) -> FloatArray:
        """Vehicle deceleration, g."""
        return self.wall_force / self.model.mass * 1000.0 / 9.80665

    def parts(self) -> dict[int, str]:
        """Part IDs and names (crushable parts and the body)."""
        out: dict[int, str] = {}
        for p in self.model.paths:
            for e in p.elements:
                out.setdefault(e.part_id, e.name)
        out[self.model.body_part[0]] = self.model.body_part[1]
        return dict(sorted(out.items()))

    def sections(self) -> dict[int, tuple[LoadPath, Section]]:
        """Section ID -> (its load path, the section), by ID."""
        return dict(sorted((s.section_id, (p, s)) for p in self.model.paths
                           for s in p.sections))

    def part_energies(self, times: ArrayLike | None = None) -> PartEnergies:
        """Part energies as LS-DYNA's matsum gives them (J): internal
        (crush energy less hourglass, plus the elastic energy of each path
        in its last part), kinetic, hourglass."""
        t = self.time if times is None else np.asarray(times, dtype=float)
        parts = self.parts()
        ids = list(parts)
        col = {pid: i for i, pid in enumerate(ids)}
        n = len(t)
        internal = np.zeros((n, len(ids)))
        hourglass = np.zeros((n, len(ids)))
        kinetic = np.zeros((n, len(ids)))
        v = np.interp(t, self.time, self.velocity)
        element_mass = 0.0
        for p in self.model.paths:
            for e in p.elements:
                w = np.interp(t, self.time, self.plastic_energy[(p.name, e.part_id)])
                internal[:, col[e.part_id]] += (1.0 - e.hourglass) * w
                hourglass[:, col[e.part_id]] += e.hourglass * w
                kinetic[:, col[e.part_id]] += 0.5 * e.mass * v ** 2
                element_mass += e.mass
            # Elastic energy of the path, spread over its parts (in series).
            f = np.interp(t, self.time, self.path_force[p.name])
            for e in p.elements:
                internal[:, col[e.part_id]] += f ** 2 / (2.0 * p.stiffness) / len(
                    p.elements)
        body = self.model.mass - element_mass
        kinetic[:, col[self.model.body_part[0]]] = 0.5 * body * v ** 2
        return PartEnergies(t, np.array(ids), internal, kinetic, hourglass,
                            part_names=parts)

    def section_output(self, times: ArrayLike | None = None) -> AsciiOutput:
        """Section forces as LS-DYNA's secforc gives them (kN, kN mm)."""
        t = self.time if times is None else np.asarray(times, dtype=float)
        secs = self.sections()
        ids = tuple(secs)
        data: dict[str, FloatArray] = {
            k: np.zeros((len(t), len(ids))) for k in (
                "x_force", "y_force", "z_force", "total_force", "x_moment",
                "y_moment", "z_moment", "total_moment", "x_centroid",
                "y_centroid", "z_centroid", "area")}
        decel = np.interp(t, self.time, self.wall_force) / self.model.mass
        for j, sid in enumerate(ids):
            path, s = secs[sid]
            fp = np.interp(t, self.time, self.path_force[path.name])
            f = s.share * np.where(fp > 0, np.maximum(fp - s.mass_ahead * decel, 0.0),
                                   0.0)
            d = np.asarray(s.direction, dtype=float)
            vec = f[:, None] * d[None, :]
            data["x_force"][:, j], data["y_force"][:, j], data["z_force"][:, j] = vec.T
            data["total_force"][:, j] = np.linalg.norm(vec, axis=1)
            lever = np.array([0.0, 12.0, 25.0])          # mm, offset of the load
            moment = np.cross(lever, vec)
            for k, name in enumerate(("x_moment", "y_moment", "z_moment")):
                data[name][:, j] = moment[:, k]
            data["total_moment"][:, j] = np.linalg.norm(moment, axis=1)
            for k, name in enumerate(("x_centroid", "y_centroid", "z_centroid")):
                data[name][:, j] = s.centroid[k] + (
                    np.interp(t, self.time, self.displacement) if k == 0 else 0.0)
            data["area"][:, j] = s.area
        names = {sid: secs[sid][1].name for sid in ids}
        return AsciiOutput("secforc", t, ids, data, names=names,
                           title=self._title(), version=_VERSION_LINE)

    def weld_output(self, times: ArrayLike | None = None) -> AsciiOutput:
        """Spot weld forces as LS-DYNA's swforc gives them (kN): a weld
        has no force and ``failure`` 1 from its failure time on."""
        t = self.weld_time if times is None else np.asarray(times, dtype=float)
        n = len(self.weld_ids)
        k = np.clip(np.searchsorted(self.weld_time, t, side="right") - 1, 0, None)
        failed = t[:, None] >= np.where(np.isfinite(self.weld_failure_time),
                                        self.weld_failure_time, np.inf)[None, :]
        lengths = {i: w.length for p in self.model.paths for w in p.welds
                   for i in w.ids}
        data = {
            "axial": np.where(failed, 0.0, self.weld_axial[k].reshape(len(t), n)),
            "shear": np.where(failed, 0.0, self.weld_shear[k].reshape(len(t), n)),
            "failure": failed.astype(float),
            "length": np.tile([lengths[i] for i in self.weld_ids], (len(t), 1)),
        }
        return AsciiOutput("swforc", t, self.weld_ids, data, title=self._title(),
                           version=_VERSION_LINE)

    def _title(self) -> str:
        return (f"Synthetic full-width frontal, {self.model.speed:g} km/h, "
                f"{self.model.name}")

    def write(self, directory: str | Path, *, matsum_interval: float = 0.5,
              secforc_interval: float = 0.2, swforc_interval: float = 0.5,
              date: dt.date | None = None) -> tuple[Path, Path]:
        """Write ``matsum`` and ``secforc`` (the paths returned) and, when
        the model has spot welds, ``swforc`` into ``directory`` (created),
        sampled every ``matsum_interval`` / ``secforc_interval`` /
        ``swforc_interval`` ms."""
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        end = float(self.time[-1])
        tm = np.arange(0.0, end + 1e-9, matsum_interval)
        ts = np.arange(0.0, end + 1e-9, secforc_interval)
        p = self.part_energies(tm)
        m = write_matsum(folder / "matsum", p.time, p.part_ids, p.part_names,
                         p.internal, p.kinetic, p.hourglass, title=self._title(),
                         date=date)
        s = write_secforc(folder / "secforc", self.section_output(ts),
                          title=self._title(), date=date)
        if self.weld_ids:
            tw = np.arange(0.0, end + 1e-9, swforc_interval)
            write_swforc(folder / "swforc", self.weld_output(tw),
                         title=self._title(), date=date)
        return m, s


class _Welds:
    """Spot welds of one load path during the simulation."""

    def __init__(self, path: LoadPath) -> None:
        self.lines = path.welds
        self.ids = [i for w in self.lines for i in w.ids]
        self.line = np.repeat(np.arange(len(self.lines)),
                              [w.count for w in self.lines])
        self.base = np.concatenate([
            w.shear_share * np.linspace(1.0 + w.gradient, 1.0 - w.gradient, w.count)
            / w.count for w in self.lines])
        self.peel = np.repeat([w.peel for w in self.lines],
                              [w.count for w in self.lines])
        self.sn = np.repeat([w.axial_strength for w in self.lines],
                            [w.count for w in self.lines])
        self.ss = np.repeat([w.shear_strength for w in self.lines],
                            [w.count for w in self.lines])
        self.alive = np.ones(len(self.ids), dtype=bool)
        self.failed_at = np.full(len(self.ids), math.nan)
        self.factor: dict[int, float] = {}          # part ID -> strength factor

    def update(self, force: float, crushed: dict[int, float], time: float
               ) -> tuple[FloatArray, FloatArray]:
        """Forces of the welds for a path force; fails those at their limit."""
        lost = np.array([1.0 - self.alive[self.line == j].mean()
                         for j in range(len(self.lines))])
        boost = np.array([1.0 + w.redistribution * x / (1.0 - x) if x < 1 else 0.0
                          for w, x in zip(self.lines, lost)])
        shear = self.base * force * boost[self.line] * self.alive
        fold = np.array([crushed[w.part_id] for w in self.lines])
        axial = self.peel * shear * fold[self.line]
        fails = self.alive & ((axial / self.sn) ** 2 + (shear / self.ss) ** 2 >= 1.0)
        if fails.any():
            self.alive &= ~fails
            self.failed_at[fails] = time
            shear[fails] = 0.0
            axial[fails] = 0.0
            for j, w in enumerate(self.lines):
                gone = 1.0 - self.alive[self.line == j].mean()
                self.factor[w.part_id] = 1.0 - w.strength_loss * gone
        return axial, shear


def simulate(model: FrontalModel, *, end_time: float = 100.0,
             dt: float = 0.01, weld_interval: float = 0.1) -> FrontalRun:
    """Run the model from first contact to ``end_time`` ms (time step
    ``dt`` ms, semi-implicit Euler; spot welds are checked every
    ``weld_interval`` ms)."""
    if not model.paths:
        raise ValueError("The model has no load paths.")
    steps = int(round(end_time / dt))
    every = max(1, int(round(weld_interval / dt)))
    welds = {p.name: _Welds(p) for p in model.paths if p.welds}
    rec_w: list[tuple[float, dict[str, tuple[FloatArray, FloatArray]]]] = []
    v = model.speed / 3.6                                  # mm/ms
    d = 0.0
    plastic = {p.name: 0.0 for p in model.paths}
    crush = {(p.name, e.part_id): 0.0 for p in model.paths for e in p.elements}
    energy = dict.fromkeys(crush, 0.0)
    rec_t = np.empty(steps + 1)
    rec_d = np.empty(steps + 1)
    rec_v = np.empty(steps + 1)
    rec_f = {p.name: np.empty(steps + 1) for p in model.paths}
    rec_c = {k: np.empty(steps + 1) for k in crush}
    rec_e = {k: np.empty(steps + 1) for k in crush}
    bottomed: set[str] = set()

    def record(i: int, forces: dict[str, float]) -> None:
        rec_t[i], rec_d[i], rec_v[i] = i * dt, d, v
        for name, f in forces.items():
            rec_f[name][i] = f
        for k in crush:
            rec_c[k][i] = crush[k]
            rec_e[k][i] = energy[k]

    record(0, dict.fromkeys(plastic, 0.0))
    for i in range(1, steps + 1):
        forces = {}
        for p in model.paths:
            u = d - p.gap
            f = p.stiffness * (u - plastic[p.name])
            if f <= 0.0:
                forces[p.name] = 0.0
                continue
            for _ in range(len(p.elements) + 2):
                remaining = [e for e in p.elements
                             if crush[(p.name, e.part_id)] < e.length - 1e-9]
                if not remaining:
                    bottomed.add(p.name)
                    break
                held = welds[p.name].factor if p.name in welds else {}

                def strength(e: CrushElement, path: str = p.name,
                             held: dict[int, float] = held) -> float:
                    return e.strength(crush[(path, e.part_id)]) * held.get(
                        e.part_id, 1.0)

                weakest = min(remaining, key=strength)
                key = (p.name, weakest.part_id)
                s = strength(weakest)
                if f <= s:
                    break
                step = min((f - s) / p.stiffness, weakest.length - crush[key])
                crush[key] += step
                plastic[p.name] += step
                energy[key] += s * step
                f = p.stiffness * (u - plastic[p.name])
            forces[p.name] = f
        v -= sum(forces.values()) / model.mass * dt
        d += v * dt
        record(i, forces)
        if welds and i % every == 0:
            state = {}
            for p in model.paths:
                if p.name in welds:
                    fold = {e.part_id: crush[(p.name, e.part_id)] / e.length
                            for e in p.elements}
                    state[p.name] = welds[p.name].update(forces[p.name], fold, i * dt)
            rec_w.append((i * dt, state))
    notes = tuple(f"load path {name} crushed completely (blocked)"
                  for name in sorted(bottomed))
    if not welds:
        return FrontalRun(model, rec_t, rec_d, rec_v, rec_f, rec_c, rec_e, notes,
                          {"dt": dt})
    ids = [i for w in welds.values() for i in w.ids]
    order = np.argsort(ids)
    zero = np.zeros(len(ids))
    axial = np.vstack([zero] + [np.concatenate([s[n][0] for n in welds])
                                for _, s in rec_w])[:, order]
    shear = np.vstack([zero] + [np.concatenate([s[n][1] for n in welds])
                                for _, s in rec_w])[:, order]
    failed_at = np.concatenate([w.failed_at for w in welds.values()])[order]
    return FrontalRun(model, rec_t, rec_d, rec_v, rec_f, rec_c, rec_e, notes,
                      {"dt": dt}, np.array([0.0] + [t for t, _ in rec_w]),
                      tuple(int(ids[k]) for k in order), axial, shear, failed_at)


# --- Writers -------------------------------------------------------------------


def _header(title: str, date: dt.date | None) -> list[str]:
    day = (date or dt.date(2026, 1, 1)).strftime("%m/%d/%Y")
    return [f" {title[:72]:<72}", f"{_VERSION_LINE} date {day}", ""]


def _legend(names: dict[int, str], ids: Sequence[int]) -> list[str]:
    lines = ["{BEGIN LEGEND}", " Entity #        Title"]
    lines += [f"{int(i):9d}     {names.get(int(i), ''):<70}" for i in ids]
    return lines + ["{END LEGEND}", "", "", ""]


def _e(value: float, width: int, digits: int = 4) -> str:
    return f"{value + 0.0:{width}.{digits}E}"   # no "-0.0000E+00"


def write_matsum(path: str | Path, time: ArrayLike, part_ids: Sequence[int] | ArrayLike,
                 names: dict[int, str], internal: ArrayLike,
                 kinetic: ArrayLike | None = None, hourglass: ArrayLike | None = None,
                 *, title: str = "", date: dt.date | None = None) -> Path:
    """Write part energies (time, part) in the LS-DYNA matsum layout."""
    t = np.asarray(time, dtype=float)
    ids = [int(i) for i in np.asarray(part_ids)]
    ie = np.asarray(internal, dtype=float)
    ke = np.zeros_like(ie) if kinetic is None else np.asarray(kinetic, dtype=float)
    hg = np.zeros_like(ie) if hourglass is None else np.asarray(hourglass, dtype=float)
    if ie.shape != (len(t), len(ids)) or ke.shape != ie.shape or hg.shape != ie.shape:
        raise ValueError("Energies must have shape (time, part).")
    out = _header(title, date) + _legend(names, ids)
    z = _e(0.0, 13)
    for i, ti in enumerate(t):
        out += ["", f" time ={_e(ti, 13)}"]
        for j, pid in enumerate(ids):
            out += [
                f" mat.#={pid:5d}             inten={_e(ie[i, j], 13)}     kinen="
                f"{_e(ke[i, j], 13)}     eroded_ie={z}     eroded_ke={z}",
                f" x-mom={z}     y-mom={z}     z-mom={z}",
                f" x-rbv={z}     y-rbv={z}     z-rbv={z}",
                f"                         hgeng={_e(hg[i, j], 13)}"
                f"                             eroded_he={z}",
                "", "",
            ]
        out += ["", ""]
    target = Path(path)
    target.write_text("\n".join(out) + "\n")
    return target


def write_secforc(path: str | Path, output: AsciiOutput, *, title: str = "",
                  date: dt.date | None = None) -> Path:
    """Write section forces (an `AsciiOutput` with the secforc channels:
    forces, moments, centroids, area) in the LS-DYNA secforc layout."""
    need = ("x_force", "y_force", "z_force", "total_force")
    missing = [c for c in need if c not in output.data]
    if missing:
        raise ValueError(f"Missing channels {missing}.")

    def get(name: str, i: int, j: int) -> float:
        a = output.data.get(name)
        return 0.0 if a is None or not np.isfinite(a[i, j]) else float(a[i, j])

    out = _header(title or output.title, date) + _legend(output.names, output.ids)
    out += [" line#1  section#     time        x-force     y-force     z-force    "
            "magnitude",
            " line#2  resultant  moments       x-moment    y-moment    z-moment   "
            "magnitude",
            " line#3  centroids                x           y           z            "
            "area  "]
    for i, ti in enumerate(output.time):
        for j, sid in enumerate(output.ids):
            f = [get(c, i, j) for c in need]
            m = [get(c, i, j) for c in ("x_moment", "y_moment", "z_moment",
                                        "total_moment")]
            c = [get(k, i, j) for k in ("x_centroid", "y_centroid", "z_centroid",
                                        "area")]
            out += [
                f"{int(sid):12d}{_e(ti, 15, 5)}{_e(f[0], 15)}"
                + "".join(_e(x, 12) for x in f[1:]),
                f"ac ID ={0:8d}{_e(m[0], 27)}" + "".join(_e(x, 12) for x in m[1:]),
                f"{_e(c[0], 42)}" + "".join(_e(x, 12) for x in c[1:]),
                "",
            ]
    target = Path(path)
    target.write_text("\n".join(out) + "\n")
    return target


def write_swforc(path: str | Path, output: AsciiOutput, *, title: str = "",
                 date: dt.date | None = None, element: str = "spotweld beam") -> Path:
    """Write spot weld forces (an `AsciiOutput` with ``axial``, ``shear``
    and ``failure``, optionally ``length``) in the LS-DYNA swforc layout.
    A weld with ``failure`` 1 or more is written as failed."""
    missing = [c for c in ("axial", "shear", "failure") if c not in output.data]
    if missing:
        raise ValueError(f"Missing channels {missing}.")
    length = output.data.get("length")
    head = (" constraint #      axial        shear         time  failure"
            "                                       length  rslt moment      torsion")
    out = _header(title or output.title, date)
    for i, ti in enumerate(output.time):
        out.append(head)
        for j, wid in enumerate(output.ids):
            failed = output.data["failure"][i, j] >= 1.0
            flag = "failure" if failed else "    0.0"
            extra = "" if length is None else (
                f"{_e(float(length[i, j]), 13, 5)}{_e(0.0, 13, 5)}{_e(0.0, 13, 5)}")
            out.append(f"{j + 1:11d}{_e(float(output.data['axial'][i, j]), 13, 5)}"
                       f"{_e(float(output.data['shear'][i, j]), 13, 5)}"
                       f"{_e(float(ti), 13, 5)}  {flag}    {element}  ID "
                       f"{int(wid):10d}{extra}")
        out.append("")
    target = Path(path)
    target.write_text("\n".join(out) + "\n")
    return target
