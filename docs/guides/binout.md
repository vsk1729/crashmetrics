# LS-DYNA binout

Module: `crashmetrics.binout` (NumPy only). Command: `crashmetrics-binout`.

Most crash runs write their time histories (glstat, matsum, nodout,
secforc, rcforc, sleout, swforc ...) to binary `binout` files rather
than to ASCII files. `read_binout` reads them and gives every output as
the same object the ASCII readers return, so nothing else changes:

```python
from crashmetrics.binout import read_binout

bo = read_binout("runs/loop12")        # a run folder, a file or a list of files
print(bo.summary())                     # outputs, states, time range, entities

nodout = bo.output("nodout")            # AsciiOutput, as read_nodout gives
energies = bo.glstat()                  # GlobalEnergies, as read_glstat
parts = bo.matsum()                     # PartEnergies, as read_matsum
bo.read("nodout", "x_acceleration")     # one variable: (states, nodes)
bo.metadata("nodout")                   # IDs, legend, LS-DYNA version
bo.to_csv("csv")                        # one CSV per output
```

## Run folders with binout only

The functions that take a run folder look for the ASCII file first and
read it from the folder's binout files when it is missing:

| Function | Reads from binout |
| --- | --- |
| `lsdyna_ascii.read_run` | Every supported output without an ASCII file |
| `lsdyna.check_run` (energy checks) | glstat, matsum |
| `quality.check_model` (model quality sheet) | glstat, matsum, sleout (d3hsp stays text) |
| `loadpath.load_run` | matsum, secforc |
| `spotweld.load_welds` | swforc |

Anything that takes an `AsciiOutput` (for example
`pedestrian.clearance.head_impact`) takes `bo.output("nodout")`.

Files are found by name: `binout`, `binout0000`, `binout0001` ... (an
MPP run writes several, each with some of the outputs), also with a job
prefix such as `run1.binout0000`. They are read in name order.

## What you get

`bo.branches` lists the outputs by their folder in the file:
`glstat`, `matsum`, `nodout`, `rcforc`, `secforc`, `sleout`, `spcforc`,
`swforc`, `abstat`, `deforc`, `rbdout`, ..., and outputs with a kind
below them, such as `elout/shell`, `elout/beam`, `ncforc/slave_1`,
`jntforc/type0` or `bndout/velocity/nodes`.

`bo.output(name)` turns one into an `AsciiOutput`: times, entity IDs,
one `(states, entities)` array per channel, totals, titles from the
legend, the model title and the LS-DYNA version. The channel names are
the binout variable names, which the ASCII readers use too. A few
outputs need more than a name:

| Output | Done |
| --- | --- |
| rcforc | The `side` of each value gives `surfa_` (slave) or `surfb_` (master) channels, as in the ASCII file |
| sleout | `slave` and `master` become `surfa_energy` and `surfb_energy`; binout has master values only for two-sided contacts, so single-sided contacts get 0; the totals become `totals` |
| spcforc | Forces per node (a node in several constraint sets: added up, as in the ASCII file), resultants as `totals` |
| deforc | Rotational springs (`irot` in the metadata) get the ASCII names `x_moment` ... `resultant_moment` and `relative_rotation`; translational springs `change_in_length` for `displacement` |
| swforc | `failure_time` is 1e16 while a weld holds and a negative or zero value after it fails, so it is not a time: NaN, as in the ASCII file; the failure state comes from `failure` |
| jntforc | binout splits it by joint type (`jntforc/type0` ...); `output("jntforc")` combines them when their times agree |
| elout, ncforc, rbdout | Entity IDs are stored with each state and may change; values are placed by ID |
| Others | Variables with one value per entity are channels, with one value per state totals |

Variables with several values per entity (stresses at several
integration points in elout) are not turned into channels; read them
with `bo.read(name, variable)`.

