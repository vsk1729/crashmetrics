"""Euro NCAP frontal impact scoring: MPDB and full width (2026 protocols).

Follows the Euro NCAP Crash Protection Frontal Impact Protocol v1.1
(September 2025, for 2026-2028) and CP 007 Assessment Modifiers v1.1.

Scoring scheme
--------------
Each injury criterion gets a colour band from its higher (HPL) and
lower (LPL) performance limits. The band width is ``(LPL - HPL) / 3``
(protocol Section 3.4.1)::

    green   value < HPL
    yellow  HPL <= value < HPL + width
    orange  HPL + width <= value < HPL + 2 width
    brown   HPL + 2 width <= value < LPL
    red     value >= LPL

A criterion with an LPL only (no HPL) is green below the LPL and red at
or above it. A body region takes the band of its lowest-scoring
criterion and earns that band's share of the region's points (Section
3.5: green 1.25, yellow 1.0, orange 0.75, brown 0.5, red 0 of 1.25,
i.e. 100, 80, 60, 40 and 0 %; see `BAND_FRACTIONS`).

Occupant modifiers are percentages of the region's maximum points (Q
dummy score modifiers of the whole dummy score) and full-scale modifiers
percentages of 10 points per load case. Scores do not go below zero
(CP 007, Section 1). The MPDB compatibility penalty follows CP 007
Appendix A (`compatibility_penalty`). Without hard head contact (peak resultant
head acceleration above 80 g or other evidence), HIC15 and the head
3 ms acceleration are not applied to adult dummies; Q dummies are then
assessed on the head 3 ms acceleration only.

Units: forces in N, moments in N m, deflections and displacements in
mm, accelerations in g, VC in m/s. Pass the worst of left and right.

Check all limits against the protocol version you assess to.
"""

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

__all__ = [
    "ADULT_REGIONS",
    "BAND_FRACTIONS",
    "BAND_FRACTIONS_TABLE",
    "CHEST_COMPRESSION_LIMITS",
    "CHILD_REGIONS",
    "COMPATIBILITY_MAX_PENALTY",
    "DUMMY_LIMITS",
    "FULL_SCALE_MODIFIERS",
    "FULL_SCALE_MODIFIER_BASE",
    "FWDB_OCCUPANTS",
    "FWDB_SPEED",
    "MPDB_OCCUPANTS",
    "OCCUPANT_MODIFIERS",
    "CriterionResult",
    "DummyScore",
    "Limit",
    "Occupant",
    "RegionScore",
    "TestScore",
    "colour_band",
    "compatibility_penalty",
    "compatibility_percentages",
    "damage_modifier",
    "score_dummy",
    "score_fwdb",
    "score_mpdb",
    "score_test",
]


@dataclass(frozen=True)
class Limit:
    """Performance limits of one criterion (same units as the value)."""

    hpl: float | None
    """Higher performance limit; None if the protocol gives an LPL only."""
    lpl: float
    """Lower performance limit."""
    capping: float | None = None
    """Capping limit, if the protocol gives one."""
    capping_driver_only: bool = False
    """True if the capping limit applies to the driver only."""


BAND_FRACTIONS: dict[str, float] = {
    "green": 1.0,
    "yellow": 0.8,
    "orange": 0.6,
    "brown": 0.4,
    "red": 0.0,
}
"""Share of the region points per band, from the protocol's Section 3.5
text (1.25 / 1.0 / 0.75 / 0.5 / 0 points). The colour band tables of the
same protocol (Section 3.4) print 100 / 80 / 40 / 20 / 0 % instead; pass
``band_fractions=BAND_FRACTIONS_TABLE`` to use those."""

BAND_FRACTIONS_TABLE: dict[str, float] = {
    "green": 1.0, "yellow": 0.8, "orange": 0.4, "brown": 0.2, "red": 0.0,
}
"""Band shares as printed in the Section 3.4 colour band tables."""

ADULT_REGIONS: dict[str, tuple[str, ...]] = {
    "head_neck": ("hic15", "head_a3ms", "neck_shear", "neck_tension",
                  "neck_extension"),
    "chest_abdomen": ("chest_compression", "viscous_criterion",
                      "abdomen_compression"),
    "knee_femur_pelvis": ("acetabulum_force", "femur_force", "knee_displacement"),
    "lower_leg": ("tibia_index", "tibia_force"),
}
"""Criteria of each adult body region (only those with a limit for the
dummy are used)."""

