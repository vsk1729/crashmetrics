"""Flex-PLI (flexible pedestrian legform impactor) criteria and scoring.

Functions
---------
assessment_interval
    Flex-PLI assessment interval (AIS-100 Rev.1 3.2, UN GTR 9, UN R127).
flexpli_peaks
    Peak tibia bending moment and knee ligament elongations within it.
flexpli_point_score, flexpli_score
    Euro NCAP Flex-PLI scoring (Pedestrian / VRU Assessment Protocol
    v10.0.5, used 2014-2022): tibia and knee halves per grid point, the
    grid scaled to 6 points.

Units: time in s, bending moment in N m, elongation in mm. Filter all
channels with CFC 180.

Euro NCAP limits (higher / lower performance):

======================  ===========  ===========
Tibia bending moment    282 N m      340 N m
MCL elongation          19 mm        22 mm
ACL / PCL elongation    10 mm (threshold: knee scores 0 at or above)
======================  ===========  ===========
"""

from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics._channels import as_channels
from crashmetrics.pedestrian.legform import (
    LegRegionScore,
    _fill_grid,
    _maybe_round,
    _region,
    sliding_scale,
)

__all__ = [
    "FLEXPLI_LIMITS",
    "FlexPliPeaks",
    "FlexPliPointScore",
    "assessment_interval",
    "flexpli_peaks",
    "flexpli_point_score",
    "flexpli_score",
]

FLEXPLI_LIMITS: dict[str, tuple[float, float]] = {
    "tibia_moment": (282.0, 340.0),
    "mcl_elongation": (19.0, 22.0),
    "acl_pcl_elongation": (10.0, 10.0),
}
"""Euro NCAP (higher, lower) performance limits, N m and mm (v10.0.5,
Section 1.1.3)."""

MARGINAL_MOMENT = 15.0
"""Bending moment above which the first local maximum is sought, N m."""


def _segment_end(
    t: NDArray[np.float64], m: NDArray[np.float64], start: int
) -> tuple[int, int] | None:
    """Index of the first local maximum after the moment first exceeds
    15 N m, and of the first zero crossing after it (None if none)."""
    above = np.flatnonzero(m[start:] > MARGINAL_MOMENT)
    if above.size == 0:
        return None
    i = start + int(above[0])
    while i + 1 < len(m) and m[i + 1] >= m[i]:
        i += 1
    crossing = np.flatnonzero(m[i:] <= 0.0)
    return i, (i + int(crossing[0]) if crossing.size else -1)


def assessment_interval(
    time: ArrayLike,
    bone_moments: Sequence[ArrayLike],
    t_contact: float | None = None,
) -> tuple[float, float]:
    """Flex-PLI assessment interval (AI), (start, end) in s.

    AIS-100 Rev.1 Section 3.2 (as UN GTR 9 / UN R127): from first contact
    to the last zero crossing of all femur and tibia segments after their
    first local maximum following a marginal value of 15 N m. If a segment
    does not cross zero, all curves are shifted down until every segment
    crosses zero (for the AI only).

    Parameters
    ----------
    time:
        1D time array, s.
    bone_moments:
        Femur and tibia bending moment histories (normally femur 1-3 and
        tibia 1-4), N m, positive in impact bending.
    t_contact:
        Time of first contact; the first sample by default.

    Notes
    -----
    Implementation: each segment ends at its first zero crossing after
    that first maximum; the AI ends at the latest of these. Segments that
    never exceed 15 N m do not limit the AI. With a downward shift, the
    shift is the smallest that makes every such segment reach zero after
    its maximum.
    """
    t, moments = as_channels(time, *bone_moments)
    if not moments:
        raise ValueError("Give at least one bending moment history.")
    start = 0 if t_contact is None else int(np.searchsorted(t, t_contact))
    if start >= len(t):
        raise ValueError("t_contact is after the end of the record.")

    shift = 0.0
    for m in moments:
        seg = _segment_end(t, m, start)
        if seg is not None and seg[1] < 0:
            shift = max(shift, float(np.min(m[seg[0]:])))
    ends = []
    for m in moments:
        seg = _segment_end(t, m - shift, start)
        if seg is not None:
            ends.append(seg[1])
    if not ends:
        raise ValueError("No bending moment exceeds 15 N m.")
    return float(t[start]), float(t[max(ends)])


