"""Acceleration time-history metrics.

Functions
---------
peak
    Peak acceleration and the time at which it occurs.
clip_3ms
    The "3 ms clip": the highest acceleration level that is reached
    or exceeded for 3 ms, cumulatively or continuously.

Inputs are normally a filtered resultant in g (see
``crashmetrics.signals``), with time in seconds. The signal is
treated as piecewise linear between samples.
"""

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike

__all__ = ["PeakResult", "clip_3ms", "peak"]


@dataclass(frozen=True)
class PeakResult:
    """Result of a peak calculation."""

    value: float
    """Peak value, in the unit of the input acceleration."""

    time: float
    """Time of the peak in seconds."""

    @property
    def time_ms(self) -> float:
        """Time of the peak in milliseconds."""
        return self.time * 1000.0


def _validate(time, acceleration):
    t = np.asarray(time, dtype=float)
    a = np.asarray(acceleration, dtype=float)

    if t.ndim != 1 or a.ndim != 1:
        raise ValueError("time and acceleration must be 1D arrays.")
    if len(t) != len(a) or len(t) < 2:
        raise ValueError(
            "time and acceleration must have equal lengths and contain "
            "at least two samples."
        )
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(a)):
        raise ValueError("Inputs must contain only finite values.")
    if np.any(np.diff(t) <= 0):
        raise ValueError("Time values must be strictly increasing.")
    return t, a


def peak(
    time: ArrayLike,
    acceleration: ArrayLike,
    absolute: bool = False,
) -> PeakResult:
    """Return the peak acceleration and when it occurs.

    Parameters
    ----------
    time:
        1D time array in seconds.
    acceleration:
        1D acceleration, for example a resultant in g.
    absolute:
        If True, return the largest magnitude, for signed axis
        components. The reported value keeps its sign.

    Returns
    -------
    PeakResult
        Peak value (in the unit of ``acceleration``) and its time.
        If the peak occurs more than once, the first is reported.
    """
    t, a = _validate(time, acceleration)
    index = int(np.argmax(np.abs(a) if absolute else a))
    return PeakResult(value=float(a[index]), time=float(t[index]))


def _time_at_or_above(t, a, level, strict=False):
    """Total time for which the piecewise-linear signal is >= level.

    With ``strict=True``, measures the time strictly above ``level``.
    """
    dt = np.diff(t)
    lo = np.minimum(a[:-1], a[1:])
    hi = np.maximum(a[:-1], a[1:])

    if strict:
        # A segment rising from exactly `level` is above it almost
        # everywhere; a flat segment at `level` is not above it.
        above = (lo >= level) & (hi > level)
    else:
        above = lo >= level
    total = float(np.sum(dt[above]))

    # Segments that cross the level contribute a linear fraction.
    crossing = (lo < level) & (hi > level)
    fraction = (hi[crossing] - level) / (hi[crossing] - lo[crossing])
    return total + float(np.sum(dt[crossing] * fraction))


def _cumulative_level(t, a, duration):
    """Exact highest level reached or exceeded for ``duration`` in total.

    The cumulative time at or above a level is non-increasing in the
    level and linear between consecutive sample values, so the answer
    is found by a binary search over the sample values followed by a
    linear solve.
    """
    levels = np.unique(a)

    # Largest k with time_at_or_above(levels[k]) >= duration.
    # levels[0] is the minimum, where the whole record qualifies.
    lo_k, hi_k = 0, len(levels) - 1
    while lo_k < hi_k:
        mid = (lo_k + hi_k + 1) // 2
        if _time_at_or_above(t, a, levels[mid]) >= duration:
            lo_k = mid
        else:
            hi_k = mid - 1
    k = lo_k

    if k == len(levels) - 1:
        return float(levels[k])

    lower, upper = levels[k], levels[k + 1]
    # Between the two levels the time is linear, from its value just
    # above `lower` to its value at `upper`.
    g_lower = _time_at_or_above(t, a, lower, strict=True)
    g_upper = _time_at_or_above(t, a, upper)

    if g_lower <= duration:
        # A plateau at `lower` supplies the remaining time.
        return float(lower)

    fraction = (g_lower - duration) / (g_lower - g_upper)
    return float(lower + fraction * (upper - lower))


def _longest_run_at_or_above(t, a, level):
    """Longest continuous time for which the signal is >= level."""
    above = a >= level
    if not np.any(above):
        return 0.0

    # Start and end indices of runs of consecutive samples >= level.
    edges = np.diff(np.concatenate(([0], above.astype(np.int8), [0])))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1) - 1

    lengths = t[ends] - t[starts]

    # Extend each run into the neighbouring segments that cross.
    has_left = starts > 0
    i = starts[has_left]
    lengths[has_left] += (t[i] - t[i - 1]) * (a[i] - level) / (a[i] - a[i - 1])

    has_right = ends < len(a) - 1
    j = ends[has_right]
    lengths[has_right] += (
        (t[j + 1] - t[j]) * (a[j] - level) / (a[j] - a[j + 1])
    )
    return float(np.max(lengths))


def _continuous_level(t, a, duration):
    """Highest level held continuously for ``duration``, by bisection."""
    low, high = float(np.min(a)), float(np.max(a))
    if _longest_run_at_or_above(t, a, high) >= duration:
        return high

    for _ in range(200):
        middle = 0.5 * (low + high)
        if middle in (low, high):
            break
        if _longest_run_at_or_above(t, a, middle) >= duration:
            low = middle
        else:
            high = middle
    return low


def clip_3ms(
    time: ArrayLike,
    acceleration: ArrayLike,
    duration_ms: float = 3.0,
    mode: Literal["cumulative", "continuous"] = "cumulative",
) -> float:
    """Return the 3 ms clip of an acceleration signal.

    Parameters
    ----------
    time:
        1D time array in seconds.
    acceleration:
        1D acceleration, normally a filtered resultant in g.
    duration_ms:
        Exceedance duration in milliseconds. Defaults to 3 ms.
    mode:
        ``"cumulative"`` (default): the highest level that the signal
        reaches or exceeds for ``duration_ms`` in total, possibly over
        several separate intervals.

        ``"continuous"``: the highest level that the signal reaches or
        exceeds throughout a single interval of ``duration_ms``.

        Check which definition your assessment protocol requires.

    Returns
    -------
    float
        Clip level, in the unit of ``acceleration``.

    Notes
    -----
    The signal is linearly interpolated between samples. The
    cumulative value is computed exactly for that interpolation; the
    continuous value is found by bisection to floating-point
    precision. The continuous value is never higher than the
    cumulative value.
    """
    t, a = _validate(time, acceleration)

    if not math.isfinite(duration_ms) or duration_ms <= 0:
        raise ValueError("duration_ms must be positive and finite.")

    duration = duration_ms / 1000.0
    if t[-1] - t[0] < duration:
        raise ValueError(
            f"The signal spans {(t[-1] - t[0]) * 1000.0:.3f} ms, shorter "
            f"than duration_ms={duration_ms:g}."
        )

    if mode == "cumulative":
        return _cumulative_level(t, a, duration)
    if mode == "continuous":
        return _continuous_level(t, a, duration)
    raise ValueError("mode must be 'cumulative' or 'continuous'.")