CHILD_REGIONS: dict[str, tuple[str, ...]] = {
    "head": ("hic15", "head_a3ms"),
    "neck": ("neck_tension", "neck_extension"),
    "chest": ("chest_compression", "chest_a3ms"),
}
"""Criteria of each Q6 / Q10 body region."""

_HEAD_IMPACT = ("hic15", "head_a3ms")
_OPTIONAL = {"neck_extension"}  # Q dummies: only with head-to-interior contact


def _head_neck(
    shear: Limit, tension: Limit, extension: Limit, capping: bool = True
) -> dict[str, Limit]:
    hic = Limit(500.0, 700.0, 700.0 if capping else None)
    a3ms = Limit(72.0, 80.0, 80.0 if capping else None)
    return {"hic15": hic, "head_a3ms": a3ms, "neck_shear": shear,
            "neck_tension": tension, "neck_extension": extension}


DUMMY_LIMITS: dict[str, dict[str, Limit]] = {
    "hybrid3_05": {
        **_head_neck(Limit(1200.0, 2000.0, 2700.0, True),
                     Limit(1700.0, 2600.0, 2900.0, True),
                     Limit(36.0, 49.0, 57.0, True)),
        "viscous_criterion": Limit(0.5, 1.0, 1.0),
        "femur_force": Limit(2600.0, 6200.0),
        "knee_displacement": Limit(6.0, 15.0),
        "tibia_index": Limit(None, 1.3),
        "tibia_force": Limit(None, 8000.0),
    },
    "hybrid3_50": {
        **_head_neck(Limit(1900.0, 3100.0, 3100.0), Limit(2700.0, 3300.0, 3300.0),
                     Limit(42.0, 57.0, 57.0)),
        "viscous_criterion": Limit(0.5, 1.0, 1.0),
        "femur_force": Limit(3800.0, 9100.0),
        "knee_displacement": Limit(6.0, 15.0),
        "tibia_index": Limit(0.4, 1.3),
        "tibia_force": Limit(2000.0, 8000.0),
    },
    "thor_50": {
        **_head_neck(Limit(1900.0, 3100.0, 3100.0), Limit(2700.0, 3300.0, 3300.0),
                     Limit(42.0, 57.0, 57.0)),
        "abdomen_compression": Limit(None, 88.0),
        "acetabulum_force": Limit(3300.0, 4100.0),
        "femur_force": Limit(3800.0, 9100.0),
        "knee_displacement": Limit(6.0, 15.0),
        "tibia_index": Limit(0.4, 1.3),
        "tibia_force": Limit(2000.0, 8000.0),
    },
    "hybrid3_95": {
        **_head_neck(Limit(2300.0, 3800.0), Limit(3300.0, 4000.0),
                     Limit(56.0, 76.0), capping=False),
        "viscous_criterion": Limit(0.5, 1.0),
        "femur_force": Limit(4800.0, 11500.0),
        "knee_displacement": Limit(6.0, 17.0),
        "tibia_index": Limit(0.4, 1.3),
        "tibia_force": Limit(4000.0, 10000.0),
    },
    "q6": {
        "hic15": Limit(500.0, 700.0, 700.0),
        "head_a3ms": Limit(60.0, 80.0, 80.0),
        "neck_tension": Limit(1700.0, 2620.0),
        "neck_extension": Limit(None, 36.0),
        "chest_compression": Limit(30.0, 42.0, 56.0),
    },
    "q10": {
        "hic15": Limit(500.0, 700.0, 700.0),
        "head_a3ms": Limit(60.0, 80.0, 80.0),
        "neck_tension": Limit(1700.0, 2620.0),
        "neck_extension": Limit(None, 49.0),
        "chest_compression": Limit(None, 56.0, 56.0),
        "chest_a3ms": Limit(41.0, 55.0, 55.0),
    },
}
"""Limits per dummy from the protocol's Section 3.5 (kN converted to N).
Chest compression of adult dummies depends on the test speed; see
`CHEST_COMPRESSION_LIMITS`. The THOR chest compression is Rmax.
Hybrid III 95th tibia HPLs are bracketed in the protocol (to apply once
a lower leg certification procedure exists). Hybrid III 5th neck capping
applies to the driver only. Q6 / Q10 neck extension and Q10 chest
compression are printed as single values and used as LPLs."""

