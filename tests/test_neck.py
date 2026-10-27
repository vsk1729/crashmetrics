import numpy as np
import pytest

from crashmetrics.neck import (
    FMVSS208_NECK_FORCE_LIMITS,
    NECK_FORCE_LIMITS,
    NIJ_INTERCEPTS,
    OC_DISTANCE_HYBRID3,
    R94_NECK_EXTENSION_LIMIT,
    NijIntercepts,
    neck_force_criterion,
    neck_loads,
    nij,
    occipital_condyle_moment,
)

# --- Occipital condyle moment and peak loads ----------------------------------


def test_occipital_condyle_moment_hand_calculation():
    # 50 N m - 1000 N * 0.01778 m
    assert occipital_condyle_moment(50.0, 1000.0) == pytest.approx(32.22)
    assert OC_DISTANCE_HYBRID3 == 0.01778
    np.testing.assert_allclose(
        occipital_condyle_moment([10.0, -20.0], [100.0, -100.0], d=0.02),
        [8.0, -18.0],
    )
    with pytest.raises(ValueError, match="same shape"):
        occipital_condyle_moment([1.0, 2.0], [1.0])


def _neck_signals():
    t = np.array([0.0, 0.01, 0.02, 0.03])
    fx = np.array([0.0, 500.0, -800.0, 0.0])
    fz = np.array([0.0, 2000.0, -1500.0, 0.0])
    my = np.array([0.0, 20.0, -40.0, 0.0])
    return t, fx, fz, my


def test_neck_loads_hybrid3_hand_calculation():
    t, fx, fz, my = _neck_signals()
    loads = neck_loads(t, fx, fz, my)

    # M_OC = My - Fx * 0.01778: 20 - 8.89 = 11.11 and -40 + 14.224 = -25.776
    np.testing.assert_allclose(loads.moment, [0.0, 11.11, -25.776, 0.0])
    assert loads.extension_moment.value == pytest.approx(25.776)
    assert loads.extension_moment.time == 0.02
    assert loads.flexion_moment.value == pytest.approx(11.11)
    assert loads.tension.value == 2000.0 and loads.tension.time == 0.01
    assert loads.compression.value == 1500.0 and loads.compression.time == 0.02
    assert loads.shear_positive.value == 500.0
    assert loads.shear_negative.value == 800.0
    assert loads.shear is loads.shear_negative


def test_neck_loads_thor_uses_upper_neck_moment():
    t, fx, fz, my = _neck_signals()
    loads = neck_loads(t, fx, fz, my, dummy="thor")
    np.testing.assert_allclose(loads.moment, my)
    assert loads.extension_moment.value == 40.0
    with pytest.raises(ValueError, match="Hybrid III"):
        neck_loads(t, fx, fz, my, dummy="thor", oc_distance=0.02)
    with pytest.raises(ValueError, match="dummy"):
        neck_loads(t, fx, fz, my, dummy="hybrid2")  # type: ignore[arg-type]


def test_neck_loads_window_and_absent_loads():
    t, fx, fz, my = _neck_signals()
    loads = neck_loads(t, fx, fz, my, t_end=0.015)
    assert loads.compression.value == 0.0
    assert loads.shear_negative.value == 0.0
    assert loads.extension_moment.value == 0.0  # abs(min(M)) with M >= 0


# --- Nij ----------------------------------------------------------------------


def test_nij_intercepts_from_fmvss_208():
    assert NIJ_INTERCEPTS["hybrid3_50"] == NijIntercepts(6806.0, 6160.0, 310.0, 135.0)
    assert NIJ_INTERCEPTS["hybrid3_05"] == NijIntercepts(4287.0, 3880.0, 155.0, 67.0)
    assert FMVSS208_NECK_FORCE_LIMITS["hybrid3_50"] == (4170.0, 4000.0)
    assert FMVSS208_NECK_FORCE_LIMITS["hybrid3_05"] == (2620.0, 2520.0)


def test_nij_hand_calculation_all_categories():
    t = np.array([0.0, 0.01, 0.02, 0.03, 0.04])
    #               NTE      NTF     NCE      NCF
    fz = np.array([0.0, 3403.0, 680.6, -3080.0, -616.0])
    my = np.array([0.0, -27.0, 93.0, -13.5, 248.0])

    result = nij(t, fz, my)

    # NTE 0.5 + 0.2, NTF 0.1 + 0.3, NCE 0.5 + 0.1, NCF 0.1 + 0.8
    np.testing.assert_allclose(result.history, [0.0, 0.7, 0.4, 0.6, 0.9])
    assert result.categories == pytest.approx(
        {"NTE": 0.7, "NTF": 0.4, "NCE": 0.6, "NCF": 0.9}
    )
    assert result.value == pytest.approx(0.9)
    assert result.category == "NCF"
    assert result.time == 0.04


