import math

import numpy as np
import pytest

from crashmetrics.head import (
    BRIC_CRITICAL_VELOCITIES,
    DAMAGE_PARAMETERS,
    DamageParameters,
    bric,
    damage,
    damage_from_acceleration,
    external_force,
    loading_phase_end,
)


def _haversine(t, amplitude, start, duration):
    phase = (t - start) / duration
    inside = (phase >= 0) & (phase <= 1)
    return np.where(inside, amplitude * np.sin(np.pi * phase) ** 2, 0.0)


# --- DAMAGE: parameters -------------------------------------------------------


def test_damage_parameters_from_euro_ncap():
    p = DAMAGE_PARAMETERS
    assert (p.kxx, p.kyy, p.kzz) == (32142.0, 23493.0, 16935.0)
    assert (p.kxy, p.kyz, p.kxz) == (0.0, 0.0, 1636.3)
    assert p.a1 == 5.9148e-3
    assert p.beta == 2.9903
    assert p.max_duration == 0.2
    assert p.external_force_limit == -500.0


def test_damage_stiffness_matrix_is_a_spring_network():
    k = DamageParameters(kxy=10.0, kyz=20.0, kxz=30.0).stiffness_matrix()
    np.testing.assert_allclose(k, k.T)
    # Each row sums to the spring to ground of that axis.
    np.testing.assert_allclose(k.sum(axis=1), [32142.0, 23493.0, 16935.0])
    assert k[0, 1] == -10.0 and k[1, 2] == -20.0 and k[0, 2] == -30.0


# --- DAMAGE: verification -----------------------------------------------------


def test_damage_matches_reference_implementation():
    # Expected values computed with the model developers' reference
    # implementation (UVA-CAB/DAMAGE, version 2.0) for this input.
    t = np.linspace(0.0, 0.1, 1001)
    ax = _haversine(t, 4000.0, 0.0, 0.03)
    ay = _haversine(t, -6000.0, 0.005, 0.04)
    az = _haversine(t, 2500.0, 0.01, 0.025)

    result = damage_from_acceleration(t, ax, ay, az)

    assert result.value == pytest.approx(0.8556468556688221, rel=1e-9)
    assert result.time == pytest.approx(0.034)
    assert result.end_reason == "end of record"
    # The reference reverses the z component; reversing the input back
    # changes the result.
    reversed_z = damage_from_acceleration(t, ax, ay, -az)
    assert reversed_z.value == pytest.approx(0.8819913466830123, rel=1e-9)


def test_damage_single_axis_step_overshoot():
    # y is uncoupled (kxy = kyz = 0). A step alpha from rest peaks at
    # (alpha / k) (1 + exp(-zeta pi / sqrt(1 - zeta^2))), zeta = a1 sqrt(k) / 2.
    t = np.linspace(0.0, 0.1, 10001)
    alpha = 1000.0
    zeros = np.zeros_like(t)
    result = damage_from_acceleration(t, zeros, np.full_like(t, alpha), zeros)

    k = DAMAGE_PARAMETERS.kyy
    zeta = DAMAGE_PARAMETERS.a1 * math.sqrt(k) / 2
    damped = math.sqrt(k) * math.sqrt(1 - zeta**2)
    peak = alpha / k * (1 + math.exp(-zeta * math.pi / math.sqrt(1 - zeta**2)))
    assert result.value == pytest.approx(DAMAGE_PARAMETERS.beta * peak, rel=1e-5)
    assert result.time == pytest.approx(math.pi / damped, abs=2e-5)
    np.testing.assert_allclose(result.displacement[:, [0, 2]], 0.0, atol=0.0)


