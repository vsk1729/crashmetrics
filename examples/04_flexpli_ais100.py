"""Example 4: Flex-PLI signals, AIS-100 compliance and Euro NCAP Flex-PLI score.

Steps: find the assessment interval from the bone bending moments, take
the peaks inside it, check them against AIS-100 Rev.1, then score a
bumper grid with the Euro NCAP (2014-2022) Flex-PLI scale.
"""

import numpy as np

from crashmetrics.pedestrian import (
    bumper_legform,
    check_flexpli,
    check_headform_tests,
    check_headform_zones,
    check_legacy_legform,
    check_relaxation_width,
    check_upper_legform_bumper,
    flexpli_peaks,
    flexpli_score,
)

# --- 1. Which legform test applies? -----------------------------------------
for height in (390.0, 460.0, 520.0):
    print(f"Lower bumper height {height:.0f} mm -> {bumper_legform(height)}")

# --- 2. Flex-PLI channels (synthetic, CFC 180 filtered) ---------------------
t = np.arange(0.0, 0.06, 1e-4)                      # s, 10 kHz


def pulse(peak, duration, delay=0.0):
    phase = np.clip((t - delay) / duration, 0.0, 1.5)
    return peak * np.sin(np.pi * phase)             # rises, then goes negative


tibia = [pulse(305.0, 0.028), pulse(270.0, 0.030), pulse(210.0, 0.032),
         pulse(150.0, 0.034)]                       # N m, T1-T4
femur = [pulse(160.0, 0.026), pulse(140.0, 0.027), pulse(120.0, 0.029)]
mcl, acl, pcl = pulse(19.8, 0.030), pulse(6.1, 0.030), pulse(3.4, 0.031)  # mm

peaks = flexpli_peaks(t, tibia, mcl, acl, pcl, femur_moments=femur)
print(f"Assessment interval: {peaks.interval[0] * 1000:.1f} to "
      f"{peaks.interval[1] * 1000:.1f} ms")
print(f"Peaks: tibia T{peaks.tibia_segment + 1} {peaks.tibia_moment:.0f} N m, "
      f"MCL {peaks.mcl:.1f} mm, ACL {peaks.acl:.1f} mm, PCL {peaks.pcl:.1f} mm")

# --- 3. AIS-100 Rev.1 compliance --------------------------------------------
check = check_flexpli(peaks.tibia_moment, peaks.mcl, peaks.acl, peaks.pcl)
print(f"AIS-100 Flex-PLI: {'PASS' if check.passed else 'FAIL'}, worst "
      f"{check.worst} at {check.utilisation[check.worst]:.0%} of its limit")
relaxed = check_flexpli(355.0, 20.0, 8.0, 5.0, relaxed_zone=True)
print(f"In a nominated relaxation zone (355 N m <= 380 N m): "
      f"{'PASS' if relaxed.passed else 'FAIL'}; total width 2 x 132 mm "
      f"{'PASS' if check_relaxation_width([132.0, 132.0]).passed else 'FAIL'}")

# Original AIS-100 (legacy legform) and the upper legform to bumper
legacy = check_legacy_legform(knee_bending_angle=16.5, knee_shear_displacement=4.2,
                              tibia_acceleration=182.0)
print(f"Legacy legform: {'PASS' if legacy.passed else 'FAIL'} "
      f"(worst {legacy.worst} {legacy.values[legacy.worst]:g} vs "
      f"{legacy.limits[legacy.worst]:g})")
upper = check_upper_legform_bumper(sum_of_forces=6900.0, bending_moment=455.0)
print(f"Upper legform to bumper: {'PASS' if upper.passed else 'FAIL'}")

# --- 4. AIS-100 headform zones and tests -------------------------------------
zones = check_headform_zones(child_area=0.62, adult_area=0.41,
                             hic1000_child_area=0.40, hic1000_adult_area=0.30)
print(f"HIC1000 zone: {zones.values['child_share']:.0%} of child area, "
      f"{zones.values['total_share']:.0%} of total -> "
      f"{'PASS' if zones.passed else 'FAIL'}")
tests = check_headform_tests([("hic1000", 812.0), ("hic1000", 955.0),
                              ("hic1700", 1420.0)])
print(f"Headform tests: {'PASS' if tests.passed else 'FAIL'} {tests.values}")

# --- 5. Euro NCAP Flex-PLI grid score (6 points) -----------------------------
grid = ["L+5", "L+4", "L+3", "L+2", "L+1", "L0", "L-1", "L-2", "L-3", "L-4", "L-5"]
score = flexpli_score(grid, {
    "L0": (peaks.tibia_moment, peaks.mcl, peaks.acl, peaks.pcl),
    "L+2": (262.0, 17.5, 4.0, 3.0),
    "L+4": (318.0, 21.0, 10.4, 2.0),     # ACL >= 10 mm: knee scores 0
})
print(f"Euro NCAP Flex-PLI: {score.points:.3f} / {score.max_points:g} points")