CHEST_COMPRESSION_LIMITS: dict[str, dict[int, Limit]] = {
    "hybrid3_05": {35: Limit(18.0, 34.0, 34.0), 50: Limit(18.0, 34.0, 34.0),
                   56: Limit(22.0, 42.0, 42.0)},
    "hybrid3_50": {35: Limit(20.0, 42.0, 42.0), 50: Limit(20.0, 42.0, 42.0)},
    "thor_50": {35: Limit(29.0, 54.0, 54.0), 50: Limit(35.0, 60.0, 60.0)},
    "hybrid3_95": {50: Limit(28.0, 55.0), 56: Limit(28.0, 55.0)},
}
"""Adult chest compression limits (mm) by test speed (km/h)."""

MPDB_OCCUPANTS: dict[str, tuple[str, dict[str, float]]] = {
    "driver": ("thor_50", dict.fromkeys(ADULT_REGIONS, 1.25)),
    "front_passenger": ("hybrid3_05", dict.fromkeys(ADULT_REGIONS, 1.25)),
    "rear_q6": ("q6", {"head": 2.5, "neck": 1.25, "chest": 1.25}),
    "rear_q10": ("q10", {"head": 2.5, "neck": 1.25, "chest": 1.25}),
}
"""MPDB (offset) test: dummy and region points per position (20 points)."""

FWDB_OCCUPANTS: dict[str, tuple[str, dict[str, float]]] = {
    "driver": ("hybrid3_05", dict.fromkeys(ADULT_REGIONS, 1.25)),
    "front_passenger": ("thor_50", dict.fromkeys(ADULT_REGIONS, 0.625)),
    "rear_passenger": ("hybrid3_05", {"head_neck": 0.625, "chest_abdomen": 1.25,
                                      "knee_femur_pelvis": 0.625}),
}
"""Full width test (35 km/h): dummy and region points per position
(10 points); the rear passenger's lower leg is not scored."""

FWDB_SPEED = 35
"""Full width test speed, km/h (protocol Section 3.2)."""

OCCUPANT_MODIFIERS: dict[str, tuple[str, float]] = {
    "head_bottoming_out": ("head_neck", 20.0),
    "unstable_airbag_contact": ("head_neck", 20.0),
    "hazardous_airbag_deployment": ("head_neck", 20.0),
    "excursion_450mm": ("head_neck", 50.0),
    "excursion_550mm": ("head_neck", 100.0),
    "steering_wheel_contact": ("chest_abdomen", 20.0),
    "shoulder_belt_load": ("chest_abdomen", 40.0),
    "submarining": ("knee_femur_pelvis", 100.0),
    "knee_load_variable": ("knee_femur_pelvis", 20.0),
    "knee_load_concentrated": ("knee_femur_pelvis", 20.0),
    "pedal_rearward_100mm": ("lower_leg", 50.0),
    "pedal_rearward_200mm": ("lower_leg", 100.0),
    "pedal_vertical_72mm": ("lower_leg", 20.0),
    "pedal_blocking": ("lower_leg", 20.0),
    "incorrect_airbag_deployment": ("per region", 20.0),
    "q6_excursion_550mm": ("head", 100.0),
    "q10_excursion_450mm": ("head", 50.0),
    "q10_excursion_550mm": ("head", 100.0),
    "q_full_belt_slippage": ("dummy", 100.0),
    "q_partial_belt_slippage": ("dummy", 50.0),
    "q_restraint": ("dummy", 100.0),
    "q_submarining": ("dummy", 100.0),
    "q_ejection": ("dummy", 100.0),
    "q_crs_attachment": ("dummy", 100.0),
}
"""Occupant modifiers (protocol Section 4.3.1): body region and penalty in
% of that region's points (``"dummy"``: of the Q dummy score). DAMAGE:
see `damage_modifier`. Reference data for building the inputs."""

FULL_SCALE_MODIFIERS: dict[str, float] = {
    "a_pillar_100mm": 2.5,
    "steering_column": 1.25,
    "bodyshell_integrity": 1.25,
    "footwell_rupture": 1.25,
    "door_opening": 5.0,
    "door_detachment": 100.0,
    "restraint_failure": 100.0,
}
"""Full-scale test modifiers (Section 4.3.2), % of 10 points. Door opening
applies per door; steering column uses the worst of rearward (>= 90 mm),
vertical (>= 72 mm) and lateral (>= 90 mm)."""

