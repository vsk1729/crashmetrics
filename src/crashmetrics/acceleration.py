"""Acceleration time-history metrics.

Functions
---------
peak
    Peak acceleration and the time at which it occurs.
clip_3ms
    The "3 ms clip": the highest acceleration level that is reached
    or exceeded for 3 ms, cumulatively or continuously.
exceedance_level
    The highest level reached or exceeded for any given duration.
exceedance_duration
    How long a signal is at or above a given level.
exceedance_check
    Compare a signal's exceedance curve with a level-duration limit
    (e.g. UN-ECE R94 femur and neck force criteria).

Inputs are normally a filtered resultant in g (see
``crashmetrics.signals``), with time in seconds. The signal is
treated as piecewise linear between samples.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "ExceedanceCheckResult",
    "PeakResult",
    "clip_3ms",
    "exceedance_check",
    "exceedance_duration",
    "exceedance_level",
    "peak",
]


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
    if not math.isfinite(duration_ms) or duration_ms <= 0:
        raise ValueError("duration_ms must be positive and finite.")
    return exceedance_level(time, acceleration, duration_ms, mode)


def exceedance_level(
    time: ArrayLike,
    signal: ArrayLike,
    duration_ms: float,
    mode: Literal["cumulative", "continuous"] = "cumulative",
) -> float:
    """Return the highest level reached or exceeded for ``duration_ms``.

    This generalises :func:`clip_3ms` to any duration and any signal,
    for example a femur force. A duration of 0 returns the maximum.

    Parameters
    ----------
    time:
        1D time array in seconds.
    signal:
        1D signal.
    duration_ms:
        Exceedance duration in milliseconds, zero or more.
    mode:
        ``"cumulative"`` (total time, possibly over several intervals)
        or ``"continuous"`` (a single interval).

    Returns
    -------
    float
        Level, in the unit of ``signal``.
    """
    t, a = _validate(time, signal)

    if not math.isfinite(duration_ms) or duration_ms < 0:
        raise ValueError("duration_ms must be non-negative and finite.")
    if mode not in ("cumulative", "continuous"):
        raise ValueError("mode must be 'cumulative' or 'continuous'.")

    duration = duration_ms / 1000.0
    if t[-1] - t[0] < duration:
        raise ValueError(
            f"The signal spans {(t[-1] - t[0]) * 1000.0:.3f} ms, shorter "
            f"than duration_ms={duration_ms:g}."
        )
    if duration == 0:
        return float(np.max(a))

    if mode == "cumulative":
        return _cumulative_level(t, a, duration)
    return _continuous_level(t, a, duration)


def exceedance_duration(
    time: ArrayLike,
    signal: ArrayLike,
    level: float,
    mode: Literal["cumulative", "continuous"] = "cumulative",
) -> float:
    """Return how long the signal is at or above ``level``, in ms.

    Parameters
    ----------
    time:
        1D time array in seconds.
    signal:
        1D signal, linearly interpolated between samples.
    level:
        Threshold, in the unit of ``signal``.
    mode:
        ``"cumulative"``: total time at or above ``level``.
        ``"continuous"``: the longest single interval at or above it.

    Returns
    -------
    float
        Duration in milliseconds.
    """
    t, a = _validate(time, signal)
    if not math.isfinite(level):
        raise ValueError("level must be finite.")
    if mode == "cumulative":
        return 1000.0 * _time_at_or_above(t, a, level)
    if mode == "continuous":
        return 1000.0 * _longest_run_at_or_above(t, a, level)
    raise ValueError("mode must be 'cumulative' or 'continuous'.")


@dataclass(frozen=True)
class ExceedanceCheckResult:
    """Result of :func:`exceedance_check`."""

    peak: float
    """Peak of the assessed signal (after ``direction`` is applied)."""

    peak_time: float
    """Time of the peak, in seconds."""

    utilisation: float
    """Largest ratio of the exceedance curve to the limit; above 1 the
    limit is exceeded."""

    critical_duration_ms: float
    """Duration (ms) at which the utilisation is largest."""

    passed: bool
    """True if ``utilisation <= 1``."""

    levels: NDArray[np.float64]
    """Levels of the exceedance curve, highest first."""

    durations_ms: NDArray[np.float64]
    """Time (ms) the signal is at or above each level."""


def _limit_points(
    limit: Sequence[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    points = tuple((float(d), float(v)) for d, v in limit)
    if len(points) < 1:
        raise ValueError("limit needs at least one point.")
    durations = [p[0] for p in points]
    values = [p[1] for p in points]
    if durations[0] != 0.0 or any(b <= a for a, b in zip(durations, durations[1:])):
        raise ValueError("limit durations must start at 0 ms and increase.")
    if any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("limit values must be positive and finite.")
    if any(b > a for a, b in zip(values, values[1:])):
        raise ValueError("limit values must not increase with duration.")
    return points


def exceedance_check(
    time: ArrayLike,
    signal: ArrayLike,
    limit: Sequence[tuple[float, float]],
    mode: Literal["cumulative", "continuous"] = "cumulative",
    direction: Literal["positive", "negative", "absolute"] = "positive",
) -> ExceedanceCheckResult:
    """Check a signal against a level-duration (exceedance) limit.

    Parameters
    ----------
    time:
        1D time array in s.
    signal:
        1D signal, e.g. a force in N.
    limit:
        (duration in ms, level) points starting at 0 ms, with increasing
        duration and non-increasing level. The limit is linear between
        points and constant after the last one.
    mode:
        ``"cumulative"`` (total time above a level, possibly over several
        intervals) or ``"continuous"`` (a single interval).
    direction:
        Which part of the signal is assessed: ``"positive"`` values,
        ``"negative"`` values (as magnitudes, e.g. compression stored as
        negative force) or ``"absolute"`` values.

    Notes
    -----
    For each level ``L``, let ``D(L)`` be the time the assessed signal is
    at or above ``L``. The limit is exceeded if ``L > limit(D(L))`` for
    some ``L``; the utilisation is the largest ``L / limit(D(L))``.

    In cumulative mode ``D`` is linear in ``L`` between sample values, so
    checking every sample value and every level where ``D`` meets a
    limit breakpoint is exact for the linearly interpolated signal. In
    continuous mode 2000 evenly spaced levels are added as well.
    """
    points = _limit_points(limit)
    if mode not in ("cumulative", "continuous"):
        raise ValueError("mode must be 'cumulative' or 'continuous'.")
    if direction not in ("positive", "negative", "absolute"):
        raise ValueError("direction must be 'positive', 'negative' or 'absolute'.")

    t, s = _validate(time, signal)
    if direction == "positive":
        assessed = np.maximum(s, 0.0)
    elif direction == "negative":
        assessed = np.maximum(-s, 0.0)
    else:
        assessed = np.abs(s)

    peak_index = int(np.argmax(assessed))
    peak_value = float(assessed[peak_index])
    if peak_value <= 0.0:
        empty = np.zeros(0)
        return ExceedanceCheckResult(
            peak=0.0, peak_time=float(t[peak_index]), utilisation=0.0,
            critical_duration_ms=0.0, passed=True, levels=empty,
            durations_ms=empty,
        )

    span_ms = (t[-1] - t[0]) * 1000.0
    candidates = [assessed[assessed > 0.0]]
    candidates.append(np.array([
        exceedance_level(t, assessed, d, mode) for d, _ in points if d <= span_ms
    ]))
    if mode == "continuous":
        candidates.append(np.linspace(0.0, peak_value, 2001)[1:])
    levels = np.unique(np.concatenate(candidates))
    levels = levels[levels > 0.0][::-1]  # highest first

    durations_ms = np.array(
        [exceedance_duration(t, assessed, level, mode) for level in levels]
    )
    allowed = np.interp(durations_ms, [p[0] for p in points], [p[1] for p in points])
    ratios = levels / allowed
    worst = int(np.argmax(ratios))
    return ExceedanceCheckResult(
        peak=peak_value,
        peak_time=float(t[peak_index]),
        utilisation=float(ratios[worst]),
        critical_duration_ms=float(durations_ms[worst]),
        passed=bool(ratios[worst] <= 1.0),
        levels=levels,
        durations_ms=durations_ms,
    )
