# Load paths and energy across runs

Modules: `crashmetrics.loadpath` (analysis) and `crashmetrics.synthetic`
(a toy frontal crash that writes LS-DYNA-style output). NumPy only.

These are the questions after every crash run:

1. Which parts absorbed the energy, and when?
2. How was the load shared between the upper, middle and lower load
   paths?
3. Did the structure crush in the intended order (crash box before
   rail)?
4. Against the previous loop, which parts changed? That is, what is the
   culprit?

`crashmetrics.loadpath` answers them from the two files every crash run
writes: **matsum** (part energies) and **secforc** (section forces).

| Step | Functions |
| --- | --- |
| Read a run folder; pick parts and sections by ID or title | `load_run`, `select_parts`, `select_sections` |
| Energy per part and group, share, when it is absorbed | `energy_ranking`, `energy_history` |
| Section forces: one component, the main load positive, CFC filter | `section_forces` |
| Peak, mean force, impulse, loading time | `force_metrics` |
| Load split between paths, against a target | `load_split` |
| Crush sequence of chains of parts | `crush_sequence` |
| Baseline against variant: changes ranked, culprit parts, curve similarity | `compare_runs` |
| Many runs side by side; CSV | `energy_matrix` |
| All of it as Markdown | `loadpath_report` |

Results are in **kJ, kN and ms**, whatever the model units (`unit_system=`,
default mm-ms-kg).

## No data at hand? Use the synthetic frontal model

```python
from crashmetrics.synthetic import VARIANTS, frontal_model, simulate

simulate(frontal_model("baseline")).write("runs/baseline")   # matsum + secforc
```

`crashmetrics.synthetic` is a lumped full-width frontal crash against a
rigid wall at 56 km/h. It has 1500 kg on parallel load paths:

| Path (LH and RH) | Parts, front to rear | Mean force, kN |
| --- | --- | --- |
| Main rail | bumper beam (half), crash box, front rail, rear rail | 45, 95, 150, 230 |
| Upper | upper (shotgun) rail, after a 60 mm gap | 45 |
| Lower | subframe extension, subframe (half), after a 90 mm gap | 35, 80 |

A part crushes at its strength: an initial peak to start the first fold,
then folding waves around the mean force. In a chain the **weakest**
part crushes first, as in a real structure, so a rear part weaker than
the one in front of it gives a wrong crush sequence.

The result is a realistic run: 432 mm of crush, a 53 g peak, about
1.3 m/s rebound, and the energy balance closed within 0.2 %.

| Variant | What changes | What the analysis should find |
| --- | --- | --- |
| `baseline` | Reference car | Load split about 17 / 59 / 24 %; crush in order |
| `weak_front_rail_lh` | LH front rail 80 kN instead of 150 kN | The LH front rail crushes before the LH crash box; it absorbs 15 kJ less; the rear rails pick it up |
| `no_lower_path` | Subframe extensions and subframe removed | The middle path carries about 80 %; the rear rails crush (+17 kJ each) |
| `weak_welds_front_rail_lh` | LH front rail flange welds at about a third of their strength | The welds unzip and the rail absorbs 3 kJ less; see [Spot weld failure](spot-welds.md) |
| `poor_model_quality` | The same crash from a poorly prepared model (added mass, hourglass, contact energy) | See [Model quality check sheet](model-quality.md) |

The files are written in the LS-DYNA ASCII layout and say in their
header that they are synthetic. The model also has spot welds and writes
`swforc`, and it writes `glstat`, `sleout` and a short `d3hsp` for the
model quality checks. The `write_...` functions write any data in those
layouts. The model is for teaching and for testing
tools, not a vehicle simulation.

## Reading runs

```python
from crashmetrics.loadpath import load_run, select_parts

run = load_run("runs/baseline")                    # name = folder name
run = load_run("job12", unit_system="mm-s-t")      # files: matsum or job12.matsum
select_parts(run, "Crash box*")                    # [110, 111]
select_parts(run, [120, "Rear rail*"])             # IDs and title patterns
```

- `load_run` reads `matsum` and `secforc` (also `MATSUM` or a job
  prefix such as `run1.matsum`). Either may be missing, but not both.
- Titles come from the files' legend, so the `*PART` and
  `*DATABASE_CROSS_SECTION` titles in your model decide how easy the
  selection is.
- Patterns use `*` and `?`, case ignored.

| `unit_system` | Force | Energy | Time |
| --- | --- | --- | --- |
| `mm-ms-kg` (default) | kN | J (kN mm) | ms |
| `mm-s-t` | N | mJ (N mm) | s |
| `mm-s-kg` | mN | µJ | s |
| `m-s-kg` | N | J | s |

## 1. Energy absorption

```python
from crashmetrics.loadpath import energy_history, energy_ranking

groups = {"crash boxes": "Crash box*", "front rails": "Front rail*",
          "upper rails": "Upper rail*", "lower path": "Subframe*"}
ranking = energy_ranking(run, exclude="Body*", groups=groups)
print(ranking.table(top=8))
t, energy = energy_history(run, groups)            # kJ over time, for plots
```

- Absorbed energy is the matsum **internal energy** plus the internal
  energy of eroded elements (`include_eroded=True`), at the end of the
  run or at `time=`.
