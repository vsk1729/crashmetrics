"""Example 30: load paths and energy absorption of one frontal crash run.

A full-width frontal run at 56 km/h (synthetic: the toy model of
crashmetrics.synthetic writes matsum and secforc in the LS-DYNA ASCII
format; point load_run at your own run folder instead):

1. Which parts absorbed the energy, and when.
2. Section forces: one component, the main load positive, CFC 60.
3. Load split between the upper, middle and lower load paths.
4. Crush sequence: bumper, crash box, front rail, rear rail, in order?
"""

from crashmetrics.loadpath import (
    crush_sequence,
    energy_history,
    energy_ranking,
    force_metrics,
    load_run,
    load_split,
    section_forces,
)
from crashmetrics.synthetic import frontal_model, simulate

# --- The run (replace with load_run("path/to/your/run")) -------------------------
simulate(frontal_model("baseline")).write("runs/baseline")
run = load_run("runs/baseline")                       # matsum + secforc, mm-ms-kg

# --- 1. Energy absorption --------------------------------------------------------
groups = {"bumper": "Bumper*", "crash boxes": "Crash box*",
          "front rails": "Front rail*", "rear rails": "Rear rail*",
          "upper rails": "Upper rail*", "lower path": "Subframe*"}
ranking = energy_ranking(run, exclude="Body*", groups=groups)
print(ranking.table(top=8))
print()
t, energy = energy_history(run, groups)
print("Energy absorbed by group over time (kJ):")
print(f"{'ms':>6}" + "".join(f"{g:>13}" for g in groups))
for ms in (5, 10, 20, 30, 40, 60):
    k = int(abs(t - ms).argmin())
    print(f"{ms:6d}" + "".join(f"{energy[g][k]:13.1f}" for g in groups))

# --- 2. Section forces -----------------------------------------------------------
forces = section_forces(run, cfc=60)
flipped = [forces.names[i] for i, f in zip(forces.ids, forces.flipped) if f]
print()
print(f"Section forces: component {set(forces.components)}, CFC 60; sign reversed "
      f"for {len(flipped)} of {len(forces.ids)} sections (their normals point "
      "forwards)")
print(f"{'section':24} {'peak kN':>8} {'at ms':>6} {'mean kN':>8} {'kN ms':>8} "
      f"{'from-to ms':>11}")
for m in force_metrics(forces):
    if m.name.endswith("LH"):
        print(f"{m.name:24} {m.peak:8.1f} {m.peak_time:6.1f} {m.mean:8.1f} "
              f"{m.impulse:8.0f} {m.onset:5.1f}-{m.end:4.1f}")

# --- 3. Load split ---------------------------------------------------------------
# One cut per path (LH + RH): sections in series along a path carry the
# same load and must not be added.
paths = {"upper": "Upper rail*", "middle": "Front rail*",
         "lower": "Subframe extension*"}
split = load_split(forces, paths, target={"upper": 20, "middle": 55, "lower": 25})
print()
print(split.summary())
k = int(abs(split.time - 35.0).argmin())
print("  at 35 ms: " + ", ".join(f"{p} {split.history[k, i]:.0f} %"
                                 for i, p in enumerate(split.paths)))

# --- 4. Crush sequence -----------------------------------------------------------
chains = {f"main rail {s}": ["Bumper*", f"Crash box {s}", f"Front rail {s}",
                             f"Rear rail {s}"] for s in ("LH", "RH")}
print()
for check in crush_sequence(run, chains):
    print(check.summary())
