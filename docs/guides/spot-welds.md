# Spot weld failure

Module: `crashmetrics.spotweld` (NumPy only). Synthetic runs with failing
welds come from `crashmetrics.synthetic`.

A load path only works while its connections hold. When a flange unzips,
the section opens and the part stops carrying load, so weld failure is
often the reason behind a part that "absorbed less energy". LS-DYNA
writes the force of every spot weld to **swforc**; this module answers:

1. Which welds failed, when, and in what order?
2. Did a line of welds unzip (many failures within a short time)?
3. Which welds hold but are close to their limit?
4. Against a baseline: which welds fail only now, or earlier?

| Step | Functions |
| --- | --- |
| Read swforc of a run folder | `load_welds`, `WeldRun` |
| Name the welds (swforc has no titles) | `groups_by_id`, or your own name → IDs |
| Failure criterion and utilisation | `WeldLimits` |
| Every weld: peak forces, forces before failure, utilisation | `weld_summary`, `WeldSummary.failed`, `.critical`, `.groups`, `.table` |
| Failures over time, sequence, first failure per group, bursts | `failure_history` |
| Baseline against variant | `compare_welds` |
| All of it as Markdown | `weld_report` |

Forces are in **kN** and times in **ms**, whatever the model units
(`unit_system=`, default mm-ms-kg).

## Reading a run

```python
from crashmetrics.spotweld import load_welds

run = load_welds("runs/baseline")                  # folder with swforc
run = load_welds("job12/job12.swforc", unit_system="mm-s-t")
run.failed                                         # IDs by failure time
run.axial, run.shear, run.failure_time             # (time, weld) kN; ms per weld
```

A weld counts as failed from the first state LS-DYNA prints `failure`
for it (or the printed `failure time`, if earlier). All connection
types in the file are read: spot weld beams and solids, constraint
welds, generalized welds.

## Naming the welds

swforc has no titles, so groups are given as name → weld IDs:

```python
groups = {"B-pillar flange": range(36094001, 36094031), "Sill": [4601, 4602, 4610]}

from crashmetrics.spotweld import groups_by_id
groups = groups_by_id(run, 1000, {120: "Front rail LH", 121: "Front rail RH"})
```

`groups_by_id` uses the numbering: welds with the same `ID // divisor`
form a group, named from your mapping or `"120xxx"`. A weld in several
groups counts in the first.

## Limits and utilisation

```python
from crashmetrics.spotweld import WeldLimits

limits = WeldLimits(axial=9.0, shear=12.0)                 # kN, all welds
limits = {"default": WeldLimits(9.0, 12.0),                # or per group
          "Front rail LH": WeldLimits(11.0, 14.0)}
```

```text
(axial / axial limit)^n + (shear / shear limit)^m ≥ 1      n = m = 2 by default
```

This is the force criterion of `*CONSTRAINED_SPOTWELD`. Only axial
tension counts (`compression=True` to count both).

**Utilisation** is the share of the failing load reached: 0.8 means both
forces could still grow by 25 % (1 / 0.8) before the criterion is met.
For n = m it is the failure function to the power 1/n; otherwise it is
solved numerically.

Without limits there is no utilisation, unless the file prints its own
failure measure between 0 and 1 (some weld materials), which is then
used.

!!! warning "Limits are yours"
    The limits are not in swforc. Take them from the weld card or the
    material data of your model. Welds with a stress- or damage-based
    failure (`*MAT_SPOTWELD` options) are still read and their failures
    found, but the force criterion here is then only a comparison.

## Every weld

```python
from crashmetrics.spotweld import weld_summary

summary = weld_summary(run, limits=limits, groups=groups)
print(summary.table())
summary.failed                 # failed welds, first failure first
summary.critical(0.8)          # hold, but at 80 % or more of their limit
summary.groups()               # welds, failed, first failure, highest utilisation
```

Each weld has its peak axial and shear force, the forces at the last
state before failure, its peak utilisation and when it occurred.

A weld that **failed well below its limit** (example 32: at 31 % of the
design load) points to the weld definition (strength, diameter, a wrong
card), not to the load.

## Failures over time

```python
from crashmetrics.spotweld import failure_history

history = failure_history(run, groups=groups)
print(history.summary())
history.count                  # failed welds at each time
history.sequence               # (ms, weld ID, group) in order
history.first                  # group -> (ms, weld ID) of its first failure
history.bursts                 # unzipping
```

A **burst** is 3 or more welds of one group (`burst_size=`), each
failing within 1 ms of the one before (`burst_window=`). Welds outside
every group are treated as one group.

## Comparing runs

```python
from crashmetrics.spotweld import compare_welds

comparison = compare_welds(baseline, variant, limits=limits, groups=groups)
print(comparison.summary())
comparison.new_failures        # fail only in the variant
comparison.recovered           # fail only in the baseline
comparison.earlier, comparison.later
comparison.increased           # hold in both, by utilisation increase
```

Welds are matched by ID. A failure counts as earlier or later when its
time moves by more than 0.5 ms (`time_tolerance=`). Welds in only one
run are listed in `notes`.

`weld_report(run, baseline=..., limits=..., groups=...)` gives the
summary, the failure history and the comparison as one Markdown page.

Pair this with [Load paths and energy](load-paths.md): `compare_runs`
shows which part lost energy, and `compare_welds` shows whether its
welds are the reason.

## Synthetic runs with welds

`crashmetrics.synthetic` puts lines of spot welds on the flanges of the
crash boxes, front rails, rear rails and upper rails (84 welds) and
writes `swforc` next to `matsum` and `secforc`:

- A line carries a share of its load path's force as shear, more on the
  welds at the front. As the part folds, each weld also gets a peel
  (axial) force.
- A weld fails at `(axial / Sn)² + (shear / Ss)² ≥ 1`. The welds left
  take part of its load, and the part loses strength as its welds fail.

| Variant | Welds | What the analysis should find |
| --- | --- | --- |
| `baseline` | All hold | Highest utilisation 85 % (first crash box welds) |
| `weak_welds_front_rail_lh` | LH front rail flange welds at about a third of their strength | All 14 fail, front to rear, from 14.5 ms; a burst of 8 at 39 ms; the LH front rail absorbs 3 kJ less |

## Example

```python
--8<-- "examples/32_spot_weld_failure.py"
```

Output:

```text
--8<-- "examples/expected/32_spot_weld_failure.txt"
```

## Tested with

- **Synthetic runs**, whose failure times are known: the file gives each
  failure at the first output state after the true time.
- **A real full-width frontal crash** from a public repository (no
  licence, so checked locally only and not included): 394 connections of
  three types, 32 failed; 30 of them at the same output state, reported
  as one burst.
- **A real bolted joint** (spot weld beam, R13; no licence, local only):
  one weld, no failure.
