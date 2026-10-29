"""Example 14: homologation compliance, UN R94 / AIS-098, UN R95 /
AIS-099, UN R135 and post-crash electrical safety of an electric car.

Synthetic test results. Head, neck and femur criteria are computed from
signals; the others are given as peak values from the test report. The
car is electric, so the fuel leakage requirements stay "not assessed".
"""

import numpy as np

from crashmetrics.acceleration import clip_3ms
from crashmetrics.homologation import (
    HVBus,
    check_electrical_safety,
    check_r94_occupant,
    check_r94_vehicle,
    check_r95_occupant,
    check_r95_vehicle,
    check_r135_occupant,
    check_r135_vehicle,
    combine,
)
from crashmetrics.pedestrian import calculate_hic

t = np.arange(0.0, 0.15, 1e-4)                           # s


def bump(peak, start, width):
    phase = (t - start) / width
    return np.where((phase > 0) & (phase < 1), peak * np.sin(np.pi * phase), 0.0)


# --- 1. UN R94 / AIS-098: 56 km/h, 40 % offset, two Hybrid III 50th ---------
def r94_occupant(position, head_g, chest_mm, femur_kn, neck_kn):
    head = bump(head_g, 0.055, 0.05)
    return check_r94_occupant(
        hpc=calculate_hic(t, head, window_ms=36.0).value,   # intervals <= 36 ms
        head_a3ms=clip_3ms(t, head),
        neck_tension=(t, bump(neck_kn * 1000, 0.045, 0.05)),
        neck_shear=(t, bump(-650.0, 0.045, 0.05)),
        neck_extension=24.0, thcc=chest_mm, vc=0.38,
        femur_left=(t, bump(-femur_kn * 1000, 0.04, 0.03)),
        femur_right=(t, bump(-0.8 * femur_kn * 1000, 0.04, 0.03)),
        tibia_compression=2900.0, tibia_index=0.66, knee_slider=3.1,
        position=position)


r94 = combine(
    "UN R94 / AIS-098",
    r94_occupant("driver", head_g=62.0, chest_mm=34.2, femur_kn=5.9, neck_kn=1.7),
    r94_occupant("passenger", head_g=55.0, chest_mm=43.1, femur_kn=4.4, neck_kn=1.5),
    check_r94_vehicle(steering_upward=28.0, steering_rearward=46.0, door_opened=False,
                      doors_unlocked_after=True, doors_open_without_tools=True),
)
print(r94.summary())
print(f"-> passed: {r94.passed}, failures: {r94.failures}, worst: {r94.worst}\n")

# --- 2. Post-crash electrical safety (R94 5.2.8, the same in R137) ------------
electrical = check_electrical_safety(
    buses=[
        HVBus("traction battery DC", "DC", working_voltage=355.0, voltage=352.0,
              isolation_resistance=92_000.0),          # 259 ohm/V: isolation route
        HVBus("drive inverter AC", "AC", working_voltage=355.0, voltage=4.0),
        HVBus("charger DC+AC", "DC+AC", working_voltage=400.0,
              isolation_resistance=48_000.0, ac_part_protected=True),
    ],
    electrolyte="non-aqueous", electrolyte_leaked_anywhere=False,
    reess_retained=True, reess_entered_cabin=False, fire_or_explosion=False,
)
print(electrical.summary(), "\n")

# --- 3. UN R95 / AIS-099: 50 km/h mobile barrier, ES-2 ------------------------
r95 = combine(
    "UN R95 / AIS-099",
    check_r95_occupant(head_contact=False, rdc=35.8, vc=0.52, pspf=2900.0,
                       apf=1650.0),
    check_r95_vehicle(door_opened=False, non_struck_doors_unlocked=True,
                      egress_possible=True, dangerous_detachment=False),
)
print(r95.summary(), "\n")

# --- 4. UN R135: 32 km/h pole at 75 deg, WorldSID 50th -----------------------
spine = bump(68.0, 0.03, 0.03) + bump(20.0, 0.0405, 0.002)   # short spike
r135 = combine(
    "UN R135",
    check_r135_occupant(hic36=455.0, shoulder_force=2350.0,
                        thorax_rib_deflection=47.5, abdominal_rib_deflection=58.0,
                        lower_spine=(t, spine), pubic_force=3510.0),
    check_r135_vehicle(struck_door_separated=False, other_doors_held=True),
)
print(r135.summary())
print(f"-> passed: {r135.passed}, failures: {r135.failures}, "
      f"complete: {r135.complete} (not assessed: {r135.not_assessed})")
