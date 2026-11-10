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

- **Model quality** (`ModelQuality`): mass scaling (added mass), time
  step, contact friction and negative contact energy, warnings and the
  termination, as a solver would report them.

`frontal_model` gives a reference car and variants with known causes
(`VARIANTS`); `simulate` runs it; `FrontalRun.write` writes ``matsum``
(part energies), ``secforc`` (section forces), ``swforc`` (spot weld
forces), ``glstat`` (global energies), ``sleout`` (contact energies) and
a short ``d3hsp`` in the LS-DYNA ASCII format, so every reader and
analysis of crashmetrics can be tried without a solver. `write_matsum`,
`write_secforc`, `write_swforc`, `write_glstat`, `write_sleout`,
`write_d3hsp` and `write_nodout` (nodal time histories, used by
`crashmetrics.pedestrian.synthetic`) write any data in those formats.

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

from crashmetrics.energy_check import GlobalEnergies, PartEnergies
from crashmetrics.lsdyna_ascii import AsciiOutput

__all__ = [
    "VARIANTS",
    "CrushElement",
    "FrontalModel",
    "FrontalRun",
    "LoadPath",
    "ModelQuality",
    "Section",
    "WeldLine",
    "frontal_model",
    "simulate",
    "write_d3hsp",
    "write_glstat",
    "write_matsum",
    "write_nodout",
    "write_secforc",
    "write_sleout",
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
class ModelQuality:
    """What a solver would report about the model itself (it does not
    change the crash): mass scaling, time step, contacts, messages and
    termination."""

    added_mass: float = 0.004
    """Mass added by mass scaling at the start, share of the model mass."""
    added_mass_growth: float = 0.002
    """Further share added by the time of maximum crush."""
    timestep: float = 1.0e-3
    """Time step, ms (``dt2ms`` is written as its negative over 0.9)."""
    mass_scaled: bool = True
    timestep_drop: float = 0.0
    """Share by which the time step falls at maximum crush (without mass
    scaling)."""
    friction: float = 0.008
    """Contact friction energy, share of the absorbed energy."""
    contact_loss: float = 0.0
    """Negative energy of the self contact, share of the absorbed energy."""
    smallest_timestep: float = 0.9e-3
    """Smallest element time step before mass scaling, ms."""
    smallest_part: int = 110
    warnings: int = 2
    error_at: float | None = None
    """ms at which the run stops with an error termination."""
    mass_center: tuple[float, float, float] = (1310.0, 2.0, 545.0)
    """mm."""


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
    quality: ModelQuality = field(default_factory=ModelQuality)

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
    if name == "poor_model_quality":
        # The same crash, reported by a poorly prepared model.
        for pid in (110, 111):
            car = car.replace_element(pid, hourglass=0.16)
        return replace(car, name=name, quality=ModelQuality(
            added_mass=0.058, added_mass_growth=0.021, contact_loss=0.045,
            smallest_timestep=0.21e-3, smallest_part=150, warnings=37))
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
    "poor_model_quality": "The baseline crash from a poorly prepared model: 5.8 % "
                          "added mass rising to 7.9 %, 16 % hourglass energy in "
                          "the crash boxes, negative contact energy, very small "
                          "elements",
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

    def part_masses(self) -> dict[int, float]:
        """Part ID -> mass, kg (the body takes the rest of the model mass)."""
        out: dict[int, float] = {}
        for p in self.model.paths:
            for e in p.elements:
                out[e.part_id] = out.get(e.part_id, 0.0) + e.mass
        out[self.model.body_part[0]] = self.model.mass - sum(out.values())
        return dict(sorted(out.items()))

    def _absorbed(self, t: FloatArray) -> FloatArray:
        """Crush energy of all parts at times ``t``, J."""
        total = np.sum(list(self.plastic_energy.values()), axis=0)
        return np.asarray(np.interp(t, self.time, total))

    def contact_output(self, times: ArrayLike | None = None) -> AsciiOutput:
        """Contact energies as LS-DYNA's sleout gives them (J): the wall
        contact and a bumper contact with friction, and the self contact
        of the front end, which loses energy when the model's
        ``contact_loss`` is set."""
        t = self.time if times is None else np.asarray(times, dtype=float)
        q = self.model.quality
        w = self._absorbed(t)
        ids = (1, 2, 3)
        names = {1: "Vehicle to rigid wall", 2: "Front end self contact",
                 3: "Bumper to crash boxes"}
        friction = np.column_stack((0.6 * q.friction * w, 0.3 * q.friction * w,
                                    0.1 * q.friction * w))
        surfa = 0.5 * friction
        surfa[:, 1] -= 0.5 * q.contact_loss * w
        surfb = surfa.copy()
        data = {"surfa_energy": surfa, "surfb_energy": surfb,
                "friction_energy": friction}
        totals = {"surfa_energy": surfa.sum(axis=1), "surfb_energy": surfb.sum(axis=1),
                  "total_energy": (surfa + surfb).sum(axis=1),
                  "friction_energy": friction.sum(axis=1)}
        return AsciiOutput("sleout", t, ids, data, totals, names, self._title(),
                           _VERSION_LINE)

    def global_energies(self, times: ArrayLike | None = None) -> GlobalEnergies:
        """Global energies as LS-DYNA's glstat gives them (J, kg, ms):
        the part energies summed, the contact (sliding) energy, the added
        mass and the time step."""
        t = self.time if times is None else np.asarray(times, dtype=float)
        q = self.model.quality
        p = self.part_energies(t)
        kinetic = np.nan_to_num(p.kinetic).sum(axis=1)
        internal = p.internal.sum(axis=1)
        hourglass = np.nan_to_num(p.hourglass).sum(axis=1)
        sliding = self.contact_output(t).totals["total_energy"]
        total = kinetic + internal + hourglass + sliding
        w = self._absorbed(t)
        progress = w / max(float(np.max(w)), 1e-12)
        added = (q.added_mass + q.added_mass_growth * progress) * self.model.mass
        return GlobalEnergies(
            t, kinetic, internal, hourglass, sliding, total=total,
            energy_ratio=total / total[0], added_mass=added,
            added_mass_percent=100.0 * added / self.model.mass,
            time_step=q.timestep * (1.0 - q.timestep_drop * progress))

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
        """Write ``matsum`` and ``secforc`` (the paths returned), ``glstat``,
        ``sleout``, ``d3hsp`` and, when the model has spot welds,
        ``swforc`` into ``directory`` (created), sampled every
        ``matsum_interval`` / ``secforc_interval`` / ``swforc_interval``
        ms. A model with ``quality.error_at`` stops there."""
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        q = self.model.quality
        planned = float(self.time[-1])
        end = planned if q.error_at is None else min(planned, q.error_at)
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
        write_glstat(folder / "glstat", self.global_energies(tm), title=self._title(),
                     date=date)
        write_sleout(folder / "sleout", self.contact_output(tm), title=self._title(),
                     date=date)
        small = [("shell", q.smallest_part * 1000 + k, q.smallest_part,
                  q.smallest_timestep * (1.0 + 0.004 * k)) for k in range(6)]
        small += [("shell", 120001 + k, 120, 1.02e-3 * (1.0 + 0.003 * k))
                  for k in range(4)]
        write_d3hsp(
            folder / "d3hsp", title=self._title(), part_masses=self.part_masses(),
            total_mass=self.model.mass, mass_center=q.mass_center,
            end_time=planned, problem_time=end,
            dt2ms=-q.timestep / 0.9 if q.mass_scaled else 0.0,
            smallest_timesteps=sorted(small, key=lambda r: r[3]),
            warnings=q.warnings, error=q.error_at is not None,
            counts={"nodes": 412_530, "shell_elements": 398_214,
                    "solid_elements": 5_120, "beam_elements": len(self.weld_ids),
                    "materials": len(self.part_masses()), "contacts": 3},
            date=date)
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


_NODOUT_HEADER = (" nodal point  x-disp     y-disp      z-disp      x-vel       y-vel"
                  "       z-vel      x-accl      y-accl      z-accl      x-coor"
                  "      y-coor      z-coor")


def write_nodout(path: str | Path, time: ArrayLike, node_ids: Sequence[int] | ArrayLike,
                 displacement: ArrayLike, velocity: ArrayLike, acceleration: ArrayLike,
                 coordinates: ArrayLike | None = None, *,
                 names: dict[int, str] | None = None, title: str = "",
                 date: dt.date | None = None) -> Path:
    """Write nodal displacements, velocities and accelerations (each
    (time, node, 3)) and optionally current coordinates in the LS-DYNA
    nodout layout (translational block only)."""
    t = np.asarray(time, dtype=float)
    ids = [int(i) for i in np.asarray(node_ids)]
    arrays = [np.asarray(a, dtype=float)
              for a in (displacement, velocity, acceleration)]
    coords = (np.zeros_like(arrays[0]) if coordinates is None
              else np.asarray(coordinates, dtype=float))
    shape = (len(t), len(ids), 3)
    if any(a.shape != shape for a in [*arrays, coords]):
        raise ValueError(f"Arrays must have shape (time, node, 3) = {shape}.")
    out = _header(title, date) + _legend(names or {}, ids)
    for i, ti in enumerate(t):
        out += [f" n o d a l   p r i n t   o u t   f o r   t i m e  s t e p{i + 1:8d}"
                f"                              ( at time {ti:.7E} )", "",
                _NODOUT_HEADER]
        for j, nid in enumerate(ids):
            values = [*arrays[0][i, j], *arrays[1][i, j], *arrays[2][i, j],
                      *coords[i, j]]
            out.append(f"{nid:9d}" + "".join(f"{v + 0.0:12.5E}" for v in values))
        out += ["", "", ""]
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


def write_glstat(path: str | Path, energies: GlobalEnergies, *, title: str = "",
                 date: dt.date | None = None) -> Path:
    """Write global energies in the LS-DYNA glstat layout (the energy
    lines, the energy ratio, the time step and the added mass)."""
    g = energies
    n = len(g.time)

    def col(a: FloatArray | None) -> FloatArray:
        return np.zeros(n) if a is None else np.asarray(a, dtype=float)

    rows: list[tuple[str, FloatArray]] = [
        ("time...........................", g.time),
        ("time step......................", col(g.time_step)),
        ("kinetic energy.................", g.kinetic),
        ("internal energy................", g.internal),
        ("hourglass energy ..............", col(g.hourglass)),
        ("system damping energy..........", col(g.damping)),
        ("sliding interface energy.......", col(g.sliding)),
        ("external work..................", col(g.external_work)),
        ("total energy...................", g.total_energy()),
        ("total energy / initial energy..", g.ratio()),
    ]
    out = _header(title, date)
    for i in range(n):
        out += ["", f" dt of cycle {i * 500 + 1:7d} is controlled by shell "
                "element of the model", ""]
        out += [f" {label}{_e(float(a[i]), 14, 5)}" for label, a in rows]
        if g.added_mass is not None:
            out += ["", "",
                    " added mass....................."
                    f"{_e(float(g.added_mass[i]), 14, 5)}",
                    " percentage increase............"
                    f"{_e(float(col(g.added_mass_percent)[i]), 14, 5)}"]
        out += [""]
    target = Path(path)
    target.write_text("\n".join(out) + "\n")
    return target


def write_sleout(path: str | Path, output: AsciiOutput, *, title: str = "",
                 date: dt.date | None = None) -> Path:
    """Write contact energies (an `AsciiOutput` with ``surfa_energy``,
    ``surfb_energy`` and ``friction_energy``) in the LS-DYNA sleout
    layout."""
    need = ("surfa_energy", "surfb_energy", "friction_energy")
    missing = [c for c in need if c not in output.data]
    if missing:
        raise ValueError(f"Missing channels {missing}.")
    out = _header(title or output.title, date) + _legend(output.names, output.ids)
    for i, ti in enumerate(output.time):
        a, b, f = (output.data[c][i] for c in need)
        out += [f" contact interface energy file, time={_e(float(ti), 14, 7)}",
                f"    #             slave       master       cycle={i * 500 + 1:14d}"
                "    frictional", ""]
        out += [f"{int(cid):10d}{_e(float(a[j]), 13)}{_e(float(b[j]), 13)}"
                f"{'':31}{_e(float(f[j]), 13)}" for j, cid in enumerate(output.ids)]
        out += ["",
                f" summary   total slave side={_e(float(np.sum(a)), 14, 7)}",
                f"           total mastr side={_e(float(np.sum(b)), 14, 7)}",
                "           total energy    ="
                f"{_e(float(np.sum(a) + np.sum(b)), 14, 7)}",
                f"           friction energy ={_e(float(np.sum(f)), 14, 7)}",
                "", "", ""]
    target = Path(path)
    target.write_text("\n".join(out) + "\n")
    return target


def write_d3hsp(
    path: str | Path,
    *,
    title: str = "",
    part_masses: dict[int, float],
    total_mass: float,
    mass_center: tuple[float, float, float] | None = None,
    end_time: float,
    problem_time: float | None = None,
    dt2ms: float = 0.0,
    smallest_timesteps: Sequence[tuple[str, int, int, float]] = (),
    warnings: int = 0,
    error: bool = False,
    counts: dict[str, int] | None = None,
    date: dt.date | None = None,
) -> Path:
    """Write the lines of an LS-DYNA d3hsp that `crashmetrics.d3hsp`
    reads: run information, model size, termination time and ``dt2ms``,
    the mass summary with the mass centre, the smallest time steps,
    warnings and the termination (with an error message when ``error``).
    """
    day = date or dt.date(2026, 1, 1)
    c = counts or {}

    def setting(label: str, value: str) -> str:
        return f"    {label:.<47}{value:>14}"

    out = [f" {title[:72]:<72}", "",
           f"      Date: {day.strftime('%m/%d/%Y')}      Time: 00:00:00",
           "     |  Version : smp s crashmetrics synthetic         |",
           "     |  Revision: not LS-DYNA output                   |",
           "     |  Precision  : Single precision (I4R4)             |", "",
           " Input file: synthetic.k", "",
           setting("number of materials or property sets", str(c.get("materials", 0))),
           setting("number of nodal+scalar points", str(c.get("nodes", 0))),
           setting("number of solid elements", str(c.get("solid_elements", 0))),
           setting("number of beam elements", str(c.get("beam_elements", 0))),
           setting("number of shell elements", str(c.get("shell_elements", 0))),
           setting("number of number of contact definitions",
                   str(c.get("contacts", 0))),
           setting("termination time", _e(end_time, 14)),
           setting("time step scale factor", _e(0.9, 14)),
           setting("time step size for mass scaled solution, dt2ms", _e(dt2ms, 14)),
           "", " summary of mass"]
    out += [f" part id   ={pid:9d}   mass={_e(mass, 15, 8)}"
            for pid, mass in part_masses.items()]
    out += ["", f" t o t a l  m a s s          ={_e(total_mass, 15, 8)}"]
    if mass_center is not None:
        out += [f" {axis}-coordinate of mass center ={_e(v, 15, 8)}"
                for axis, v in zip("xyz", mass_center)]
    if smallest_timesteps:
        out += ["", f" {len(smallest_timesteps)} smallest timesteps",
                " ------------------------------------------------",
                " element       number                part    timestep"]
        out += [f" {kind:<10}{eid:10d}{pid:20d}{_e(step, 12)}"
                for kind, eid, pid, step in smallest_timesteps]
    for k in range(warnings):
        out += ["", f" *** Warning {40538 if k % 2 else 41123} "
                f"({'SOL+538' if k % 2 else 'SOL+1123'})",
                "     Synthetic warning of the crashmetrics teaching model."]
    reached = end_time if problem_time is None else problem_time
    if error:
        out += ["", " *** Error 40509 (SOL+509)",
                "     Negative volume in a solid element (synthetic).", "",
                " E r r o r   t e r m i n a t i o n"]
    else:
        out += ["", " *** termination time reached ***", "",
                " N o r m a l    t e r m i n a t i o n"]
    out += ["", f" Problem time       ={_e(reached, 14)}",
            f" Problem cycle      ={int(reached * 1000):10d}"]
    target = Path(path)
    target.write_text("\n".join(out) + "\n")
    return target
