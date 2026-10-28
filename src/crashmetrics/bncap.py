"""Bharat NCAP adult occupant protection scoring (AIS-197).

Follows AIS-197 (Bharat NCAP): Annexure IV (assessment criteria),
Annexure VI (safety assist qualifiers), Annexure VII (modifiers) and
Annexure VIII (scoring), with the star thresholds of Table 2A.

Tests: ODB frontal at 64 km/h (Hybrid III 50th driver and passenger,
16 points), MDB side at 50 km/h (ES-2, 16 points) and the pole side test
at 29 km/h (pass/fail, `pole_test_passed`).

Scoring
-------
Each criterion scores 0-4 points on a linear sliding scale between the
higher (4 points) and lower (0 points) performance limit
(`sliding_points`). Neck shear and tension and femur compression
are scored from their exceedance curves against force-duration limits
(`curve_points`): the lowest point on the curve gives the score.
A body region takes its lowest-scoring criterion, then point modifiers
are subtracted (not below zero). Region scores are rounded to 3
decimals.

Frontal: the regions of driver and passenger are grouped into head &
neck, chest, knee/femur/pelvis and leg & foot; each group takes the
worst region or limb of the two occupants (16 points). Side: head,
chest, abdomen and pelvis, 4 points each (16 points).

Capping (Annexure IV 3.2 and 4.2): a biomechanical value above the
lower performance (capping) limit of a critical region (frontal head,
neck, chest; side head, chest, abdomen, pelvis) removes all points of
that test and caps the rating at 0 stars; a critical region scoring zero
after modifiers caps it at 1 star.

Units: forces in N, moments in N m, deflections and displacements in
mm, accelerations in g, VC in m/s, time in s.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike

from crashmetrics.acceleration import _validate, exceedance_duration, exceedance_level

from ._scoring import linear_fraction

__all__ = [
    "AOP_STAR_THRESHOLDS",
    "COP_STAR_THRESHOLDS",
    "COP_STAR_THRESHOLDS_TWO_SEATER",
    "FEMUR_CURVES",
    "FRONTAL_LIMITS",
    "NECK_SHEAR_CURVES",
    "NECK_TENSION_CURVES",
    "SIDE_LIMITS",
    "AopRating",
    "CurveScore",
    "FrontalOccupant",
    "RegionResult",
    "SideOccupant",
    "TestResult",
    "a_pillar_modifier",
    "aop_rating",
    "backplate_modifier",
    "colour",
    "cop_stars",
    "curve_points",
    "pedal_blocking_modifier",
    "pedal_upward_modifier",
    "pole_test_passed",
    "score_frontal",
    "score_side",
    "sliding_points",
    "steering_column_modifier",
    "t12_modifier",
]

MAX_POINTS = 4.0

Curve = tuple[tuple[float, float], ...]

NECK_SHEAR_CURVES: tuple[Curve, Curve] = (
    ((0.0, 1900.0), (25.0, 1200.0), (35.0, 1200.0), (45.0, 1100.0)),
    ((0.0, 3100.0), (25.0, 1500.0), (35.0, 1500.0), (45.0, 1100.0)),
)
"""Neck shear (higher, lower performance) curves, (duration ms, force N),
Annexure IV 3.2.2. The lower curve is also the capping limit."""

NECK_TENSION_CURVES: tuple[Curve, Curve] = (
    ((0.0, 2700.0), (35.0, 2300.0), (60.0, 1100.0)),
    ((0.0, 3300.0), (35.0, 2900.0), (60.0, 1100.0)),
)
"""Neck tension (higher, lower performance) curves, Annexure IV 3.2.2."""

FEMUR_CURVES: tuple[Curve, Curve] = (
    ((0.0, 3800.0),),
    ((0.0, 9070.0), (10.0, 7560.0)),
)
"""Femur compression (higher, lower performance) curves, Annexure IV
3.2.4: 3.8 kN; 9.07 kN at 0 ms to 7.56 kN at 10 ms and longer."""

FRONTAL_LIMITS: dict[str, tuple[float, float]] = {
    "hic15": (500.0, 700.0),
    "head_a3ms": (72.0, 88.0),
    "neck_extension": (42.0, 57.0),
    "chest_compression": (22.0, 42.0),
    "viscous_criterion": (0.5, 1.0),
    "knee_displacement": (6.0, 15.0),
    "tibia_index": (0.4, 1.3),
    "tibia_force": (2000.0, 8000.0),
    "pedal_rearward": (100.0, 200.0),
}
"""Frontal (higher, lower) performance limits, Annexure IV 3.2."""

SIDE_LIMITS: dict[str, tuple[float, float]] = {
    "hic15": (500.0, 700.0),
    "head_a3ms": (72.0, 88.0),
    "rib_deflection": (22.0, 42.0),
    "rib_vc": (0.32, 1.0),
    "abdominal_force": (1000.0, 2500.0),
    "pubic_force": (3000.0, 6000.0),
}
"""Side (ES-2) (higher, lower) performance limits, Annexure IV 4.2."""

AOP_STAR_THRESHOLDS: tuple[tuple[int, float], ...] = (
    (5, 27.0), (4, 22.0), (3, 16.0), (2, 10.0), (1, 4.0),
)
"""Minimum frontal + side score per star rating (AIS-197 Table 2A)."""

COP_STAR_THRESHOLDS: tuple[tuple[int, float], ...] = (
    (5, 41.0), (4, 35.0), (3, 27.0), (2, 18.0), (1, 9.0),
)
"""Child occupant protection (49 points) thresholds (Table 2B)."""

COP_STAR_THRESHOLDS_TWO_SEATER: tuple[tuple[int, float], ...] = (
    (5, 20.0), (4, 17.0), (3, 13.0), (2, 9.0), (1, 5.0),
)
"""Child occupant protection thresholds for two-seaters (22 points),
Annexure VIII 4.3."""


# --- Points ------------------------------------------------------------------


def sliding_points(
    value: float, hpl: float, lpl: float, max_points: float = MAX_POINTS
) -> float:
    """Linear sliding scale: ``max_points`` at or below the HPL, 0 at or
    above the LPL."""
    return max_points * linear_fraction(value, hpl, lpl)


def colour(points: float) -> str:
    """Colour of a 4-point region score (Annexure VIII): green 4.000,
    yellow 2.670-3.999, orange 1.330-2.669, brown 0.001-1.329, red 0."""
    p = round(points, 3)
    if p >= 4.0:
        return "green"
    if p >= 2.67:
        return "yellow"
    if p >= 1.33:
        return "orange"
    if p > 0.0:
        return "brown"
    return "red"


@dataclass(frozen=True)
class CurveScore:
    """Score of an exceedance curve between two force-duration curves."""

    points: float
    """Lowest point score on the curve (0-4)."""
    level: float
    """Level of the exceedance curve where the score is lowest."""
    duration_ms: float
    """Duration at that level, ms."""
    exceeds_lower: bool
    """True if the curve goes above the lower performance (capping)
    curve."""


def _interp(curve: Curve, duration: float) -> float:
    return float(np.interp(duration, [p[0] for p in curve], [p[1] for p in curve]))


def curve_points(
    time: ArrayLike,
    signal: ArrayLike,
    curves: tuple[Curve, Curve],
    direction: Literal["positive", "negative", "absolute"] = "positive",
    mode: Literal["cumulative", "continuous"] = "cumulative",
    max_points: float = MAX_POINTS,
) -> CurveScore:
    """Score an exceedance curve against higher and lower force-duration
    curves (Annexure IV 3.2.2 and 3.2.4).

    For each level L of the exceedance curve, with duration D(L) at or
    above it, the points are interpolated between the higher curve H(D)
    (``max_points``) and the lower curve W(D) (0). The score is the lowest
    point on the curve.

    Parameters
    ----------
    curves:
        (higher, lower) curves as (duration ms, value) points, linear
        between points and constant after the last.
    direction:
        Part of the signal assessed (e.g. ``"negative"`` for femur
        compression stored as negative force, ``"absolute"`` for shear).
    mode:
        AIS-197 assesses the curves as cumulative exceedance.
    """
    t, s = _validate(time, signal)
    if direction == "positive":
        a = np.maximum(s, 0.0)
    elif direction == "negative":
        a = np.maximum(-s, 0.0)
    elif direction == "absolute":
        a = np.abs(s)
    else:
        raise ValueError("direction must be 'positive', 'negative' or 'absolute'.")
    if mode not in ("cumulative", "continuous"):
        raise ValueError("mode must be 'cumulative' or 'continuous'.")
    peak = float(np.max(a))
    if peak <= 0.0:
        return CurveScore(max_points, 0.0, 0.0, False)

    span_ms = (t[-1] - t[0]) * 1000.0
    breaks = sorted({d for curve in curves for d, _ in curve if d <= span_ms})
    candidates = [a[a > 0.0], np.array([exceedance_level(t, a, d, mode)
                                        for d in breaks])]
    if mode == "continuous":
        candidates.append(np.linspace(0.0, peak, 2001)[1:])
    levels = np.unique(np.concatenate(candidates))
    levels = levels[levels > 0.0]

    best = (max_points, peak, exceedance_duration(t, a, peak, mode))
    exceeds = False
    for level in levels:
        duration = exceedance_duration(t, a, float(level), mode)
        high, low = _interp(curves[0], duration), _interp(curves[1], duration)
        if level > low:
            exceeds = True
        if level <= high:
            pts = max_points
        elif level >= low:
            pts = 0.0
        else:
            pts = max_points * (low - level) / (low - high)
        if pts < best[0]:
            best = (pts, float(level), duration)
    return CurveScore(best[0], best[1], best[2], exceeds)


# --- Modifiers ---------------------------------------------------------------


def _ramp(value: float, start: float, end: float, max_penalty: float) -> float:
    if not math.isfinite(value):
        raise ValueError("value must be finite.")
    return max_penalty * min(1.0, max(0.0, (value - start) / (end - start)))


def steering_column_modifier(
    rearward: float = 0.0, upward: float = 0.0, lateral: float = 0.0
) -> float:
    """Steering column displacement penalty, 0-1 point (Annexure VII
    2.1.5): none up to 90 % of the EEVC limits (100 mm rearward, 80 mm
    upward, 100 mm lateral), 1 point beyond 110 %; worst of the three.
    Applied to the driver's head."""
    return max(
        _ramp(rearward, 90.0, 110.0, 1.0),
        _ramp(upward, 72.0, 88.0, 1.0),
        _ramp(lateral, 90.0, 110.0, 1.0),
    )


