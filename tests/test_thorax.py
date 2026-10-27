import math

import numpy as np
import pytest

from crashmetrics.acceleration import clip_3ms
from crashmetrics.thorax import (
    CTI_INTERCEPTS,
    THOR_IR_TRACC_OFFSET,
    VC_CONSTANTS,
    chest_deflection,
    cti,
    cti_from_signals,
    thor_abdomen_deflection,
    thor_chest_deflection,
    thor_rib_displacement,
    viscous_criterion,
)

# --- Hybrid III chest deflection ----------------------------------------------


def test_chest_deflection_peak_and_sign():
    t = np.array([0.0, 0.01, 0.02, 0.03])
    d = np.array([0.0, 25.0, 38.5, 12.0])
    result = chest_deflection(t, d)
    assert result.value == 38.5 and result.time == 0.02
    assert chest_deflection(t, -d, compression_negative=True).value == 38.5
    assert chest_deflection(t, d, t_end=0.015).value == 25.0


# --- Viscous criterion --------------------------------------------------------


def test_vc_constants_from_euro_ncap():
    assert VC_CONSTANTS["hybrid3_50"] == (1.3, 0.229)
    assert VC_CONSTANTS["hybrid3_05"] == (1.3, 0.187)
    assert VC_CONSTANTS["hybrid3_95"] == (1.3, 0.254)
    assert VC_CONSTANTS["worldsid_50"] == (1.0, 0.170)


def test_vc_five_point_velocity_is_exact_for_a_cubic():
    # D = 400 t^3 m, so V = 1200 t^2 m/s exactly for the 5-point formula.
    t = np.linspace(0.0, 0.05, 501)
    d_mm = 400.0 * t**3 * 1000.0
    result = viscous_criterion(t, d_mm)

    expected = 1.3 * (1200.0 * t**2) * (400.0 * t**3) / 0.229
    np.testing.assert_allclose(result.history[2:-2], expected[2:-2], rtol=1e-9)
    np.testing.assert_allclose(result.velocity[2:-2], 1200.0 * t[2:-2] ** 2,
                               rtol=1e-9)
    assert np.all(np.isnan(result.history[[0, 1, -2, -1]]))
    assert result.time == t[-3]
    assert result.value == pytest.approx(expected[-3], rel=1e-9)


def test_vc_sinusoid_maximum():
    # D = A sin(w t): VC = sf A^2 w sin(2 w t) / (2 Dc), max sf A^2 w / (2 Dc).
    amplitude, w = 0.05, 2 * np.pi / 0.04
    t = np.linspace(0.0, 0.02, 2001)
    d_mm = 1000.0 * amplitude * np.sin(w * t)
    result = viscous_criterion(t, d_mm, dummy="hybrid3_05")
    expected = 1.3 * amplitude**2 * w / (2 * 0.187)
    assert result.value == pytest.approx(expected, rel=1e-5)
    assert result.time == pytest.approx(np.pi / 4 / w, abs=1e-5)


def test_vc_options_and_errors():
    t = np.linspace(0.0, 0.05, 501)
    d_mm = 400.0 * t**3 * 1000.0
    base = viscous_criterion(t, d_mm)
    flipped = viscous_criterion(t, -d_mm, compression_negative=True)
    assert flipped.value == pytest.approx(base.value)
    custom = viscous_criterion(t, d_mm, scale_factor=1.0, d_constant=0.229)
    assert custom.value == pytest.approx(base.value / 1.3)
    windowed = viscous_criterion(t, d_mm, t_end=0.025)
    assert windowed.time == pytest.approx(0.025)

    with pytest.raises(ValueError, match="both"):
        viscous_criterion(t, d_mm, scale_factor=1.0)
    with pytest.raises(ValueError, match="Unknown dummy"):
        viscous_criterion(t, d_mm, dummy="thor")
    with pytest.raises(ValueError, match="Uniformly"):
        viscous_criterion(t**2, d_mm)
    with pytest.raises(ValueError, match="No VC values"):
        viscous_criterion(t, d_mm, t_start=0.0499)
    with pytest.raises(ValueError, match="at least 5"):
        viscous_criterion(t[:4], d_mm[:4])


