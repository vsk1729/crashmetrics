"""crashmetrics.pulse and crashmetrics.signals on real crash test data.

Vehicle acceleration channels of two tests of the NHTSA Vehicle Crash
Test Database (public information; see tests/data/nhtsa/README.md for
the source, licence and test details):

- Test 2320: a 1996 Dodge Neon into a rigid barrier at 56.5 km/h. The
  source repository reports peak, crush, time and restitution of this
  measured pulse from its own code; they must agree.
- Test 4429: a 1999 Lincoln Navigator head-on into a 1996 Dodge Neon,
  48.5 km/h each. Momentum conservation gives the truth: the velocity
  changes are in the inverse ratio of the masses, whatever the
  restitution.
"""

from pathlib import Path

import numpy as np
import pytest

from crashmetrics.pulse import olc, pulse_summary
from crashmetrics.signals import cfc_filter

DATA = Path(__file__).parent / "data" / "nhtsa"
G = 9.80665


def channel(*names):
    """Time (s) and the mean acceleration (g) of the named channel files."""
    signals = [np.loadtxt(DATA / name) for name in names]
    return signals[0][:, 0], np.mean([s[:, 1] for s in signals], axis=0)


def summary(time, acc_g, speed_kmh, zero=False):
    """Pulse summary from first contact, CFC 60 (SAE J211 for vehicle
    structure accelerations)."""
    if zero:                                  # remove the pre-impact offset
        acc_g = acc_g - acc_g[time < -0.002].mean()
    after = time >= 0
    filtered = cfc_filter(time, acc_g, 60)[after] * G
    return time[after], filtered, pulse_summary(time[after], filtered, speed_kmh / 3.6)


def test_files_are_as_recorded():
    t, a = channel("v02320tsv.078")
    assert len(t) == 4378 and t[0] == pytest.approx(-0.02008)
    np.testing.assert_allclose(np.diff(t), 8.0e-5, atol=1e-9)        # 12.5 kHz
    assert abs(a[t < -0.002].mean()) < 0.1                            # g, at rest
    assert a.min() == pytest.approx(-51.0, abs=0.1)                   # unfiltered


def test_rigid_barrier_pulse_matches_independent_results():
    """Test 2320 against the values the source repository reports for
    the measured pulse: peak -35.2 g, crush 740 mm at 78 ms, restitution
    0.163 (its own Rust code; same signal as recorded, CFC 60)."""
    t, a = channel("v02320tsv.078")
    _, _, s = summary(t, a, 56.5)
    assert s.peak_deceleration / G == pytest.approx(35.2, abs=0.1)
    assert s.max_displacement * 1000 == pytest.approx(740.0, abs=1.0)
    assert s.time_of_max_displacement * 1000 == pytest.approx(78.0, abs=0.2)
    assert s.restitution == pytest.approx(0.163, abs=0.002)
    # The car stops at the maximum crush and rebounds.
    assert s.time_to_zero_velocity == pytest.approx(s.time_of_max_displacement)
    assert s.delta_v == pytest.approx(56.5 / 3.6 - s.final_velocity, rel=1e-9)
    assert s.rebound_velocity >= -s.final_velocity > 0          # still rolling back


def test_rigid_barrier_pulse_is_robust_to_processing():
    t, a = channel("v02320tsv.078")
    _, _, raw = summary(t, a, 56.5)
    tt, acc, zeroed = summary(t, a, 56.5, zero=True)
    # Removing the 0.06 g pre-impact offset moves the crush by 2 mm.
    assert zeroed.max_displacement == pytest.approx(raw.max_displacement, rel=0.005)
    assert zeroed.restitution == pytest.approx(raw.restitution, abs=0.01)
    # A filter class above CFC 60 changes the integrated values little.
    _, _, s180 = (tt, None, pulse_summary(
        tt, cfc_filter(t, a - a[t < -0.002].mean(), 180)[t >= 0] * G, 56.5 / 3.6))
    assert s180.max_displacement == pytest.approx(zeroed.max_displacement, rel=1e-3)
    assert s180.peak_deceleration > zeroed.peak_deceleration
    # OLC of a 56 km/h rigid barrier test of a small 1990s car.
    assert 25.0 < olc(tt, acc, 56.5 / 3.6).value < 33.0


def test_car_to_car_obeys_momentum_conservation():
    """Test 4429: m1 dv1 = m2 dv2, and both cars end at the common
    velocity of a plastic impact (the heavier car's direction)."""
    m_navigator, m_neon, v0 = 2873.0, 1378.0, 48.5
    _, _, navigator = summary(*channel("v04429tsv.179", "v04429tsv.182"), v0, zero=True)
    _, _, neon = summary(*channel("v04429tsv.089", "v04429tsv.092"), v0, zero=True)
    ratio = neon.delta_v / navigator.delta_v
    assert ratio == pytest.approx(m_navigator / m_neon, rel=0.10)        # 1.96 vs 2.08
    common = (m_navigator - m_neon) / (m_navigator + m_neon) * v0 / 3.6  # 4.74 m/s
    assert navigator.final_velocity == pytest.approx(common, abs=1.0)    # keeps going
    assert -neon.final_velocity == pytest.approx(common, abs=1.0)        # pushed back
    assert navigator.time_to_zero_velocity is None                       # never stops
    assert neon.restitution > navigator.restitution
    assert neon.peak_deceleration > 1.8 * navigator.peak_deceleration    # the light car
