# LS-DYNA ASCII output

Module: `crashmetrics.lsdyna_ascii` (also importable from
`crashmetrics.lsdyna`); command `crashmetrics-ascii`.

LS-DYNA writes its time-history output either to `binout` or, with
`*DATABASE_<NAME>` and `BINARY = 1` (the SMP default) or `3`, to ASCII files
named after the database: `nodout`, `rcforc`, `sleout` and so on. These
readers turn the ASCII files into NumPy arrays for the injury criteria,
scoring and feature functions in this package.

## Supported files

| File | Content | Entities | Channels |
| --- | --- | --- | --- |
| `nodout` | Nodal motion (`*DATABASE_HISTORY_NODE`) | Nodes | `x_displacement` ... `z_coordinate`, `x_velocity`, `x_acceleration`, rotational `rx_displacement`, `rx_velocity`, `rx_acceleration` ... |
| `rcforc` | Contact resultant forces | Contacts | `surfa_x_force` ... `surfa_mass`, `surfa_x_moment` ..., the same for `surfb_` |
| `sleout` | Contact (sliding interface) energies | Contacts | `surfa_energy`, `surfb_energy`, `friction_energy`; file totals in `totals` |
| `secforc` | Cross-section forces (`*DATABASE_CROSS_SECTION`) | Sections | `x_force` ... `total_force`, `x_moment` ... `total_moment`, `x_centroid` ..., `area` |
| `rwforc` | Rigid wall forces | Walls | `normal_force`, `x_force`, `y_force`, `z_force` |
| `sbtout` | Seatbelts | Belts, slip rings, retractors | `belt_force`, `belt_length`, `ring_slip`, `retractor_pull_out`, `retractor_force` |
| `deforc` | Discrete elements (springs, dampers) | Elements | `x_force` ... `resultant_force`, `change_in_length`, `x_moment` ... `relative_rotation` |
| `jntforc` | Joints and joint stiffnesses | Joints | `x_force` ..., `resultant_force`, `resultant_moment`, `x_force_local` ..., stiffness output such as `phi_degrees`, `joint_energy` |
| `abstat` | Airbags and control volumes | Airbags | `volume`, `pressure`, `internal_energy`, `dm_dt_in`, `density`, `dm_dt_out`, `total_mass`, `gas_temp`, `surface_area`, `reaction`, `dm_dt_outp`, `dm_dt_outv` |
| `rbdout` | Rigid body motion | Rigid bodies | `global_x` ..., `global_dx` ... `global_rdz`, `global_vx` ..., `global_ax` ..., the same with `local_`, `dircos_11` ... `dircos_33` |
| `spcforc` | Constraint (SPC) reactions | Nodes | `x_force` ... `z_moment`; resultants in `totals` |
| `swforc` | Spotwelds and constrained welds | Weld element or constraint IDs | `axial`, `shear`, `failure`, `length`, `resultant_moment`, `torsion`, `failure_time` |

The channel names are the binout variable names, so code written for
binout data (for example read with lasso-python) works with the same
names. The `glstat` and `matsum` readers are part of the
[energy checks](lsdyna-energy.md).

## Reading one file

```python
from crashmetrics.lsdyna import read_nodout, read_rcforc, read_secforc

nodout = read_nodout("run01/nodout")
print(nodout.summary())                       # title, version, states, entities, channels

t = nodout.time                               # (n,) in the model's time unit
az = nodout.channel("z_acceleration", 22626)  # (n,) for one node
all_az = nodout.channel("z_acceleration")     # (n, n_nodes); one node -> (n,)
a_res = nodout.magnitude(("x_acceleration", "y_acceleration", "z_acceleration"), 22626)
head = nodout.entity(22626)                   # {channel: (n,)}

big = read_nodout("run01/nodout", ids=[22626, 22627])   # read only these nodes
```

`AsciiOutput` holds:

| Attribute | Content |
| --- | --- |
| `kind` | File type, e.g. `"nodout"` |
| `time`, `cycle` | Output times (and cycles where the file gives them) |
| `ids` | Entity IDs in file order |
| `data` | Channel name → array `(n_times, n_entities)`; NaN where an entity has no value |
| `totals` | File-level sums printed by LS-DYNA (`sleout`, `spcforc`) |
| `names` | Entity titles from the `{BEGIN LEGEND}` block |
| `title`, `version` | Model title and LS-DYNA version line |