When a run was restarted and an output goes back in time, the states
from the restart time on are replaced by the restarted ones, as for the
ASCII files. A binout whose run stopped while writing is read up to its
last complete record; `bo.notes` says so.

## Checking a file

`bo.verify()` compares each file's symbol tables (the file's own index
of every variable) with the records themselves and lists any
difference. It is empty for a sound file. The reader itself does not
need the symbol tables, so a file whose index was never written (a run
that was killed) still reads.

## The file layout

The reader was written from the file layout itself, worked out from
public binout files. Their bytes were checked against the ASCII files
the same runs wrote. No code or documentation of other binout readers
was used.

- **Header**: 8 bytes: the header length; the sizes of the record
  length field (8 bytes), of file offsets (8), of the command (1) and
  of the type code (1); a byte-order flag (1: little-endian).
- **Records**: `[length][command][payload]`, the length counting its
  own field. Command 2 changes the directory (absolute, or relative to
  the current one); 3 stores a variable as `[type][name length][name]
  [values]`; 7 holds the offset of the first symbol table; 5 is a
  symbol table (per directory, each variable's name, type, offset and
  number of values), ending with the offset of the next table (0 for
  the last).
- **Type codes**: 1 text; 3 and 4 integers of 4 and 8 bytes; 9 and 10
  floats of 4 and 8 bytes (single and double precision runs).
- **Folders**: one per output (`/nodout`) or per output and kind
  (`/elout/shell`), each with a `metadata` folder and one folder per
  output state (`d000001` ..., or `d1` ... in some outputs), some with a
  `misc` sub-folder.

`write_binout` writes this layout (one symbol table at the end). It is
used for the tests and the synthetic runs (`simulate(...).write(folder,
binout=True)`); whether LS-PrePost or other tools read its files has not
been checked.

## Example

```python
--8<-- "examples/36_binout.py"
```

Output:

```text
--8<-- "examples/expected/36_binout.txt"
```

## Tested with

- **The plate run's binout (LS-DYNA R14, MIT licence, in the
  repository)**, whose ASCII rcforc, spcforc, glstat and matsum the same
  run wrote. rcforc and the glstat and matsum values are equal, as are
  the entity order and contact and part titles. The spcforc forces agree
  to the 5 digits ASCII prints. Its symbol tables agree with every
  record.
- **LS-DYNA's own binout to ASCII converter (l2a)**, run locally on
  four public binouts: the ASCII files it wrote and this reader give the
  same numbers to the printed digits for nodout (4 372 nodes, 21
  channels), glstat, matsum, rcforc, sleout, spcforc, swforc, deforc and
  abstat, with the same entities in the same order and the same titles.
  From the swforc of an MPP frontal crash (394 welds), the spot weld
  analysis finds the same 32 failed welds at the same times. Only the
  numbers were compared; the converter's code was not used. Where the
  two differ, binout has more: rcforc tie counts and areas, the weld
  length of constraint welds, and a third airbag (a control volume with
  materials) that the converter left out.
- **A whole run converted to binout** (the synthetic frontal crash):
  the energy ranking, section forces, spot weld table, model quality
  sheet and energy checks are the same as from the ASCII files.
- **Synthetic files** for single precision, several files, restarts,
  sub-folders, IDs per state, files cut off while writing, and invalid
  files.
- **Checked locally, not included** (too large, or no licence to copy
  them): an 81 MB 2D impact (LS-DYNA R11, single precision; MIT): node
  coordinates equal the initial coordinates plus the displacements to
  1e-7, the glstat total equals the sum of its parts, and the matsum
  part energies add up to the glstat internal energy. An MPP bolt run
  (R12, four files, 1000 states, ten outputs) and an MPP frontal crash
  (R9.3.1, six files: swforc with 394 welds, jntforc, deforc, abstat)
  were checked in the same way. Every file's symbol tables agree with
  its records.

See the [protocol notes](../protocol-notes.md#ls-dyna-binout) for the
interpretations.