def test_damage_coupled_step_matches_modal_solution():
    # Constant angular acceleration from rest, solved independently mode by
    # mode: with M = I and C = a1 K the system is classically damped.
    alpha = np.array([800.0, 0.0, 600.0])  # SAE J211 axes
    t = np.linspace(0.0, 0.1, 10001)
    result = damage_from_acceleration(t, *(np.full_like(t, a) for a in alpha))

    lam, phi = np.linalg.eigh(DAMAGE_PARAMETERS.stiffness_matrix())
    w = np.sqrt(lam)
    zeta = DAMAGE_PARAMETERS.a1 * w / 2
    wd = w * np.sqrt(1 - zeta**2)
    forcing = alpha * np.array([1.0, 1.0, -1.0])  # z reversed in model axes
    static = (phi.T @ forcing) / lam
    response = 1 - np.exp(-np.outer(t, zeta * w)) * (
        np.cos(np.outer(t, wd)) + zeta / np.sqrt(1 - zeta**2) * np.sin(np.outer(t, wd))
    )
    x = (response * static) @ phi.T
    expected = DAMAGE_PARAMETERS.beta * np.max(np.linalg.norm(x, axis=1))

    assert result.value == pytest.approx(expected, rel=1e-6)
    np.testing.assert_allclose(result.displacement, x, rtol=0, atol=1e-8)

    # The x-z coupling makes the sign of z matter.
    flipped = damage_from_acceleration(
        t, np.full_like(t, 800.0), np.zeros_like(t), np.full_like(t, -600.0)
    )
    assert flipped.value > 1.1 * result.value


def test_damage_from_angular_velocity_differentiates():
    t = np.linspace(0.0, 0.08, 801)
    period = 0.02
    pulse = t <= period
    omega = np.where(pulse, 15.0 * (1 - np.cos(2 * np.pi * t / period)), 0.0)
    alpha = np.where(
        pulse, 30.0 * np.pi / period * np.sin(2 * np.pi * t / period), 0.0
    )
    zeros = np.zeros_like(t)

    from_velocity = damage(t, omega, zeros, zeros)
    exact = damage_from_acceleration(t, alpha, zeros, zeros)

    assert from_velocity.value == pytest.approx(exact.value, rel=2e-3)
    assert from_velocity.time == pytest.approx(exact.time, abs=2e-4)


# --- DAMAGE: evaluation window ------------------------------------------------


def test_damage_window_ends_after_200_ms():
    t = np.linspace(0.0, 0.3, 3001)
    a = _haversine(t, 3000.0, 0.01, 0.02) + _haversine(t, 9000.0, 0.25, 0.02)
    zeros = np.zeros_like(t)

    result = damage_from_acceleration(t, a, zeros, zeros)

    assert result.end_reason == "max duration"
    assert result.start == 0.0
    assert result.end == pytest.approx(0.2, abs=1e-4)
    keep = t <= result.end
    truncated = damage_from_acceleration(t[keep], a[keep], zeros[keep], zeros[keep])
    assert result.value == truncated.value


def test_damage_window_starts_at_t0_from_rest():
    t = np.linspace(-0.02, 0.1, 1201)
    a = _haversine(t, 3000.0, 0.0, 0.02)
    zeros = np.zeros_like(t)
    early = _haversine(t, 9000.0, -0.02, 0.01)  # before T0: ignored

    result = damage_from_acceleration(t, a + early, zeros, zeros, t0=0.0)
    keep = t >= 0.0
    expected = damage_from_acceleration(t[keep], a[keep], zeros[keep], zeros[keep])

    assert result.start == pytest.approx(0.0, abs=1e-12)
    assert result.value == pytest.approx(expected.value, rel=1e-12)


def test_damage_window_ends_on_external_force():
    t = np.linspace(0.0, 0.2, 2001)
    a = _haversine(t, 3000.0, 0.0, 0.03)
    zeros = np.zeros_like(t)

    neck_fx = np.where(t >= 0.05, -600.0, 0.0)
    by_neck = damage_from_acceleration(t, a, zeros, zeros,
                                       head_ax_g=zeros, neck_fx=neck_fx)
    assert by_neck.end_reason == "external force"
    assert by_neck.end == pytest.approx(0.05, abs=1e-9)

    # -4.2 kg * 15 g * 9.81 = -618 N < -500 N
    head_ax = np.where(t >= 0.06, 15.0, 0.0)
    by_head = damage_from_acceleration(t, a, zeros, zeros,
                                       head_ax_g=head_ax, neck_fx=zeros)
    assert by_head.end_reason == "external force"
    assert by_head.end == pytest.approx(0.06, abs=1e-9)


def test_damage_external_force_before_t0_is_ignored():
    t = np.linspace(0.0, 0.1, 1001)
    a = _haversine(t, 3000.0, 0.03, 0.03)
    zeros = np.zeros_like(t)
    neck_fx = np.where((t >= 0.01) & (t <= 0.02), -600.0, 0.0)

    result = damage_from_acceleration(t, a, zeros, zeros, t0=0.025,
                                      head_ax_g=zeros, neck_fx=neck_fx)

    assert result.end_reason == "end of record"
    assert result.end == pytest.approx(0.1)


