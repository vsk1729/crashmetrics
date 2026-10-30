"""Example 20: design of experiments, margins as targets, sensitivity.

A driver restraint study with three design variables: airbag vent
diameter, belt load limiter level and knee bolster stiffness. The
"simulation" is a made-up response model standing in for LS-DYNA runs
(replace `simulate` with reading your runs' results).

1. A Latin hypercube DOE of 30 runs, with LS-DYNA *PARAMETER cards.
2. Each run scored with Euro NCAP 2026 limits; the distance to the
   limits (continuous) next to the points (stepped) as ML targets.
3. Which variable drives which criterion: PRCC / Spearman / SRC on the
   DOE, and Morris screening.
"""

from crashmetrics.doe import latin_hypercube, lsdyna_parameters, morris_design
from crashmetrics.frontal_scoring import Occupant, score_dummy
from crashmetrics.margins import euroncap_margins, margin_features
from crashmetrics.sensitivity import morris_effects, rank_sensitivity

BOUNDS = {"vent": (25.0, 45.0),          # airbag vent diameter, mm
          "limiter": (3.0, 5.5),         # belt load limiter, kN
          "knee_k": (80.0, 200.0)}       # knee bolster stiffness, N/mm


def simulate(vent, limiter, knee_k):
    """Made-up Hybrid III 50th driver response (50 km/h) to the design."""
    hic15 = 330 + 9.0 * (vent - 35) ** 2 / 10 + 25 * (limiter - 4)
    chest = 22 + 4.2 * (limiter - 3) + 0.10 * (vent - 25)                 # mm
    femur = 2200 + 22 * (knee_k - 80) + 150 * (5.5 - limiter)              # N
    neck_tension = 1500 + 18 * (45 - vent) + 120 * (limiter - 3)           # N
    return {"hic15": hic15, "head_a3ms": 45 + 0.03 * hic15,
            "neck_shear": 900.0, "neck_tension": neck_tension,
            "neck_extension": 25.0, "chest_compression": chest,
            "viscous_criterion": 0.25 + 0.012 * chest, "femur_force": femur,
            "knee_displacement": 4.0, "tibia_index": 0.5, "tibia_force": 2200.0}


# --- 1. Latin hypercube design -------------------------------------------------
design = latin_hypercube(BOUNDS, n=30, seed=7)
print(f"{design.method}: {len(design)} runs of {', '.join(design.names)}")
first = design.rows()[0]
print(lsdyna_parameters({k: round(first[k], 3) for k in design.names},
                        title=str(first["run"])))

# --- 2. Results, points and margins per run -------------------------------------
rows = []
for run in design.rows():
    values = simulate(run["vent"], run["limiter"], run["knee_k"])
    score = score_dummy("hybrid3_50", Occupant(values, hard_contact=True),
                        {"head_neck": 1.25, "chest_abdomen": 1.25,
                         "knee_femur_pelvis": 1.25, "lower_leg": 1.25})
    margins = euroncap_margins("hybrid3_50", values, speed=50)
    rows.append({**run, "points": score.points,
                 **{k: values[k]
                    for k in ("hic15", "chest_compression", "femur_force")},
                 **margin_features(margins, fields=("position", "margin_lpl"))})

print("run     vent  limiter knee_k | HIC15 chest femur | chest position  points")
for r in rows[:6]:
    print(f"{r['run']}  {r['vent']:5.1f}  {r['limiter']:5.2f}  {r['knee_k']:5.0f}  | "
          f"{r['hic15']:5.0f} {r['chest_compression']:5.1f} {r['femur_force']:5.0f} | "
          f"{r['chest_compression.position']:+14.3f}  {r['points']:.2f}")
print("(position: 0 at the HPL, 1 at the LPL; points change in steps, the position"
      " does not)")

# --- 3. Sensitivity of each criterion to the design variables ---------------------
for output in ("hic15", "chest_compression", "femur_force"):
    print()
    print(rank_sensitivity(rows, design.names, output).summary())

# HIC has its minimum near a 35 mm vent: a strong but not monotonic effect,
# which rank measures miss. Morris screening shows it as a large mu* with a
# large sigma (non-linear).
morris = morris_design(BOUNDS, trajectories=12, levels=4, seed=3)
results = [simulate(*run) for run in morris.values]
for output in ("hic15", "chest_compression"):
    effects = morris_effects(morris, [r[output] for r in results])
    print(f"\nMorris screening of {output} ({len(morris)} runs): " + ", ".join(
        f"{e.name} mu* {e.mu_star:.1f} sigma {e.sigma:.1f}" for e in effects))
