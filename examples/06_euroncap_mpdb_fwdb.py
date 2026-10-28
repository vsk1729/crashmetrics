"""Example 6: Euro NCAP 2026 frontal scoring, MPDB (20 points) and full width (10).

Each occupant gives its peak values (worst of left and right), whether
the head had hard contact, and any modifiers. Values in N, N m, mm, g, m/s.
"""

from crashmetrics.frontal_scoring import (
    FULL_SCALE_MODIFIERS,
    OCCUPANT_MODIFIERS,
    Occupant,
    compatibility_penalty,
    damage_modifier,
    score_fwdb,
    score_mpdb,
)


def show(name, test):
    print(f"{name}: {test.points:.3f} / {test.max_points:g} points "
          f"(occupants {test.occupant_points:.3f}, full-scale -"
          f"{test.full_scale_deduction:.3f}, "
          f"compatibility -{test.compatibility_penalty:.3f})")
    for position, dummy in test.occupants.items():
        regions = ", ".join(f"{r.name} {r.points:.2f} ({r.band}, {r.governing})"
                            for r in dummy.regions.values())
        print(f"  {position:15s} {dummy.dummy:10s} "
              f"{dummy.points:.2f}/{dummy.max_points:g}: {regions}")


# --- MPDB: THOR driver, Hybrid III 5th passenger, Q6 and Q10 rear -------------
thor_driver = Occupant(
    values={"head_peak": 62.0,                       # no hard contact (<= 80 g)
            "neck_shear": 1500.0, "neck_tension": 2800.0, "neck_extension": 30.0,
            "chest_compression": 50.0,               # Rmax
            "abdomen_compression": 70.0, "acetabulum_force": 3000.0,
            "femur_force": 4000.0, "knee_displacement": 5.0,
            "tibia_index": 0.3, "tibia_force": 1500.0},
    modifiers={"head_neck": [damage_modifier(0.44)]},         # -20 %
)
h3_passenger = Occupant(
    values={"head_peak": 95.0, "hic15": 600.0, "head_a3ms": 70.0,
            "neck_shear": 1000.0, "neck_tension": 1500.0, "neck_extension": 30.0,
            "chest_compression": 20.0, "viscous_criterion": 0.4,
            "femur_force": 2000.0, "knee_displacement": 3.0,
            "tibia_index": 1.0, "tibia_force": 6000.0},
)
q6 = Occupant(values={"hic15": 1200.0, "head_a3ms": 65.0, "neck_tension": 1000.0,
                      "chest_compression": 35.0}, hard_contact=False)
q10 = Occupant(values={"hic15": 450.0, "head_a3ms": 50.0, "neck_tension": 2100.0,
                       "neck_extension": 20.0, "chest_compression": 40.0,
                       "chest_a3ms": 50.0}, hard_contact=True)

compat = compatibility_penalty(sd=119.0, olc=34.9, bottoming_out=False)
mpdb = score_mpdb(
    {"driver": thor_driver, "front_passenger": h3_passenger,
     "rear_q6": q6, "rear_q10": q10},
    full_scale_modifiers=[FULL_SCALE_MODIFIERS["a_pillar_100mm"]],   # 2.5 % of 10
    compatibility_penalty=compat,
)
show("MPDB", mpdb)

# --- Full width (35 km/h): Hybrid III 5th driver and rear, THOR passenger -----
belt_load = OCCUPANT_MODIFIERS["shoulder_belt_load"]          # ('chest_abdomen', 40.0)
fw_driver = Occupant(values={**h3_passenger.values, "chest_compression": 24.0},
                     modifiers={belt_load[0]: [belt_load[1]]})
thor_passenger = Occupant(values={**thor_driver.values, "chest_compression": 33.0})
rear = Occupant(values={"head_peak": 70.0, "neck_shear": 900.0, "neck_tension": 1800.0,
                        "neck_extension": 20.0, "chest_compression": 22.0,
                        "viscous_criterion": 0.3, "femur_force": 1500.0,
                        "knee_displacement": 2.0})
fw = score_fwdb({"driver": fw_driver, "front_passenger": thor_passenger,
                 "rear_passenger": rear})
show("Full width", fw)
print(f"Frontal offset + full width: {mpdb.points + fw.points:.3f} / 30 points")
