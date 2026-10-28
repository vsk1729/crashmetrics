"""Example 3: Euro NCAP legforms (aPLI, upper legform) and the VRU score.

Grid points use Euro NCAP names ("L+3", "U-2", ...). Untested points are
filled by symmetry and from the worst adjacent tested point.
"""

from crashmetrics.pedestrian import (
    apli_point_score,
    apli_score,
    leg_colour,
    upper_legform_alpha,
    upper_legform_energy,
    upper_legform_score,
    vru_score,
)

# --- 1. One aPLI test: femur moment (N m), tibia moment (N m), MCL (mm) ------
one = apli_point_score(femur_moment=[410.0, 395.0, 372.0],   # three femur gauges
                       tibia_moment=[290.0, 301.0, 260.0, 240.0],
                       mcl_elongation=28.5)
print(f"aPLI point   : femur {one.femur:.3f}, knee/tibia {one.knee_tibia:.3f} "
      f"(tibia {one.tibia:.3f}, MCL {one.mcl:.3f}) -> {leg_colour(one.knee_tibia)}")

# --- 2. aPLI grid -----------------------------------------------------------
grid_l = ["L+5", "L+4", "L+3", "L+2", "L+1", "L0", "L-1", "L-2", "L-3", "L-4", "L-5"]
apli = apli_score(grid_l, {
    "L0": (370.0, 250.0, 22.0),
    "L+2": (400.0, 257.0, 20.0),
    "L+4": (438.0, 300.0, 29.0),
    "L-5": (385.0, 330.0, 36.0),        # corner, asymmetric structure
}, asymmetric_points=["L+5", "L-5"])
print(f"aPLI femur   : {apli.femur.points:.3f} / {apli.femur.max_points:g}")
print(f"aPLI knee    : {apli.knee_tibia.points:.3f} / {apli.knee_tibia.max_points:g}")
for point in ("L+3", "L-1", "L+5"):
    print(f"  {point}: {apli.knee_tibia.scores[point]:.3f} "
          f"({apli.knee_tibia.sources[point]})")

# --- 3. Upper legform: is a test needed? ------------------------------------
alpha = upper_legform_alpha(ibrl=(0.0, 650.0), wad930=(120.0, 820.0))  # x rearward, mm
energy = upper_legform_energy(alpha)
print(f"Upper legform: alpha {alpha:.1f} deg, energy {energy.energy:.0f} J, "
      f"test velocity {energy.test_velocity:.2f} m/s, "
      f"test required {energy.test_required}")

grid_u = ["U+4", "U+3", "U+2", "U+1", "U0", "U-1", "U-2", "U-3", "U-4"]
pelvis = upper_legform_score(grid_u, {"U0": 5260.0, "U+2": 6800.0, "U+4": 4890.0})
print(f"Pelvis       : {pelvis.points:.3f} / {pelvis.max_points:g}")

# --- 4. Total passive VRU score (head from example 2 or a number) -----------
total = vru_score(head=6.119, pelvis=pelvis, femur=apli.femur,
                  knee_tibia=apli.knee_tibia)
print(f"VRU total    : {total.total:.3f} / {total.max_total:g} "
      f"({total.percentage:.1f} %)")
