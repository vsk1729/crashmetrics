"""Example 8: vehicle crash pulse (OLC, delta-V, crush) and crash box energy.

The vehicle acceleration is in its direction of travel, so it is
negative while the car decelerates, in SI units (s, m/s^2, m/s).
"""

import numpy as np

from crashmetrics.energy import (
      absorbed_energy,
      crush_metrics,
      integrate_acceleration,
      kinetic_energy,
)
from crashmetrics.pulse import olc, pulse_summary
from crashmetrics.signals import cfc_filter

# --- 1. Vehicle pulse: 50 km/h into a barrier, about 100 ms -----------------
t = np.arange(0.0, 0.15, 1e-4)
v0 = 50.0 / 3.6                                         # m/s
shape = np.where(t < 0.1, np.sin(np.pi * t / 0.1), 0.0)
rng = np.random.default_rng(3)
# Half-sine sized for a 15 % rebound: delta-V = 1.15 x v0
a_raw = -1.15 * v0 * np.pi / 0.2 * shape + 5.0 * rng.standard_normal(t.size)
a = cfc_filter(t, a_raw, cfc=180)                       # Euro NCAP uses CFC 180 for OLC

result = olc(t, a, v0=v0)
print(f"OLC          : {result.value:.1f} g "
      f"(free flight ends {result.t1 * 1000:.1f} ms, "
      f"restraint phase ends {result.t2 * 1000:.1f} ms)")

summary = pulse_summary(t, a, v0=v0)
print(f"Delta-V      : {summary.delta_v:.2f} m/s, "
      f"rebound {summary.rebound_velocity:.2f} m/s "
      f"(restitution {summary.restitution:.2f})")
print(f"Dynamic crush: {summary.max_displacement * 1000:.0f} mm at "
      f"{summary.time_of_max_displacement * 1000:.1f} ms")
print(f"Deceleration : peak {summary.peak_deceleration / 9.81:.1f} g, "
      f"mean {summary.mean_deceleration / 9.81:.1f} g")

# Velocity and displacement histories, and the energy to absorb
velocity, displacement = integrate_acceleration(t, a, v0=v0)
print(f"Kinetic energy at 50 km/h, 1500 kg: {kinetic_energy(1500.0, v0) / 1000:.1f} kJ")

# --- 2. Crash box: force (kN) against crush (mm) gives energy in J ----------
crush = np.linspace(0.0, 180.0, 901)                    # mm
force = (110.0 * (crush / 4.0) * np.exp(1.0 - crush / 4.0)        # initial peak
         + 55.0 * (1.0 - np.exp(-crush / 5.0)) + 8.0 * np.sin(crush / 6.0))   # kN
energy_curve = absorbed_energy(crush, force)
box = crush_metrics(crush, force, mass=1.2, max_displacement=150.0)
print(f"Crash box    : {box.energy / 1000:.2f} kJ over {box.crush_distance:.0f} mm, "
      f"mean {box.mean_force:.1f} kN, peak {box.peak_force:.1f} kN at "
      f"{box.peak_force_displacement:.1f} mm")
print(f"               CFE {box.crush_force_efficiency:.2f}, "
      f"SEA {box.specific_energy_absorption / 1000:.1f} kJ/kg, "
      f"energy at full stroke {energy_curve[-1] / 1000:.2f} kJ")
