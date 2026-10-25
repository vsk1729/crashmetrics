"""Independent numerical reference checks for HIC."""

import numpy as np
import pytest

from crashmetrics.pedestrian.hic import calculate_hic


def reference_hic(time, acceleration, window_ms, step_ms=0.02):
    """Brute-force reference on a fine uniform time grid.

    This is a test reference, not a regulatory implementation.
    """
    t = np.asarray(time, dtype=float)
    a = np.asarray(acceleration, dtype=float)

    step = step_ms / 1000.0
    window = window_ms / 1000.0

    grid = np.arange(t[0], t[-1], step)
    grid = np.append(grid, t[-1])
    grid = np.unique(np.concatenate((grid, t)))

    values = np.interp(grid, t, a)
    best = 0.0

    for i in range(len(grid) - 1):
        for j in range(i + 1, len(grid)):
            duration = grid[j] - grid[i]

            if duration > window + 1e-12:
                break

            # Direct integration, independently of cumulative sums.
            segment_t = grid[i:j + 1]
            segment_a = values[i:j + 1]

            # Written out by hand: np.trapezoid needs NumPy >= 2.0
            # and np.trapz is deprecated there.
            integral = np.sum(
                0.5
                * (segment_a[:-1] + segment_a[1:])
                * np.diff(segment_t)
            )
            average = integral / duration
            best = max(best, duration * average**2.5)

    return best


def test_varying_pulse_against_fine_grid_reference():
    time = np.array([
        0.000, 0.002, 0.005, 0.009,
        0.012, 0.016, 0.020, 0.025, 0.030,
    ])

    acceleration = np.array([
        0.0, 20.0, 60.0, 100.0,
        80.0, 40.0, 15.0, 5.0, 0.0,
    ])

    actual = calculate_hic(
        time,
        acceleration,
        window_ms=15.0,
        resolution_ms=0.1,
    )

    reference = reference_hic(
        time,
        acceleration,
        window_ms=15.0,
        step_ms=0.02,
    )

    assert actual.value == pytest.approx(
        reference, rel=2e-4
    )
