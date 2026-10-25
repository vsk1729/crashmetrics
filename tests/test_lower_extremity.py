import numpy as np
import pytest

from crashmetrics.acceleration import exceedance_duration, exceedance_level
from crashmetrics.lower_extremity import (
    FEMUR_FORCE_LIMITS,
    TIBIA_INDEX_CRITICAL_VALUES,
    femur_force_criterion,
    tibia_index,
)

# --- Tibia Index -----------------------------------------------------------


def test_tibia_index_hand_calculation():
    # MR = hypot(120, 160) = 200 N m; Fz = -3590 N (compression).
    t = np.array([0.0, 0.001, 0.002])
    mx = np.array([0.0, 120.0, 0.0])
    my = np.array([0.0, 160.0, 0.0])
    fz = np.array([0.0, -3590.0, 0.0])

    result = tibia_index(t, mx, my, fz, dummy="hybrid3_50")

    assert result.value == pytest.approx(200.0 / 225.0 + 3590.0 / 35900.0)
    assert result.time == pytest.approx(0.001)
    np.testing.assert_allclose(result.history, [0.0, result.value, 0.0])


def test_tibia_index_is_zero_in_tension():
    t = np.array([0.0, 0.001])
    result = tibia_index(t, [100.0, 100.0], [0.0, 0.0], [0.0, 500.0],
                         dummy="hybrid3_50")
    assert result.value == 0.0


def test_tibia_index_positive_compression_convention():
    t = np.array([0.0, 0.001])
    negative = tibia_index(t, [0, 225.0], [0, 0], [0, -35900.0], dummy="hybrid3_50")
    positive = tibia_index(t, [0, 225.0], [0, 0], [0, 35900.0], dummy="hybrid3_50",
                           compression_negative=False)
    assert negative.value == pytest.approx(2.0)
    assert positive.value == pytest.approx(2.0)


def test_tibia_index_explicit_critical_values_match_table():
    t = np.linspace(0, 0.01, 11)
    mx = 50 * np.sin(300 * t)
    my = 80 * np.cos(300 * t)
    fz = -4000 * np.sin(300 * t) ** 2

    by_name = tibia_index(t, mx, my, fz, dummy="hybrid3_05")
    explicit = tibia_index(t, mx, my, fz, critical_moment=114.0,
                           critical_force=22900.0)
    assert by_name.value == pytest.approx(explicit.value)


def test_tibia_index_critical_values_from_euro_ncap():
    assert TIBIA_INDEX_CRITICAL_VALUES["hybrid3_50"] == (225.0, 35900.0)
    assert TIBIA_INDEX_CRITICAL_VALUES["hybrid3_05"] == (114.0, 22900.0)
    assert TIBIA_INDEX_CRITICAL_VALUES["hybrid3_95"] == (306.0, 44100.0)
    assert TIBIA_INDEX_CRITICAL_VALUES["thor_50"] == (225.0, 35900.0)


def test_tibia_index_validation():
    t = [0.0, 0.001]
    with pytest.raises(ValueError, match="Unknown dummy"):
        tibia_index(t, [0, 1], [0, 1], [0, -1], dummy="hybrid2")
    with pytest.raises(ValueError):
        tibia_index(t, [0, 1], [0, 1], [0, -1])
    with pytest.raises(ValueError):
        tibia_index(t, [0, 1], [0, 1], [0, -1], dummy="hybrid3_50",
                    critical_moment=225.0)
    with pytest.raises(ValueError):
        tibia_index(t, [0, 1], [0, 1], [0, -1, 2], dummy="hybrid3_50")


# --- exceedance helpers ----------------------------------------------------


def test_exceedance_duration_and_level_are_inverse():
    t = np.array([0.0, 5.0, 10.0]) / 1000.0
    a = np.array([0.0, 100.0, 0.0])

    assert exceedance_duration(t, a, 70.0) == pytest.approx(3.0)
    assert exceedance_level(t, a, 3.0) == pytest.approx(70.0)
    assert exceedance_level(t, a, 0.0) == pytest.approx(100.0)


# --- femur force criterion ----------------------------------------------


def trapezoid_compression(peak_n, ramp_ms, hold_ms, start_ms=5.0, end_ms=60.0):
    """Femur Fz (negative = compression) with a trapezoidal pulse."""
    t_ms = np.array([0.0, start_ms, start_ms + ramp_ms,
                     start_ms + ramp_ms + hold_ms,
                     start_ms + 2 * ramp_ms + hold_ms, end_ms])
    fz = -np.array([0.0, 0.0, peak_n, peak_n, 0.0, 0.0])
    return t_ms / 1000.0, fz


def r94_limit(d_ms):
    return np.interp(d_ms, [0.0, 10.0], [9070.0, 7580.0])


