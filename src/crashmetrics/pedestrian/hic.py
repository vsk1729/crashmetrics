
"""Head Injury Criterion (HIC) calculations."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class HICResult:
    """Result of a HIC calculation."""

    value: float
    start_time: float
    end_time: float

    @property
    def duration_ms(self) -> float:
        """Duration of the critical interval in milliseconds."""
        return (self.end_time - self.start_time) * 1000.0


def calculate_hic(
    time,
    acceleration,
    window_ms: float = 15.0,
    resolution_ms: float = 0.1,
) -> HICResult:
    """Calculate HIC using a refined, linearly interpolated time grid.

    Parameters
    ----------
    time:
        One-dimensional time array in seconds.
    acceleration:
        One-dimensional non-negative resultant acceleration in g.
    window_ms:
        Maximum interval duration in milliseconds.
    resolution_ms:
        Spacing of the refined time grid in milliseconds.

    Returns
    -------
    HICResult
        Approximate maximum HIC and its interval.

    Notes
    -----
    Acceleration is linearly interpolated onto a uniform time grid.
    Integration uses the trapezoidal rule. The maximum is searched
    over endpoints on that refined grid, so the result is an
    approximation whose accuracy depends on resolution_ms.

    This numerical method is not, by itself, evidence of compliance
    with a regulatory assessment protocol.
    """
    t = np.asarray(time, dtype=float)
    a = np.asarray(acceleration, dtype=float)

    if t.ndim != 1 or a.ndim != 1:
        raise ValueError("time and acceleration must be 1D arrays.")

    if len(t) != len(a) or len(t) < 2:
        raise ValueError(
            "time and acceleration must have equal lengths "
            "and contain at least two samples."
        )

    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(a)):
        raise ValueError("Inputs must contain only finite values.")

    if np.any(np.diff(t) <= 0):
        raise ValueError("Time values must be strictly increasing.")

    if np.any(a < 0):
        raise ValueError(
            "Acceleration must be a non-negative resultant magnitude in g."
        )

    if not np.isfinite(window_ms) or window_ms <= 0:
        raise ValueError("window_ms must be positive and finite.")

    if not np.isfinite(resolution_ms) or resolution_ms <= 0:
        raise ValueError("resolution_ms must be positive and finite.")

    duration = t[-1] - t[0]
    max_duration = window_ms / 1000.0
    step = resolution_ms / 1000.0

    if duration <= 0:
        raise ValueError("The input time duration must be positive.")

    if duration < max_duration:
        raise ValueError(
            "The input signal must span at least window_ms."
        )

    # Refine the signal using linear interpolation.


    # Uniform refinement grid, including the final time.
    base_grid = np.arange(t[0], t[-1], step)
    base_grid = np.append(base_grid, t[-1])

    # Preserve all original samples: they are breakpoints of the
    # piecewise-linear acceleration interpolation.
    original_grid = t

    # Add shifted points so candidate intervals can span the exact
    # requested maximum duration.
    shifted_base = base_grid - max_duration
    shifted_original = original_grid - max_duration

    shifted_grid = np.concatenate(
        (shifted_base, shifted_original)
    )
    shifted_grid = shifted_grid[
        (shifted_grid >= t[0]) & (shifted_grid <= t[-1])
    ]

    # The union preserves signal breakpoints and interval candidates.
    grid = np.unique(
        np.concatenate((base_grid, original_grid, shifted_grid))
    )
    refined_a = np.interp(grid, t, a)



    # Cumulative trapezoidal integration.
    increments = (
        0.5
        * (refined_a[:-1] + refined_a[1:])
        * np.diff(grid)
    )
    cumulative = np.concatenate(([0.0], np.cumsum(increments)))

    best_value = -1.0
    best_start = float(grid[0])
    best_end = float(grid[1])

    # Search candidate start points for every end point.
    for j in range(1, len(grid)):
        earliest_time = grid[j] - max_duration
        first = np.searchsorted(grid, earliest_time, side="left")
        starts = np.arange(first, j)

        if starts.size == 0:
            continue

        intervals = grid[j] - grid[starts]

        valid = intervals <= max_duration + step * 1e-8
        starts = starts[valid]
        intervals = intervals[valid]

        if starts.size == 0:
            continue

        integrated_acceleration = cumulative[j] - cumulative[starts]
        average_acceleration = integrated_acceleration / intervals

        values = intervals * average_acceleration**2.5
        local_index = int(np.argmax(values))
        local_value = float(values[local_index])

        if local_value > best_value:
            best_value = local_value
            best_start = float(grid[starts[local_index]])
            best_end = float(grid[j])

    if best_value < 0:
        raise ValueError("No valid HIC interval could be evaluated.")

    return HICResult(
        value=best_value,
        start_time=best_start,
        end_time=best_end,
    )