def a_pillar_modifier(displacement: float) -> float:
    """A-pillar rearward displacement penalty on the chest, 0-2 points:
    0 up to 100 mm, 2 above 200 mm (Annexure VII 2.1.6.1)."""
    return _ramp(displacement, 100.0, 200.0, 2.0)


def pedal_upward_modifier(displacement: float) -> float:
    """Upward pedal displacement penalty on the lower leg, 0-1 point: none
    up to 90 % of 80 mm, 1 point beyond 110 % (Annexure VII 2.1.8)."""
    return _ramp(displacement, 72.0, 88.0, 1.0)


def pedal_blocking_modifier(rearward: float) -> float:
    """Blocked pedal penalty on the foot and ankle, 0-1 point between 50
    and 175 mm rearward displacement (Annexure VII 2.1.9.2)."""
    return _ramp(rearward, 50.0, 175.0, 1.0)


def backplate_modifier(fy: float) -> float:
    """Side backplate load penalty on the chest, 0-2 points between Fy
    1.0 and 4.0 kN (``fy`` in N, Annexure VII 3.2)."""
    return _ramp(abs(fy), 1000.0, 4000.0, 2.0)


def t12_modifier(fy: float, mx: float) -> float:
    """Side T12 load penalty on the chest, 0-2 points, worst of Fy 1.5-2.0
    kN and Mx 150-200 N m (Annexure VII 3.3 text; its limits table gives
    1.0 kN as the Fy higher limit). ``fy`` in N, ``mx`` in N m;
    magnitudes are used."""
    return max(_ramp(abs(fy), 1500.0, 2000.0, 2.0), _ramp(abs(mx), 150.0, 200.0, 2.0))


