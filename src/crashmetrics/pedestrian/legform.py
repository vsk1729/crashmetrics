"""Euro NCAP legform scoring: aPLI (femur, knee/tibia) and upper legform (pelvis).

Functions:

- `sliding_scale`: Score between a higher and a lower performance limit.
- `leg_colour`: Colour of a leg grid-point score.
- `apli_point_score`: Femur and knee/tibia scores of one aPLI test.
- `upper_legform_point_score`: Score of one upper legform test.
- `upper_legform_alpha`, `upper_legform_energy`: Upper legform impact
  angle, energy and test velocity, and whether a test is required.
- `apli_score`, `upper_legform_score`: Femur, knee/tibia and pelvis
  points of a full grid, filling untested points by symmetry and from
  the worst adjacent result.

Units: force in N, bending moment in N m, MCL elongation in mm, energy
in J. The Euro NCAP limits (both protocols):

| Criterion | Higher limit | Lower limit |
| --- | --- | --- |
| Upper legform sum of forces | 5.0 kN | 6.0 kN |
| aPLI femur bending moment | 390 N m | 440 N m |
| aPLI tibia bending moment | 275 N m | 320 N m |
| aPLI MCL elongation | 27 mm | 32 mm |

Region maxima: ``"euroncap_2026"`` (Crash Protection - VRU Impacts
v1.1) pelvis 2.5, femur 2.5, knee/tibia 5; ``"euroncap_2023"`` (VRU
Assessment Protocol v11.4) pelvis 4.5, femur 4.5, knee/tibia 9.

Grid points lie on a line across the vehicle. Give them as numbers
(lateral index, ``-5`` to ``5``; ``5.5`` for an extra point 50 mm
outboard) or as Euro NCAP names such as ``"L+3"``, ``"L0"``, ``"U-2"``.
Point ``-n`` is the mirror of ``n``.
"""

import math
import re
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
from numpy.typing import ArrayLike

from .._scoring import linear_fraction

__all__ = [
    "LEGFORM_LIMITS",
    "LEGFORM_PROTOCOLS",
    "ApliPointScore",
    "ApliScore",
    "LegRegionScore",
    "LegformProtocol",
    "UpperLegformEnergy",
    "apli_point_score",
    "apli_score",
    "leg_colour",
    "round_score",
    "sliding_scale",
    "upper_legform_alpha",
    "upper_legform_energy",
    "upper_legform_point_score",
    "upper_legform_score",
]

LEGFORM_LIMITS: dict[str, tuple[float, float]] = {
    "upper_legform_sum_of_forces": (5000.0, 6000.0),
    "apli_femur_moment": (390.0, 440.0),
    "apli_tibia_moment": (275.0, 320.0),
    "apli_mcl_elongation": (27.0, 32.0),
}
"""(higher, lower) performance limits: N, N m, N m and mm."""

UPPER_LEGFORM_NOMINAL_MASS = 7.4
"""Mass used for the nominal impact energy, kg."""

UPPER_LEGFORM_TEST_MASS = 10.5
"""Upper legform impactor test mass, kg."""

UPPER_LEGFORM_NOMINAL_VELOCITY = 11.11
"""Nominal velocity vo, m/s (40 km/h)."""

UPPER_LEGFORM_MIN_ENERGY = 160.0
"""A test is not required below this nominal impact energy, J."""


@dataclass(frozen=True)
class LegformProtocol:
    """Maximum points of the leg body regions in one protocol version."""

    name: str
    pelvis_points: float
    femur_points: float
    knee_tibia_points: float


LEGFORM_PROTOCOLS: dict[str, LegformProtocol] = {
    "euroncap_2026": LegformProtocol(
        name="Euro NCAP Crash Protection - VRU Impacts v1.1 (2026)",
        pelvis_points=2.5,
        femur_points=2.5,
        knee_tibia_points=5.0,
    ),
    "euroncap_2023": LegformProtocol(
        name="Euro NCAP Assessment Protocol - VRU v11.4 (2023)",
        pelvis_points=4.5,
        femur_points=4.5,
        knee_tibia_points=9.0,
    ),
}


def _protocol(protocol: str) -> LegformProtocol:
    if protocol not in LEGFORM_PROTOCOLS:
        known = ", ".join(sorted(LEGFORM_PROTOCOLS))
        raise ValueError(f"Unknown protocol {protocol!r}. Known: {known}.")
    return LEGFORM_PROTOCOLS[protocol]


# --- point scores -----------------------------------------------------------


