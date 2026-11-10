# Model quality check sheet

Module: `crashmetrics.quality` (NumPy only). Synthetic runs to try it
come from `crashmetrics.synthetic`.

Before anyone reads injury values or intrusions from a crash run, the
run itself has to be trusted: did it finish, is the mass right, how
much mass did mass scaling add, is the energy balance sound, do the
contacts behave? Teams usually check this by hand in several files.
`check_model` does it in one pass and gives one sheet per run.

```python
from crashmetrics.quality import check_model

sheet = check_model("runs/loop12", target_mass=1500.0, target_cg=(1305, 0, 550))
print(sheet.summary())          # or sheet.table() for Markdown
sheet.passed, sheet.failures, sheet.warnings
```

It reads `d3hsp`, `glstat`, `matsum` and `sleout` from the run folder
(upper case or a job prefix such as `run1.glstat` also work). A missing
or unreadable file skips its checks; at least one file is needed.

## The checks

| Group | Check | Passes when | From |
| --- | --- | --- | --- |
| Run | Termination | Normal termination | d3hsp |
| Run | End time reached | Problem time ≥ 99.5 % of the termination time | d3hsp, glstat |
| Run | Errors | No error messages | d3hsp |
| Run | Warnings | Reported; advisory limit if you set one | d3hsp |
| Mass | Total mass | Within ± 1 % of `target_mass` | d3hsp |
| Mass | Centre of gravity | Within 10 mm of `target_cg` | d3hsp |
| Mass | Added mass, start | ≤ 5 % of the model mass | glstat |
| Mass | Added mass, peak | ≤ 5 % of the model mass | glstat |
| Mass | Added mass, growth | Advisory: ≤ 1 % point during the run | glstat |
| Mass | Added mass per part | ≤ 20 % of the part's mass | matsum, d3hsp |
| Time step | Time step | Advisory: falls ≤ 10 % below its first value | glstat |
| Time step | Mass scaling | Reported (`dt2ms`) | d3hsp |
| Time step | Smallest elements | Advisory: mass factor ≤ 4 | d3hsp, glstat |
| Energy | Energy ratio | 0.95 to 1.05 | glstat |
| Energy | Hourglass energy | ≤ 10 % of the internal energy | glstat |
| Energy | Negative contact energy | ≤ 5 % (total sliding energy) | glstat |
| Energy | Damping energy | ≤ 5 % | glstat |
| Energy | Hourglass energy per part | ≤ 10 % of the part's internal energy | matsum |
| Energy | Negative internal energy per part | ≤ 1 % | matsum |
| Contacts | Negative energy per contact | ≤ 1 % of the peak internal energy | sleout, glstat |

Each check has a status:

- `PASS` or `FAIL`: against its limit. A sheet passes when nothing fails.
- `WARN`: an advisory limit was passed; the sheet still passes.
- `INFO`: reported without a limit (no target given, or the limit set to
  `None`).
- `SKIP`: the file or value is missing; the note says which.

Values are in **kg, mm, ms and kJ** for any unit system
(`unit_system=`, default mm-ms-kg).

!!! warning "The limits are common practice, not a standard"
    The defaults are widely used rules of thumb. Set your team's values
    with `QualityLimits`. The energy checks are those of
    [LS-DYNA energy checks](lsdyna-energy.md) and take `EnergyLimits`.

```python
from crashmetrics.energy_check import EnergyLimits
from crashmetrics.quality import QualityLimits

limits = QualityLimits(added_mass=3.0, mass_tolerance=0.5, warnings=50,
                       contact_negative=None,                  # report only
                       energy=EnergyLimits(part_hourglass=0.05))
sheet = check_model("runs/loop12", limits=limits)
```

## What the checks mean

- **Added mass.** Mass scaling adds mass to elements whose time step is
  below the chosen one (`dt2ms`). The start value shows what the mesh
  needs; growth during the run means elements deform into smaller time
  steps. Too much added mass changes the crash energy.
- **Added mass per part** needs the per-part added mass in `matsum`
  (written when mass scaling is on) and the part masses in `d3hsp`.
- **Smallest elements.** The table of smallest time steps in `d3hsp`
  shows which elements control the run. With mass scaling, the mass
  factor is `(time step / element time step)²`: a factor of 20 means
  that element is 20 times heavier than meshed. The note lists the parts
  that fill the table, which is where to remesh.
- **Time step.** Without mass scaling the time step falls as elements
  deform; a large fall often comes just before an error termination.
- **Negative energy per contact.** Negative contact energy comes from
  initial penetrations or parts passing through each other. The energy
  group checks the total; this check names the contact.
- **Hourglass energy per part** names the parts whose elements deform in
  zero-energy modes; their absorbed energy is not reliable.

## Several runs side by side

```python
from crashmetrics.quality import quality_matrix

print(quality_matrix([check_model(f"runs/{name}") for name in runs]))
```

One row per check, one column per run, with the status and the number
behind it (percent, mm or factor). `values=False` gives the status only.

## From data already read

```python
from crashmetrics.quality import check_model_data

sheet = check_model_data("loop12", d3hsp=d, glstat=g, matsum=p, sleout=s,
                         target_mass=1500.0)
```

Use this when the files have other names or the data comes from a
binout reader.

## Synthetic runs

`crashmetrics.synthetic` writes `d3hsp`, `glstat` and `sleout` next to
`matsum`, `secforc` and `swforc`. `ModelQuality` sets what the solver
would report (added mass, time step, contact energies, warnings,
termination) without changing the crash itself.

| Run | Set-up | The sheet should show |
| --- | --- | --- |
| `baseline` | 0.4 % added mass rising to 0.6 %, friction only in the contacts | Passed |
| `poor_model_quality` | 5.8 % added mass rising to 7.9 %, 16 % hourglass in the crash boxes, negative energy in the self contact, 0.21 µs elements | 4 failures, 2 warnings |
| `ModelQuality(error_at=38.0, ...)` | Stops at 38 ms with an error | Termination, end time and errors fail |

## Example

```python
--8<-- "examples/33_model_quality.py"
```

Output:

```text
--8<-- "examples/expected/33_model_quality.txt"
```

## Tested with

- **Synthetic runs**, whose faults are known.
- **Real LS-DYNA output (MIT licence, in the repository):** a drop test
  (`glstat`, `matsum`) and its trimmed `d3hsp`, including the mass
  centre.
- **Real run folders checked locally** (no licence or not MIT, so not
  included): a ball drop with all files; a bolted joint whose energy
  ratio grows with external work; a quasi-static crimping run with very
  heavy mass scaling; a run whose `glstat` has one state (reported as
  unreadable, its checks skipped).