# --- Occupant inputs ---------------------------------------------------------

Series = tuple[ArrayLike, ArrayLike]
"""(time in s, signal) of a channel."""


@dataclass(frozen=True)
class FrontalOccupant:
    """Hybrid III 50th results in the ODB test (driver or passenger).

    Leg values are given per side as ``(left, right)``; for the tibia
    give the worse of upper and lower. Modifiers are points to subtract
    per region: ``"head"``, ``"neck"``, ``"chest"``, ``"knee_left"``,
    ``"knee_right"``, ``"lower_leg_left"``, ``"lower_leg_right"``,
    ``"foot"`` (see the ``*_modifier`` helpers for the sliding ones).
    """

    neck_shear: Series
    """Upper neck Fx history, N (both directions assessed)."""
    neck_tension: Series
    """Upper neck Fz history, N (tension positive)."""
    neck_extension: float
    """Extension moment at the occipital condyle, N m (magnitude)."""
    chest_compression: float
    viscous_criterion: float
    femur: tuple[Series, Series]
    """Femur Fz histories (left, right), compression negative."""
    knee_displacement: tuple[float, float]
    tibia_index: tuple[float, float]
    tibia_force: tuple[float, float]
    """Peak tibia compression, N (positive)."""
    hic15: float | None = None
    head_a3ms: float | None = None
    hard_contact: bool = True
    """If False (peak head acceleration <= 80 g and no other evidence),
    the head scores 4 points."""
    pedal_rearward: float | None = None
    """Worst pedal rearward displacement, mm (driver only)."""
    modifiers: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class SideOccupant:
    """ES-2 results in the MDB side test."""

    hic15: float
    head_a3ms: float
    rib_deflection: float
    """Worst rib, mm."""
    rib_vc: float
    """Worst rib VC, m/s."""
    abdominal_force: float
    """Peak total abdominal force, N."""
    pubic_force: float
    """Peak pubic symphysis force, N."""
    modifiers: Mapping[str, float] = field(default_factory=dict)
    """Points to subtract per region (``"head"``, ``"chest"``,
    ``"abdomen"``, ``"pelvis"``), e.g. ``{"chest": backplate_modifier(fy)
    + t12_modifier(fy, mx)}``."""


