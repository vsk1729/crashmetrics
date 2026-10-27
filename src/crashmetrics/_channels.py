"""Input checks and time windows shared by the injury criteria modules."""

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]


def as_channels(
    time: ArrayLike, *channels: ArrayLike, min_samples: int = 2
) -> tuple[FloatArray, list[FloatArray]]:
    """Validate a time array and channels of the same length."""
    t = np.asarray(time, dtype=float)
    arrays = [np.asarray(c, dtype=float) for c in channels]
    if t.ndim != 1 or any(a.ndim != 1 for a in arrays):
        raise ValueError("time and channels must be 1D arrays.")
    if len(t) < min_samples or any(len(a) != len(t) for a in arrays):
        raise ValueError(
            "time and channels must have equal lengths and contain at least "
            f"{min_samples} samples."
        )
    if not np.all(np.isfinite(t)) or not all(np.all(np.isfinite(a)) for a in arrays):
        raise ValueError("Inputs must contain only finite values.")
    if np.any(np.diff(t) <= 0):
        raise ValueError("Time values must be strictly increasing.")
    return t, arrays


def window(
    t: FloatArray,
    arrays: Sequence[FloatArray],
    t_start: float | None,
    t_end: float | None,
    min_samples: int = 1,
) -> tuple[FloatArray, list[FloatArray]]:
    """Keep the samples with ``t_start <= t <= t_end`` (bounds optional)."""
    for name, value in (("t_start", t_start), ("t_end", t_end)):
        if value is not None and not math.isfinite(value):
            raise ValueError(f"{name} must be finite.")
    if t_start is not None and t_end is not None and t_end < t_start:
        raise ValueError("t_end must not be before t_start.")
    keep = np.ones(len(t), dtype=bool)
    if t_start is not None:
        keep &= t >= t_start
    if t_end is not None:
        keep &= t <= t_end
    if int(np.sum(keep)) < min_samples:
        raise ValueError(
            f"The time window contains fewer than {min_samples} samples."
        )
    return t[keep], [a[keep] for a in arrays]


def uniform_step(t: FloatArray, rel_tol: float = 1e-3) -> float:
    """Sample interval of uniformly sampled data; raise otherwise."""
    steps = np.diff(t)
    step = (t[-1] - t[0]) / (len(t) - 1)
    if np.max(np.abs(steps - step)) > rel_tol * step:
        raise ValueError(
            "Uniformly sampled data is needed. Use "
            "crashmetrics.signals.resample_uniform() first."
        )
    return float(step)
