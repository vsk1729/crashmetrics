"""Euro NCAP side impact scoring: AE-MDB, pole and far side (2026).

Follows the Euro NCAP Crash Protection Side Impact Protocol v1.1
(October 2025, for 2026-2028). The side impact total is 35 points:

- AE-MDB, 15 points: driver WorldSID 50th (10), rear Q10 (2.5), rear
  Q6 (2.5).
- Pole, 10 points: driver WorldSID 50th (10).
- Far side, 10 points: main AE-MDB and pole load cases (2 + 2),
  robustness AE-MDB and pole (2 + 2), occupant-to-occupant (2).

Functions:

- `score_side_dummy`: One dummy in the AE-MDB or pole test: colour
  band per criterion, region points, modifiers.
- `score_ae_mdb`, `score_pole`: Test scores with the test modifiers
  (door opening, door detachment, restraint failure, head protection
  zone, rollover).
- `far_side_zone`: Head excursion zone from the measured excursion and
  the excursion lines.
- `score_far_side_case`: One far side load case: zone points, capping,
  pelvis/lumbar modifier.
- `score_far_side`: Main, robustness and occupant-to-occupant points,
  with the disqualification rules.
- `score_side`: The 35-point side impact total.

The colour bands, band points and result types are shared with
`crashmetrics.frontal_scoring` (the protocol's Section 3.3 is the same
scheme). Units: forces N, moments N m, compressions mm, accelerations g,
VC m/s. Pass the worst of left and right where a dummy has both.

Check all limits against the protocol version you assess to.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from crashmetrics.frontal_scoring import (
    BAND_FRACTIONS,
    CriterionResult,
    DummyScore,
    Limit,
    RegionScore,
    TestScore,
    colour_band,
)

__all__ = [
    "AE_MDB_OCCUPANTS",
    "FAR_SIDE_CAPPING_LIMITS",
    "FAR_SIDE_PELVIS_LIMITS",
    "FAR_SIDE_ZONE_POINTS",
    "FAR_SIDE_ZONES",
    "POLE_OCCUPANTS",
    "SIDE_DUMMY_LIMITS",
    "SIDE_REGIONS",
    "FarSideCase",
    "FarSideCaseScore",
    "FarSideScore",
    "SideOccupant",
    "SideScore",
    "far_side_zone",
    "score_ae_mdb",
    "score_far_side",
    "score_far_side_case",
    "score_pole",
    "score_side",
    "score_side_dummy",
]

Test = Literal["ae_mdb", "pole"]

# --- Limits and layout ------------------------------------------------------

SIDE_DUMMY_LIMITS: dict[str, dict[str, Limit]] = {
    "worldsid_50": {
        "hic15": Limit(500.0, 700.0, 700.0),
        "head_a3ms": Limit(72.0, 80.0, 80.0),
        "chest_compression": Limit(28.0, 50.0, 50.0),      # pole capping: 55 mm
        "abdomen_compression": Limit(47.0, 65.0, 65.0),
        "pubic_force": Limit(1700.0, 2800.0, 2800.0),
    },
    "q6": {
        "hic15": Limit(500.0, 700.0, 700.0),
        "head_a3ms": Limit(60.0, 80.0, 80.0),
        "neck_tension": Limit(None, 2400.0),
        "chest_a3ms": Limit(None, 67.0),
    },
    "q10": {
        "hic15": Limit(500.0, 700.0, 700.0),
        "head_a3ms": Limit(60.0, 80.0, 80.0),
        "neck_tension": Limit(None, 2200.0),
        "chest_a3ms": Limit(None, 67.0),
    },
}
"""Higher and lower performance limits and capping limits (protocol
Section 3.4; kN converted to N). The WorldSID chest compression capping
limit is 50 mm in the AE-MDB test and 55 mm in the pole test. Q6 / Q10
neck tension and chest 3 ms acceleration are printed as single values
and used as LPLs (green below, red at or above)."""

POLE_CHEST_CAPPING = 55.0
"""WorldSID chest compression capping limit in the pole test, mm."""

SIDE_REGIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "worldsid_50": {
        "head": ("hic15", "head_a3ms"),
        "chest": ("chest_compression",),
        "abdomen": ("abdomen_compression",),
        "pelvis": ("pubic_force",),
    },
    "q6": {"head": ("hic15", "head_a3ms"), "neck": ("neck_tension",),
           "chest": ("chest_a3ms",)},
    "q10": {"head": ("hic15", "head_a3ms"), "neck": ("neck_tension",),
            "chest": ("chest_a3ms",)},
}
"""Criteria of each body region per dummy."""

_MODIFIER_INPUTS = {"head_peak", "shoulder_force", "chest_vc", "abdomen_vc"}

AE_MDB_OCCUPANTS: dict[str, tuple[str, dict[str, float]]] = {
    "driver": ("worldsid_50", {"head": 2.5, "chest": 2.5, "abdomen": 2.5,
                               "pelvis": 2.5}),
    "rear_q10": ("q10", {"head": 1.25, "neck": 0.625, "chest": 0.625}),
    "rear_q6": ("q6", {"head": 1.25, "neck": 0.625, "chest": 0.625}),
}
"""AE-MDB test: dummy and region points per position (15 points)."""

POLE_OCCUPANTS: dict[str, tuple[str, dict[str, float]]] = {
    "driver": ("worldsid_50", {"head": 2.5, "chest": 2.5, "abdomen": 2.5,
                               "pelvis": 2.5}),
}
"""Pole test: dummy and region points (10 points)."""

TEST_MODIFIER_BASE = 10.0
"""Test modifiers are percentages of 10 points per adult load case."""


# --- Near side dummies ------------------------------------------------------


@dataclass(frozen=True)
class SideOccupant:
    """Measured values and assessment inputs of one side impact occupant."""

    values: Mapping[str, float]
    """Criterion values (keys of `SIDE_REGIONS` for the dummy). Optional
    WorldSID inputs for modifiers: ``"shoulder_force"`` (N),
    ``"chest_vc"`` and ``"abdomen_vc"`` (m/s); and ``"head_peak"`` (g)
    to infer hard head contact."""
    hard_contact: bool | None = None
    """Hard head contact (from high-speed film); inferred from
    ``values["head_peak"] > 80`` g if None. Without it the head is
    assessed on the 3 ms acceleration only."""
    incorrect_airbag_deployment: bool = False
    """WorldSID: -20 % of every body region (Section 4.2.1)."""
    modifiers: Mapping[str, Sequence[float]] = field(default_factory=dict)
    """Further modifiers per region in % of the region points."""
    dummy_modifiers: Sequence[float] = ()
    """Modifiers of the whole dummy score in % (Q dummies: e.g. 50 for
    CRS-to-vehicle attachment)."""


def score_side_dummy(
    dummy: str,
    occupant: SideOccupant,
    region_points: Mapping[str, float],
    test: Test = "ae_mdb",
    band_fractions: Mapping[str, float] = BAND_FRACTIONS,
) -> DummyScore:
    """Score one dummy in the AE-MDB or pole test.

    Each criterion gets a colour band from its HPL and LPL; a body
    region earns the band share of its points of its lowest-scoring
    criterion, minus its modifiers (not below zero).

    WorldSID modifiers applied from the values: shoulder force at or
    above 3.0 kN and chest VC at or above 1.0 m/s remove the chest
    points (-100 %); abdomen VC at or above 1.0 m/s removes the abdomen
    points; an incorrect airbag deployment takes 20 % of every region.

    Capping limits exceeded are reported in ``capping_exceeded`` (the
    protocol extract does not state their consequence for the near side
    tests, as in the frontal scoring).
    """
    if dummy not in SIDE_DUMMY_LIMITS:
        raise ValueError(f"Unknown dummy {dummy!r}. Known: "
                         f"{', '.join(sorted(SIDE_DUMMY_LIMITS))}.")
    if test not in ("ae_mdb", "pole"):
        raise ValueError('test must be "ae_mdb" or "pole".')
    limits = dict(SIDE_DUMMY_LIMITS[dummy])
    if dummy == "worldsid_50" and test == "pole":
        c = limits["chest_compression"]
        limits["chest_compression"] = Limit(c.hpl, c.lpl, POLE_CHEST_CAPPING)
    regions_map = SIDE_REGIONS[dummy]
    values = dict(occupant.values)
    extra = {k: values.pop(k) for k in list(values) if k in _MODIFIER_INPUTS}
    known = {c for crit in regions_map.values() for c in crit}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"Unknown criteria for {dummy}: {sorted(unknown)}.")
    if set(occupant.modifiers) - set(region_points):
        raise ValueError("Modifiers given for regions that are not scored.")

    hard_contact = occupant.hard_contact
    if hard_contact is None:
        if "head_peak" not in extra:
            raise ValueError("Give hard_contact or values['head_peak'].")
        hard_contact = extra["head_peak"] > 80.0

    auto: dict[str, list[float]] = {r: list(occupant.modifiers.get(r, ()))
                                    for r in region_points}
    if dummy == "worldsid_50":
        if extra.get("shoulder_force", 0.0) >= 3000.0 and "chest" in auto:
            auto["chest"].append(100.0)
        if extra.get("chest_vc", 0.0) >= 1.0 and "chest" in auto:
            auto["chest"].append(100.0)
        if extra.get("abdomen_vc", 0.0) >= 1.0 and "abdomen" in auto:
            auto["abdomen"].append(100.0)
        if occupant.incorrect_airbag_deployment:
            for region in auto:
                auto[region].append(20.0)

    regions: dict[str, RegionScore] = {}
    capped: list[str] = []
    for region, max_points in region_points.items():
        if region not in regions_map:
            raise ValueError(f"Unknown region {region!r} for {dummy}.")
        results = []
        for crit in regions_map[region]:
            if crit == "hic15" and not hard_contact:
                continue                       # head on 3 ms only (3.4)
            if crit not in values:
                raise ValueError(f"Missing value for {crit!r} ({dummy}).")
            limit = limits[crit]
            value = float(values[crit])
            exceeded = limit.capping is not None and value >= limit.capping
            if exceeded:
                capped.append(crit)
            results.append(CriterionResult(crit, value, limit,
                                           colour_band(value, limit), exceeded))
        worst = min(results, key=lambda r: band_fractions[r.band])
        percent = float(sum(auto[region]))
        points = max(0.0, band_fractions[worst.band] * max_points
                     - percent / 100.0 * max_points)
        regions[region] = RegionScore(region, points, float(max_points), worst.band,
                                      worst.name, percent, tuple(results))

    max_total = float(sum(region_points.values()))
    dummy_percent = float(sum(occupant.dummy_modifiers))
    points = max(0.0, sum(r.points for r in regions.values())
                 - dummy_percent / 100.0 * max_total)
    return DummyScore(dummy, points, max_total, regions, bool(hard_contact),
                      tuple(capped))


def _test_score(scores: Mapping[str, DummyScore],
                modifiers: Sequence[float]) -> TestScore:
    occupant_points = sum(d.points for d in scores.values())
    deduction = sum(modifiers) / 100.0 * TEST_MODIFIER_BASE
    return TestScore(
        points=max(0.0, occupant_points - deduction),
        max_points=sum(d.max_points for d in scores.values()),
        occupants=dict(scores),
        occupant_points=occupant_points,
        full_scale_deduction=deduction,
        compatibility_penalty=0.0,
    )


def _door_modifiers(door_openings: int, door_detachment: bool,
                    restraint_failure: bool) -> list[float]:
    if door_openings < 0:
        raise ValueError("door_openings must be >= 0.")
    mods = [5.0] * door_openings
    if door_detachment:
        mods.append(100.0)
    if restraint_failure:
        mods.append(100.0)
    return mods


def score_ae_mdb(
    driver: SideOccupant,
    rear_q10: SideOccupant,
    rear_q6: SideOccupant,
    door_openings: int = 0,
    door_detachment: bool = False,
    restraint_failure: bool = False,
    band_fractions: Mapping[str, float] = BAND_FRACTIONS,
) -> TestScore:
    """AE-MDB test score, 15 points.

    Parameters
    ----------
    driver, rear_q10, rear_q6:
        The three occupants.
    door_openings:
        Doors that opened: -5 % of 10 points each (Section 4.2.2).
    door_detachment:
        Structural door detachment: -100 %.
    restraint_failure:
        Restraint failure: -100 %.
    """
    occupants = {"driver": driver, "rear_q10": rear_q10, "rear_q6": rear_q6}
    scores = {pos: score_side_dummy(d, occupants[pos], pts, "ae_mdb", band_fractions)
              for pos, (d, pts) in AE_MDB_OCCUPANTS.items()}
    return _test_score(scores, _door_modifiers(door_openings, door_detachment,
                                               restraint_failure))


def score_pole(
    driver: SideOccupant | None,
    head_protection_fitted: bool = True,
    curtain_zone_rows_failed: int = 0,
    rollover_protection: bool = True,
    door_openings: int = 0,
    door_detachment: bool = False,
    restraint_failure: bool = False,
    band_fractions: Mapping[str, float] = BAND_FRACTIONS,
) -> TestScore:
    """Pole test score, 10 points.

    Parameters
    ----------
    driver:
        The driver WorldSID. Without a near side head protection system
        the pole test is not performed and scores zero (pass
        ``head_protection_fitted=False``; ``driver`` may be None).
    curtain_zone_rows_failed:
        Seat rows whose head protection does not cover the measurement
        zone: -10 % each (Section 4.2.2).
    rollover_protection:
        False if rollover sensing or curtain inflation (6 s) is not
        shown: -20 %.
    door_openings, door_detachment, restraint_failure:
        As for `score_ae_mdb`.
    """
    if not head_protection_fitted:
        return TestScore(0.0, 10.0, {}, 0.0, 0.0, 0.0)
    if driver is None:
        raise ValueError("Give the driver occupant.")
    if curtain_zone_rows_failed < 0:
        raise ValueError("curtain_zone_rows_failed must be >= 0.")
    dummy, points = POLE_OCCUPANTS["driver"]
    scores = {"driver": score_side_dummy(dummy, driver, points, "pole",
                                         band_fractions)}
    mods = _door_modifiers(door_openings, door_detachment, restraint_failure)
    mods += [10.0] * curtain_zone_rows_failed
    if not rollover_protection:
        mods.append(20.0)
    return _test_score(scores, mods)


# --- Far side -----------------------------------------------------------------

FAR_SIDE_ZONES = ("green", "yellow", "orange", "brown", "red", "capping")
"""Head excursion zones from best to worst. ``"brown"`` is the red zone
when the red (intrusion) line is more than 125 mm outboard of the orange
line."""

FAR_SIDE_ZONE_POINTS: dict[bool, dict[str, float]] = {
    True: {"green": 2.0, "yellow": 2.0, "orange": 1.5, "brown": 1.0, "red": 0.5,
           "capping": 0.0},
    False: {"green": 2.0, "yellow": 1.0, "orange": 0.5, "brown": 0.0, "red": 0.0,
            "capping": 0.0},
}
"""Points per main load case (out of 2) by zone, with (True) and without
(False) a far side countermeasure (Section 3.5.3)."""

FAR_SIDE_CAPPING_LIMITS: dict[str, float] = {
    "hic15": 700.0,                    # with direct contact
    "head_a3ms": 80.0,
    "upper_neck_tension": 3740.0,
    "upper_neck_flexion": 248.0,       # Mx at the occipital condyle
    "upper_neck_extension": 50.0,      # negative My at the occipital condyle
    "lower_neck_tension": 3740.0,
    "lower_neck_flexion": 248.0,
    "lower_neck_extension": 100.0,
    "chest_compression": 50.0,
    "abdomen_compression": 65.0,
}
"""Far side capping limits (Section 3.5.3): exceeding any caps the load
case. Units N, N m, mm, g; moments as magnitudes."""

FAR_SIDE_PELVIS_LIMITS: dict[str, float] = {
    "pubic_force": 2800.0,
    "lumbar_fy": 2000.0,
    "lumbar_fz": 3500.0,
    "lumbar_mx": 120.0,
}
"""Far side pelvis / lumbar modifier limits (Section 4.2.3): exceeding
any removes 25 % of the load case points."""

FAR_SIDE_CASE_POINTS = 2.0


def far_side_zone(
    head_clearance: float,
    red_line_offset: float,
) -> str:
    """Return the far side head excursion zone.

    Parameters
    ----------
    head_clearance:
        Lateral distance, mm, by which the peak head excursion stays
        short of the struck-side seat centreline (the orange line):
        positive while the head has not reached it, negative beyond it.
        The yellow line is at +125 mm and the green line at +250 mm.
    red_line_offset:
        How far the red line (maximum interior door panel intrusion from
        the AE-MDB and pole tests) lies outboard of the orange line, mm;
        negative if the intrusion reaches inboard of the seat
        centreline.

    Returns
    -------
    str
        ``"green"``, ``"yellow"``, ``"orange"``, ``"brown"`` (red zone
        with the red line more than 125 mm outboard), ``"red"`` or
        ``"capping"`` (beyond the red line). A head exactly on a line
        is in the better zone.
    """
    for name, v in (("head_clearance", head_clearance),
                    ("red_line_offset", red_line_offset)):
        if not math.isfinite(v):
            raise ValueError(f"{name} must be finite.")
    if head_clearance < -red_line_offset:
        return "capping"
    if head_clearance >= 250.0:
        return "green"
    if head_clearance >= 125.0:
        return "yellow"
    if head_clearance >= 0.0:
        return "orange"
    return "brown" if red_line_offset > 125.0 else "red"


@dataclass(frozen=True)
class FarSideCase:
    """One far side load case (sled or virtual test)."""

    zone: str
    """Head excursion zone (`FAR_SIDE_ZONES`), e.g. from
    `far_side_zone`."""
    values: Mapping[str, float] = field(default_factory=dict)
    """Injury values for capping (`FAR_SIDE_CAPPING_LIMITS` keys) and the
    pelvis / lumbar modifier (`FAR_SIDE_PELVIS_LIMITS` keys)."""


@dataclass(frozen=True)
class FarSideCaseScore:
    """Score of one far side main load case."""

    points: float
    zone: str
    zone_points: float
    capped: tuple[str, ...]
    """Capping reasons: criteria at or above their limit, or
    ``"capping zone"``."""
    pelvis_modifier: float
    """Points removed by the pelvis / lumbar modifier."""


def score_far_side_case(case: FarSideCase, countermeasure: bool) -> FarSideCaseScore:
    """Score one far side main load case, 2 points.

    The zone gives the points (`FAR_SIDE_ZONE_POINTS`); a capping zone
    or any capping limit exceeded gives zero; exceeding a pelvis /
    lumbar limit removes 25 % of 2 points.
    """
    if case.zone not in FAR_SIDE_ZONES:
        raise ValueError(f"zone must be one of {FAR_SIDE_ZONES}.")
    known = set(FAR_SIDE_CAPPING_LIMITS) | set(FAR_SIDE_PELVIS_LIMITS)
    unknown = set(case.values) - known
    if unknown:
        raise ValueError(f"Unknown far side values: {sorted(unknown)}.")
    zone_points = FAR_SIDE_ZONE_POINTS[bool(countermeasure)][case.zone]
    capped = [k for k, lim in FAR_SIDE_CAPPING_LIMITS.items()
              if k in case.values and abs(case.values[k]) >= lim]
    if case.zone == "capping":
        capped.append("capping zone")
    pelvis = any(abs(case.values[k]) >= lim
                 for k, lim in FAR_SIDE_PELVIS_LIMITS.items() if k in case.values)
    modifier = 0.25 * FAR_SIDE_CASE_POINTS if pelvis else 0.0
    points = 0.0 if capped else max(0.0, zone_points - modifier)
    return FarSideCaseScore(points, case.zone, zone_points, tuple(capped),
                            modifier if not capped else 0.0)


@dataclass(frozen=True)
class FarSideScore:
    """Far side score, 10 points."""

    points: float
    main_ae_mdb: FarSideCaseScore
    main_pole: FarSideCaseScore
    robustness_ae_mdb: float
    robustness_pole: float
    occupant_to_occupant: float
    disqualified: tuple[str, ...]
    """Reasons the far side rewards were removed (empty if none)."""
    max_points: float = 10.0


def _zone_rank(zone: str) -> int:
    return FAR_SIDE_ZONES.index(zone)


def _robustness(main: FarSideCase, cases: Sequence[str], countermeasure: bool,
                validated: bool) -> float:
    if not validated or not cases:
        return 0.0
    for zone in cases:
        if zone not in FAR_SIDE_ZONES:
            raise ValueError(f"zone must be one of {FAR_SIDE_ZONES}.")
    if main.zone in ("red", "capping"):
        return 0.0
    if not countermeasure and main.zone != "green":
        return 0.0
    for zone in cases:
        if zone in ("red", "capping"):
            return 0.0
        if _zone_rank(zone) > _zone_rank(main.zone) + 1:
            return 0.0
    return FAR_SIDE_CASE_POINTS


def score_far_side(
    main_ae_mdb: FarSideCase,
    main_pole: FarSideCase,
    robustness_ae_mdb: Sequence[str] = (),
    robustness_pole: Sequence[str] = (),
    countermeasure: bool = True,
    virtual_testing_validated: bool = True,
    occupant_to_occupant_passed: bool = False,
    near_side_driver_points: float | None = None,
    structural_failure: bool = False,
    far_side_restraint_failure: bool = False,
) -> FarSideScore:
    """Far side score, 10 points (Section 3.5).

    Parameters
    ----------
    main_ae_mdb, main_pole:
        Main load cases (75 deg AE-MDB and pole pulses), 2 points each.
    robustness_ae_mdb, robustness_pole:
        Zones of the robustness load cases (AE-MDB: 60, 75 raised,
        90 and 90 raised; pole: 75 raised and 90). Each robustness set
        scores 2 points if every case is at most one zone worse than its
        main load case and none is red; nothing if the main case is red,
        and, without a countermeasure, only if the main case is green.
    countermeasure:
        True if the vehicle has a far side countermeasure.
    virtual_testing_validated:
        False if the virtual test data is missing or fails validation:
        only the main load cases are scored.
    occupant_to_occupant_passed:
        True if the occupant-to-occupant requirements are all met
        (dual-occupancy pole test, coverage, symmetry): 2 points.
    near_side_driver_points:
        Driver points of the AE-MDB plus pole tests (out of 20); below
        17.0 the far side rewards are removed.
    structural_failure:
        Door, latch, hinge, roof or sill failure in the AE-MDB or pole
        test: far side rewards removed.
    far_side_restraint_failure:
        Failure of a far side restraint (e.g. centre airbag) in either
        test: far side rewards removed.
    """
    mdb = score_far_side_case(main_ae_mdb, countermeasure)
    pole = score_far_side_case(main_pole, countermeasure)
    if "capping zone" in mdb.capped or "capping zone" in pole.capped:
        # head excursion in the capping zone caps both far side load cases
        def capped(c: FarSideCaseScore) -> FarSideCaseScore:
            reasons = tuple(dict.fromkeys(c.capped + ("capping zone",)))
            return FarSideCaseScore(0.0, c.zone, c.zone_points, reasons, 0.0)

        mdb, pole = capped(mdb), capped(pole)
    rob_mdb = _robustness(main_ae_mdb, robustness_ae_mdb, countermeasure,
                          virtual_testing_validated)
    rob_pole = _robustness(main_pole, robustness_pole, countermeasure,
                           virtual_testing_validated)
    o2o = FAR_SIDE_CASE_POINTS if occupant_to_occupant_passed else 0.0

    reasons = []
    if structural_failure:
        reasons.append("structural failure in the AE-MDB or pole test")
    if far_side_restraint_failure:
        reasons.append("far side restraint failure")
    if near_side_driver_points is not None and near_side_driver_points < 17.0:
        reasons.append(f"near side driver points {near_side_driver_points:.2f} "
                       "below 17.0 of 20")
    total = 0.0 if reasons else mdb.points + pole.points + rob_mdb + rob_pole + o2o
    return FarSideScore(total, mdb, pole, rob_mdb, rob_pole, o2o, tuple(reasons))


# --- Side impact total -------------------------------------------------------


@dataclass(frozen=True)
class SideScore:
    """Euro NCAP side impact score, 35 points."""

    points: float
    ae_mdb: TestScore
    pole: TestScore
    far_side: FarSideScore
    max_points: float = 35.0

    def summary(self) -> str:
        """A short text report."""
        lines = [f"Euro NCAP side impact: {self.points:.3f} / {self.max_points:g}"]
        for name, test in (("AE-MDB", self.ae_mdb), ("Pole", self.pole)):
            lines.append(f"  {name:8} {test.points:6.3f} / {test.max_points:g}"
                         f"  (modifiers -{test.full_scale_deduction:.3f})")
            for pos, dummy in test.occupants.items():
                regions = ", ".join(f"{r.name} {r.points:.3f} {r.band}"
                                    for r in dummy.regions.values())
                cap = f"  CAPPING: {', '.join(dummy.capping_exceeded)}" \
                    if dummy.capping_exceeded else ""
                lines.append(f"    {pos:9} {dummy.points:6.3f} / "
                             f"{dummy.max_points:g}: {regions}{cap}")
        f = self.far_side
        lines.append(f"  Far side {f.points:6.3f} / {f.max_points:g}  (main AE-MDB "
                     f"{f.main_ae_mdb.points:g} {f.main_ae_mdb.zone}, main pole "
                     f"{f.main_pole.points:g} {f.main_pole.zone}, robustness "
                     f"{f.robustness_ae_mdb:g} + {f.robustness_pole:g}, O2O "
                     f"{f.occupant_to_occupant:g})")
        for reason in f.disqualified:
            lines.append(f"    far side rewards removed: {reason}")
        return "\n".join(lines)


def score_side(ae_mdb: TestScore, pole: TestScore, far_side: FarSideScore) -> SideScore:
    """Return the 35-point side impact total (sum of the three parts)."""
    return SideScore(ae_mdb.points + pole.points + far_side.points,
                     ae_mdb, pole, far_side)