@dataclass(frozen=True)
class RegionResult:
    points: float
    """Points after modifiers, rounded to 3 decimals (not below zero)."""
    raw_points: float
    """Points before modifiers."""
    governing: str
    """Criterion with the lowest score."""
    criteria: dict[str, float]
    """Points per criterion."""
    capped: bool
    """A criterion of a critical region is above its capping limit."""

    @property
    def colour(self) -> str:
        return colour(self.points)


@dataclass(frozen=True)
class TestResult:
    points: float
    """Test score (0-16); 0 if capped."""
    groups: dict[str, float]
    """Points per (grouped) body region."""
    regions: dict[str, dict[str, RegionResult]]
    """Region results per occupant."""
    capped: bool
    """A capping limit was exceeded (0 stars)."""
    critical_zero: bool
    """A critical region scores zero after modifiers (at most 1 star)."""
    test_modifiers: float


def _region(
    scores: Mapping[str, float], modifier: float, capped: bool = False
) -> RegionResult:
    governing = min(scores, key=lambda k: scores[k])
    raw = scores[governing]
    if not math.isfinite(modifier) or modifier < 0:
        raise ValueError("Modifiers are points to subtract (>= 0).")
    return RegionResult(round(max(0.0, raw - modifier), 3), raw, governing,
                        dict(scores), capped)