def round_score(score: float, decimals: int = 3) -> float:
    """Round a score half up, as in the protocols' worked examples."""
    quantum = Decimal(1).scaleb(-decimals)
    return float(Decimal(repr(float(score))).quantize(quantum, ROUND_HALF_UP))


def _maybe_round(score: float, round_to: int | None) -> float:
    return score if round_to is None else round_score(score, round_to)


def sliding_scale(value: float, higher: float, lower: float) -> float:
    """Return the score of ``value`` on a linear sliding scale.

    1 at or below the higher performance limit, 0 at or above the
    lower performance limit, linear in between.
    """
    return linear_fraction(value, higher, lower)


def leg_colour(score: float) -> str:
    """Colour of a leg grid-point score, after rounding to 3 decimals.

    Green 1.000; yellow 0.750 to < 1.000; orange 0.500 to < 0.750;
    brown 0.001 to < 0.500; red 0.000 (VRU Assessment Protocol v11.4,
    Section 1.3.3.2).
    """
    s = round_score(score)
    if not 0.0 <= s <= 1.0:
        raise ValueError(f"score must be between 0 and 1, got {score!r}.")
    if s == 1.0:
        return "green"
    if s >= 0.75:
        return "yellow"
    if s >= 0.5:
        return "orange"
    if s >= 0.001:
        return "brown"
    return "red"


def _peak(values: ArrayLike, name: str) -> float:
    a = np.asarray(values, dtype=float)
    if a.size == 0:
        raise ValueError(f"{name} is empty.")
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must contain only finite values.")
    return float(np.max(np.abs(a)))


def upper_legform_point_score(
    sum_of_forces: ArrayLike, round_to: int | None = 3
) -> float:
    """Score of one upper legform test from the sum of forces.

    Parameters
    ----------
    sum_of_forces:
        Peak sum of the upper and lower forces in N, or its time
        history (the peak magnitude is used).
    round_to:
        Decimal places of the score (the protocols' examples use 3);
        None keeps it unrounded.
    """
    higher, lower = LEGFORM_LIMITS["upper_legform_sum_of_forces"]
    peak = _peak(sum_of_forces, "sum_of_forces")
    return _maybe_round(sliding_scale(peak, higher, lower), round_to)


@dataclass(frozen=True)
class ApliPointScore:
    """Scores of one aPLI test."""

    femur_moment: float
    """Peak femur bending moment used, N m."""

    tibia_moment: float
    """Peak tibia bending moment used, N m."""

    mcl_elongation: float
    """Peak MCL elongation used, mm."""

    femur: float
    """Femur score."""

    tibia: float
    """Tibia bending moment score."""

    mcl: float
    """MCL elongation score."""

    knee_tibia: float
    """Knee/tibia score: the lower of ``tibia`` and ``mcl``."""


def apli_point_score(
    femur_moment: ArrayLike,
    tibia_moment: ArrayLike,
    mcl_elongation: ArrayLike,
    round_to: int | None = 3,
) -> ApliPointScore:
    """Femur and knee/tibia scores of one aPLI test.

    Parameters
    ----------
    femur_moment:
        Femur bending moment in N m: a peak, the peaks of several
        gauges, or time histories. The largest magnitude is used
        ("worst performing femur bending moment").
    tibia_moment:
        Tibia bending moment in N m, as for ``femur_moment``.
    mcl_elongation:
        MCL elongation in mm (peak or time history).
    round_to:
        Decimal places of each score; None keeps them unrounded.
    """
    femur = _peak(femur_moment, "femur_moment")
    tibia = _peak(tibia_moment, "tibia_moment")
    mcl = _peak(mcl_elongation, "mcl_elongation")

    femur_score = _maybe_round(
        sliding_scale(femur, *LEGFORM_LIMITS["apli_femur_moment"]), round_to
    )
    tibia_score = _maybe_round(
        sliding_scale(tibia, *LEGFORM_LIMITS["apli_tibia_moment"]), round_to
    )
    mcl_score = _maybe_round(
        sliding_scale(mcl, *LEGFORM_LIMITS["apli_mcl_elongation"]), round_to
    )
    return ApliPointScore(
        femur_moment=femur,
        tibia_moment=tibia,
        mcl_elongation=mcl,
        femur=femur_score,
        tibia=tibia_score,
        mcl=mcl_score,
        knee_tibia=min(tibia_score, mcl_score),
    )


# --- upper legform energy ---------------------------------------------------


