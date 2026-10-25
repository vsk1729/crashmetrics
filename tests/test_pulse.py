import math

import numpy as np
import pytest

from crashmetrics.pulse import OLC_GRAVITY, olc, pulse_summary


def closed_form_olc(decel, free_flight=0.065, restraint=0.235):
    """OLC for a vehicle at constant deceleration that has not stopped.

    Relative occupant displacement in free flight is decel * t**2 / 2,
    so t1 = sqrt(2 * free_flight / decel). In the restraint phase the
    relative displacement is decel * t1 * (t2 - t1) / 2, so
    t2 = t1 + 2 * restraint / (decel * t1), and the occupant velocity
    matches the vehicle velocity when OLC = decel * t2 / (t2 - t1).
    """
    t1 = math.sqrt(2.0 * free_flight / decel)
    t2 = t1 + 2.0 * restraint / (decel * t1)
    return decel * t2 / (t2 - t1), t1, t2


def independent_olc(t, acc, v0, dt=2e-6):
    """Independent OLC: find the occupant deceleration D for which the
    largest relative displacement (reached when the velocities match)
    is exactly free flight + restraint = 0.300 m. Uses a fine grid and
    bisection on D, not the t1/t2 equations."""
    tt = np.arange(t[0], t[-1], dt)
    aa = np.interp(tt, t, acc)
    vehicle_v = v0 + np.concatenate(([0], np.cumsum(0.5 * (aa[1:] + aa[:-1]) * dt)))
    vehicle_s = np.concatenate(
        ([0], np.cumsum(0.5 * (vehicle_v[1:] + vehicle_v[:-1]) * dt))
    )
    i1 = int(np.argmax(v0 * (tt - tt[0]) - vehicle_s >= 0.065))

    def max_relative(decel):
        occ_v = np.where(np.arange(tt.size) < i1, v0, v0 - decel * (tt - tt[i1]))
        occ_s = np.concatenate(([0], np.cumsum(0.5 * (occ_v[1:] + occ_v[:-1]) * dt)))
        j = i1 + int(np.argmax(occ_v[i1:] <= vehicle_v[i1:]))
        return occ_s[j] - vehicle_s[j]

    low, high = 1.0, 5000.0
    for _ in range(60):
        middle = 0.5 * (low + high)
        if max_relative(middle) > 0.300:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


def mpdb_like_pulse():
    """Synthetic 50 km/h pulse with rebound; not test data."""
    t = np.arange(0.0, 0.15, 5e-5)
    shape = 25 * np.sin(np.pi * np.clip(t / 0.11, 0, 1)) ** 2 + 10 * np.sin(
        np.pi * np.clip((t - 0.02) / 0.05, 0, 1)
    )
    return t, -9.81 * shape, 50 / 3.6


# --- OLC -------------------------------------------------------------------


@pytest.mark.parametrize("decel", [150.0, 200.0, 300.0])
def test_olc_matches_closed_form_for_constant_deceleration(decel):
    expected, t1, t2 = closed_form_olc(decel)
    v0 = decel * t2 * 1.5  # vehicle still moving at t2
    t = np.linspace(0.0, 1.2 * t2, 4001)

    result = olc(t, np.full_like(t, -decel), v0)

    assert result.value_si == pytest.approx(expected, rel=1e-9)
    assert result.value == pytest.approx(expected / OLC_GRAVITY, rel=1e-9)
    assert result.t1 == pytest.approx(t1, rel=1e-9)
    assert result.t2 == pytest.approx(t2, rel=1e-9)


def test_olc_matches_independent_formulation_for_realistic_pulse():
    t, acc, v0 = mpdb_like_pulse()

    result = olc(t, acc, v0)
    reference = independent_olc(t, acc, v0)

    assert result.value_si == pytest.approx(reference, rel=1e-4)


def test_olc_is_independent_of_sampling():
    t, acc, v0 = mpdb_like_pulse()
    fine = olc(t, acc, v0).value
    coarse = olc(t[::4], acc[::4], v0).value
    assert coarse == pytest.approx(fine, rel=1e-3)