def _scale(name: str, value: float, limits: Mapping[str, tuple[float, float]]
           ) -> tuple[float, bool]:
    hpl, lpl = limits[name]
    return sliding_points(value, hpl, lpl), value > lpl


_FRONTAL_MODIFIER_REGIONS = {"head", "neck", "chest", "knee_left", "knee_right",
                             "lower_leg_left", "lower_leg_right", "foot"}


def _frontal_regions(occ: FrontalOccupant, driver: bool) -> dict[str, RegionResult]:
    unknown = set(occ.modifiers) - _FRONTAL_MODIFIER_REGIONS
    if unknown:
        raise ValueError(f"Unknown modifier regions: {sorted(unknown)}.")
    mod = occ.modifiers
    out: dict[str, RegionResult] = {}

    if occ.hard_contact:
        if occ.hic15 is None or occ.head_a3ms is None:
            raise ValueError("hic15 and head_a3ms are needed with hard contact.")
        hic, c1 = _scale("hic15", occ.hic15, FRONTAL_LIMITS)
        a3, c2 = _scale("head_a3ms", occ.head_a3ms, FRONTAL_LIMITS)
        out["head"] = _region({"hic15": hic, "head_a3ms": a3},
                              mod.get("head", 0.0), c1 or c2)
    else:
        out["head"] = _region({"no hard contact": MAX_POINTS}, mod.get("head", 0.0))

    shear = curve_points(*occ.neck_shear, NECK_SHEAR_CURVES, direction="absolute")
    tension = curve_points(*occ.neck_tension, NECK_TENSION_CURVES)
    ext, c3 = _scale("neck_extension", abs(occ.neck_extension), FRONTAL_LIMITS)
    out["neck"] = _region(
        {"neck_shear": shear.points, "neck_tension": tension.points,
         "neck_extension": ext},
        mod.get("neck", 0.0), shear.exceeds_lower or tension.exceeds_lower or c3)

    comp, c4 = _scale("chest_compression", occ.chest_compression, FRONTAL_LIMITS)
    vc, c5 = _scale("viscous_criterion", occ.viscous_criterion, FRONTAL_LIMITS)
    out["chest"] = _region({"chest_compression": comp, "viscous_criterion": vc},
                           mod.get("chest", 0.0), c4 or c5)

    for i, side in enumerate(("left", "right")):
        femur = curve_points(*occ.femur[i], FEMUR_CURVES, direction="negative")
        knee, _ = _scale("knee_displacement", occ.knee_displacement[i],
                         FRONTAL_LIMITS)
        out[f"knee_{side}"] = _region({"femur_force": femur.points,
                                       "knee_displacement": knee},
                                      mod.get(f"knee_{side}", 0.0))
        ti, _ = _scale("tibia_index", occ.tibia_index[i], FRONTAL_LIMITS)
        tf, _ = _scale("tibia_force", occ.tibia_force[i], FRONTAL_LIMITS)
        out[f"lower_leg_{side}"] = _region({"tibia_index": ti, "tibia_force": tf},
                                           mod.get(f"lower_leg_{side}", 0.0))
    if driver:
        if occ.pedal_rearward is None:
            raise ValueError("pedal_rearward is needed for the driver.")
        pedal, _ = _scale("pedal_rearward", occ.pedal_rearward, FRONTAL_LIMITS)
        out["foot"] = _region({"pedal_rearward": pedal}, mod.get("foot", 0.0))
    elif "foot" in occ.modifiers:
        raise ValueError("The passenger's foot and ankle is not assessed.")
    return out