FULL_SCALE_MODIFIER_BASE = 10.0
"""Full-scale modifiers are percentages of 10 points per load case."""


def colour_band(value: float, limit: Limit) -> str:
    """Colour band of a criterion value (see the module notes)."""
    if not math.isfinite(value):
        raise ValueError("value must be finite.")
    if limit.hpl is None:
        return "green" if value < limit.lpl else "red"
    if not limit.hpl < limit.lpl:
        raise ValueError("HPL must be below LPL.")
    if value < limit.hpl:
        return "green"
    if value >= limit.lpl:
        return "red"
    fraction = (value - limit.hpl) / (limit.lpl - limit.hpl)
    if fraction < 1 / 3:
        return "yellow"
    if fraction < 2 / 3:
        return "orange"
    return "brown"


@dataclass(frozen=True)
class CriterionResult:
    name: str
    value: float
    limit: Limit
    band: str
    capping_exceeded: bool
    """True if the value is at or above the capping limit."""


@dataclass(frozen=True)
class RegionScore:
    name: str
    points: float
    """Points after modifiers (not below zero)."""
    max_points: float
    band: str
    """Band of the lowest-scoring criterion."""
    governing: str
    """Criterion that set the band."""
    modifier_percent: float
    """Sum of the occupant modifiers applied, % of ``max_points``."""
    criteria: tuple[CriterionResult, ...]


@dataclass(frozen=True)
class DummyScore:
    dummy: str
    points: float
    max_points: float
    regions: dict[str, RegionScore]
    hard_contact: bool
    capping_exceeded: tuple[str, ...]
    """Criteria at or above their capping limit. The protocol extract does
    not state the consequence, so it is reported, not applied."""


@dataclass(frozen=True)
class Occupant:
    """Measured values and assessment inputs of one occupant."""

    values: Mapping[str, float]
    """Criterion values (keys of `ADULT_REGIONS` /
    `CHILD_REGIONS`, plus optional ``"head_peak"`` in g)."""
    hard_contact: bool | None = None
    """Head hard contact; inferred from ``values["head_peak"] > 80`` g if
    None."""
    modifiers: Mapping[str, Sequence[float]] = field(default_factory=dict)
    """Occupant modifiers per region, in % of the region points, e.g.
    ``{"head_neck": [20.0]}``."""
    dummy_modifiers: Sequence[float] = ()
    """Modifiers of the whole dummy score in % (Q dummy score modifiers,
    e.g. 50 for partial belt slippage)."""


def damage_modifier(damage: float) -> float:
    """Head and neck modifier for THOR DAMAGE, %: 20 for 0.42 <= DAMAGE <
    0.47, 40 at 0.47 or above, else 0."""
    if not math.isfinite(damage):
        raise ValueError("damage must be finite.")
    if damage >= 0.47:
        return 40.0
    return 20.0 if damage >= 0.42 else 0.0


def _limits_for(dummy: str, speed: int) -> dict[str, Limit]:
    if dummy not in DUMMY_LIMITS:
        known = ", ".join(sorted(DUMMY_LIMITS))
        raise ValueError(f"Unknown dummy {dummy!r}. Known: {known}.")
    limits = dict(DUMMY_LIMITS[dummy])
    if dummy in CHEST_COMPRESSION_LIMITS:
        by_speed = CHEST_COMPRESSION_LIMITS[dummy]
        if speed not in by_speed:
            raise ValueError(f"No chest limits for {dummy} at {speed} km/h; "
                             f"available: {sorted(by_speed)}.")
        limits["chest_compression"] = by_speed[speed]
    return limits