def upper_legform_alpha(
    ibrl: tuple[float, float], wad930: tuple[float, float]
) -> float:
    """Upper legform impact angle alpha, in degrees.

    Parameters
    ----------
    ibrl:
        ``(x, z)`` of the internal bumper reference line at the grid
        point's lateral position, in a side view with x positive
        rearward and z upward.
    wad930:
        ``(x, z)`` of WAD 930 at the same lateral position, same units.

    Returns
    -------
    float
        Angle to the ground of the impact direction, which is
        perpendicular to the straight line through the two points:
        0 for a vertical line, 45 for a line at 45 degrees. Negative if
        the line leans forward beyond vertical.
    """
    dx = float(wad930[0]) - float(ibrl[0])
    dz = float(wad930[1]) - float(ibrl[1])
    if not (math.isfinite(dx) and math.isfinite(dz)):
        raise ValueError("Coordinates must be finite.")
    if dz <= 0:
        raise ValueError(
            "WAD 930 must be above the internal bumper reference line."
        )
    inclination = math.degrees(math.atan2(dz, dx))
    return 90.0 - inclination


@dataclass(frozen=True)
class UpperLegformEnergy:
    """Upper legform nominal impact energy and test velocity."""

    alpha: float
    """Impact angle used, degrees."""

    nominal_velocity: float
    """vc = 11.11 cos(1.2 alpha), m/s."""

    energy: float
    """Nominal impact energy En = 0.5 x 7.4 kg x vc^2, J."""

    test_velocity: float
    """vt = sqrt(2 En / 10.5 kg), m/s."""

    test_required: bool
    """False if ``energy`` is below 160 J."""


def upper_legform_energy(alpha: float) -> UpperLegformEnergy:
    """Nominal impact energy and test velocity of the upper legform.

    Parameters
    ----------
    alpha:
        Impact angle in degrees, from `upper_legform_alpha`.
        Negative angles are treated as 0 (this package's reading of the
        protocol's alignment rule; check it for your case).

    Notes
    -----
    En = 0.5 x 7.4 kg x (11.11 m/s x cos(1.2 alpha))^2, and the test
    velocity with the 10.5 kg impactor is vt = sqrt(2 En / 10.5 kg). No
    test is required if En is below 160 J.
    """
    a = float(alpha)
    if not math.isfinite(a):
        raise ValueError("alpha must be finite.")
    if a > 75.0:
        raise ValueError(
            "alpha must not exceed 75 degrees: cos(1.2 alpha) would be "
            "negative."
        )
    a = max(a, 0.0)
    vc = UPPER_LEGFORM_NOMINAL_VELOCITY * math.cos(math.radians(1.2 * a))
    energy = 0.5 * UPPER_LEGFORM_NOMINAL_MASS * vc**2
    return UpperLegformEnergy(
        alpha=a,
        nominal_velocity=vc,
        energy=energy,
        test_velocity=math.sqrt(2.0 * energy / UPPER_LEGFORM_TEST_MASS),
        test_required=energy >= UPPER_LEGFORM_MIN_ENERGY,
    )


# --- grid scoring -----------------------------------------------------------

_NAME = re.compile(r"\s*[A-Za-z]*\s*([+-]?\d+(?:\.\d+)?)\s*")


def _position(point: Hashable) -> float:
    if isinstance(point, bool):
        raise ValueError(f"Invalid grid point {point!r}.")
    if isinstance(point, (int, float, np.integer, np.floating)):
        value = float(point)
    elif isinstance(point, str) and (match := _NAME.fullmatch(point)):
        value = float(match.group(1))
    else:
        raise ValueError(
            f"Invalid grid point {point!r}: use a lateral index such as 3 "
            "or -2.5, or a name such as 'L+3' or 'U-2'."
        )
    if not math.isfinite(value):
        raise ValueError(f"Invalid grid point {point!r}.")
    return value


@dataclass(frozen=True)
class LegRegionScore:
    """Points of one body region from a legform grid."""

    region: str
    """``"pelvis"``, ``"femur"`` or ``"knee_tibia"``."""

    points: float
    max_points: float
    percentage: float
    """Sum of grid-point scores as a percentage of the number of points."""

    total: float
    """Sum of the grid-point scores."""

    grid_points: int
    scores: dict[Hashable, float]
    """Score of every grid point, from the highest lateral index down."""

    sources: dict[Hashable, str]
    """Where each score comes from: ``"tested"``, ``"symmetry of X"``,
    ``"worst adjacent X"`` or ``"not required (E < 160 J)"``."""

    protocol: str

    @property
    def colours(self) -> dict[Hashable, str]:
        """Colour of every grid point."""
        return {p: leg_colour(s) for p, s in self.scores.items()}