def brute_force_utilisation(t, fz, step_ms=0.005):
    """Independent check: highest level exceeded for each duration on a
    fine duration grid, compared with the R94 limit."""
    compression = np.maximum(-fz, 0.0)
    grid_t = np.arange(t[0], t[-1], 1e-6)
    values = np.sort(np.interp(grid_t, t, compression))[::-1]
    ratios = []
    for d in np.arange(0.0, 30.0, step_ms):
        n = int(round(d / 1000.0 / 1e-6))
        level = values[min(n, values.size - 1)]
        ratios.append(level / r94_limit(d))
    return max(ratios)


def test_femur_short_peak_below_limit_passes():
    # 8.5 kN held 2 ms: allowed level at ~2+ ms is above 8.5 kN.
    t, fz = trapezoid_compression(8500.0, ramp_ms=1.0, hold_ms=2.0)
    result = femur_force_criterion(t, fz)

    assert result.peak_compression == pytest.approx(8500.0)
    assert result.passed
    assert result.utilisation < 1.0


def test_femur_long_hold_above_long_term_limit_fails():
    # 8.0 kN held 15 ms exceeds 7.58 kN for more than 10 ms.
    t, fz = trapezoid_compression(8000.0, ramp_ms=2.0, hold_ms=15.0)
    result = femur_force_criterion(t, fz)

    assert not result.passed
    assert result.utilisation == pytest.approx(8000.0 / 7580.0, rel=1e-6)
    assert result.critical_duration_ms >= 10.0


def test_femur_peak_above_9_07_kn_fails_immediately():
    t, fz = trapezoid_compression(9500.0, ramp_ms=0.5, hold_ms=0.001)
    result = femur_force_criterion(t, fz)

    assert not result.passed
    # Peak held 0.001 ms: allowed force is the limit at 0.001 ms.
    assert result.utilisation == pytest.approx(9500.0 / r94_limit(0.001), rel=1e-9)


@pytest.mark.parametrize("seed", range(4))
def test_femur_matches_brute_force(seed):
    rng = np.random.default_rng(seed)
    t = np.linspace(0.0, 0.06, 601)
    fz = -np.abs(8000 * np.sin(np.pi * np.clip((t - 0.005) / 0.03, 0, 1))
                 + rng.normal(0, 300, t.size))

    result = femur_force_criterion(t, fz)

    assert result.utilisation == pytest.approx(
        brute_force_utilisation(t, fz), rel=2e-3
    )


def test_femur_exceedance_curve_is_consistent():
    t, fz = trapezoid_compression(8000.0, ramp_ms=2.0, hold_ms=6.0)
    result = femur_force_criterion(t, fz)

    assert np.all(np.diff(result.levels) < 0)  # highest first
    assert np.all(np.diff(result.durations_ms) >= -1e-9)
    assert result.durations_ms[0] == pytest.approx(6.0)  # plateau hold


def test_femur_continuous_mode_is_not_stricter():
    t1, f1 = trapezoid_compression(7800.0, ramp_ms=1.0, hold_ms=6.0, start_ms=5.0)
    t2, f2 = trapezoid_compression(7800.0, ramp_ms=1.0, hold_ms=6.0, start_ms=5.0)
    t = np.concatenate((t1, t2 + 0.07))
    fz = np.concatenate((f1, f2))

    cumulative = femur_force_criterion(t, fz, mode="cumulative")
    continuous = femur_force_criterion(t, fz, mode="continuous")

    # Two 6 ms holds: 12 ms cumulative above 7.58 kN fails, but no
    # single 10 ms interval does.
    assert not cumulative.passed
    assert continuous.passed


def test_femur_positive_compression_and_custom_limit():
    t, fz = trapezoid_compression(5000.0, ramp_ms=1.0, hold_ms=5.0)
    result = femur_force_criterion(
        t, -fz, compression_negative=False, limit=((0.0, 6000.0), (5.0, 4000.0))
    )
    assert not result.passed


def test_femur_no_compression():
    t = np.linspace(0, 0.01, 11)
    result = femur_force_criterion(t, np.full_like(t, 500.0))
    assert result.passed and result.utilisation == 0.0


def test_femur_limit_table_and_validation():
    assert FEMUR_FORCE_LIMITS["r94_hybrid3_50"] == ((0.0, 9070.0), (10.0, 7580.0))
    t, fz = trapezoid_compression(5000.0, ramp_ms=1.0, hold_ms=5.0)
    with pytest.raises(ValueError, match="Unknown limit"):
        femur_force_criterion(t, fz, limit="r94_thor")
    with pytest.raises(ValueError, match="start at 0"):
        femur_force_criterion(t, fz, limit=((1.0, 9000.0),))
    with pytest.raises(ValueError, match="not increase"):
        femur_force_criterion(t, fz, limit=((0.0, 5000.0), (5.0, 6000.0)))