def score_dummy(
    dummy: str,
    occupant: Occupant,
    region_points: Mapping[str, float],
    speed: int = 50,
    band_fractions: Mapping[str, float] = BAND_FRACTIONS,
    driver: bool = False,
    exclude: Collection[str] = (),
) -> DummyScore:
    """Score one dummy.

    Parameters
    ----------
    dummy:
        Key of `DUMMY_LIMITS`.
    occupant:
        Values, hard contact and modifiers.
    region_points:
        Maximum points per body region (e.g. from `MPDB_OCCUPANTS`).
        Regions not listed are not scored.
    speed:
        Test speed for the adult chest compression limits, km/h.
    band_fractions:
        Share of the region points per band.
    driver:
        True for the driver (driver-only capping limits).
    exclude:
        Criteria not assessed (e.g. ``knee_displacement``, ``tibia_index``
        and ``tibia_force`` in virtual tests); they need no value.

    Raises
    ------
    ValueError
        For unknown criteria, or a missing value of a scored criterion.
    """
    limits = _limits_for(dummy, speed)
    child = dummy in ("q6", "q10")
    regions_map = CHILD_REGIONS if child else ADULT_REGIONS
    values = dict(occupant.values)
    head_peak = values.pop("head_peak", None)
    known = {c for crit in regions_map.values() for c in crit}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"Unknown criteria: {sorted(unknown)}.")
    if set(occupant.modifiers) - set(region_points):
        raise ValueError("Modifiers given for regions that are not scored.")

    hard_contact = occupant.hard_contact
    if hard_contact is None:
        if head_peak is None:
            raise ValueError("Give hard_contact or values['head_peak'].")
        hard_contact = head_peak > 80.0

    skipped: set[str] = set()
    if not hard_contact:
        skipped = {"hic15"} if child else set(_HEAD_IMPACT)

    regions: dict[str, RegionScore] = {}
    capped: list[str] = []
    for region, max_points in region_points.items():
        if region not in regions_map:
            raise ValueError(f"Unknown region {region!r} for {dummy}.")
        results = []
        for crit in regions_map[region]:
            if crit not in limits or crit in skipped or crit in exclude:
                continue
            if crit not in values:
                if crit in _OPTIONAL and child:
                    continue
                raise ValueError(f"Missing value for {crit!r} ({dummy}).")
            limit = limits[crit]
            value = float(values[crit])
            exceeded = (limit.capping is not None and value >= limit.capping
                        and (driver or not limit.capping_driver_only))
            if exceeded:
                capped.append(crit)
            results.append(CriterionResult(crit, value, limit,
                                           colour_band(value, limit), exceeded))
        if results:
            worst = min(results, key=lambda r: band_fractions[r.band])
            band, governing = worst.band, worst.name
        else:  # no head impact criterion applies without hard contact
            band, governing = "green", "no hard contact"
        percent = float(sum(occupant.modifiers.get(region, ())))
        points = max(0.0, band_fractions[band] * max_points
                     - percent / 100.0 * max_points)
        regions[region] = RegionScore(region, points, float(max_points), band,
                                      governing, percent, tuple(results))

    max_points = float(sum(region_points.values()))
    dummy_percent = float(sum(occupant.dummy_modifiers))
    points = max(0.0, sum(r.points for r in regions.values())
                 - dummy_percent / 100.0 * max_points)
    return DummyScore(
        dummy=dummy,
        points=points,
        max_points=max_points,
        regions=regions,
        hard_contact=bool(hard_contact),
        capping_exceeded=tuple(capped),
    )


@dataclass(frozen=True)
class TestScore:
    points: float
    """Test score after full-scale modifiers and compatibility (>= 0)."""
    max_points: float
    occupants: dict[str, DummyScore]
    occupant_points: float
    full_scale_deduction: float
    """Points removed by full-scale modifiers."""
    compatibility_penalty: float


def score_test(
    occupants: Mapping[str, DummyScore],
    full_scale_modifiers: Sequence[float] = (),
    compatibility_penalty: float = 0.0,
) -> TestScore:
    """Combine dummy scores into a test score.

    ``full_scale_modifiers`` are percentages of
    `FULL_SCALE_MODIFIER_BASE` (10 points), e.g. 2.5 for A-pillar
    displacement; ``compatibility_penalty`` is in points.
    """
    if not math.isfinite(compatibility_penalty) or compatibility_penalty < 0:
        raise ValueError("compatibility_penalty must be finite and >= 0.")
    occupant_points = sum(d.points for d in occupants.values())
    deduction = sum(full_scale_modifiers) / 100.0 * FULL_SCALE_MODIFIER_BASE
    return TestScore(
        points=max(0.0, occupant_points - deduction - compatibility_penalty),
        max_points=sum(d.max_points for d in occupants.values()),
        occupants=dict(occupants),
        occupant_points=occupant_points,
        full_scale_deduction=deduction,
        compatibility_penalty=compatibility_penalty,
    )