@dataclass(frozen=True)
class FlexPliPeaks:
    """Peak Flex-PLI values within the assessment interval."""

    tibia_moment: float
    """Largest |moment| of the tibia segments, N m."""
    tibia_segment: int
    """Index (0-based) of the tibia segment with the largest moment."""
    mcl: float
    acl: float
    pcl: float
    """Largest |elongation|, mm."""
    interval: tuple[float, float]


def flexpli_peaks(
    time: ArrayLike,
    tibia_moments: Sequence[ArrayLike],
    mcl: ArrayLike,
    acl: ArrayLike,
    pcl: ArrayLike,
    interval: tuple[float, float] | None = None,
    femur_moments: Sequence[ArrayLike] = (),
) -> FlexPliPeaks:
    """Peak absolute tibia bending moment and ligament elongations.

    The peaks are taken within ``interval``; if None, it is computed with
    :func:`assessment_interval` from the femur and tibia moments.
    """
    t, chans = as_channels(time, *tibia_moments, mcl, acl, pcl)
    n_tibia = len(tibia_moments)
    if n_tibia == 0:
        raise ValueError("Give at least one tibia bending moment history.")
    if interval is None:
        interval = assessment_interval(t, [*femur_moments, *chans[:n_tibia]])
    keep = (t >= interval[0]) & (t <= interval[1])
    peaks = [float(np.max(np.abs(c[keep]))) for c in chans]
    tibia = peaks[:n_tibia]
    worst = int(np.argmax(tibia))
    return FlexPliPeaks(tibia[worst], worst, peaks[n_tibia], peaks[n_tibia + 1],
                        peaks[n_tibia + 2], (float(interval[0]), float(interval[1])))


@dataclass(frozen=True)
class FlexPliPointScore:
    """Euro NCAP score of one Flex-PLI test (0-1)."""

    tibia: float
    """0-0.5 from the tibia bending moment."""
    knee: float
    """0-0.5 from the MCL elongation; 0 if ACL or PCL reaches 10 mm."""
    total: float


def flexpli_point_score(
    tibia_moment: float,
    mcl: float,
    acl: float,
    pcl: float,
    round_to: int | None = 3,
) -> FlexPliPointScore:
    """Score of one Flex-PLI test (Euro NCAP v10.0.5, Section 1.3.2.4).

    Tibia: 0.5 x sliding scale of the worst tibia moment (282-340 N m).
    Knee: 0.5 x sliding scale of the MCL elongation (19-22 mm), only if
    the ACL and PCL elongations are below 10 mm, else 0.
    """
    tibia = 0.5 * sliding_scale(abs(tibia_moment), *FLEXPLI_LIMITS["tibia_moment"])
    threshold = FLEXPLI_LIMITS["acl_pcl_elongation"][0]
    if max(abs(acl), abs(pcl)) >= threshold:
        knee = 0.0
    else:
        knee = 0.5 * sliding_scale(abs(mcl), *FLEXPLI_LIMITS["mcl_elongation"])
    tibia, knee = _maybe_round(tibia, round_to), _maybe_round(knee, round_to)
    return FlexPliPointScore(tibia, knee, _maybe_round(tibia + knee, round_to))


def flexpli_score(
    grid_points: Iterable[Hashable],
    tests: Mapping[Hashable, FlexPliPointScore | tuple[float, float, float, float]],
    max_points: float = 6.0,
    symmetric: bool = True,
    asymmetric_points: Iterable[Hashable] = (),
    round_to: int | None = 3,
) -> LegRegionScore:
    """Euro NCAP Flex-PLI lower leg score of a bumper grid (6 points).

    Parameters
    ----------
    grid_points:
        All grid points (``"L+5"`` ... ``"L-5"`` or lateral indices).
    tests:
        ``{point: (tibia_moment, mcl, acl, pcl)}`` peaks (N m, mm), or a
        :class:`FlexPliPointScore`, for the tested points.
    max_points:
        Region maximum (6 points).

    Untested points take their mirror point's result (if symmetric), else
    the worst adjacent result. The point scores are summed, divided by
    the number of grid points and multiplied by ``max_points``.
    """
    known: dict[Hashable, tuple[float, str]] = {}
    for p, value in tests.items():
        score = (value if isinstance(value, FlexPliPointScore)
                 else flexpli_point_score(*value, round_to=round_to))
        known[p] = (score.total, "tested")
    scores, sources = _fill_grid(grid_points, known, symmetric, asymmetric_points,
                                 None, 0.0)
    return _region("lower_leg", scores, sources, max_points, "euroncap_flexpli")