def test_olc_respects_time_offset():
    t, acc, v0 = mpdb_like_pulse()
    base = olc(t, acc, v0)
    shifted = olc(t + 0.5, acc, v0)
    assert shifted.value == pytest.approx(base.value, rel=1e-9)
    assert shifted.t1 == pytest.approx(base.t1, abs=1e-12)


def test_olc_custom_gravity_only_rescales():
    t, acc, v0 = mpdb_like_pulse()
    a = olc(t, acc, v0)
    b = olc(t, acc, v0, gravity=9.80665)
    assert b.value_si == a.value_si
    assert b.value == pytest.approx(a.value_si / 9.80665)


def test_olc_wrong_sign_gives_clear_error():
    t, acc, v0 = mpdb_like_pulse()
    with pytest.raises(ValueError, match="negative while the vehicle"):
        olc(t, -acc, v0)


def test_olc_record_ends_during_free_flight():
    t, acc, v0 = mpdb_like_pulse()
    with pytest.raises(ValueError, match="free-flight phase"):
        olc(t[:200], acc[:200], v0)  # 10 ms


def test_olc_record_ends_during_restraint_phase():
    t, acc, v0 = mpdb_like_pulse()
    full = olc(t, acc, v0)
    cut = int(0.5 * (full.t1 + full.t2) / 5e-5)
    with pytest.raises(ValueError, match="restraint phase"):
        olc(t[:cut], acc[:cut], v0)


@pytest.mark.parametrize(
    "kwargs", [{"v0": 0.0}, {"v0": -5.0}, {"v0": 10.0, "restraint": 0.0}]
)
def test_olc_validation(kwargs):
    t = np.linspace(0.0, 0.1, 101)
    with pytest.raises(ValueError):
        olc(t, np.full_like(t, -100.0), **kwargs)


# --- pulse_summary ---------------------------------------------------------


def test_pulse_summary_constant_deceleration_to_stop():
    v0, decel = 15.0, 300.0
    t_stop = v0 / decel
    # Samples at t_stop and 1 ns later make the step in acceleration
    # nearly exact (acceleration is linear between samples).
    t = np.unique(np.concatenate((np.linspace(0.0, 0.08, 1601),
                                  [t_stop, t_stop + 1e-9])))
    acc = np.where(t <= t_stop, -decel, 0.0)

    s = pulse_summary(t, acc, v0)

    assert s.time_to_zero_velocity == pytest.approx(t_stop, rel=1e-6)
    assert s.max_displacement == pytest.approx(v0**2 / (2 * decel), rel=1e-6)
    assert s.mean_deceleration == pytest.approx(decel, rel=1e-6)
    assert s.peak_deceleration == pytest.approx(decel)
    # The 1 ns ramp leaves a residual velocity of 300 * 1e-9 / 2.
    assert s.rebound_velocity == pytest.approx(0.0, abs=1e-6)
    assert s.delta_v == pytest.approx(v0, rel=1e-6)


def test_pulse_summary_with_rebound():
    # 20 m/s, constant 400 m/s^2 for 60 ms: v goes to -4 m/s.
    t = np.linspace(0.0, 0.06, 6001)
    s = pulse_summary(t, np.full_like(t, -400.0), 20.0)

    assert s.time_to_zero_velocity == pytest.approx(0.05)
    assert s.time_of_max_displacement == pytest.approx(0.05)
    assert s.max_displacement == pytest.approx(20.0**2 / 800.0)
    assert s.final_velocity == pytest.approx(-4.0)
    assert s.rebound_velocity == pytest.approx(4.0)
    assert s.restitution == pytest.approx(0.2)
    assert s.delta_v == pytest.approx(24.0)


def test_pulse_summary_vehicle_still_moving():
    t = np.linspace(0.0, 0.02, 201)
    s = pulse_summary(t, np.full_like(t, -100.0), 10.0)

    assert s.time_to_zero_velocity is None
    assert s.mean_deceleration is None
    assert s.time_of_max_displacement == pytest.approx(0.02)
    assert s.max_displacement == pytest.approx(10 * 0.02 - 50 * 0.02**2)
