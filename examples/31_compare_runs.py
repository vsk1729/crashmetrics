"""Example 31: compare crash runs and find the culprit part.

Three runs of the same frontal crash (synthetic, crashmetrics.synthetic):
the baseline, a variant with a thinner LH front rail, and one without
the lower load path. Point load_run at your own run folders instead.

1. Thinner LH front rail: which parts changed, and the crush sequence.
2. No lower load path: where its load went (load split, rear rails).
3. All runs side by side (energy matrix, CSV).
4. A Markdown report of one run against the baseline.
"""

from crashmetrics.loadpath import (
    compare_runs,
    crush_sequence,
    energy_matrix,
    load_run,
    load_split,
    loadpath_report,
    section_forces,
)
from crashmetrics.synthetic import VARIANTS, frontal_model, simulate

runs = {}
for variant in VARIANTS:
    simulate(frontal_model(variant)).write(f"runs/{variant}")
    runs[variant] = load_run(f"runs/{variant}")
base = runs["baseline"]
groups = {"crash boxes": "Crash box*", "front rails": "Front rail*",
          "rear rails": "Rear rail*", "upper rails": "Upper rail*",
          "lower path": "Subframe*"}
chains = {f"main rail {s}": ["Bumper*", f"Crash box {s}", f"Front rail {s}",
                             f"Rear rail {s}"] for s in ("LH", "RH")}

# --- 1. Thinner LH front rail ----------------------------------------------------
weak = runs["weak_front_rail_lh"]
print(compare_runs(base, weak, exclude="Body*", groups=groups, cfc=60).summary(top=4))
print()
for check in crush_sequence(weak, chains):
    print(check.summary())

# --- 2. No lower load path -------------------------------------------------------
print()
nolower = runs["no_lower_path"]
print(compare_runs(base, nolower, exclude="Body*", groups=groups, cfc=60,
                   rate=False).summary(top=3))
paths = {"upper": "Upper rail*", "middle": "Front rail*",
         "lower": "Subframe extension*"}
print()
print(f"{'load split':20}" + "".join(f"{p:>9}" for p in paths))
for name, run in runs.items():
    have = {p: s for p, s in paths.items() if p != "lower" or name != "no_lower_path"}
    split = load_split(section_forces(run, cfc=60), have)
    share = dict(zip(split.paths, split.share))
    print(f"{name:20}" + "".join(
        f"{share[p]:8.1f}%" if p in share else f"{'-':>9}" for p in paths))

# --- 3. All runs side by side ----------------------------------------------------
print()
matrix = energy_matrix(list(runs.values()), exclude="Body*")
print("Absorbed energy, kJ (change against the baseline):")
print(matrix.table(top=8))
matrix.to_csv("energy_matrix.csv")                   # for Excel or a dashboard

# --- 4. Report -------------------------------------------------------------------
report = loadpath_report(weak, baseline=base, exclude="Body*", groups=groups,
                         paths=paths, chains=chains, top=5, cfc=60)
print()
print("\n".join(report.splitlines()[:9]))
print(f"... {len(report.splitlines())} lines of Markdown")
