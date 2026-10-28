"""Example 5: frontal dummy criteria from signals (Hybrid III and THOR).

Synthetic, already filtered channels in SI units (s, N, N m, rad/s, g)
with deflections in mm. Replace them with your test or CAE channels,
filtered with the CFC classes of Euro NCAP CP 005.
"""

import numpy as np

from crashmetrics.head import bric, damage, loading_phase_end
from crashmetrics.lower_extremity import (
    femur_force_criterion,
    knee_slider_displacement,
    tibia_compression,
    tibia_index,
)
from crashmetrics.neck import neck_force_criterion, neck_loads, nij
from crashmetrics.pelvis import acetabulum_force, iliac_force_drop
from crashmetrics.thorax import (
    chest_deflection,
    cti_from_signals,
    thor_abdomen_deflection,
    thor_chest_deflection,
    viscous_criterion,
)

t = np.arange(0.0, 0.15, 1e-4)                        # 10 kHz, 150 ms


def bump(peak, start, duration):
    """Smooth pulse: 0 -> peak -> 0 between start and start + duration."""
    phase = np.clip((t - start) / duration, 0.0, 1.0)
    return peak * np.sin(np.pi * phase) ** 2


# --- Head (THOR): DAMAGE and BrIC from angular velocity (CFC 60) -------------
wx, wy, wz = bump(8.0, 0.03, 0.06), bump(32.0, 0.035, 0.07), bump(-12.0, 0.04, 0.06)
head_ax = -bump(45.0, 0.02, 0.07) + bump(15.0, 0.09, 0.04)    # g
neck_fx = bump(900.0, 0.03, 0.06)                              # N
dmg = damage(t, wx, wy, wz, t0=0.0, head_ax_g=head_ax, neck_fx=neck_fx)
print(f"DAMAGE      : {dmg.value:.3f} (window {dmg.start * 1000:.0f}-"
      f"{dmg.end * 1000:.1f} ms, ends by {dmg.end_reason})")
print(f"BrIC        : {bric(t, wx, wy, wz).value:.3f}")

# --- Neck (Hybrid III) over the loading phase -------------------------------
t_end = loading_phase_end(t, head_ax)
fx = bump(-700.0, 0.03, 0.05)                            # shear, N
fz = bump(1900.0, 0.03, 0.05)                            # tension, N
my = bump(-25.0, 0.035, 0.05)                            # extension, N m
loads = neck_loads(t, fx, fz, my, dummy="hybrid3", t_end=t_end)
print(f"Loading end : {t_end * 1000:.1f} ms")
print(f"Neck        : tension {loads.tension.value:.0f} N, "
      f"shear {loads.shear.value:.0f} N, "
      f"extension {loads.extension_moment.value:.1f} N m (at the occipital condyle)")
r94 = neck_force_criterion(t, fz, "r94_tension")
print(f"R94 tension : utilisation {r94.utilisation:.2f}, passed {r94.passed}")
n = nij(t, fz, my, fx=fx, dummy="hybrid3_50")
print(f"Nij         : {n.value:.3f} ({n.category})")

# --- Chest -------------------------------------------------------------------
deflection = bump(31.0, 0.03, 0.06)                            # mm, compression +
vc = viscous_criterion(t, deflection, dummy="hybrid3_50")
print(f"Chest (H3)  : {chest_deflection(t, deflection).value:.1f} mm, "
      f"VC {vc.value:.3f} m/s")
spine = bump(38.0, 0.03, 0.06)                                 # resultant g
print(f"CTI         : {cti_from_signals(t, spine, deflection).value:.3f}")

r0 = 120.0                                                     # IR-TRACC length, mm
ribs = {name: (r0 - bump(c, 0.03, 0.06), bump(4.0, 0.03, 0.06), bump(-3.0, 0.03, 0.06))
        for name, c in (("ul", 30.0), ("ur", 36.0), ("ll", 28.0), ("lr", 33.0))}
chest = thor_chest_deflection(t, ribs["ul"], ribs["ur"], ribs["ll"], ribs["lr"])
print(f"THOR Rmax   : {chest.rmax:.1f} mm at {chest.location}")
abdomen = thor_abdomen_deflection(t, (200.0 - bump(48.0, 0.03, 0.06), 0 * t, 0 * t),
                                  (200.0 - bump(55.0, 0.03, 0.06), 0 * t, 0 * t))
print(f"THOR abdomen: {abdomen.value:.1f} mm ({abdomen.side})")

# --- Pelvis (THOR) ----------------------------------------------------------
acet = acetabulum_force(t, -bump(2600.0, 0.04, 0.05), bump(900.0, 0.04, 0.05),
                        bump(700.0, 0.04, 0.05))
iliac = -bump(4500.0, 0.03, 0.05) + np.where(t > 0.052, bump(1500.0, 0.03, 0.05), 0.0)
print(f"Acetabulum  : {acet.value:.0f} N, iliac force drop "
      f"{iliac_force_drop(t, iliac).value:.0f} N")

# --- Legs -------------------------------------------------------------------
femur = -bump(6500.0, 0.03, 0.04)                              # compression negative
f = femur_force_criterion(t, femur, limit="r94_hybrid3_50")
print(f"Femur       : {f.peak_compression:.0f} N, R94 utilisation {f.utilisation:.2f}")
slider = knee_slider_displacement(t, -bump(4.2, 0.04, 0.03))
print(f"Knee slider : {slider.value:.1f} mm")
tib_fz = -bump(3200.0, 0.04, 0.04)
ti = tibia_index(t, bump(60.0, 0.04, 0.04), bump(90.0, 0.04, 0.04), tib_fz,
                 dummy="hybrid3_50")
print(f"Tibia       : TI {ti.value:.3f}, compression "
      f"{tibia_compression(t, tib_fz).value:.0f} N")
