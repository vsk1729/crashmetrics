"""Example 33: model quality check sheet of a crash run.

Before reading injury values or intrusions, check the run itself. Two
runs of the same synthetic frontal crash (crashmetrics.synthetic writes
d3hsp, glstat, matsum and sleout in the LS-DYNA layout; point
check_model at your own run folder instead): a well prepared model and
a poorly prepared one, and a run that stopped with an error.

1. The sheet of the good model, against target mass and centre of gravity.
2. The poor model: what fails and why.
3. Both side by side.
4. A run that terminated with an error, and your own limits.
"""

from dataclasses import replace

from crashmetrics.energy_check import EnergyLimits
from crashmetrics.quality import QualityLimits, check_model, quality_matrix
from crashmetrics.synthetic import ModelQuality, frontal_model, simulate

for variant in ("baseline", "poor_model_quality"):
    simulate(frontal_model(variant)).write(f"runs/{variant}")
target = {"target_mass": 1500.0, "target_cg": (1305.0, 0.0, 550.0)}   # kg, mm

# --- 1. A well prepared model ----------------------------------------------------
good = check_model("runs/baseline", **target)
print(good.summary())

# --- 2. A poorly prepared model --------------------------------------------------
poor = check_model("runs/poor_model_quality", **target)
print()
print(f"Model quality, {poor.run}: {poor.verdict()}")
for check in (*poor.failures, *poor.warnings):
    note = f" ({check.note})" if check.note else ""
    print(f"  {check.status} {check.name}: {check.value}, limit {check.limit}{note}")

# --- 3. Side by side -------------------------------------------------------------
print()
print(quality_matrix([good, poor]))

# --- 4. An error termination, and your own limits --------------------------------
stopped = replace(frontal_model(), name="stopped", quality=ModelQuality(
    error_at=38.0, mass_scaled=False, timestep_drop=0.25))
simulate(stopped).write("runs/stopped")
sheet = check_model("runs/stopped")
print()
for name in ("Termination", "End time reached", "Errors", "Time step"):
    check = sheet.check(name)
    print(f"{check.status} {name}: {check.value}"
          + (f" ({check.note})" if check.note else ""))
limits = QualityLimits(added_mass=3.0, mass_tolerance=0.5,
                       energy=EnergyLimits(hourglass=0.05, part_hourglass=0.03))
strict = check_model("runs/baseline", limits=limits, **target)
print(f"Baseline with stricter limits: {strict.verdict()}: "
      + "; ".join(f"{c.name} {c.value} (limit {c.limit})" for c in strict.failures))