def test_external_force_hand_calculation():
    # -4.2 kg * 10 g * 9.81 m/s^2 + 200 N
    assert external_force(10.0, 200.0) == pytest.approx(-212.02)
    np.testing.assert_allclose(external_force([0.0, -5.0], [-100.0, 0.0]),
                               [-100.0, 206.01])


def test_damage_input_errors():
    t = np.linspace(0.0, 0.1, 101)
    zeros = np.zeros_like(t)
    with pytest.raises(ValueError, match="both"):
        damage_from_acceleration(t, zeros, zeros, zeros, head_ax_g=zeros)
    with pytest.raises(ValueError, match="finite"):
        damage_from_acceleration(t, zeros, zeros, zeros, t0=math.nan)
    with pytest.raises(ValueError, match="before the end"):
        damage_from_acceleration(t, zeros, zeros, zeros, t0=0.5)
    with pytest.raises(ValueError, match="at least 3"):
        damage(t[:2], zeros[:2], zeros[:2], zeros[:2])


# --- BrIC ---------------------------------------------------------------------


def test_bric_hand_calculation():
    t = np.array([0.0, 0.01, 0.02, 0.03])
    wx = np.array([0.0, 33.125, 10.0, 0.0])  # half of wxC
    wy = np.array([0.0, 5.0, -28.225, 0.0])  # half of wyC, at another time
    wz = np.zeros(4)

    result = bric(t, wx, wy, wz)

    assert result.value == pytest.approx(math.sqrt(0.5))
    assert result.peaks == pytest.approx((33.125, 28.225, 0.0))
    assert result.critical == (66.25, 56.45, 42.87)


def test_bric_equals_one_at_the_critical_values():
    t = np.array([0.0, 0.01])
    for name, crit in BRIC_CRITICAL_VELOCITIES.items():
        for axis in range(3):
            w = [np.zeros(2), np.zeros(2), np.zeros(2)]
            w[axis] = np.array([0.0, -crit[axis]])
            assert bric(t, *w, critical=name).value == pytest.approx(1.0)


def test_bric_critical_values_from_takhounts_2013():
    mps = BRIC_CRITICAL_VELOCITIES["mps"]
    csdm = BRIC_CRITICAL_VELOCITIES["csdm"]
    assert mps == (66.30, 53.80, 41.50)
    assert csdm == (66.20, 59.10, 44.25)
    # The published average set is the mean of the two, rounded.
    for avg, a, b in zip(BRIC_CRITICAL_VELOCITIES["average"], mps, csdm):
        assert avg == pytest.approx((a + b) / 2, abs=0.006)


def test_bric_custom_critical_values_and_window():
    t = np.array([0.0, 0.01, 0.02, 0.03])
    wx = np.array([0.0, 20.0, 0.0, 99.0])
    zeros = np.zeros(4)
    result = bric(t, wx, zeros, zeros, critical=(40.0, 50.0, 60.0), t_end=0.02)
    assert result.value == pytest.approx(0.5)
    with pytest.raises(ValueError, match="Unknown critical set"):
        bric(t, wx, zeros, zeros, critical="nope")
    with pytest.raises(ValueError, match="positive"):
        bric(t, wx, zeros, zeros, critical=(40.0, 0.0, 60.0))


# --- Loading phase ------------------------------------------------------------


def test_loading_phase_end_interpolates_zero_crossing():
    t = np.array([0.0, 0.001, 0.002, 0.003, 0.004])
    ax = np.array([0.0, -10.0, -5.0, 5.0, 2.0])
    assert loading_phase_end(t, ax) == pytest.approx(0.0025)


def test_loading_phase_end_on_sine_pulse():
    # Deceleration pulse crossing zero at 60.05 ms, between two samples.
    t = np.linspace(0.0, 0.1, 1001)
    ax = -30.0 * np.sin(np.pi * t / 0.06005)
    assert loading_phase_end(t, ax) == pytest.approx(0.06005, abs=1e-9)


def test_loading_phase_end_without_crossing():
    t = np.array([0.0, 0.001, 0.002])
    assert loading_phase_end(t, [0.0, -5.0, -1.0]) == 0.002
    assert loading_phase_end(t, [0.0, 5.0, 1.0]) == 0.002