def _fill_grid(
    grid_points: Iterable[Hashable],
    known: Mapping[Hashable, tuple[float, str]],
    symmetric: bool,
    asymmetric_points: Iterable[Hashable],
    energies: Mapping[Hashable, float] | None,
    energy_tolerance: float,
) -> tuple[dict[Hashable, float], dict[Hashable, str]]:
    """Score every grid point: tested, then symmetry, then worst adjacent."""
    points = list(grid_points)
    if not points:
        raise ValueError("grid_points is empty.")
    position = {p: _position(p) for p in points}
    by_position: dict[float, Hashable] = {}
    for p, x in position.items():
        key = round(x, 6)
        if key in by_position:
            raise ValueError(
                f"Grid points {by_position[key]!r} and {p!r} have the same "
                "lateral position."
            )
        by_position[key] = p

    for p in known:
        if p not in position:
            raise ValueError(f"Result given for {p!r}, which is not a grid point.")
    asymmetric = set(asymmetric_points)
    for p in asymmetric:
        if p not in position:
            raise ValueError(f"Asymmetric point {p!r} is not a grid point.")

    def energy_ok(target: Hashable, source: Hashable) -> bool:
        if energies is None:
            return True
        e_source = energies[source]
        return abs(energies[target] - e_source) <= energy_tolerance * e_source

    scores = {p: known[p][0] for p in known}
    sources = {p: known[p][1] for p in known}

    if symmetric:
        for p in points:
            if p in scores or p in asymmetric:
                continue
            mirror = by_position.get(round(-position[p], 6))
            if (
                mirror is not None
                and mirror in known
                and mirror not in asymmetric
                and energy_ok(p, mirror)
            ):
                scores[p] = known[mirror][0]
                sources[p] = f"symmetry of {mirror!r}"

    filled = dict(scores)
    order = sorted(points, key=lambda p: position[p])
    for i, p in enumerate(order):
        if p in filled:
            continue
        neighbours = [
            q
            for q in (order[i - 1] if i > 0 else None,
                      order[i + 1] if i + 1 < len(order) else None)
            if q is not None and q in filled and energy_ok(p, q)
        ]
        if not neighbours:
            note = (
                " within the 10 % energy tolerance" if energies is not None else ""
            )
            raise ValueError(
                f"Grid point {p!r} has no tested, symmetric or adjacent "
                f"result{note}; it needs a test."
            )
        # Worst score; on a tie, prefer a tested neighbour as the source.
        worst = min(neighbours, key=lambda q: (filled[q], sources[q] != "tested"))
        scores[p] = filled[worst]
        sources[p] = f"worst adjacent {worst!r}"

    ordered = sorted(points, key=lambda p: -position[p])
    return ({p: scores[p] for p in ordered}, {p: sources[p] for p in ordered})


def _region(
    region: str,
    scores: dict[Hashable, float],
    sources: dict[Hashable, str],
    max_points: float,
    protocol: str,
) -> LegRegionScore:
    total = sum(scores.values())
    fraction = total / len(scores)
    return LegRegionScore(
        region=region,
        points=fraction * max_points,
        max_points=max_points,
        percentage=100.0 * fraction,
        total=total,
        grid_points=len(scores),
        scores=scores,
        sources=sources,
        protocol=protocol,
    )


