import numpy as np
import pytest
from numpy.lib.stride_tricks import sliding_window_view

from crashmetrics.acceleration import clip_3ms, peak


def triangle(peak_g=100.0, base_ms=10.0, start_ms=0.0):
    """Time (s) and acceleration of a symmetric triangular pulse."""
    t_ms = [start_ms, start_ms + base_ms / 2, start_ms + base_ms]
    return np.array(t_ms) / 1000.0, np.array([0.0, peak_g, 0.0])


def fine_grid_reference(t, a, duration_ms, mode, step=1e-6):
    """Brute-force 3 ms clip on a very fine uniform grid."""
    grid = np.arange(t[0], t[-1], step)
    values = np.interp(grid, t, a)
    n = int(round(duration_ms / 1000.0 / step))

    if mode == "cumulative":
        return np.sort(values)[::-1][n - 1]

    # Continuous: maximum over windows of the minimum in the window.
    return np.max(np.min(sliding_window_view(values, n), axis=1))


# --- peak ---------------------------------------------------------------


def test_peak_value_and_time():
    t = np.array([0.0, 0.001, 0.002, 0.003])
    a = np.array([1.0, 7.0, 3.0, 7.0])

    result = peak(t, a)

    assert result.value == 7.0
    assert result.time == pytest.approx(0.001)  # first occurrence


def test_peak_absolute_keeps_sign():
    t = np.array([0.0, 0.001, 0.002])
    a = np.array([2.0, -9.0, 5.0])

    assert peak(t, a).value == 5.0
    assert peak(t, a, absolute=True).value == -9.0


def test_peak_rejects_bad_input():
    with pytest.raises(ValueError):
        peak([0.0, 0.001], [1.0])
    with pytest.raises(ValueError):
        peak([0.0, 0.0], [1.0, 2.0])


# --- 3 ms clip: analytic cases -------------------------------------------


def test_clip_of_constant_signal():
    t = np.linspace(0.0, 0.010, 11)
    a = np.full_like(t, 50.0)

    assert clip_3ms(t, a) == pytest.approx(50.0)
    assert clip_3ms(t, a, mode="continuous") == pytest.approx(50.0)


def test_clip_of_triangle():
    # Time at or above L is 10 * (1 - L/100) ms, which is 3 ms at L = 70.
    t, a = triangle()

    assert clip_3ms(t, a) == pytest.approx(70.0)
    assert clip_3ms(t, a, mode="continuous") == pytest.approx(70.0)


def test_cumulative_and_continuous_differ_for_two_pulses():
    t1, a1 = triangle(start_ms=0.0)
    t2, a2 = triangle(start_ms=20.0)
    t = np.concatenate((t1, t2))
    a = np.concatenate((a1, a2))

    # Cumulative: 20 * (1 - L/100) = 3 ms at L = 85.
    assert clip_3ms(t, a) == pytest.approx(85.0)
    # Continuous: each pulse alone, 10 * (1 - L/100) = 3 ms at L = 70.
    assert clip_3ms(t, a, mode="continuous") == pytest.approx(70.0)


def test_clip_with_short_plateau():
    # Ramp to 80 g in 5 ms, hold 2 ms, ramp down in 5 ms.
    # Time at or above L < 80: 2 + 10 * (1 - L/80) = 3 ms at L = 72.
    t = np.array([0.0, 5.0, 7.0, 12.0]) / 1000.0
    a = np.array([0.0, 80.0, 80.0, 0.0])

    assert clip_3ms(t, a) == pytest.approx(72.0)
    assert clip_3ms(t, a, mode="continuous") == pytest.approx(72.0)


def test_clip_with_long_plateau_returns_plateau_level():
    # A 4 ms plateau at 80 g covers 3 ms on its own.
    t = np.array([0.0, 5.0, 9.0, 14.0]) / 1000.0
    a = np.array([0.0, 80.0, 80.0, 0.0])

    assert clip_3ms(t, a) == pytest.approx(80.0)
    assert clip_3ms(t, a, mode="continuous") == pytest.approx(80.0)


def test_plateau_below_peak_is_handled_exactly():
    # A spike to 100 g (1 ms wide at the base) on a 5 ms plateau at 40 g.
    # Above 40 g there is only 1 ms, so the cumulative clip is 40 g.
    t = np.array([0.0, 1.0, 3.0, 3.5, 4.0, 6.0, 7.0]) / 1000.0
    a = np.array([0.0, 40.0, 40.0, 100.0, 40.0, 40.0, 0.0])

    assert clip_3ms(t, a) == pytest.approx(40.0)
    assert clip_3ms(t, a, mode="continuous") == pytest.approx(40.0)


def test_custom_duration():
    t, a = triangle()
    # 10 * (1 - L/100) = 5 ms at L = 50.
    assert clip_3ms(t, a, duration_ms=5.0) == pytest.approx(50.0)


# --- 3 ms clip: against brute force ---------------------------------------


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("mode", ["cumulative", "continuous"])
def test_clip_matches_fine_grid_reference(seed, mode):
    rng = np.random.default_rng(seed)
    t = np.cumsum(rng.uniform(1e-4, 5e-4, 60))
    t -= t[0]
    a = np.abs(np.cumsum(rng.normal(0.0, 8.0, t.size))) + 5.0

    expected = fine_grid_reference(t, a, 3.0, mode)
    actual = clip_3ms(t, a, mode=mode)

    assert actual == pytest.approx(expected, rel=1e-3, abs=1e-2)


def test_continuous_never_exceeds_cumulative():
    rng = np.random.default_rng(42)
    t = np.arange(0.0, 0.05, 1e-4)
    a = np.abs(50 * np.sin(200 * t) + rng.normal(0, 10, t.size))

    assert clip_3ms(t, a, mode="continuous") <= clip_3ms(t, a) + 1e-12


def test_clip_is_below_peak_and_above_minimum():
    t = np.arange(0.0, 0.03, 5e-5)
    a = 100.0 * np.sin(np.pi * t / 0.03)

    value = clip_3ms(t, a)

    assert np.min(a) < value < np.max(a)


# --- 3 ms clip: validation ----------------------------------------------


def test_clip_rejects_signal_shorter_than_duration():
    t = np.linspace(0.0, 0.002, 5)
    with pytest.raises(ValueError, match="shorter than duration_ms"):
        clip_3ms(t, np.ones_like(t))


@pytest.mark.parametrize("duration_ms", [0.0, -3.0, float("inf")])
def test_clip_rejects_invalid_duration(duration_ms):
    t = np.linspace(0.0, 0.01, 11)
    with pytest.raises(ValueError):
        clip_3ms(t, np.ones_like(t), duration_ms=duration_ms)


def test_clip_rejects_unknown_mode():
    t = np.linspace(0.0, 0.01, 11)
    with pytest.raises(ValueError, match="mode"):
        clip_3ms(t, np.ones_like(t), mode="average")
