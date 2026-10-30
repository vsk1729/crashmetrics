"""Tests for calculate_hic(method="exact") and the grid search accuracy.

The exact method maximises HIC over continuous end points of the
linearly interpolated signal. It is checked against closed-form optima,
against an independent brute-force search, and for consistency of the
reported interval.
"""

import numpy as np
import pytest

from crashmetrics.pedestrian.hic import calculate_hic


def interval_hic(t, a, t1, t2):
    """HIC of [t1, t2] for the linearly interpolated signal, integrated
    independently (trapezoids are exact on a piecewise-linear signal when
    the breakpoints are included)."""
    inside = t[(t > t1) & (t < t2)]
    x = np.concatenate(([t1], inside, [t2]))
    y = np.interp(x, t, a)
    integral = np.sum(0.5 * (y[1:] + y[:-1]) * np.diff(x))
    return (t2 - t1) * (integral / (t2 - t1)) ** 2.5


def brute_force(t, a, window_ms, step_ms):
    """Maximum over all pairs of a fine uniform grid (plus the samples)."""
    grid = np.unique(np.concatenate((np.arange(t[0], t[-1], step_ms / 1000), t)))
    y = np.interp(grid, t, a)
    c = np.concatenate(([0.0], np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(grid))))
    best = 0.0
    for i in range(len(grid) - 1):
        j = np.arange(i + 1, len(grid))
        d = grid[j] - grid[i]
        keep = d <= window_ms / 1000 + 1e-12
        d, j = d[keep], j[keep]
        if len(d):
            best = max(best, float(np.max(d * ((c[j] - c[i]) / d) ** 2.5)))
    return best


def triangle(peak, half_width, start=0.010, end=0.06, rate=10_000.0):
    corners = [0.0, start, start + half_width, start + 2 * half_width, end]
    # Samples at 10 kHz plus the corners, so the interpolation is the triangle.
    t = np.unique(np.concatenate((np.arange(0.0, end, 1.0 / rate), corners)))
    a = np.interp(t, corners, [0.0, 0.0, peak, 0.0, 0.0])
    return t, a


def test_constant_acceleration_closed_form():
    t = np.linspace(0.0, 0.05, 501)
    a = np.full_like(t, 80.0)
    result = calculate_hic(t, a, method="exact")
    assert result.value == pytest.approx(0.015 * 80.0 ** 2.5, rel=1e-12)
    assert result.duration_ms == pytest.approx(15.0, abs=1e-9)


def test_triangle_closed_form_interior_optimum():
    # Symmetric triangle, peak P and half width T: the optimum is the
    # interval of half width 4T/7 around the peak (a(t1) = a(t2) = 0.6 I/D),
    # HIC = (8T/7) (5P/7)^2.5. The end points fall between grid points.
    peak, half = 90.0, 0.00413
    t, a = triangle(peak, half)
    expected = 8 * half / 7 * (5 * peak / 7) ** 2.5
    exact = calculate_hic(t, a, method="exact")
    grid = calculate_hic(t, a)
    assert exact.value == pytest.approx(expected, rel=1e-10)
    assert exact.start_time == pytest.approx(0.010 + half - 4 * half / 7, abs=1e-12)
    assert exact.end_time == pytest.approx(0.010 + half + 4 * half / 7, abs=1e-12)
    assert grid.value <= exact.value
    assert grid.value == pytest.approx(expected, rel=1e-3)


def test_window_limited_plateau():
    # A long plateau: the optimum is any 36 ms window inside it.
    t, a = triangle(60.0, 0.002, end=0.2)
    a = np.where((t > 0.02) & (t < 0.1), 60.0, 0.0)
    result = calculate_hic(t, a, window_ms=36.0, method="exact")
    assert result.value == pytest.approx(0.036 * 60.0 ** 2.5, rel=1e-12)
    assert result.duration_ms == pytest.approx(36.0, abs=1e-9)


@pytest.mark.parametrize("seed", range(8))
def test_exact_bounds_grid_and_brute_force(seed):
    rng = np.random.default_rng(seed)
    t = np.sort(np.concatenate(([0.0, 0.03], rng.uniform(0.0, 0.03, 40))))
    t = t[np.concatenate(([True], np.diff(t) > 1e-5))]
    a = rng.uniform(0.0, 120.0, len(t))
    window = 15.0 if seed % 2 else 8.0
    exact = calculate_hic(t, a, window_ms=window, method="exact")
    grid = calculate_hic(t, a, window_ms=window)
    fine = brute_force(t, a, window, 0.01)
    # The exact optimum is at least every grid candidate ...
    assert exact.value >= grid.value * (1 - 1e-12)
    assert exact.value >= fine * (1 - 1e-12)
    # ... close to the fine search, and its interval is consistent.
    assert exact.value == pytest.approx(fine, rel=2e-3)
    assert exact.duration_ms <= window + 1e-9
    assert interval_hic(t, a, exact.start_time, exact.end_time) == pytest.approx(
        exact.value, rel=1e-9)


def test_grid_accuracy_on_smooth_pulse():
    t = np.arange(0.0, 0.05, 1e-4)
    phase = (t - 0.005) / 0.010
    a = np.where((phase > 0) & (phase < 1), 120.0 * np.sin(np.pi * phase), 0.0)
    exact = calculate_hic(t, a, method="exact").value
    for resolution in (0.4, 0.1, 0.05):
        grid = calculate_hic(t, a, resolution_ms=resolution).value
        assert 0 <= (exact - grid) / exact < 5e-4


def test_dense_record_uses_grid_only_and_stays_accurate():
    # More than 20 000 samples, far denser than the grid: the samples are
    # not added as candidates, the integral stays exact.
    t = np.arange(0.0, 0.3, 1e-5)
    phase = (t - 0.02) / 0.012
    a = np.where((phase > 0) & (phase < 1), 100.0 * np.sin(np.pi * phase), 0.0)
    grid = calculate_hic(t, a)
    exact = calculate_hic(t, a, method="exact")
    assert grid.value <= exact.value
    assert grid.value == pytest.approx(exact.value, rel=1e-4)


def test_zero_signal_exact():
    t = np.linspace(0.0, 0.05, 101)
    assert calculate_hic(t, np.zeros_like(t), method="exact").value == 0.0


def test_rejects_unknown_method():
    t = np.linspace(0.0, 0.05, 101)
    with pytest.raises(ValueError, match="method"):
        calculate_hic(t, np.ones_like(t), method="fast")