def _score_layout(
    layout: Mapping[str, tuple[str, dict[str, float]]],
    occupants: Mapping[str, Occupant],
    speed: int,
    band_fractions: Mapping[str, float],
    full_scale_modifiers: Sequence[float],
    compatibility_penalty: float,
) -> TestScore:
    missing = set(layout) - set(occupants)
    extra = set(occupants) - set(layout)
    if missing or extra:
        raise ValueError(f"Occupants must be {sorted(layout)}; missing "
                         f"{sorted(missing)}, unexpected {sorted(extra)}.")
    scores = {
        position: score_dummy(dummy, occupants[position], points, speed,
                              band_fractions, driver=position == "driver")
        for position, (dummy, points) in layout.items()
    }
    return score_test(scores, full_scale_modifiers, compatibility_penalty)


def score_mpdb(
    occupants: Mapping[str, Occupant],
    full_scale_modifiers: Sequence[float] = (),
    compatibility_penalty: float = 0.0,
    band_fractions: Mapping[str, float] = BAND_FRACTIONS,
) -> TestScore:
    """MPDB (offset) test score, 20 points at 50 km/h.

    ``occupants`` has keys ``"driver"`` (THOR 50th), ``"front_passenger"``
    (Hybrid III 5th), ``"rear_q6"`` and ``"rear_q10"``. Give the
    compatibility penalty in points (see `compatibility_penalty`).
    """
    return _score_layout(MPDB_OCCUPANTS, occupants, 50, band_fractions,
                         full_scale_modifiers, compatibility_penalty)


def score_fwdb(
    occupants: Mapping[str, Occupant],
    full_scale_modifiers: Sequence[float] = (),
    speed: int = FWDB_SPEED,
    band_fractions: Mapping[str, float] = BAND_FRACTIONS,
) -> TestScore:
    """Full width test score, 10 points.

    ``occupants`` has keys ``"driver"`` (Hybrid III 5th),
    ``"front_passenger"`` (THOR 50th) and ``"rear_passenger"`` (Hybrid III
    5th). The test runs at 35 km/h, which selects the chest compression
    limits; ``speed`` overrides it.
    """
    return _score_layout(FWDB_OCCUPANTS, occupants, speed, band_fractions,
                         full_scale_modifiers, 0.0)


def compatibility_percentages(sd: float, olc: float) -> tuple[float, float]:
    """MPDB compatibility sliding scales, % (CP 007 Appendix A.3).

    The barrier deformation standard deviation ``sd`` (mm) scales linearly
    from 50 mm (0 %) to 150 mm (100 %), the trolley OLC (g) from 25 g
    (0 %) to 40 g (100 %); both are clamped to 0-100 %.
    """
    for name, v in (("sd", sd), ("olc", olc)):
        if not math.isfinite(v):
            raise ValueError(f"{name} must be finite.")

    def scale(v: float, lo: float, hi: float) -> float:
        return 100.0 * min(1.0, max(0.0, (v - lo) / (hi - lo)))

    return scale(sd, 50.0, 150.0), scale(olc, 25.0, 40.0)


COMPATIBILITY_MAX_PENALTY = 5.0
"""Largest compatibility penalty, points (25 % of the 20-point MPDB score,
or 50 % of 10 points)."""


def compatibility_penalty(sd: float, olc: float, bottoming_out: bool) -> float:
    """MPDB compatibility penalty in points (CP 007, Appendix A).

    With ``s`` and ``o`` the SD and OLC sliding scales (0 to 1, see
    `compatibility_percentages`)::

        penalty = 1.25 (s + o + 2 s o) + 1.25 if bottoming out, <= 5 points

    This is the scoring rationale of CP 007 Figure 2 (1.25 points for the
    SD alone, 1.25 for the OLC alone, 5 for both at 100 %, 1.25 points =
    6.25 % of the MPDB score added for bottoming out) and reproduces its
    three worked examples (2.826, 5.0 and 2.242 points).
    """
    sd_pct, olc_pct = compatibility_percentages(sd, olc)
    s_, o_ = sd_pct / 100.0, olc_pct / 100.0
    penalty = 1.25 * (s_ + o_ + 2.0 * s_ * o_) + (1.25 if bottoming_out else 0.0)
    return min(COMPATIBILITY_MAX_PENALTY, penalty)
