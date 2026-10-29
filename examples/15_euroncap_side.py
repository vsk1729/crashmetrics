"""Example 15: Euro NCAP 2026 side impact, AE-MDB, pole and far side (35 points).

Synthetic results. WorldSID head criteria come from the head
acceleration signal; rib compressions are the largest of the measured
ribs; far side zones come from the measured head excursion.
"""

import numpy as np

from crashmetrics.acceleration import clip_3ms
from crashmetrics.pedestrian import calculate_hic
from crashmetrics.side_scoring import (
    FarSideCase,
    SideOccupant,
    far_side_zone,
    score_ae_mdb,
    score_far_side,
    score_pole,
    score_side,
)

t = np.arange(0.0, 0.12, 1e-4)                            # s


def bump(peak, start, width):
    phase = (t - start) / width
    return np.where((phase > 0) & (phase < 1), peak * np.sin(np.pi * phase), 0.0)


def worldsid(head_g, hard_contact, ribs_chest, ribs_abdomen, pubic, **extra):
    """WorldSID occupant from a head pulse and per-rib peak compressions."""
    head = bump(head_g, 0.03, 0.02)
    values = {
        "hic15": calculate_hic(t, head, window_ms=15.0).value,
        "head_a3ms": clip_3ms(t, head),
        "chest_compression": max(ribs_chest),              # worst thorax rib
        "abdomen_compression": max(ribs_abdomen),           # worst abdomen rib
        "pubic_force": pubic,
        **extra,
    }
    return SideOccupant(values, hard_contact=hard_contact)


def child(head_g, neck_n, chest_g):
    return SideOccupant({"hic15": 0.0, "head_a3ms": head_g, "neck_tension": neck_n,
                         "chest_a3ms": chest_g}, hard_contact=False)


def assess(label, mdb_driver, pole_driver, far_side_main, far_side_robust,
           door_openings=0):
    mdb = score_ae_mdb(mdb_driver, rear_q10=child(48, 1650, 52),
                       rear_q6=child(44, 1500, 47), door_openings=door_openings)
    pole = score_pole(pole_driver)
    driver_points = mdb.occupants["driver"].points + pole.occupants["driver"].points
    far = score_far_side(
        FarSideCase(far_side_zone(*far_side_main[0]), far_side_main[1]),
        FarSideCase(far_side_zone(*far_side_main[2]), far_side_main[3]),
        robustness_ae_mdb=far_side_robust[0], robustness_pole=far_side_robust[1],
        countermeasure=True, occupant_to_occupant_passed=True,
        near_side_driver_points=driver_points,
    )
    result = score_side(mdb, pole, far)
    print(f"--- {label}")
    print(result.summary())
    print()
    return result


# Head excursion: (clearance to the struck-side seat centreline, red line
# offset) in mm; red line 210 mm outboard of the seat centreline.
main = ((265.0, 210.0), {"chest_compression": 31.0, "lumbar_mx": 85.0},
        (170.0, 210.0), {"chest_compression": 36.0, "upper_neck_tension": 2100.0})
robust = (["green", "yellow", "yellow", "orange"], ["yellow", "orange"])

good = assess(
    "Variant A: centre airbag, stiff B-pillar",
    worldsid(58.0, False, [24.0, 27.5, 26.0], [38.0, 41.5], 1450.0,
             shoulder_force=1900.0, chest_vc=0.31, abdomen_vc=0.28),
    worldsid(76.0, True, [31.0, 34.5, 29.0], [44.0, 49.0], 1850.0,
             shoulder_force=2300.0, chest_vc=0.45, abdomen_vc=0.40),
    main, robust,
)
weak = assess(
    "Variant B: softer B-pillar, one door opened",
    worldsid(66.0, False, [33.0, 38.5, 35.0], [52.0, 55.5], 2150.0,
             shoulder_force=2600.0, chest_vc=0.52, abdomen_vc=0.47),
    worldsid(84.0, True, [41.0, 46.0, 39.0], [57.0, 60.0], 2400.0,
             shoulder_force=3050.0, chest_vc=0.71, abdomen_vc=0.55),
    main, robust, door_openings=1,
)
print(f"Variant A {good.points:.3f} / 35, variant B {weak.points:.3f} / 35 "
      f"(far side {weak.far_side.points:g}: {', '.join(weak.far_side.disqualified)})")
