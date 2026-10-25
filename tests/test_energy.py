import math

import numpy as np
import pytest

from crashmetrics.energy import (
    absorbed_energy,
    crush_metrics,
    integrate_acceleration,
    kinetic_energy,
)

# --- integrate_acceleration ---------------------------------------------


def test_constant_acceleration_is_integrated_exactly():
    t = np.linspace(0.0, 0.1, 101)
    a = np.full_like(t, -200.0)  # m/s^2

    v, x = integrate_acceleration(t, a, v0=15.0, x0=1.0)

    np.testing.assert_allclose(v, 15.0 - 200.0 * t, atol=1e-12)
    # Trapezoid of a linear velocity is exact for the quadratic.
    np.testing.assert_allclose(x, 1.0 + 15.0 * t - 100.0 * t**2, atol=1e-12)


def test_mm_ms_units_give_m_per_s_and_mm():
    t_ms = np.linspace(0.0, 50.0, 501)
    a = np.full_like(t_ms, -0.3)  # mm/ms^2, about 30.6 g

    v, x = integrate_acceleration(t_ms, a, v0=15.0)  # 15 mm/ms = 15 m/s

    assert v[-1] == pytest.approx(15.0 - 0.3 * 50.0)
    assert x[-1] == pytest.approx(15.0 * 50.0 - 0.15 * 50.0**2)


def test_integrate_rejects_bad_time():
    with pytest.raises(ValueError):
        integrate_acceleration([0.0, 0.0, 0.1], [1.0, 1.0, 1.0])


# --- absorbed_energy ------------------------------------------------------


def test_energy_of_constant_force():
    d = np.linspace(0.0, 100.0, 11)  # mm
    f = np.full_like(d, 50.0)  # kN

    e = absorbed_energy(d, f)

    assert e[0] == 0.0
    assert e[-1] == pytest.approx(5000.0)  # kN x mm = J


def test_energy_of_linear_spring_is_exact():
    k = 2.0
    d = np.linspace(0.0, 30.0, 7)

    e = absorbed_energy(d, k * d)

    np.testing.assert_allclose(e, 0.5 * k * d**2)


def test_unloading_returns_energy():
    # Load linearly to 10 mm and 20 kN, unload elastically to 8 mm.
    d = np.array([0.0, 10.0, 8.0])
    f = np.array([0.0, 20.0, 0.0])

    e = absorbed_energy(d, f)

    assert e[1] == pytest.approx(100.0)
    assert e[2] == pytest.approx(100.0 - 20.0)


# --- crush_metrics --------------------------------------------------------


def test_crush_metrics_for_ideal_square_response():
    d = np.array([0.0, 1e-9, 100.0])
    f = np.array([0.0, 50.0, 50.0])

    result = crush_metrics(d, f, mass=0.5)

    assert result.energy == pytest.approx(5000.0)
    assert result.crush_distance == pytest.approx(100.0)
    assert result.peak_force == pytest.approx(50.0)
    assert result.mean_force == pytest.approx(50.0)
    assert result.crush_force_efficiency == pytest.approx(1.0)
    assert result.specific_energy_absorption == pytest.approx(10000.0)


def test_crush_metrics_with_initial_peak():
    # Peak of 100 kN at 5 mm, then a 40 kN plateau to 100 mm.
    d = np.array([0.0, 5.0, 10.0, 100.0])
    f = np.array([0.0, 100.0, 40.0, 40.0])

    result = crush_metrics(d, f)

    energy = 0.5 * 5 * 100 + 0.5 * 5 * (100 + 40) + 90 * 40
    assert result.energy == pytest.approx(energy)
    assert result.peak_force == 100.0
    assert result.peak_force_displacement == 5.0
    assert result.mean_force == pytest.approx(energy / 100.0)
    assert result.crush_force_efficiency == pytest.approx(energy / 100.0 / 100.0)
    assert result.specific_energy_absorption is None


def test_max_displacement_cuts_with_interpolation():
    k = 2.0
    d = np.array([0.0, 10.0, 20.0, 30.0])

    result = crush_metrics(d, k * d, max_displacement=15.0)

    assert result.crush_distance == pytest.approx(15.0)
    assert result.energy == pytest.approx(0.5 * k * 15.0**2)
    assert result.peak_force == pytest.approx(30.0)


def test_max_displacement_on_a_sample_point():
    d = np.array([0.0, 10.0, 20.0])
    result = crush_metrics(d, np.full_like(d, 5.0), max_displacement=10.0)
    assert result.energy == pytest.approx(50.0)


def test_springback_uses_maximum_crush():
    d = np.array([0.0, 10.0, 8.0])
    f = np.array([0.0, 20.0, 0.0])

    result = crush_metrics(d, f)

    assert result.crush_distance == pytest.approx(10.0)
    assert result.energy == pytest.approx(80.0)
    assert result.mean_force == pytest.approx(8.0)


def test_crush_metrics_nonzero_start_displacement():
    d = np.array([50.0, 60.0, 70.0])
    f = np.array([10.0, 10.0, 10.0])

    result = crush_metrics(d, f)

    assert result.crush_distance == pytest.approx(20.0)
    assert result.mean_force == pytest.approx(10.0)


def test_crush_metrics_validation():
    d = np.array([0.0, 10.0, 20.0])
    f = np.array([0.0, 5.0, 5.0])

    with pytest.raises(ValueError, match="never reaches"):
        crush_metrics(d, f, max_displacement=25.0)
    with pytest.raises(ValueError):
        crush_metrics(d, f, max_displacement=0.0)
    with pytest.raises(ValueError):
        crush_metrics(d, f, mass=0.0)
    with pytest.raises(ValueError):
        crush_metrics([0.0, 0.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        crush_metrics([0.0, 1.0], [1.0, math.nan])


def test_cfe_is_nan_without_positive_force():
    result = crush_metrics([0.0, 10.0], [0.0, 0.0])
    assert math.isnan(result.crush_force_efficiency)


# --- kinetic_energy and energy balance ----------------------------------


def test_kinetic_energy():
    assert kinetic_energy(1500.0, 15.0) == pytest.approx(168750.0)
    np.testing.assert_allclose(kinetic_energy(2.0, [0.0, 3.0]), [0.0, 9.0])
    with pytest.raises(ValueError):
        kinetic_energy(-1.0, 3.0)


def test_work_done_equals_kinetic_energy_lost():
    """A mass decelerated by a varying force: work = KE lost."""
    mass = 10.0  # kg
    t = np.linspace(0.0, 0.05, 20001)  # s
    a = -400.0 * np.sin(np.pi * t / 0.05)  # m/s^2

    v, x = integrate_acceleration(t, a, v0=15.0)
    force = -mass * a  # N, opposing motion, positive in crush direction

    work = absorbed_energy(x, force)[-1]  # N x m = J
    ke_lost = kinetic_energy(mass, 15.0) - kinetic_energy(mass, v[-1])

    assert work == pytest.approx(ke_lost, rel=1e-6)
