"""Euro NCAP headform grid scoring for pedestrian and cyclist protection.

Functions
---------
hic_colour
    Colour band of a HIC15 value.
verification_colour
    Colour assigned to a verification test, with the 10 % HIC tolerance.
correction_factor
    Correction factor from verification tests.
headform_score
    Head score of a full impact-point grid.

The rules follow the Euro NCAP protocols named in :data:`PROTOCOLS`:

- ``"euroncap_2026"``: Crash Protection - Vulnerable Road User Impacts,
  v1.1, September 2025 (head maximum 10 points, A-pillar rewards).
- ``"euroncap_2023"``: Assessment Protocol - Vulnerable Road User
  Protection, v11.4, December 2023 (head maximum 18 points).

Check them against the protocol version you assess to.

Grid points are identified by any hashable key, for example
``(row, column)`` tuples such as ``(12, -6)``. Each grid point holds
either a predicted HIC15 value or one of these labels:

- ``"green"``, ``"yellow"``, ``"orange"``, ``"brown"``, ``"red"``:
  predicted colour
- ``"default_red"``: defaulted red (for example roof), always 0 points
- ``"blue"``: blue point, scored from its own test result
- ``"a_pillar"``: A-pillar point; 0 points unless tested for the
  rewards of the 2026 protocol (in 2023 it scores as default red)
"""

import math
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass, field

__all__ = [
    "COLOUR_POINTS",
    "PROTOCOLS",
    "CorrectionFactorResult",
    "HeadformProtocol",
    "HeadformScore",
    "VerificationTest",
    "correction_factor",
    "headform_score",
    "hic_colour",
    "verification_colour",
]

COLOURS = ("green", "yellow", "orange", "brown", "red")
SPECIAL_LABELS = ("default_red", "blue", "a_pillar")

COLOUR_POINTS: dict[str, float] = {
    "green": 1.00,
    "yellow": 0.75,
    "orange": 0.50,
    "brown": 0.25,
    "red": 0.00,
}
"""Points per grid point for each colour."""

# Upper HIC15 limit (exclusive) of each colour; red has none.
_HIC_LIMITS = (("green", 650.0), ("yellow", 1000.0), ("orange", 1350.0),
               ("brown", 1700.0))

# Accepted HIC15 range [low, high) that confirms a predicted colour,
# with the 10 % tolerance, exactly as tabulated in both protocols.
_TOLERANCE_RANGES: dict[str, tuple[float, float]] = {
    "green": (-math.inf, 722.22),
    "yellow": (590.91, 1111.11),
    "orange": (909.09, 1500.00),
    "brown": (1227.27, 1888.89),
    "red": (1545.45, math.inf),
}


@dataclass(frozen=True)
class HeadformProtocol:
    """Scoring parameters of one protocol version."""

    name: str
    max_points: float
    """Points available for the headform zone."""

    a_pillar_rewards: tuple[tuple[float, float, float], ...] | None
    """(impact speed km/h, HIC15 limit, points per grid point), or None
    if A-pillar points cannot earn points."""

    correction_range: tuple[float, float] = (0.850, 1.150)
    """Range of correction factors that are accepted without review."""


PROTOCOLS: dict[str, HeadformProtocol] = {
    "euroncap_2026": HeadformProtocol(
        name="Euro NCAP Crash Protection - VRU Impacts v1.1 (2026)",
        max_points=10.0,
        a_pillar_rewards=(
            (20.0, 1000.0, 1.0),
            (30.0, 1700.0, 2.0),
            (40.0, 1700.0, 3.0),
        ),
    ),
    "euroncap_2023": HeadformProtocol(
        name="Euro NCAP Assessment Protocol - VRU v11.4 (2023)",
        max_points=18.0,
        a_pillar_rewards=None,
    ),
}
"""Built-in protocol versions."""


def _check_hic(hic: float, name: str = "HIC15") -> float:
    value = float(hic)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative, got {hic!r}.")
    return value


def hic_colour(hic: float) -> str:
    """Return the colour band of a HIC15 value.

    Green < 650 <= yellow < 1000 <= orange < 1350 <= brown < 1700 <= red.
    """
    value = _check_hic(hic)
    for colour, limit in _HIC_LIMITS:
        if value < limit:
            return colour
    return "red"


def verification_colour(predicted: str, measured_hic: float) -> str:
    """Colour assigned to a verification test result.

    A 10 % tolerance on HIC15 applies only to confirm the predicted
    colour. If the measured value lies in the predicted colour's
    accepted range, the predicted colour stands; otherwise the colour
    is taken from the measured HIC15 without tolerance.

    Accepted ranges (as tabulated in the protocols): green < 722.22;
    yellow 590.91 to < 1111.11; orange 909.09 to < 1500.00; brown
    1227.27 to < 1888.89; red >= 1545.45.
    """
    if predicted not in COLOURS:
        raise ValueError(
            f"predicted must be one of {', '.join(COLOURS)}, got {predicted!r}."
        )
    value = _check_hic(measured_hic, "measured_hic")
    low, high = _TOLERANCE_RANGES[predicted]
    if low <= value < high:
        return predicted
    return hic_colour(value)