def _test_modifiers(door_openings: int, fuel_leakage: bool,
                    other: float) -> float:
    if door_openings < 0 or not math.isfinite(other) or other < 0:
        raise ValueError("Test modifiers must be non-negative.")
    return float(door_openings) + (1.0 if fuel_leakage else 0.0) + other


def score_frontal(
    driver: FrontalOccupant,
    passenger: FrontalOccupant,
    door_openings: int = 0,
    fuel_leakage: bool = False,
    other_test_modifiers: float = 0.0,
) -> TestResult:
    """ODB frontal test score, 16 points (Annexures IV and VIII).

    Groups: head & neck (head, neck), chest, knee/femur/pelvis (both
    knees) and leg & foot (both lower legs and the driver's foot), each
    the worst region or limb of driver and passenger. Test modifiers:
    1 point per door opening, 1 point for fuel leakage (or the EV / hybrid
    post-crash penalty) and ``other_test_modifiers`` points.
    """
    regions = {"driver": _frontal_regions(driver, True),
               "passenger": _frontal_regions(passenger, False)}
    group_members = {
        "head_neck": ("head", "neck"),
        "chest": ("chest",),
        "knee_femur_pelvis": ("knee_left", "knee_right"),
        "leg_foot": ("lower_leg_left", "lower_leg_right", "foot"),
    }
    groups = {
        g: min(r[m].points for r in regions.values() for m in members if m in r)
        for g, members in group_members.items()
    }
    critical = ("head", "neck", "chest")
    capped = any(r[c].capped for r in regions.values() for c in critical)
    critical_zero = any(r[c].points == 0.0 for r in regions.values() for c in critical)
    mods = _test_modifiers(door_openings, fuel_leakage, other_test_modifiers)
    points = 0.0 if capped else max(0.0, round(sum(groups.values()) - mods, 3))
    return TestResult(points, groups, regions, capped, critical_zero, mods)


def score_side(
    occupant: SideOccupant,
    door_openings: int = 0,
    fuel_leakage: bool = False,
    other_test_modifiers: float = 0.0,
) -> TestResult:
    """MDB side test score, 16 points: head, chest (worst rib), abdomen
    and pelvis, 4 points each (Annexures IV 4.2 and VIII). All four are
    critical regions. ``other_test_modifiers`` covers e.g. a hazardous
    airbag deployment carried over from the pole test (1 point)."""
    unknown = set(occupant.modifiers) - {"head", "chest", "abdomen", "pelvis"}
    if unknown:
        raise ValueError(f"Unknown modifier regions: {sorted(unknown)}.")
    mod = occupant.modifiers
    hic, c1 = _scale("hic15", occupant.hic15, SIDE_LIMITS)
    a3, c2 = _scale("head_a3ms", occupant.head_a3ms, SIDE_LIMITS)
    rib, c3 = _scale("rib_deflection", occupant.rib_deflection, SIDE_LIMITS)
    vc, c4 = _scale("rib_vc", occupant.rib_vc, SIDE_LIMITS)
    abd, c5 = _scale("abdominal_force", occupant.abdominal_force, SIDE_LIMITS)
    pub, c6 = _scale("pubic_force", occupant.pubic_force, SIDE_LIMITS)
    regions = {
        "head": _region({"hic15": hic, "head_a3ms": a3}, mod.get("head", 0.0),
                        c1 or c2),
        "chest": _region({"rib_deflection": rib, "rib_vc": vc},
                         mod.get("chest", 0.0), c3 or c4),
        "abdomen": _region({"abdominal_force": abd}, mod.get("abdomen", 0.0), c5),
        "pelvis": _region({"pubic_force": pub}, mod.get("pelvis", 0.0), c6),
    }
    groups = {k: r.points for k, r in regions.items()}
    capped = any(r.capped for r in regions.values())
    critical_zero = any(r.points == 0.0 for r in regions.values())
    mods = _test_modifiers(door_openings, fuel_leakage, other_test_modifiers)
    points = 0.0 if capped else max(0.0, round(sum(groups.values()) - mods, 3))
    return TestResult(points, groups, {"driver": regions}, capped, critical_zero,
                      mods)