Methods: `channel(name, id)`, `entity(id)`, `magnitude(channels, id)`,
`name(id)`, `summary()` and `to_csv(path, channels=None, ids=None)`
(a wide table, columns `channel[id]`).

!!! note "Units"
    Values are in the model's units. For an mm, ms, kg, kN model
    (dummy and most vehicle models), acceleration in mm/ms² × 1000 is
    m/s², force is in kN, moment in kN·mm (= N·m) and angular velocity
    in rad/ms. Convert before calling the injury criteria, which work
    in SI units and g.

### Contact sides

`rcforc` and `sleout` call the two contact sides `slave` / `master` in
older LS-DYNA versions and `SURFA` / `SURFB` from R13 on. Both are read
as `surfa_*` (slave) and `surfb_*` (master). Single-surface contacts
have no resultants in `rcforc` and do not appear as entities there.

## A whole run directory

```python
from crashmetrics.lsdyna import read_run

run = read_run("run01")                         # {"nodout": ..., "rcforc": ..., ...}
wall = run["rwforc"].channel("normal_force", 1)
belt = run["sbtout"].channel("belt_force", 1)
```

Files are found by name (`nodout`, `NODOUT`, or with a job-ID prefix
such as `run1.nodout`). Requested databases without any output state are
left out; `skip_errors=True` leaves out unreadable files instead of
raising. A file with any other name is read with `read_ascii(path)`,
which recognises the type from its content.

## Command line

```bash
crashmetrics-ascii run01                     # summary of every ASCII file in run01
crashmetrics-ascii run01 run02 --csv tables  # also write run01_nodout.csv, ...
crashmetrics-ascii results/contact.txt --kind rcforc
```

The exit code is 0 when everything was read and 2 when a file or
directory could not be read.

## Complete example

The real LS-DYNA R16 output of a helmeted Hybrid III head: HIC and BrIC
from the head centre of gravity node in `nodout`, the upper neck load
from `secforc`, and a run directory with `rcforc` and `spcforc`:

```python
--8<-- "examples/18_lsdyna_ascii.py"
```

Output:

```text
--8<-- "examples/expected/18_lsdyna_ascii.txt"
```

## How the files are read, and what was checked

- Values are found by their labels and the column headers of the file,
  not by fixed positions, so extra lines and columns from newer LS-DYNA
  versions are skipped rather than misread.
- Numbers that touch each other (`0.00000E+00-3.12000E+00`), Fortran
  exponents without the `E` (`1.00000-100`) and overflow fields
  (`*****`, read as NaN) are handled.
- If a run was restarted and the file goes back in time, the states from
  the restart time on are replaced by the restarted ones.
- MPP and SMP files have the same layout and are read the same way.

The readers were checked on real LS-DYNA output from public projects:
native ASCII files from LS-DYNA R13, R14 and R16 (SMP), and MPP binout
files from 2013 to 2021 converted to ASCII with LS-DYNA's l2a tool (see
`tests/data/lsdyna/README.md`):

| File | Checked against |
| --- | --- |
| `nodout`, `secforc` | 36 runs of a helmet study: HIC, BrIC and neck moment recomputed from the arrays read here equal the study's own results to 1e-15 |
| `nodout`, `rcforc`, `sleout`, `secforc`, `spcforc`, `swforc`, `abstat`, `deforc` | Every value of 21 real files (up to 270 000 values each) compared with a second, independent parser: no difference |
| `sleout`, `spcforc` | Sum over contacts or nodes against LS-DYNA's printed totals (force transducer contacts are not in the `sleout` totals) |
| `rwforc`, `sbtout`, `jntforc`, `rbdout` | The layout written by l2a only; no public real file with data was found |

If one of your files is not read correctly, please open an issue with a
short excerpt.

Not covered yet: `elout`, `ncforc`, `nodfor`, `bndout`, `gceout`,
`sphout`, `dbfsi` and `binout` itself.