@dataclass(frozen=True)
class VerificationTest:
    """One verification test and how it was assessed."""

    point: Hashable
    predicted_colour: str
    measured_hic: float
    assessed_colour: str
    predicted_points: float
    actual_points: float


@dataclass(frozen=True)
class CorrectionFactorResult:
    """Correction factor from verification tests."""

    factor: float
    """Factor applied to the predicted score (rounded if requested)."""

    unrounded_factor: float
    predicted_score: float
    """Predicted points of the verification points."""

    actual_score: float
    """Points of the verification points from the tests."""

    accepted: bool
    """True if the factor is inside the protocol's accepted range."""

    tests: tuple[VerificationTest, ...]


def _predicted_colour(value: str | float) -> str:
    if isinstance(value, str):
        if value not in COLOURS:
            raise ValueError(f"Unknown grid label {value!r}.")
        return value
    return hic_colour(value)


def correction_factor(
    tests: Mapping[Hashable, tuple[str | float, float]],
    protocol: str = "euroncap_2026",
    round_to: int | None = 3,
) -> CorrectionFactorResult:
    """Return the correction factor from verification tests.

    Parameters
    ----------
    tests:
        ``{point: (prediction, measured_hic)}``, where ``prediction`` is a
        predicted colour or predicted HIC15. Do not include blue or
        default red points.
    protocol:
        Key of :data:`PROTOCOLS`, used for the accepted range.
    round_to:
        Decimal places to round the factor to before it is applied.
        The protocols' worked examples use three (for example
        6.50 / 7.00 = 0.929). Use None to keep it unrounded.

    Returns
    -------
    CorrectionFactorResult

    Notes
    -----
    ``factor = actual score / predicted score`` of the verification
    points, each scored with :data:`COLOUR_POINTS`.
    """
    if protocol not in PROTOCOLS:
        raise ValueError(f"Unknown protocol {protocol!r}.")
    if not tests:
        raise ValueError("At least one verification test is needed.")

    results = []
    for point, (prediction, measured) in tests.items():
        predicted = _predicted_colour(prediction)
        assessed = verification_colour(predicted, measured)
        results.append(
            VerificationTest(
                point=point,
                predicted_colour=predicted,
                measured_hic=float(measured),
                assessed_colour=assessed,
                predicted_points=COLOUR_POINTS[predicted],
                actual_points=COLOUR_POINTS[assessed],
            )
        )

    predicted_score = sum(r.predicted_points for r in results)
    actual_score = sum(r.actual_points for r in results)
    if predicted_score == 0:
        raise ValueError(
            "The verification points have a predicted score of zero, so "
            "the correction factor is undefined."
        )

    unrounded = actual_score / predicted_score
    factor = unrounded if round_to is None else round(unrounded, round_to)
    low, high = PROTOCOLS[protocol].correction_range
    return CorrectionFactorResult(
        factor=factor,
        unrounded_factor=unrounded,
        predicted_score=predicted_score,
        actual_score=actual_score,
        accepted=low <= factor <= high,
        tests=tuple(results),
    )


def _a_pillar_points(
    tests: Sequence[tuple[float, float]], protocol: HeadformProtocol
) -> float:
    """Highest reward earned by an A-pillar point's tests."""
    assert protocol.a_pillar_rewards is not None
    best = 0.0
    for speed, hic in tests:
        _check_hic(hic)
        matched = False
        for reward_speed, limit, points in protocol.a_pillar_rewards:
            if math.isclose(float(speed), reward_speed):
                matched = True
                if hic < limit:
                    best = max(best, points)
        if not matched:
            speeds = ", ".join(f"{s:g}" for s, _, _ in protocol.a_pillar_rewards)
            raise ValueError(
                f"A-pillar test speed {speed!r} km/h is not one of {speeds}."
            )
    return best


@dataclass(frozen=True)
class HeadformScore:
    """Head score of an impact-point grid."""

    score: float
    """Head points, out of ``max_score``, capped at the maximum."""

    max_score: float
    percentage: float
    """Grid score as a percentage of the maximum (capped at 100)."""

    grid_points: int
    """Number of grid points, the maximum achievable grid score."""

    total_points: float
    """Grid score before the 100 % cap: corrected predicted points plus
    blue and A-pillar points."""

    predicted_points: float
    """Predicted points of the coloured (non-special) grid points."""

    corrected_points: float
    """``predicted_points`` multiplied by the correction factor."""

    blue_points: float
    a_pillar_points: float
    correction: CorrectionFactorResult | None
    """None when no verification tests were given (no correction)."""

    colour_counts: dict[str, int] = field(default_factory=dict)
    """Number of grid points per predicted colour or label."""

    protocol: str = ""


