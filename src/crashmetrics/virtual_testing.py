"""Euro NCAP frontal sled and virtual testing (VTC), 2026 protocols.

Implements the frontal part of

- Euro NCAP Crash Protection Virtual Testing Protocol v1.0.2 (December
  2025): model quality criteria (Section 5.2), the ISO/TS 18571 sensor
  score (5.3.1), the assessment criteria deviation (5.3.2) and the
  acceptance criteria (5.4), and
- Euro NCAP Crash Protection Frontal Impact Protocol v1.2: the load case
  matrix (Section 3.3.1), the sled and virtual testing score (10 points:
  driver and front passenger, 2.5 sled and 2.5 virtual each) and its
  rules (no HBM data: virtual score halved; validation not met: sled
  load cases only).

Workflow:

1. The vehicle manufacturer simulates the load cases of
   `FRONTAL_LOAD_CASES` (Hybrid III 5th, 50th and 95th, 35, 50 and
   56 km/h, plus a 50th percentile human body model driver).
2. Two load cases are run as physical sled tests. For each, the
   simulation is validated: model quality (`check_model_quality`),
   ISO/TS 18571 sensor scores above 0.5 (`sensor_score`) and assessment
   criteria within 30 % (`kpi_checks`), combined by
   `validate_load_case`.
3. `score_sled_virtual` scores one occupant from the two sled tests and
   the three virtual-only load cases.

Interpretations where the protocols are not explicit are listed in the
protocol notes (search "virtual testing").
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import ArrayLike

from crashmetrics.correlation import iso18571
from crashmetrics.energy_check import GlobalEnergies, PartEnergies
from crashmetrics.frontal_scoring import (
    ADULT_REGIONS,
    BAND_FRACTIONS,
    DummyScore,
    Occupant,
    _limits_for,
    score_dummy,
)

__all__ = [
    "FRONTAL_LOAD_CASES",
    "FRONTAL_SENSORS",
    "KPI_DEVIATION_MAX",
    "KPI_MIN_TEST_RATIO",
    "QUALITY_LIMITS",
    "SENSOR_SCORE_MIN",
    "SLED_REGION_POINTS",
    "SLED_VIRTUAL_MAX",
    "VIRTUAL_NOT_APPLICABLE",
    "VIRTUAL_REGION_POINTS",
    "Check",
    "CheckResult",
    "KpiResult",
    "LoadCase",
    "SensorScore",
    "SledVirtualScore",
    "axis_weights",
    "check_model_quality",
    "frontal_end_time",
    "kpi_check",
    "kpi_checks",
    "model_quality_inputs",
    "score_sled_virtual",
    "sensor_score",
    "validate_load_case",
]

VT_PROTOCOL = "Euro NCAP Crash Protection Virtual Testing Protocol v1.0.2"
FRONTAL_PROTOCOL = "Euro NCAP Crash Protection Frontal Impact Protocol v1.2"


# --- Load cases -------------------------------------------------------------------

@dataclass(frozen=True)
class LoadCase:
    """One column of the frontal sled and virtual load case matrix."""

    number: int
    speed: int
    """Severity, km/h."""
    pulse: str
    driver: str
    """Dummy key (`crashmetrics.frontal_scoring.DUMMY_LIMITS`) or
    ``"hbm_50"`` for the human body model."""
    front_passenger: str | None


FRONTAL_LOAD_CASES: dict[int, LoadCase] = {
    1: LoadCase(1, 50, "UN R137 pulse (VM)", "hybrid3_50", "hybrid3_95"),
    2: LoadCase(2, 56, "56 km/h rigid wall pulse (VM)", "hybrid3_95", "hybrid3_05"),
    3: LoadCase(3, 35, "Euro NCAP FWDB pulse", "hybrid3_50", "hybrid3_05"),
    4: LoadCase(4, 35, "Euro NCAP FWDB pulse", "hybrid3_05", "hybrid3_50"),
    5: LoadCase(5, 56, "56 km/h rigid wall pulse (VM)", "hybrid3_05", "hybrid3_95"),
    6: LoadCase(6, 50, "UN R137 pulse (VM)", "hbm_50", None),
}
"""Frontal Impact Protocol v1.2, Section 3.3.1 (columns numbered here
from left to right). Load cases 1-5 are Hybrid III load cases (two of
them sled tested); 6 is the human body model driver."""


# --- Thresholds ------------------------------------------------------------------

QUALITY_LIMITS: dict[str, float] = {
    "hourglass_ratio": 0.10,
    "added_mass_ratio": 0.05,
    "added_mass_ratio_separate": 0.025,
    "hpoint_dz_mm": 10.0,
    "hpoint_window_ms": 5.0,
    "sled_x_score": 0.95,
    "end_time_margin": 0.40,
}
"""Virtual Testing Protocol Section 5.2 and definitions: hourglass
energy below 10 % of the maximum internal energy (whole set-up and each
dummy), added mass below 5 % of the model mass (2.5 % for separate
driver and passenger models), H-point z displacement below 10 mm in the
first 5 ms, sled x acceleration ISO score above 0.95 (separate models),
end time = time of maximum head x excursion + 40 %."""

SENSOR_SCORE_MIN = 0.5
"""Acceptance: sensor ISO score must exceed 0.5 (Section 5.4.1)."""

KPI_DEVIATION_MAX = 0.30
"""Acceptance: dAC below 30 % for each assessment criterion (5.4.2)."""

KPI_MIN_TEST_RATIO = 0.5
"""dAC is calculated where AC_test / AC_limit >= 50 % (5.3.2)."""

FRONTAL_SENSORS: dict[str, tuple[str, ...]] = {
    "head": ("x", "y", "z"),
    "chest_acceleration": ("x", "y", "z"),
    "chest_deflection": ("x",),
    "pelvis": ("x", "y", "z"),
    "sled": ("x",),
    "shoulder_belt": ("force",),
}
"""Sensors whose ISO score decides acceptance (Section 5.4.1): head CoG,
chest and pelvis accelerations, chest deflection x, sled x acceleration
and shoulder belt (B3) force. Others are monitored only."""

VIRTUAL_NOT_APPLICABLE = ("knee_displacement", "tibia_index", "tibia_force")
"""Criteria not applicable to virtual tests (Frontal Impact Protocol
Sections 3.5.3 and 3.5.4)."""

SLED_REGION_POINTS = 0.625 / 2
"""Points per body region per sled load case (two sled load cases)."""

VIRTUAL_REGION_POINTS = 0.625 / 3
"""Points per body region per virtual load case (three virtual load
cases)."""

SLED_VIRTUAL_MAX = 10.0
"""Sled and virtual testing: driver 5 + front passenger 5 points."""

_REGIONS = tuple(ADULT_REGIONS)  # head_neck, chest_abdomen, knee_femur_pelvis, lower


# --- Results ----------------------------------------------------------------------

@dataclass(frozen=True)
class Check:
    """One acceptance criterion."""

    name: str
    value: float | None
    """None if not assessed."""
    limit: float
    rule: str
    """``"<"`` (value must be below the limit) or ``">"`` (above)."""
    section: str
    """Protocol section."""
    note: str = ""

    @property
    def passed(self) -> bool | None:
        """True or False; None if not assessed."""
        if self.value is None:
            return None
        return self.value < self.limit if self.rule == "<" else self.value > self.limit


@dataclass(frozen=True)
class CheckResult:
    """A set of acceptance criteria (model quality or load case validation)."""

    title: str
    checks: dict[str, Check]
    notes: tuple[str, ...] = field(default=())

    @property
    def passed(self) -> bool:
        """True if every assessed check passed (see also ``complete``)."""
        return all(c.passed for c in self.checks.values() if c.passed is not None)

    @property
    def complete(self) -> bool:
        """True if every check was assessed."""
        return all(c.passed is not None for c in self.checks.values())

    @property
    def failures(self) -> list[str]:
        return [k for k, c in self.checks.items() if c.passed is False]

    @property
    def not_assessed(self) -> list[str]:
        return [k for k, c in self.checks.items() if c.passed is None]

    def summary(self) -> str:
        """A text table, one line per check."""
        status = ("PASS" if self.passed else "FAIL") + (
            "" if self.complete else f" ({len(self.not_assessed)} not assessed)")
        lines = [f"{self.title}: {status}"]
        width = max([len(n) for n in self.checks] + [16])
        for c in self.checks.values():
            value = "-" if c.value is None else f"{c.value:.3f}"
            mark = {None: "not assessed", True: "ok", False: "FAIL"}[c.passed]
            note = f"  {c.note}" if c.note else ""
            lines.append(f"  {c.name:{width}} {value:>8} {c.rule} {c.limit:<6g} "
                         f"{mark:12} [{c.section}]{note}")
        lines.extend(f"  Note: {n}" for n in self.notes)
        return "\n".join(lines)


# --- Model quality -----------------------------------------------------------------

def _check(name: str, value: float | None, limit: float, rule: str, section: str,
           note: str = "") -> Check:
    if value is not None:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite.")
    return Check(name, value, limit, rule, section, note)


def check_model_quality(
    hourglass_ratio: float | None,
    added_mass_ratio: float | None,
    hpoint_dz_mm: float | None,
    dummy_hourglass_ratios: Mapping[str, float] | None = None,
    separate_models: bool = False,
    sled_x_score: float | None = None,
) -> CheckResult:
    """Check the simulation quality criteria (Virtual Testing Protocol 5.2).

    Parameters
    ----------
    hourglass_ratio:
        Maximum hourglass energy / maximum internal energy of the whole
        set-up (e.g. 0.03 for 3 %).
    added_mass_ratio:
        Added mass from mass scaling / total model mass.
    hpoint_dz_mm:
        Largest H-point z displacement in the first 5 ms after t0, mm.
    dummy_hourglass_ratios:
        The same ratio for each dummy, e.g. ``{"driver": 0.04}``.
    separate_models:
        True if driver and passenger are separate models (added mass
        limit 2.5 %, sled x acceleration score required).
    sled_x_score:
        ISO score of the sled x acceleration (separate models).

    Notes
    -----
    Values left None are reported as not assessed.
    """
    limits = QUALITY_LIMITS
    mass_limit = limits["added_mass_ratio_separate" if separate_models
                        else "added_mass_ratio"]
    checks = [
        _check("hourglass_ratio", hourglass_ratio, limits["hourglass_ratio"], "<",
               "5.2", "hourglass / max internal energy"),
        _check("added_mass_ratio", added_mass_ratio, mass_limit, "<", "5.2",
               "added mass / model mass"),
        _check("hpoint_dz_mm", hpoint_dz_mm, limits["hpoint_dz_mm"], "<", "5.2",
               "H-point z displacement, first 5 ms"),
    ]
    for dummy, ratio in (dummy_hourglass_ratios or {}).items():
        checks.append(_check(f"hourglass_ratio[{dummy}]", ratio,
                             limits["hourglass_ratio"], "<", "5.2"))
    if separate_models:
        checks.append(_check("sled_x_score", sled_x_score, limits["sled_x_score"], ">",
                             "5.2", "ISO score of the sled x acceleration"))
    return CheckResult("VTC model quality", {c.name: c for c in checks})


def model_quality_inputs(
    glstat: GlobalEnergies,
    matsum: PartEnergies | None = None,
    dummy_parts: Mapping[str, Sequence[int]] | None = None,
) -> dict[str, object]:
    """Hourglass and added mass ratios from LS-DYNA energy output.

    Returns keyword arguments for `check_model_quality`:
    ``hourglass_ratio`` (from glstat), ``added_mass_ratio`` (peak
    ``percentage increase`` of glstat / 100) and, with ``matsum`` and
    ``dummy_parts`` (dummy name -> part IDs), ``dummy_hourglass_ratios``.
    """
    out: dict[str, object] = {}
    if glstat.hourglass is not None:
        out["hourglass_ratio"] = float(np.nanmax(glstat.hourglass)
                                       / np.nanmax(glstat.internal))
    if glstat.added_mass_percent is not None:
        out["added_mass_ratio"] = float(np.nanmax(glstat.added_mass_percent)) / 100.0
    if matsum is not None and dummy_parts:
        if matsum.hourglass is None:
            raise ValueError("matsum has no hourglass energy.")
        ratios = {}
        ids = list(matsum.part_ids)
        for dummy, parts in dummy_parts.items():
            missing = [p for p in parts if p not in ids]
            if missing:
                raise ValueError(f"{dummy}: parts {missing} are not in matsum.")
            cols = [ids.index(p) for p in parts]
            hg = np.nansum(matsum.hourglass[:, cols], axis=1)
            ie = np.nansum(matsum.internal[:, cols], axis=1)
            ratios[dummy] = float(np.nanmax(hg) / np.nanmax(ie))
        out["dummy_hourglass_ratios"] = ratios
    return out


def frontal_end_time(
    time: ArrayLike, head_x_displacement: ArrayLike, t0: float = 0.0
) -> float:
    """End time of the frontal data: the time of maximum head x
    excursion plus a 40 % margin, measured from ``t0``.

    ``head_x_displacement`` is the head x excursion relative to the
    vehicle (sled); its largest absolute value is used.
    """
    t = np.asarray(time, dtype=float)
    x = np.asarray(head_x_displacement, dtype=float)
    if t.ndim != 1 or t.shape != x.shape or len(t) < 2:
        raise ValueError("time and head_x_displacement must be 1D, equal length.")
    t_max = float(t[int(np.nanargmax(np.abs(x)))])
    return t0 + (1.0 + QUALITY_LIMITS["end_time_margin"]) * (t_max - t0)


# --- Sensor score ------------------------------------------------------------------

@dataclass(frozen=True)
class SensorScore:
    """ISO/TS 18571 score of one sensor (Virtual Testing Protocol 5.3.1)."""

    sensor: str
    score: float
    """Weighted sensor score S = sum(w_i S_i)."""
    axis_scores: dict[str, float]
    weights: dict[str, float]


def axis_weights(test: Mapping[str, ArrayLike]) -> dict[str, float]:
    """Axis weights from the physical test: w_i = max|c_i| / sum_j max|c_j|.

    One axis gets weight 1; if every axis is zero, the weights are equal.
    """
    if not test:
        raise ValueError("Give at least one axis.")
    peaks = {axis: float(np.nanmax(np.abs(np.asarray(v, dtype=float))))
             for axis, v in test.items()}
    total = sum(peaks.values())
    if total <= 0 or not math.isfinite(total):
        return {axis: 1.0 / len(peaks) for axis in peaks}
    return {axis: p / total for axis, p in peaks.items()}


def sensor_score(
    sensor: str,
    time: ArrayLike,
    test: Mapping[str, ArrayLike],
    simulation: Mapping[str, ArrayLike],
    simulation_time: ArrayLike | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
) -> SensorScore:
    """ISO/TS 18571 sensor score of a simulation against the sled test.

    Parameters
    ----------
    sensor:
        Sensor name, e.g. ``"head"``.
    time:
        Test time, s.
    test, simulation:
        Axis -> signal, e.g. ``{"x": ax, "y": ay, "z": az}``; the same
        axes in both. Filter both the same way first (CP 005 channel
        classes); simulation output is submitted unfiltered.
    simulation_time:
        Simulation time if it differs from the test time.
    t_start, t_end:
        Rating interval, s (T0 to Tend, see `frontal_end_time`).
    """
    if set(test) != set(simulation):
        raise ValueError(f"{sensor}: test axes {sorted(test)} and simulation axes "
                         f"{sorted(simulation)} differ.")
    weights = axis_weights(test)
    scores = {
        axis: iso18571(time, test[axis], simulation[axis],
                       comparison_time=simulation_time,
                       t_start=t_start, t_end=t_end).rating
        for axis in test
    }
    total = float(sum(weights[a] * scores[a] for a in test))
    return SensorScore(sensor, total, scores, weights)


# --- Assessment criteria deviation ----------------------------------------------------

@dataclass(frozen=True)
class KpiResult:
    """Assessment criterion of test and simulation (Section 5.3.2)."""

    criterion: str
    test: float
    simulation: float
    limit: float
    """AC limit: the lower performance limit of the Frontal Impact Protocol."""
    r_test: float
    r_simulation: float
    deviation: float | None
    """dAC = |r_test - r_simulation|; None where r_test < 50 %."""

    @property
    def passed(self) -> bool | None:
        """dAC < 30 %; None if not assessed."""
        return None if self.deviation is None else self.deviation < KPI_DEVIATION_MAX


def kpi_check(
    criterion: str, test: float, simulation: float, limit: float
) -> KpiResult:
    """rAC = AC / AC_limit for test and simulation, and dAC where
    rAC_test >= 50 %."""
    for name, v in (("test", test), ("simulation", simulation), ("limit", limit)):
        if not math.isfinite(v):
            raise ValueError(f"{criterion}: {name} must be finite.")
    if limit == 0:
        raise ValueError(f"{criterion}: limit must not be zero.")
    r_test = abs(test) / abs(limit)
    r_sim = abs(simulation) / abs(limit)
    deviation = abs(r_test - r_sim) if r_test >= KPI_MIN_TEST_RATIO else None
    return KpiResult(criterion, float(test), float(simulation), float(abs(limit)),
                     r_test, r_sim, deviation)


def kpi_checks(
    dummy: str,
    test: Mapping[str, float],
    simulation: Mapping[str, float],
    speed: int,
) -> list[KpiResult]:
    """`kpi_check` for every criterion given for both test and simulation,
    with the dummy's lower performance limits at that speed (criteria not
    applicable to virtual tests are skipped)."""
    limits = _limits_for(dummy, speed)
    results = []
    for crit in test:
        if crit not in simulation or crit in VIRTUAL_NOT_APPLICABLE:
            continue
        if crit not in limits:
            raise ValueError(f"No limit for {crit!r} of {dummy}.")
        results.append(kpi_check(crit, test[crit], simulation[crit], limits[crit].lpl))
    return results


# --- Validation of one load case ----------------------------------------------------

def validate_load_case(
    label: str,
    sensors: Mapping[str, SensorScore],
    kpis: Sequence[KpiResult] = (),
    quality: CheckResult | None = None,
    required: Mapping[str, tuple[str, ...]] = FRONTAL_SENSORS,
) -> CheckResult:
    """Acceptance of one validated load case (Section 5.4).

    Required sensors must score above 0.5 (missing ones are reported as
    not assessed), each assessed criterion must deviate by less than
    30 %, and the model quality criteria must be met. Other sensors are
    listed in the notes as monitored. Axes scoring 0.5 or less are noted
    for a plausibility check (sign, units, channel mapping).
    """
    checks: dict[str, Check] = {}
    notes: list[str] = []
    for name in required:
        s = sensors.get(name)
        checks[f"iso_{name}"] = _check(f"iso_{name}", None if s is None else s.score,
                                       SENSOR_SCORE_MIN, ">", "5.4.1")
    for name, s in sensors.items():
        if name not in required:
            notes.append(f"monitored: {name} ISO score {s.score:.3f}")
        low = [a for a, v in s.axis_scores.items() if v <= SENSOR_SCORE_MIN]
        if low:
            notes.append(f"plausibility: {name} axis {', '.join(low)} ISO <= 0.5; "
                         "check sign, units and channel mapping")
    for k in kpis:
        if k.deviation is None:
            notes.append(f"{k.criterion}: test at {k.r_test:.0%} of the limit "
                         "(below 50 %), deviation not assessed")
            continue
        checks[f"dAC_{k.criterion}"] = Check(
            f"dAC_{k.criterion}", k.deviation, KPI_DEVIATION_MAX, "<", "5.4.2",
            f"rAC test {k.r_test:.2f}, sim {k.r_simulation:.2f}")
    if quality is not None:
        for key, c in quality.checks.items():
            checks[key] = c
    return CheckResult(f"VTC validation ({label})", checks, tuple(notes))


# --- Scoring --------------------------------------------------------------------------

@dataclass(frozen=True)
class SledVirtualScore:
    """Sled and virtual testing score of one occupant (5 points)."""

    position: str
    points: float
    max_points: float
    sled_points: float
    virtual_points: float
    """After the HBM halving and the validation rule."""
    virtual_raw_points: float
    """Virtual points before those rules."""
    sled: dict[int, DummyScore]
    virtual: dict[int, DummyScore]
    lower_leg_virtual_points: float
    """Default virtual lower leg points (0 if a tibia LPL was exceeded)."""
    validated: bool
    hbm_provided: bool
    notes: tuple[str, ...] = field(default=())

    def summary(self) -> str:
        """Text summary with points per load case."""
        lines = [f"Sled & virtual testing, {self.position}: "
                 f"{self.points:.3f} / {self.max_points:.1f} points"]
        for case, score in self.sled.items():
            lines.append(f"  sled    LC{case} {score.dummy:<11} {score.points:.3f} / "
                         f"{score.max_points:.3f}  " + _bands(score))
        for case, score in self.virtual.items():
            lines.append(f"  virtual LC{case} {score.dummy:<11} {score.points:.3f} / "
                         f"{score.max_points:.3f}  " + _bands(score))
        lines.append(f"  sled {self.sled_points:.3f} / 2.5, virtual "
                     f"{self.virtual_points:.3f} / 2.5 (raw "
                     f"{self.virtual_raw_points:.3f}, lower leg "
                     f"{self.lower_leg_virtual_points:.3f})")
        lines += [f"  note: {n}" for n in self.notes]
        return "\n".join(lines)


def _bands(score: DummyScore) -> str:
    return ", ".join(f"{r}: {s.band}" for r, s in score.regions.items())


def score_sled_virtual(
    position: str,
    sled: Mapping[int, Occupant],
    virtual: Mapping[int, Occupant],
    validated: bool = True,
    hbm_provided: bool = True,
    tibia_lpl_exceeded: bool = False,
    band_fractions: Mapping[str, float] = BAND_FRACTIONS,
) -> SledVirtualScore:
    """Score one front occupant in the sled and virtual load cases.

    Parameters
    ----------
    position:
        ``"driver"`` or ``"front_passenger"``.
    sled:
        Load case number (1-5) -> physical sled test results, two load
        cases. Every body region is scored: 0.625 / 2 points per region
        and load case (2.5 points).
    virtual:
        Load case number -> simulation results of the three other
        Hybrid III load cases: 0.625 / 3 points per region and load case
        (2.5 points). Knee displacement and tibia criteria are not
        applicable; the lower leg points are awarded by default.
    validated:
        False if virtual data was not provided or did not meet the VTC
        validation criteria: only the sled load cases are scored.
    hbm_provided:
        False if no human body model data was provided: the virtual
        score is halved.
    tibia_lpl_exceeded:
        True if any dummy in any physical test (including full scale)
        exceeded the tibia index or tibia force LPL: no default virtual
        lower leg points.
    band_fractions:
        Share of the region points per colour band.
    """
    if position not in ("driver", "front_passenger"):
        raise ValueError("position must be 'driver' or 'front_passenger'.")
    hiii_cases = {n for n, c in FRONTAL_LOAD_CASES.items()
                  if getattr(c, position) not in (None, "hbm_50")}
    if len(sled) != 2 or len(virtual) != 3:
        raise ValueError("Give two sled and three virtual load cases.")
    if set(sled) & set(virtual):
        raise ValueError("A load case cannot be both sled and virtual.")
    if not (set(sled) | set(virtual)) <= hiii_cases:
        raise ValueError(f"Load cases must be among {sorted(hiii_cases)}.")
    driver = position == "driver"

    sled_scores: dict[int, DummyScore] = {}
    for case, occupant in sled.items():
        lc = FRONTAL_LOAD_CASES[case]
        sled_scores[case] = score_dummy(
            getattr(lc, position), occupant,
            dict.fromkeys(_REGIONS, SLED_REGION_POINTS), lc.speed, band_fractions,
            driver=driver)

    virtual_scores: dict[int, DummyScore] = {}
    for case, occupant in virtual.items():
        lc = FRONTAL_LOAD_CASES[case]
        regions = dict.fromkeys(_REGIONS[:3], VIRTUAL_REGION_POINTS)
        virtual_scores[case] = score_dummy(
            getattr(lc, position), occupant, regions, lc.speed, band_fractions,
            driver=driver, exclude=VIRTUAL_NOT_APPLICABLE)

    sled_points = sum(s.points for s in sled_scores.values())
    lower_leg = 0.0 if tibia_lpl_exceeded else 3 * VIRTUAL_REGION_POINTS
    virtual_raw = sum(s.points for s in virtual_scores.values()) + lower_leg
    notes: list[str] = []
    virtual_points = virtual_raw
    if not validated:
        virtual_points = 0.0
        notes.append("virtual data not validated: sled load cases only")
    elif not hbm_provided:
        virtual_points = virtual_raw / 2.0
        notes.append("no HBM data: virtual score halved")
    if tibia_lpl_exceeded:
        notes.append("tibia LPL exceeded in a physical test: no default lower leg "
                     "points")
    return SledVirtualScore(
        position=position,
        points=sled_points + virtual_points,
        max_points=SLED_VIRTUAL_MAX / 2,
        sled_points=sled_points,
        virtual_points=virtual_points,
        virtual_raw_points=virtual_raw,
        sled=sled_scores,
        virtual=virtual_scores,
        lower_leg_virtual_points=lower_leg,
        validated=validated,
        hbm_provided=hbm_provided,
        notes=tuple(notes),
    )
