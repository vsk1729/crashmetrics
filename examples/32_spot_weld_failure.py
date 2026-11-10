"""Example 32: spot weld failure in a frontal crash, and against a baseline.

Two runs of the synthetic frontal model (crashmetrics.synthetic, which
writes swforc in the LS-DYNA layout; point load_welds at your own run
folder instead): the baseline, and a variant whose LH front rail flange
welds have about a third of their strength.

1. Baseline: every weld against its limits; the critical welds.
2. Variant: which welds fail, when, in what order; bursts (unzipping).
3. Variant against baseline: new failures per group.
4. What the failed welds did to the structure (load path comparison).
"""

from crashmetrics.loadpath import compare_runs, load_run
from crashmetrics.spotweld import (
    WeldLimits,
    compare_welds,
    failure_history,
    groups_by_id,
    load_welds,
    weld_summary,
)
from crashmetrics.synthetic import frontal_model, simulate

for variant in ("baseline", "weak_welds_front_rail_lh"):
    simulate(frontal_model(variant)).write(f"runs/{variant}")
base = load_welds("runs/baseline")                    # reads runs/baseline/swforc
weak = load_welds("runs/weak_welds_front_rail_lh")

# swforc has no titles: name the welds by their numbering (here the part
# ID is the first three digits of the weld ID).
parts = {110: "Crash box LH", 111: "Crash box RH", 120: "Front rail LH",
         121: "Front rail RH", 130: "Rear rail LH", 131: "Rear rail RH",
         140: "Upper rail LH", 141: "Upper rail RH"}
groups = groups_by_id(base, 1000, parts)
# Design limits of the welds, kN (axial, shear), per group.
limits = {"default": WeldLimits(9.0, 12.0),
          "Front rail LH": WeldLimits(11.0, 14.0),
          "Front rail RH": WeldLimits(11.0, 14.0),
          "Rear rail LH": WeldLimits(9.0, 13.0), "Rear rail RH": WeldLimits(9.0, 13.0),
          "Upper rail LH": WeldLimits(4.5, 6.0), "Upper rail RH": WeldLimits(4.5, 6.0)}

# --- 1. Baseline: all welds hold; which are close? ------------------------------
print(weld_summary(base, limits=limits, groups=groups).table())

# --- 2. Variant: failures over time ---------------------------------------------
print()
summary = weld_summary(weak, limits=limits, groups=groups)
print(summary.table(top=6))
print()
history = failure_history(weak, groups=groups)
print(history.summary())
print("Failed welds over time: " + ", ".join(
    f"{ms} ms: {int(history.count[abs(history.time - ms).argmin()])}"
    for ms in (10, 20, 30, 35, 40, 50)))
first = summary.failed[0]
print(f"Weld {first.weld_id} failed at {first.utilisation * 100:.0f} % of its "
      "design load: look at the weld definition, not at the load")

# --- 3. Against the baseline ----------------------------------------------------
print()
print(compare_welds(base, weak, limits=limits, groups=groups).summary(top=3))

# --- 4. What it did to the structure --------------------------------------------
print()
comparison = compare_runs(load_run("runs/baseline"),
                          load_run("runs/weak_welds_front_rail_lh"),
                          exclude="Body*", rate=False)
print(comparison.summary(top=3))
