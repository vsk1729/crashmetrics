"""Example 16: Bharat NCAP child occupant protection and the complete
star rating with the safety assist qualifiers (AIS-197).

Synthetic results for a compact SUV published in November 2026. The
adult occupant tests are scored as in example 07; here the focus is the
child occupant score (dynamic, CRS installation, vehicle based) and the
safety assist qualifiers that cap the adult stars.
"""

import datetime as dt

import numpy as np

from crashmetrics.bncap import FrontalOccupant, SideOccupant, score_frontal, score_side
from crashmetrics.bncap_cop import (
    CrsInstallation,
    VehicleBasedAssessment,
    score_child_frontal,
    score_child_side,
    score_cop,
    score_cop_dynamic,
    score_crs_installation,
    score_vehicle_based,
)
from crashmetrics.bncap_rating import SafetyAssist, bncap_rating

t = np.arange(0.0, 0.12, 1e-4)


def plateau(level, duration_ms, start_ms=20.0):
    return np.interp(t * 1000, [0, start_ms, start_ms + 1, start_ms + duration_ms,
                                start_ms + duration_ms + 1, 200],
                     [0, 0, level, level, 0, 0])


# --- 1. Adult occupant tests (frontal and side, 16 points each) ------------
def adult(chest, pedal=None):
    return FrontalOccupant(
        neck_shear=(t, plateau(-800.0, 20.0)), neck_tension=(t, plateau(1600.0, 25.0)),
        neck_extension=20.0, chest_compression=chest, viscous_criterion=0.38,
        femur=((t, plateau(-3500.0, 15.0)), (t, plateau(-3200.0, 15.0))),
        knee_displacement=(3.0, 4.0), tibia_index=(0.45, 0.5),
        tibia_force=(2100.0, 2300.0), hard_contact=False, pedal_rearward=pedal)


frontal = score_frontal(adult(27.0, pedal=40.0), adult(24.0))
side = score_side(SideOccupant(hic15=240.0, head_a3ms=42.0, rib_deflection=27.0,
                               rib_vc=0.36, abdominal_force=1150.0,
                               pubic_force=2400.0))

# --- 2. Child dynamic assessment: Q1.5 rearward, Q3 forward facing --------
child_frontal = [
    score_child_frontal("q1.5", "rearward", head_a3ms=58.0, head_peak=66.0,
                        neck_tension=1550.0, chest_a3ms=46.0),
    score_child_frontal("q3", "forward", head_a3ms=91.0, head_peak=98.0,
                        neck_tension=2050.0, chest_a3ms=53.0, head_excursion=505.0),
]
child_side = [
    score_child_side("q1.5", head_a3ms=55.0, head_peak=61.0),
    score_child_side("q3", head_a3ms=78.0, head_peak=97.0),
]
dynamic = score_cop_dynamic(child_frontal, child_side)

# --- 3. CRS installation (Annexure V 3.7) -----------------------------------
installation = score_crs_installation(
    installation_list=[
        CrsInstallation("Group 0+ belted", eligible_positions=2, failed=0),
        CrsInstallation("Group 0+ ISOFIX", eligible_positions=2, failed=0),
        CrsInstallation("Group I FWF belted", eligible_positions=3, failed=1),
        CrsInstallation("Group I ISOFIX", eligible_positions=2, failed=0),
        CrsInstallation("Group II/III booster", eligible_positions=3, failed=0),
    ],
    recommended=[CrsInstallation("OEM seat for Q1.5", 2, 0),
                 CrsInstallation("OEM seat for Q3", 2, 1)],
)

# --- 4. Vehicle based assessments (Annexure V Section 5) ---------------------
vehicle_based = score_vehicle_based(VehicleBasedAssessment(
    gabarit_all_seats=True, gabarit_handbook_and_airbag=True,
    three_simultaneous=False,
    isofix_un=True, isofix_marked=True, isofix_isize_ready=False,
    two_largest_isofix=True,
    airbag="manual",                     # manual switch and label: 3 points
))

cop = score_cop(installation, vehicle_based, dynamic)

# --- 5. Safety assist qualifiers and the rating (Annexure VI) --------------
for share in (0.95, 0.60):
    sat = SafetyAssist(
        publication=dt.date(2026, 11, 15),
        pedestrian_ais100=True, seat_belt_reminder_ais145=True,
        esc_fitted=True, esc_demonstrated=True, esc_full_fitment_commitment=True,
        side_head_protection_fitted=True, pole_test_passed=True,
        side_head_standard_fitment=share,
    )
    rating = bncap_rating(frontal, side, cop, sat)
    print(f"=== Side head protection standard in {share:.0%} of production")
    print(rating.summary() if share < 0.9 else
          rating.summary().split("\n  Bharat NCAP child")[0])
    print()