def test_nij_moves_moment_to_occipital_condyle():
    t = np.array([0.0, 0.01])
    fz = np.array([0.0, 1000.0])
    my = np.array([0.0, 30.0])
    fx = np.array([0.0, 500.0])
    moment_oc = my - fx * 0.01778

    with_fx = nij(t, fz, my, fx=fx)
    already_oc = nij(t, fz, moment_oc)

    assert with_fx.value == pytest.approx(already_oc.value)
    assert with_fx.value == pytest.approx(1000.0 / 6806.0 + (30.0 - 8.89) / 310.0)


def test_nij_small_female_and_custom_intercepts():
    t = np.array([0.0, 0.01])
    result = nij(t, [0.0, -1940.0], [0.0, -33.5], dummy="hybrid3_05")
    assert result.value == pytest.approx(0.5 + 0.5)
    assert result.category == "NCE"
    assert result.categories["NTF"] == 0.0  # never in tension-flexion

    custom = nij(t, [0.0, 100.0], [0.0, 10.0],
                 intercepts=NijIntercepts(1000.0, 1000.0, 100.0, 100.0))
    assert custom.value == pytest.approx(0.2)

    with pytest.raises(ValueError, match="Unknown dummy"):
        nij(t, [0.0, 1.0], [0.0, 1.0], dummy="thor")
    with pytest.raises(ValueError, match="positive"):
        nij(t, [0.0, 1.0], [0.0, 1.0],
            intercepts=NijIntercepts(1000.0, 0.0, 100.0, 100.0))


# --- Force-duration criteria --------------------------------------------------


def _plateau(level, start_ms, end_ms):
    t = np.arange(1001) * 1e-4  # 0 to 100 ms
    ms = np.round(t * 1000.0, 6)
    return t, np.where((ms >= start_ms) & (ms <= end_ms), level, 0.0)


def test_r94_neck_limits():
    assert NECK_FORCE_LIMITS["r94_tension"] == (
        (0.0, 3300.0), (35.0, 2900.0), (60.0, 1100.0)
    )
    assert NECK_FORCE_LIMITS["r94_shear"] == (
        (0.0, 3100.0), (25.0, 1500.0), (35.0, 1500.0), (45.0, 1100.0)
    )
    assert R94_NECK_EXTENSION_LIMIT == 57.0


def test_neck_tension_exceeds_r94_limit():
    # 3 kN held for 40 ms; the limit at 40 ms is 2.9 - 5/25 * 1.8 = 2.54 kN.
    t, fz = _plateau(3000.0, 10.0, 50.0)
    result = neck_force_criterion(t, fz, "r94_tension")
    assert result.peak == 3000.0
    assert result.critical_duration_ms == pytest.approx(40.0)
    assert result.utilisation == pytest.approx(3000.0 / 2540.0)
    assert not result.passed

    t, fz = _plateau(2000.0, 10.0, 50.0)
    result = neck_force_criterion(t, fz, "r94_tension")
    assert result.utilisation == pytest.approx(2000.0 / 2540.0)
    assert result.passed


def test_neck_shear_uses_both_directions_by_default():
    # -2 kN for 30 ms; the limit is 1.5 kN from 25 to 35 ms.
    t, fx = _plateau(-2000.0, 10.0, 40.0)
    result = neck_force_criterion(t, fx, "r94_shear")
    assert result.utilisation == pytest.approx(2000.0 / 1500.0)
    assert not result.passed

    positive_only = neck_force_criterion(t, fx, "r94_shear", direction="positive")
    assert positive_only.utilisation == 0.0
    assert positive_only.passed


def test_neck_force_criterion_custom_limit_and_errors():
    t, fz = _plateau(1500.0, 10.0, 20.0)
    result = neck_force_criterion(t, fz, ((0.0, 1000.0),))
    assert result.utilisation == pytest.approx(1.5)
    with pytest.raises(ValueError, match="Unknown limit"):
        neck_force_criterion(t, fz, "r94_compression")