# --- THOR chest ---------------------------------------------------------------


def _rotation_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def _rotation_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _rib_point(r, phi_y_deg, phi_z_deg, delta):
    # Independent geometry: the vector (R, 0, delta) rotated about z by
    # phi_z and then about y by phi_y.
    rot = _rotation_y(math.radians(phi_y_deg)) @ _rotation_z(math.radians(phi_z_deg))
    return rot @ np.array([r, 0.0, delta])


def _thor_channels():
    t = np.linspace(0.0, 0.06, 7)
    r = np.array([120.0, 115.0, 104.0, 92.0, 90.0, 97.0, 110.0])
    phi_y = np.array([0.0, 2.0, 5.5, 9.0, 12.0, 8.0, 3.0])
    phi_z = np.array([0.0, -1.5, -4.0, -8.0, -7.0, -3.0, -1.0])
    return t, r, phi_y, phi_z


@pytest.mark.parametrize("location, delta", [("upper", 15.65), ("lower", -15.65)])
def test_thor_rib_displacement_matches_rotation_geometry(location, delta):
    t, r, phi_y, phi_z = _thor_channels()
    result = thor_rib_displacement(t, r, phi_y, phi_z, location=location)

    points = np.array([_rib_point(*args, delta) for args in zip(r, phi_y, phi_z)])
    displacement = points - points[0]
    np.testing.assert_allclose(result.dx, displacement[:, 0], atol=1e-12)
    np.testing.assert_allclose(result.dy, displacement[:, 1], atol=1e-12)
    np.testing.assert_allclose(result.dz, displacement[:, 2], atol=1e-12)
    resultant = np.linalg.norm(displacement, axis=1)
    np.testing.assert_allclose(result.resultant, resultant, atol=1e-12)
    assert result.peak == pytest.approx(resultant.max())
    assert result.time == t[int(np.argmax(resultant))]


def test_thor_rib_displacement_pure_compression_and_options():
    t = np.array([0.0, 0.01, 0.02])
    r = np.array([120.0, 100.0, 95.0])
    zeros = np.zeros(3)
    result = thor_rib_displacement(t, r, zeros, zeros, location="upper")
    np.testing.assert_allclose(result.dx, [0.0, -20.0, -25.0])
    np.testing.assert_allclose(result.dz, 0.0, atol=1e-12)
    assert result.peak == pytest.approx(25.0)

    t, r, phi_y, phi_z = _thor_channels()
    in_degrees = thor_rib_displacement(t, r, phi_y, phi_z, delta=15.65)
    in_radians = thor_rib_displacement(t, r, np.radians(phi_y), np.radians(phi_z),
                                       delta=15.65, degrees=False)
    assert in_radians.peak == pytest.approx(in_degrees.peak)
    assert THOR_IR_TRACC_OFFSET == 15.65

    # Reference position at the sample at or before reference_time.
    later = thor_rib_displacement(t, r, phi_y, phi_z, location="upper",
                                  reference_time=0.015)
    assert later.resultant[1] == pytest.approx(0.0, abs=1e-12)

    with pytest.raises(ValueError, match="location"):
        thor_rib_displacement(t, r, phi_y, phi_z)
    with pytest.raises(ValueError, match="not both"):
        thor_rib_displacement(t, r, phi_y, phi_z, location="upper", delta=1.0)
    with pytest.raises(ValueError, match="before the first"):
        thor_rib_displacement(t, r, phi_y, phi_z, location="upper",
                              reference_time=-1.0)


def test_thor_chest_deflection_rmax_over_four_locations():
    t, r, phi_y, phi_z = _thor_channels()
    zeros = np.zeros_like(t)
    upper_left = (r, phi_y, phi_z)
    upper_right = (np.full_like(t, 120.0) - np.linspace(0, 10, 7), zeros, zeros)
    lower_left = (np.full_like(t, 120.0), zeros, zeros)
    lower_right = (r, phi_y, phi_z)

    result = thor_chest_deflection(t, upper_left, upper_right, lower_left,
                                   lower_right)

    upper = thor_rib_displacement(t, r, phi_y, phi_z, location="upper")
    lower = thor_rib_displacement(t, r, phi_y, phi_z, location="lower")
    assert result.ribs["upper_left"].peak == pytest.approx(upper.peak)
    assert result.ribs["lower_right"].peak == pytest.approx(lower.peak)
    assert result.ribs["upper_right"].peak == pytest.approx(10.0)
    assert result.ribs["lower_left"].peak == 0.0
    assert result.rmax == max(upper.peak, lower.peak)
    assert result.location == ("upper_left" if upper.peak >= lower.peak
                               else "lower_right")