def headform_score(
    grid: Mapping[Hashable, str | float],
    verification: Mapping[Hashable, float] | None = None,
    blue_results: Mapping[Hashable, float] | None = None,
    a_pillar_results: Mapping[Hashable, Sequence[tuple[float, float]]] | None = None,
    protocol: str = "euroncap_2026",
    round_correction_factor: int | None = 3,
) -> HeadformScore:
    """Return the Euro NCAP head score of an impact-point grid.

    Parameters
    ----------
    grid:
        ``{point: predicted HIC15 or label}`` for every grid point,
        labels as described in the module notes.
    verification:
        ``{point: measured HIC15}`` of the 40 km/h verification tests.
        Each point must be a coloured (predicted) grid point. Without
        verification tests no correction is applied, for example when
        estimating the score from CAE predictions.
    blue_results:
        ``{point: measured HIC15}`` for every blue grid point. Apply a
        zone's test result to each point of the zone (and symmetric
        points) before calling.
    a_pillar_results:
        ``{point: [(speed_kmh, HIC15), ...]}`` for tested A-pillar
        points (2026 protocol only). Untested A-pillar points score 0.
    protocol:
        Key of :data:`PROTOCOLS`.
    round_correction_factor:
        Decimal places of the correction factor; see
        :func:`correction_factor`.

    Returns
    -------
    HeadformScore

    Notes
    -----
    Each grid point can earn at most one point from its colour (green
    1, yellow 0.75, orange 0.5, brown 0.25, red 0), so the maximum
    grid score is the number of grid points. The predicted points of
    the coloured grid points are multiplied by the correction factor.
    Blue points (scored from their tests), default red points (0) and
    A-pillar points are not corrected. In the 2026 protocol each
    tested A-pillar point earns the reward of the highest speed at
    which it passes: 20 km/h with HIC15 < 1000 earns 1, 30 km/h with
    HIC15 < 1700 earns 2, 40 km/h with HIC15 < 1700 earns 3.

    ``score = min(total_points / grid_points, 1) * max_points``.

    How the A-pillar rewards combine with the grid total is this
    package's reading of the protocol (added to the grid score; the
    maximum stays the number of grid points); confirm it for your use.
    """
    if protocol not in PROTOCOLS:
        known = ", ".join(sorted(PROTOCOLS))
        raise ValueError(f"Unknown protocol {protocol!r}. Known: {known}.")
    spec = PROTOCOLS[protocol]
    if not grid:
        raise ValueError("grid is empty.")

    verification = dict(verification or {})
    blue_results = dict(blue_results or {})
    a_pillar_results = dict(a_pillar_results or {})

    counts: dict[str, int] = {}
    predicted_points = 0.0
    blue_points = 0.0
    a_pillar_points = 0.0
    colour_of: dict[Hashable, str] = {}

    for point, value in grid.items():
        if isinstance(value, str):
            if value not in COLOURS and value not in SPECIAL_LABELS:
                labels = ", ".join(COLOURS + SPECIAL_LABELS)
                raise ValueError(
                    f"Grid point {point!r}: unknown label {value!r}. "
                    f"Use a predicted HIC15 or one of: {labels}."
                )
            label = value
        else:
            label = hic_colour(value)
        counts[label] = counts.get(label, 0) + 1

        if label in COLOURS:
            colour_of[point] = label
            predicted_points += COLOUR_POINTS[label]
        elif label == "blue":
            if point not in blue_results:
                raise ValueError(f"Blue grid point {point!r} has no test result.")
            blue_points += COLOUR_POINTS[hic_colour(blue_results[point])]
        elif label == "a_pillar":
            if point in a_pillar_results:
                if spec.a_pillar_rewards is None:
                    raise ValueError(
                        f"The {protocol} protocol has no A-pillar rewards; "
                        "A-pillar points score as default red."
                    )
                a_pillar_points += _a_pillar_points(a_pillar_results[point], spec)

    for name, results, label in (
        ("blue_results", blue_results, "blue"),
        ("a_pillar_results", a_pillar_results, "a_pillar"),
    ):
        for point in results:
            if grid.get(point) != label:
                raise ValueError(
                    f"{name} has point {point!r}, which is not a "
                    f"{label!r} grid point."
                )

    correction = None
    factor = 1.0
    if verification:
        tests = {}
        for point, measured in verification.items():
            if point not in colour_of:
                raise ValueError(
                    f"Verification point {point!r} must be a coloured "
                    "(predicted) grid point, not blue, default red or "
                    "A-pillar."
                )
            tests[point] = (colour_of[point], measured)
        correction = correction_factor(
            tests, protocol=protocol, round_to=round_correction_factor
        )
        factor = correction.factor

    corrected = predicted_points * factor
    total = corrected + blue_points + a_pillar_points
    n_points = len(grid)
    fraction = min(total / n_points, 1.0)

    return HeadformScore(
        score=fraction * spec.max_points,
        max_score=spec.max_points,
        percentage=100.0 * fraction,
        grid_points=n_points,
        total_points=total,
        predicted_points=predicted_points,
        corrected_points=corrected,
        blue_points=blue_points,
        a_pillar_points=a_pillar_points,
        correction=correction,
        colour_counts=counts,
        protocol=protocol,
    )
