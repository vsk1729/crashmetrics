import math

import numpy as np
import pytest

from crashmetrics.pelvis import acetabulum_force, iliac_force_drop

# --- Acetabulum ---------------------------------------------------------------


def test_acetabulum_force_only_while_fx_compressive():
    t = np.array([0.0, 0.01, 0.02, 0.03, 0.04])
    fx = np.array([0.0, -300.0, -400.0, 200.0, 0.0])
    fy = np.array([0.0, 400.0, 300.0, 500.0, 0.0])
    fz = np.array([0.0, 0.0, 1200.0, 900.0, 0.0])

    result = acetabulum_force(t, fx, fy, fz)
    # sqrt(400^2 + 300^2 + 1200^2) = 1300; sample 3 (Fx > 0) is excluded
    assert result.value == pytest.approx(1300.0)
    assert result.time == 0.02

    positive = acetabulum_force(t, fx, fy, fz, compression_negative=False)
    assert positive.value == pytest.approx(math.sqrt(200**2 + 500**2 + 900**2))
    assert positive.time == 0.03

    windowed = acetabulum_force(t, fx, fy, fz, t_end=0.015)
    assert windowed.value == pytest.approx(500.0)


def test_acetabulum_force_never_compressive_is_zero():
    t = np.array([0.0, 0.01, 0.02])
    result = acetabulum_force(t, [0.0, 100.0, 50.0], [0.0, 900.0, 0.0],
                              [0.0, 900.0, 0.0])
    assert result.value == 0.0


# --- Iliac force drop ---------------------------------------------------------


def test_iliac_force_drop_hand_calculation():
    # IFD(t) = F(t + 1 ms) - F(t); loaded negative, unloads 2 kN in 1 ms.
    t = np.array([0.0, 0.001, 0.002, 0.003, 0.004])
    f = np.array([0.0, -3000.0, -3000.0, -1000.0, -1000.0])
    result = iliac_force_drop(t, f)
    assert result.value == pytest.approx(2000.0)
    assert result.time == pytest.approx(0.002)


def test_iliac_force_drop_interpolates_between_samples():
    # 0.5 ms samples, 1.5 ms interval: F(t + 1.5 ms) is interpolated.
    t = np.arange(9) * 0.0005
    f = np.array([0.0, -2000.0, -4000.0, -4000.0, -4000.0, -3000.0, -1000.0,
                  -1000.0, -1000.0])
    result = iliac_force_drop(t, f, interval=0.0015)
    # Largest at t = 1.5 ms: F(3.0 ms) - F(1.5 ms) = -1000 - (-4000)
    assert result.value == pytest.approx(3000.0)
    assert result.time == pytest.approx(0.0015)

    shifted = iliac_force_drop(t, f, interval=0.00075)
    # F(t + 0.75 ms) - F(t) with linear interpolation, best at t = 2 ms
    # (F(2.75 ms) = -2000, F(2 ms) = -4000) and 2.5 ms (-1000 - -3000)
    assert shifted.value == pytest.approx(2000.0)


def test_iliac_force_drop_positive_loading_convention():
    t = np.array([0.0, 0.001, 0.002, 0.003])
    f = np.array([0.0, 2500.0, 500.0, 500.0])
    assert iliac_force_drop(t, f, loaded_negative=False).value == pytest.approx(2000.0)
    # Read verbatim, a positive-loaded channel shows the drop as negative.
    assert iliac_force_drop(t, f).value == pytest.approx(2500.0)  # the rise


def test_iliac_force_drop_uses_the_last_full_interval():
    # 0.9 ms + 1 ms rounds to just above 1.9 ms; the drop must still count.
    t = np.arange(20) * 1e-4
    f = np.full_like(t, -3000.0)
    f[-1] = 0.0
    assert t[-11] + 0.001 > t[-1]
    result = iliac_force_drop(t, f)
    assert result.value == pytest.approx(3000.0)
    assert result.time == pytest.approx(0.0009)


def test_iliac_force_drop_window_and_errors():
    t = np.array([0.0, 0.001, 0.002, 0.003, 0.004])
    f = np.array([0.0, -3000.0, -3000.0, -1000.0, -1000.0])
    early = iliac_force_drop(t, f, t_end=0.0015)
    assert early.value == pytest.approx(0.0)

    with pytest.raises(ValueError, match="interval"):
        iliac_force_drop(t, f, interval=0.0)
    with pytest.raises(ValueError, match="shorter than the interval"):
        iliac_force_drop(t, f, interval=0.01)
    with pytest.raises(ValueError, match="No sample"):
        iliac_force_drop(t, f, t_start=0.0035)