# --- THOR abdomen -------------------------------------------------------------


def test_thor_abdomen_deflection_compression_and_literal_max():
    t = np.array([0.0, 0.01, 0.02, 0.03])
    zeros = np.zeros(4)
    left = (np.array([250.0, 235.0, 220.0, 240.0]), zeros, zeros)
    right = (np.array([250.0, 230.0, 205.0, 235.0]), zeros, zeros)

    result = thor_abdomen_deflection(t, left, right)

    assert result.value == pytest.approx(45.0)
    assert result.side == "right" and result.time == 0.02
    assert result.max_dx == 0.0
    np.testing.assert_allclose(result.dx["left"], [0.0, -15.0, -30.0, -10.0])


def test_thor_abdomen_deflection_with_angles():
    # Dx = R cos(phi_z) cos(phi_y) - Dx(0)
    t = np.array([0.0, 0.01])
    left = ([250.0, 220.0], [0.0, 10.0], [0.0, -5.0])
    right = ([250.0, 250.0], [0.0, 0.0], [0.0, 0.0])
    result = thor_abdomen_deflection(t, left, right)
    dx = 220.0 * math.cos(math.radians(-5.0)) * math.cos(math.radians(10.0)) - 250.0
    assert result.value == pytest.approx(-dx)
    assert result.side == "left"


def test_thor_abdomen_deflection_other_polarity():
    # If R grows in compression, the protocol's literal max(Dx) applies.
    t = np.array([0.0, 0.01, 0.02])
    zeros = np.zeros(3)
    left = (np.array([100.0, 130.0, 110.0]), zeros, zeros)
    right = (np.array([100.0, 120.0, 100.0]), zeros, zeros)
    result = thor_abdomen_deflection(t, left, right)
    assert result.max_dx == pytest.approx(30.0)
    assert result.value == 0.0


# --- CTI ----------------------------------------------------------------------


def test_cti_hand_calculation():
    assert CTI_INTERCEPTS["hybrid3_50"] == (90.0, 103.0)
    assert CTI_INTERCEPTS["hybrid3_05"] == (90.0, 84.0)
    assert cti(45.0, 51.5) == pytest.approx(1.0)
    assert cti(45.0, 42.0, dummy="hybrid3_05") == pytest.approx(1.0)
    assert cti(30.0, 20.0, intercepts=(60.0, 40.0)) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="Unknown dummy"):
        cti(45.0, 51.5, dummy="thor")
    with pytest.raises(ValueError, match="positive"):
        cti(45.0, 51.5, intercepts=(0.0, 40.0))
    with pytest.raises(ValueError, match="finite"):
        cti(math.nan, 51.5)


def test_cti_from_signals():
    t = np.linspace(0.0, 0.05, 501)
    acc = np.where((t >= 0.01) & (t <= 0.015), 60.0, 0.0)
    acc = acc + np.where((t >= 0.02) & (t <= 0.0205), 80.0, 0.0)  # short spike
    d = 51.5 * np.sin(np.pi * t / 0.05)

    result = cti_from_signals(t, acc, d)
    assert result.acceleration == pytest.approx(clip_3ms(t, acc))
    assert result.acceleration == pytest.approx(60.0)
    assert result.deflection == pytest.approx(51.5)
    assert result.value == pytest.approx(60.0 / 90.0 + 0.5)

    peak = cti_from_signals(t, acc, -d, acceleration_measure="peak",
                            compression_negative=True)
    assert peak.acceleration == 80.0
    assert peak.value == pytest.approx(80.0 / 90.0 + 0.5)
    with pytest.raises(ValueError, match="acceleration_measure"):
        cti_from_signals(t, acc, d, acceleration_measure="hic")  # type: ignore[arg-type]
