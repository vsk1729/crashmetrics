# LS-DYNA energy checks

Modules: `crashmetrics.energy_check`, `crashmetrics.lsdyna`,
`crashmetrics.d3hsp`; command `crashmetrics-energy`.

A simulation result is only as good as its energy balance. These checks
work for any load case (frontal, side, pedestrian, component tests).
The other ASCII files (`nodout`, `rcforc`, `sleout`, `secforc`,
`rwforc`, `sbtout`, `abstat` ...) are read by the
[LS-DYNA ASCII output](lsdyna-ascii.md) readers.

## From the command line

Each run is a directory with `glstat` (and optionally `matsum`), or a
glstat file:

```bash
crashmetrics-energy run01 run02 run03
crashmetrics-energy run01 --hourglass 0.05 --added-mass 2 --ratio-min 0.9 --ratio-max 1.1
crashmetrics-energy run01 --hourglass off
```

The exit code is 0 if every run passes, 1 if a check fails and 2 if a
run could not be read, so it fits batch scripts and job queues.

## From Python

```python
from crashmetrics.energy_check import EnergyLimits, check_energies
from crashmetrics.lsdyna import check_run, read_d3hsp, read_glstat, read_matsum

report = check_run("run01", limits=EnergyLimits(hourglass=0.05))
print(report.summary())
report.passed, report.failures, report.failed_parts

# Step by step, or with energies from another source:
report = check_energies(read_glstat("run01/glstat"), read_matsum("run01/matsum"))
```

## The checks

| Check | Value | Default limit |
| --- | --- | --- |
| `energy_ratio` | total / (initial total + external work), min and max over the run | 0.95 to 1.05 |
| `hourglass` | peak hourglass / peak internal energy | ≤ 0.10 |
| `negative_contact` | most negative contact (sliding) energy / reference energy | ≤ 0.05 |
| `damping` | peak system damping energy / reference energy | ≤ 0.05 |
| `added_mass` | peak added mass, % of model mass | ≤ 5 % |
| `eroded_energy` | peak eroded energy / reference energy | reported only |
| `part_hourglass` | per part: peak hourglass / peak internal energy | ≤ 0.10 |
| `part_negative_internal` | per part: most negative / peak internal energy | ≤ 0.01 |

- The **reference energy** is the largest initial total energy plus
  external work, so impacts and prescribed-motion or quasi-static cases
  are both handled.
- Part checks cover parts with at least 1 % of the model's peak internal
  energy (`part_min_internal_share`); all parts are in `report.parts`.
- Hourglass, damping and rigidwall energies appear in the output only
  when `HGEN`, `RYLEN` and `RWEN` are 2 in `*CONTROL_ENERGY`; missing
  channels are reported as skipped, with a hint.
- The 10 % hourglass limit is LS-DYNA's rule of thumb; the other
  defaults are common rules of thumb. Use your company's guideline
  values in `EnergyLimits` or on the command line.

## Run information from d3hsp

```python
run = read_d3hsp("run01/d3hsp")
print(run.summary())
run.termination, run.warnings, run.errors
run.model, run.total_mass, run.min_timestep
run.parameters["time_step_scale_factor"], run.keyword_counts["*CONTACT_option"]
run.elapsed_seconds, run.memory
```

| Attribute | Content |
| --- | --- |
| `termination`, `termination_time` | `"normal"`, `"error"` or `"incomplete"` (no banner: still running or killed) |
| `version`, `parallel`, `precision`, `release`, `revision`, `platform`, `ncpu`, `command_line`, `input_file`, `run_date` | Run information |
| `messages`, `warnings`, `errors`, `message_counts()` | Warning and error messages with their text |
| `model` | Nodes, elements by type, materials, contacts |
| `parameters` | Every echoed `label..... value` setting |
| `keyword_counts` | Keywords in the deck |
| `part_masses`, `rigid_parts`, `total_mass` | Mass summary |
| `smallest_timesteps`, `min_timestep` | The 100 smallest time steps |
| `problem_time`, `problem_cycles`, `cpu_seconds`, `elapsed_seconds`, `workers`, `worker_type`, `timing`, `memory` | Timing and memory |

The readers find values by their labels, so the line order and the
optional channels of different LS-DYNA versions do not matter. They were
verified on real LS-DYNA R14.1 and R16.1 SMP output; MPP output is
accepted but has not been checked on real files yet.

For `binout` files, read the variables with a binout reader (such as
`lasso-python`) and pass them to `GlobalEnergies.from_mapping` and
`PartEnergies.from_mapping`.

## Complete example

The repository's small LS-DYNA R14.1 sample (from the MIT-licensed
K-agent project):

```python
--8<-- "examples/09_lsdyna_energy_check.py"
```

Output:

```text
--8<-- "examples/expected/09_lsdyna_energy_check.txt"
```