# --- Pole test and rating ----------------------------------------------------


def pole_test_passed(
    hic15: float,
    head_peak: float,
    head_contact: bool,
    rib_deflection: float,
    rib_vc: float,
    abdominal_force: float,
    pubic_force: float,
) -> bool:
    """Side pole test (Annexure IV 5.2, Annexure VII 4.1): HIC15 < 700,
    peak resultant head acceleration < 80 g, no direct head contact with
    the pole, and thorax, abdomen and pelvis below the side lower
    performance limits (modifiers not applied)."""
    return (
        hic15 < 700.0 and head_peak < 80.0 and not head_contact
        and rib_deflection <= SIDE_LIMITS["rib_deflection"][1]
        and rib_vc <= SIDE_LIMITS["rib_vc"][1]
        and abdominal_force <= SIDE_LIMITS["abdominal_force"][1]
        and pubic_force <= SIDE_LIMITS["pubic_force"][1]
    )


def _stars(points: float, thresholds: Sequence[tuple[int, float]]) -> int:
    for stars, minimum in thresholds:
        if points >= minimum:
            return stars
    return 0


@dataclass(frozen=True)
class AopRating:
    stars: int
    points: float
    """Frontal + side points (0-32)."""
    frontal: float
    side: float
    reasons: tuple[str, ...]
    """Why the rating is below what the points give, if it is."""


def aop_rating(
    frontal: TestResult,
    side: TestResult,
    max_stars_allowed: int = 5,
) -> AopRating:
    """Adult occupant protection star rating (AIS-197 Table 2A and
    Annexure VII Section 5).

    - Stars from the frontal + side points: 27 / 22 / 16 / 10 / 4 for
      5 / 4 / 3 / 2 / 1 stars.
    - A capping limit exceeded in either test: 0 stars.
    - A critical region at zero points (red): at most 1 star.
    - Front and side scores differing by more than 35 % (taken here as
      35 % of the 16-point test maximum): one star less, unless both
      scores exceed 8.2 points and the total exceeds 22.
    - ``max_stars_allowed``: the highest rating whose safety assist
      qualifiers (Annexure VI: ESC, side head protection with a side pole
      test, pedestrian protection, seat belt reminders) are met; see
      `pole_test_passed`.
    """
    total = round(frontal.points + side.points, 3)
    stars = _stars(total, AOP_STAR_THRESHOLDS)
    reasons = []
    if frontal.capped or side.capped:
        stars = 0
        reasons.append("capping limit exceeded")
    if stars > 1 and (frontal.critical_zero or side.critical_zero):
        stars = 1
        reasons.append("critical body region red")
    difference = abs(frontal.points - side.points) / 16.0
    exempt = frontal.points > 8.2 and side.points > 8.2 and total > 22.0
    if stars > 0 and difference > 0.35 and not exempt:
        stars -= 1
        reasons.append("front / side difference above 35 %")
    if stars > max_stars_allowed:
        stars = max(0, max_stars_allowed)
        reasons.append("safety assist qualifiers")
    return AopRating(stars, total, frontal.points, side.points, tuple(reasons))


def cop_stars(points: float, two_seater: bool = False) -> int:
    """Child occupant protection stars from its points (49, or 22 for
    two-seaters), AIS-197 Table 2B and Annexure VIII 4.3."""
    if not math.isfinite(points):
        raise ValueError("points must be finite.")
    return _stars(points, COP_STAR_THRESHOLDS_TWO_SEATER if two_seater
                  else COP_STAR_THRESHOLDS)