- Each row gives the share and cumulative share, the times at 10 / 50 /
  90 % of the part's energy (`onset=` sets the first), and the hourglass
  energy as a share of the part's energy.
- `exclude` the parts that only carry kinetic energy (the body, rigid
  barriers). `groups` are summed.

## 2. Section forces

```python
from crashmetrics.loadpath import force_metrics, section_forces

forces = section_forces(run, cfc=60)               # kN, main load positive
forces[13]                                         # one section over time
for m in force_metrics(forces):
    print(m.name, m.peak, m.mean, m.impulse)
```

- **Component:** `"auto"` (default) takes, per section, the axis with the
  largest impulse. `"x"`, `"y"`, `"z"` or `"total"` (magnitude) choose
  one.
- **Sign:** with `orientation="auto"`, sections whose force is mainly
  negative are reversed. So the main load is positive whatever way the
  section normal points; `forces.flipped` says which. Use `"as_written"`
  for the file's sign.
- **Filter:** `cfc=60` or `180` (SAE J211) before reading peaks. Unevenly
  spaced output (MPP) is resampled at its median time step first.
- `force_metrics`:
  - peak and its time;
  - impulse (integral of the positive force, kN ms = N s);
  - onset and end (first and last time above 10 % of the peak);
  - mean force (impulse over that time).

## 3. Load split

```python
from crashmetrics.loadpath import load_split

paths = {"upper": "Upper rail*", "middle": "Front rail*",
         "lower": "Subframe extension*"}
split = load_split(forces, paths, target={"upper": 20, "middle": 55, "lower": 25})
print(split.summary())
split.history                                      # % per path over time
```

The share of each path is its impulse over the summed impulse. `peak`
gives each path's peak force, and `history` the share at each time
(where the total force is above 5 % of its peak).

!!! warning "One cut per path"
    Give each path the sections that cut it **once**, for example the
    front rails LH and RH for the middle path. Sections in series along
    the same path (crash box, front rail, rear rail) carry the same load,
    so adding them counts it twice. A section given for two paths is
    reported.

`target` (path → %) is checked against `tolerance` percentage points
(default 5). Load split targets are design choices, not a protocol.

## 4. Crush sequence

```python
from crashmetrics.loadpath import crush_sequence

chains = {"main rail LH": ["Bumper*", "Crash box LH", "Front rail LH", "Rear rail LH"]}
for check in crush_sequence(run, chains):
    print(check.summary())
```

- A stage (one part, a pattern, or a list of parts summed) **starts**
  when it has absorbed 10 % of its final energy (`onset=`).
- **Violation:** a stage starts before the stage in front of it.
- **Warning:** a stage starts before the one in front has absorbed half
  of its energy (`overlap=`).
- **Not crushed:** stages absorbing less than 2 % of the chain's energy
  (`min_energy=`), such as rear rails taking only elastic load, are left
  out of the order check and listed as not crushed.

Energy is used rather than force because a stage that carries the load
without crushing (a stiff rear rail behind a crushing crash box) has a
high force but no energy.

## 5. Comparing runs

```python
from crashmetrics.loadpath import compare_runs, energy_matrix

comparison = compare_runs(baseline, variant, exclude="Body*", groups=groups, cfc=60)
print(comparison.summary())
comparison.culprits            # the parts that explain most of the change
matrix = energy_matrix([baseline, variant, other], exclude="Body*")
print(matrix.table(top=10))    # change against the first run in brackets
matrix.to_csv("energy.csv")
```

- **Matching:** parts and sections by ID. Parts or sections only in one
  run are listed in `notes`; a removed part counts as a change to zero.
- **Culprits:** the fewest parts, largest change first, that together
  explain 80 % (`explain=`) of the summed absolute energy change. The
  share is of all changes, so energy moving from one part to another
  shows on both.
- **Sections:** peak and impulse in both runs. With `rate=True`
  (default) each section also gets an ISO/TS 18571 rating of the variant
  curve against the baseline curve (1 means the same curve), which ranks
  which section's force history changed most.
- `loadpath_report(run, baseline=..., groups=..., paths=..., chains=...)`
  puts the ranking, split, sequence and comparison in one Markdown page.

## Examples

### One run

```python
--8<-- "examples/30_load_paths.py"
```

Output:

```text
--8<-- "examples/expected/30_load_paths.txt"
```

### Baseline against variants

```python
--8<-- "examples/31_compare_runs.py"
```

Output:

```text
--8<-- "examples/expected/31_compare_runs.txt"
```

The thinner LH rail is found as a culprit, its crush order is flagged,
and the energy it no longer absorbs shows up in both rear rails. Without
the lower path, the middle path's share goes from 59 % to 81 % and the
rear rails crush, which is where cabin intrusion would start.

## Tested with

- **Synthetic runs**, whose truth is known: every number above.
- **Real LS-DYNA output (MIT licence, in the repository):** two runs of
  a helmet study's neck section (secforc; the main load found on z, run
  1 against run 0 rated 0.91), and a drop test matsum in mm-ton-s.
- **A crush test of a hat section** found in a public repository
  (checked locally only; its licence is unclear, so it is not included):
  9 parts, 3201 states, the load on the y axis found and its sign
  reversed, unevenly spaced MPP output resampled before CFC 60 and 180.
