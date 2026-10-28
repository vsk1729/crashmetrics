"""Example 7: Bharat NCAP (AIS-197) adult occupant star rating.

ODB frontal at 64 km/h (Hybrid III 50th driver and passenger, 16 points),
MDB side at 50 km/h (ES-2, 16 points) and the 29 km/h pole test.
Neck shear, neck tension and femur force are given as time histories,
because they are scored from exceedance curves.
"""

import numpy as np

from crashmetrics.bncap import (
    NECK_TENSION_CURVES,
    FrontalOccupant,
    SideOccupant,
    a_pillar_modifier,
    aop_rating,
    backplate_modifier,
    colour,
    cop_stars,
    curve_points,
    pedal_blocking_modifier,
    pole_test_passed,
    score_frontal,
    score_side,
    steering_column_modifier,
    t12_modifier,
)

t = np.arange(0.0, 0.12, 1e-4)                         # s


def plateau(level, start_ms, end_ms):
    """Force held at `level` between two times, with 2 ms ramps."""
    ms = t * 1000.0
    up = np.clip((ms - start_ms + 2.0) / 2.0, 0.0, 1.0)
    down = np.clip((end_ms + 2.0 - ms) / 2.0, 0.0, 1.0)
    return level * np.minimum(up, down)


# --- 1. One exceedance curve, to see how it scores --------------------------
tension = plateau(2600.0, 20.0, 45.0)                  # 2.6 kN for about 25 ms
score = curve_points(t, tension, NECK_TENSION_CURVES)
print(f"Neck tension curve: {score.points:.3f} / 4 points "
      f"(lowest at {score.level:.0f} N held {score.duration_ms:.1f} ms)")

# --- 2. Frontal test ----------------------------------------------------------
driver = FrontalOccupant(
    hic15=560.0, head_a3ms=62.0,                      # hard contact (default)
    neck_shear=(t, plateau(-900.0, 20.0, 40.0)),
    neck_tension=(t, tension),
    neck_extension=24.0,
    chest_compression=28.0, viscous_criterion=0.42,
    femur=((t, plateau(-4200.0, 30.0, 36.0)), (t, plateau(-3600.0, 30.0, 36.0))),
    knee_displacement=(4.0, 6.5),
    tibia_index=(0.62, 0.48), tibia_force=(2600.0, 2300.0),
    pedal_rearward=120.0,
    modifiers={
        "head": steering_column_modifier(rearward=95.0, upward=40.0),
        "chest": a_pillar_modifier(130.0),
        "foot": pedal_blocking_modifier(80.0),
    },
)
passenger = FrontalOccupant(
    hard_contact=False,                                # no head contact: 4 points
    neck_shear=(t, plateau(-600.0, 20.0, 40.0)),
    neck_tension=(t, plateau(1800.0, 20.0, 45.0)),
    neck_extension=15.0,
    chest_compression=24.0, viscous_criterion=0.35,
    femur=((t, plateau(-3000.0, 30.0, 36.0)), (t, plateau(-2800.0, 30.0, 36.0))),
    knee_displacement=(2.0, 2.5),
    tibia_index=(0.45, 0.41), tibia_force=(1900.0, 2100.0),
)
frontal = score_frontal(driver, passenger)
print(f"Frontal: {frontal.points:.3f} / 16")
for group, pts in frontal.groups.items():
    print(f"  {group:18s} {pts:.3f} ({colour(pts)})")
for occupant, regions in frontal.regions.items():
    print(f"  {occupant}: " + ", ".join(
        f"{name} {r.points:.2f} [{r.governing}]" for name, r in regions.items()))

# --- 3. Side test (ES-2) ------------------------------------------------------
side = score_side(SideOccupant(
    hic15=310.0, head_a3ms=48.0, rib_deflection=26.0, rib_vc=0.40,
    abdominal_force=1250.0, pubic_force=2600.0,
    modifiers={"chest": backplate_modifier(1600.0) + t12_modifier(1400.0, 120.0)},
))
print(f"Side   : {side.points:.3f} / 16 " +
      str({k: round(v, 3) for k, v in side.groups.items()}))

# --- 4. Pole test and star rating ----------------------------------------------
pole_ok = pole_test_passed(hic15=420.0, head_peak=61.0, head_contact=False,
                           rib_deflection=31.0, rib_vc=0.55, abdominal_force=1700.0,
                           pubic_force=3900.0)
print(f"Pole test passed: {pole_ok}")
rating = aop_rating(frontal, side, max_stars_allowed=5 if pole_ok else 2)
print(f"Adult occupant: {rating.points:.3f} / 32 points -> {rating.stars} stars "
      f"{'(' + '; '.join(rating.reasons) + ')' if rating.reasons else ''}")

# --- 5. Child occupant points to stars -----------------------------------------
print(f"Child occupant: 38.5 / 49 points -> {cop_stars(38.5)} stars")
