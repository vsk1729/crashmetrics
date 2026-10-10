
import numpy as np
import pytest

from crashmetrics.pedestrian.hic import calculate_hic


def test_constant_acceleration():
    """For constant acceleration, HIC = duration * a**2.5."""
    time = np.linspace(0.0, 0.015, 16)
    acceleration = np.full_like(time, 10.0)

    result = calculate_hic(time, acceleration, window_ms=15)

    expected = 0.015 * 10.0**2.5

    assert result.value == pytest.approx(expected)
    assert result.duration_ms == pytest.approx(15.0)


def test_hic36_accepts_longer_window():
    time = np.linspace(0.0, 0.036, 37)
    acceleration = np.full_like(time, 10.0)

    result = calculate_hic(time, acceleration, window_ms=36)

    expected = 0.036 * 10.0**2.5

    assert result.value == pytest.approx(expected)
    assert result.duration_ms == pytest.approx(36.0)


def test_rejects_non_increasing_time():
    with pytest.raises(ValueError):
        calculate_hic(
            [0.0, 0.002, 0.001],
            [1.0, 2.0, 3.0],
        )


def test_rejects_negative_acceleration():
    with pytest.raises(ValueError):
        calculate_hic([0.0, 0.01], [1.0, -1.0])


def test_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        calculate_hic([0.0, 0.01], [1.0, 2.0, 3.0])



def test_hic_is_zero_for_zero_acceleration():
    time = np.linspace(0.0, 0.020, 21)
    acceleration = np.zeros_like(time)

    result = calculate_hic(time, acceleration, window_ms=15)

    assert result.value == pytest.approx(0.0)


def test_hic_scales_with_acceleration_to_power_2_5():
    time = np.linspace(0.0, 0.015, 16)
    acceleration = np.full_like(time, 10.0)
    doubled_acceleration = 2.0 * acceleration

    original = calculate_hic(time, acceleration, window_ms=15)
    doubled = calculate_hic(
        time, doubled_acceleration, window_ms=15
    )

    assert doubled.value == pytest.approx(
        original.value * 2**2.5
    )


def test_nonuniform_time_sampling():
    time = np.array([0.0, 0.001, 0.003, 0.006, 0.010, 0.015])
    acceleration = np.full_like(time, 10.0)

    result = calculate_hic(time, acceleration, window_ms=15)

    expected = 0.015 * 10.0**2.5

    assert result.value == pytest.approx(expected)
    assert result.start_time == pytest.approx(0.0)
    assert result.end_time == pytest.approx(0.015)


def test_varying_acceleration_pulse():
    # A triangular acceleration pulse with a nonuniform time history.
    time = np.array([
        0.000, 0.002, 0.005, 0.009,
        0.012, 0.016, 0.020, 0.025,
        0.030,
    ])

    acceleration = np.array([
        0.0, 20.0, 60.0, 100.0,
        80.0, 40.0, 15.0, 5.0, 0.0,
    ])

    result = calculate_hic(
        time,
        acceleration,
        window_ms=15,
        resolution_ms=0.1,
    )

    assert np.isfinite(result.value)
    assert result.value > 0.0
    assert result.start_time < result.end_time
    assert result.duration_ms <= 15.0 + 1e-8



def test_rejects_non_finite_inputs():
    with pytest.raises(ValueError):
        calculate_hic([0.0, 0.01], [1.0, np.nan])

    with pytest.raises(ValueError):
        calculate_hic([0.0, np.inf], [1.0, 2.0])


def test_rejects_invalid_resolution():
    time = np.linspace(0.0, 0.020, 21)
    acceleration = np.full_like(time, 10.0)

    with pytest.raises(ValueError):
        calculate_hic(time, acceleration, resolution_ms=0.0)


def test_rejects_signal_shorter_than_window():
    time = np.linspace(0.0, 0.010, 11)
    acceleration = np.full_like(time, 10.0)

    with pytest.raises(ValueError):
        calculate_hic(time, acceleration, window_ms=15.0)



def test_coarse_resolution_can_reach_exact_window():
    time = np.linspace(0.0, 0.100, 201)
    acceleration = np.full_like(time, 10.0)

    result = calculate_hic(
        time,
        acceleration,
        window_ms=15.0,
        resolution_ms=0.4,
    )

    assert result.duration_ms == pytest.approx(15.0)
    assert result.value == pytest.approx(
        0.015 * 10.0**2.5
    )
