"""Example 9: LS-DYNA energy balance checks and the d3hsp run summary.

Uses the small LS-DYNA R14.1 output in tests/data (from the MIT-licensed
K-agent project). Point `run` at your own run directory instead.

The same check is available on the command line:

    crashmetrics-energy run01 run02 --hourglass 0.05 --added-mass 2
"""

from pathlib import Path

from crashmetrics.energy_check import EnergyLimits, check_energies
from crashmetrics.lsdyna import check_run, read_d3hsp, read_glstat, read_matsum

data = Path(__file__).resolve().parents[1] / "tests" / "data" / "lsdyna" / "kagent"
run = data / "drop_e2e"                                  # contains glstat and matsum

# --- 1. One call for a run directory ---------------------------------------
report = check_run(run, limits=EnergyLimits(hourglass=0.05))
print(report.summary())
print()

# --- 2. Or step by step, with your own limits --------------------------------
glstat = read_glstat(run / "glstat")
matsum = read_matsum(run / "matsum")
print(f"glstat: {len(glstat.time)} states up to t = {glstat.time[-1]:.4g}; "
      f"matsum parts {[int(p) for p in matsum.part_ids]}")
strict = check_energies(glstat, matsum, EnergyLimits(energy_ratio=(0.98, 1.02),
                                                     hourglass=0.02))
for check in strict.checks:
    value = "-" if check.value is None else f"{check.value:.4g}"
    print(f"  {check.name:22s} {check.status:7s} value {value:8s} limit {check.limit}")
print(f"Passed: {strict.passed}")
print()

# --- 3. Run information from d3hsp -------------------------------------------
d3hsp = read_d3hsp(data / "cold_start" / "d3hsp_minimal")
print(d3hsp.summary())