def upper_legform_score(
    grid_points: Iterable[Hashable],
    tests: Mapping[Hashable, ArrayLike],
    energies: Mapping[Hashable, float] | None = None,
    protocol: str = "euroncap_2026",
    symmetric: bool = True,
    asymmetric_points: Iterable[Hashable] = (),
    not_required_score: float = 1.0,
    energy_tolerance: float = 0.10,
    round_to: int | None = 3,
) -> LegRegionScore:
    """Pelvis points from upper legform tests on the WAD 775 grid.

    Parameters
    ----------
    grid_points:
        All grid points (``"U+4"`` ... ``"U-4"``, or lateral indices).
    tests:
        ``{point: sum of forces in N}`` (peak or time history) for the
        tested points.
    energies:
        Optional ``{point: nominal impact energy in J}`` for every grid
        point, from `upper_legform_energy`. Untested points below
        160 J get ``not_required_score``, and a symmetric or adjacent
        result is used only if the two energies differ by at most
        ``energy_tolerance`` (10 %) of the tested point's energy.
    protocol:
        ``"euroncap_2026"`` (2.5 points) or ``"euroncap_2023"`` (4.5).
    symmetric:
        Apply results to the mirror point on the other side.
    asymmetric_points:
        Points the manufacturer declared asymmetric: no symmetry is
        applied to or from them.
    not_required_score:
        Score of untested points where no test is required (below
        160 J). The protocols do not state it; 1.0 (full points) is this
        package's default.
    energy_tolerance:
        Relative energy difference allowed when a result is shared.
    round_to:
        Decimal places of each tested point's score; None keeps it.

    Returns
    -------
    LegRegionScore
        Region ``"pelvis"``: grid-point scores summed, divided by the
        number of grid points and multiplied by the region maximum.

    Notes
    -----
    Untested points take, in order: the result of their mirror point
    (if symmetric), else the worst result of the adjacent points that
    have a tested or mirrored result.
    """
    spec = _protocol(protocol)
    points = list(grid_points)
    if energies is not None:
        missing = [p for p in points if p not in energies]
        if missing:
            raise ValueError(f"energies is missing grid points {missing!r}.")
        if any(not math.isfinite(energies[p]) or energies[p] < 0 for p in points):
            raise ValueError("energies must be finite and non-negative.")
    if not 0.0 <= not_required_score <= 1.0:
        raise ValueError("not_required_score must be between 0 and 1.")

    known: dict[Hashable, tuple[float, str]] = {
        p: (upper_legform_point_score(f, round_to), "tested")
        for p, f in tests.items()
    }
    if energies is not None:
        for p in points:
            if p not in known and energies[p] < UPPER_LEGFORM_MIN_ENERGY:
                known[p] = (not_required_score, "not required (E < 160 J)")

    scores, sources = _fill_grid(
        points, known, symmetric, asymmetric_points, energies, energy_tolerance
    )
    return _region("pelvis", scores, sources, spec.pelvis_points, protocol)


@dataclass(frozen=True)
class ApliScore:
    """Femur and knee/tibia points from aPLI tests."""

    femur: LegRegionScore
    knee_tibia: LegRegionScore
    point_scores: dict[Hashable, ApliPointScore]
    """Scores of the tested points."""


def apli_score(
    grid_points: Iterable[Hashable],
    tests: Mapping[Hashable, ApliPointScore | tuple[ArrayLike, ArrayLike, ArrayLike]],
    protocol: str = "euroncap_2026",
    symmetric: bool = True,
    asymmetric_points: Iterable[Hashable] = (),
    round_to: int | None = 3,
) -> ApliScore:
    """Femur and knee/tibia points from aPLI tests on the bumper grid.

    Parameters
    ----------
    grid_points:
        All bumper test zone grid points (``"L+5"`` ... ``"L-5"``, or
        lateral indices; an extra point 50 mm outboard can be 5.5).
    tests:
        ``{point: (femur_moment, tibia_moment, mcl_elongation)}`` in
        N m, N m and mm (peaks, gauge peaks or time histories), or an
        `ApliPointScore`, for the tested points.
    protocol:
        ``"euroncap_2026"`` (femur 2.5, knee/tibia 5) or
        ``"euroncap_2023"`` (4.5 and 9).
    symmetric, asymmetric_points:
        As for `upper_legform_score`.
    round_to:
        Decimal places of each tested point's scores; None keeps them.

    Notes
    -----
    Untested points are filled separately for the femur and for the
    knee/tibia, so one untested point can take its femur score from one
    neighbour and its knee/tibia score from the other.
    """
    spec = _protocol(protocol)
    points = list(grid_points)

    point_scores: dict[Hashable, ApliPointScore] = {}
    for p, value in tests.items():
        if isinstance(value, ApliPointScore):
            point_scores[p] = value
        else:
            femur, tibia, mcl = value
            point_scores[p] = apli_point_score(femur, tibia, mcl, round_to)

    regions = {}
    for region, max_points in (
        ("femur", spec.femur_points),
        ("knee_tibia", spec.knee_tibia_points),
    ):
        known = {
            p: (getattr(s, region), "tested") for p, s in point_scores.items()
        }
        scores, sources = _fill_grid(
            points, known, symmetric, asymmetric_points, None, 0.0
        )
        regions[region] = _region(region, scores, sources, max_points, protocol)

    return ApliScore(
        femur=regions["femur"],
        knee_tibia=regions["knee_tibia"],
        point_scores=point_scores,
    )
