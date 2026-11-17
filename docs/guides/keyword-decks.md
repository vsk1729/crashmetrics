# LS-DYNA keyword decks: check before you run

Module: `crashmetrics.deck` (NumPy only). Command: `crashmetrics-deck`.

The other LS-DYNA modules read what a run wrote. This one reads the
deck before the run: every include file, every `*PARAMETER`, the parts,
sections, materials, contacts, controls and outputs. It answers the
questions a run should not be wasted on:

- Is every include file there, and is every referred ID defined?
- What do the parts weigh, where is the centre of gravity, what time
  step will the smallest elements give, how much mass would mass
  scaling add?
- Is the load case what I think it is: end time, impact speed, wall,
  contacts, energy settings?
- Will the run write what I need afterwards (glstat, matsum, secforc and
  cross sections, swforc, nodout at a high enough rate)?

It also edits a deck and writes it back with only the edited fields
changed, so it can make the variants of a design study.

```python
from crashmetrics import deck as dk

deck = dk.read_deck("model/main.k")
print(deck.info.summary())                      # files, version, unknown keywords
print(dk.model_summary(deck).table(top=20))     # parts, mass, centre of gravity
print(dk.check_deck(deck).summary())            # pass / warn / fail sheet
print(dk.load_case(deck).summary())             # what the run will do
print(dk.output_requirements(deck, ["quality", "load_paths", "nodes"]).summary())
```

From the command line (exit code 1 if a check fails, so it can stop a
batch script before a job is submitted):

```bash
crashmetrics-deck model/main.k --units mm-ms-kg --csv parts.csv
```

## 1. Reading

`read_deck` follows `*INCLUDE`, `*INCLUDE_PATH`, `*INCLUDE_PATH_RELATIVE`
and `*INCLUDE_TRANSFORM` (ID offsets, length scale and
`*DEFINE_TRANSFORMATION` moves, scales and rotations), in the order
LS-DYNA reads them. A missing or circular include is reported, not an
error, so a deck without its mesh can still be checked.

- **Formats:** fixed (10-character fields), long (`*KEYWORD LONG=Y` or
  `+` after a keyword, 20 characters), `%` (10-character IDs for large
  models) and comma separated; Fortran numbers such as `1.5+3`.
- **Parameters:** `*PARAMETER`, `*PARAMETER_LOCAL` (seen by the file and
  its includes), `*PARAMETER_EXPRESSION` (evaluated without `eval`:
  numbers, names, + - * / and ^, the usual functions) and
  `*PARAMETER_DUPLICATION`. `&name` and `-&name` are replaced where they
  are used.
- **Version:** `deck.info.version` is the tool that wrote the deck and
  its version (LS-PrePost, ANSA, HyperMesh, PRIMER), from the header
  comments; `deck.info.unknown` lists keywords without a layout here.
  These are kept and written back unchanged, never dropped.
- **Typed values:** `deck.records("SECTION_SHELL")` gives each card's
  values by name (`rec["t1"]`), with parameters applied and where each
  value is written, so it can be changed in place.

Bulk data has its own fast readers: `nodes`, `elements` (shell, solid,
thick shell, beam, discrete, seat belt, with option cards such as
`_THICKNESS`), `mass_elements`, `sets` (lists, `_GENERATE`, `_ADD`,
segments) and `curves` (with their scale factors and offsets).

### Keywords with a layout

| Group | Keywords |
| --- | --- |
| Parts | `*PART` (`_INERTIA`, `_CONTACT`, `_PRINT`), `*PART_COMPOSITE` |
| Sections | `*SECTION_SHELL`, `_SOLID`, `_TSHELL`, `_BEAM`, `_DISCRETE`, `_SEATBELT` |
| Materials | Every `*MAT_...` (ID, density; elastic constants of the common crash materials; `*MAT_024` / `*MAT_123` curves), `*MAT_ADD_...`, `*MAT_THERMAL_...`, `*EOS_...`, `*HOURGLASS` |
| Mesh | `*NODE`, `*ELEMENT_...`, `*ELEMENT_MASS...`, `*ELEMENT_INERTIA`, `*SET_...` |
| Contacts | `*CONTACT_...` with `_ID` / `_TITLE` and `_MPP` cards |
| Connections | `*CONSTRAINED_SPOTWELD`, `_NODAL_RIGID_BODY`, `_EXTRA_NODES`, `_RIGID_BODIES`, `_INTERPOLATION_SPOTWELD` |
| Load case | `*INITIAL_VELOCITY...`, `*RIGIDWALL_PLANAR...` and others, `*BOUNDARY_SPC`, `*BOUNDARY_PRESCRIBED_MOTION`, `*LOAD_BODY` |
| Controls | `*CONTROL_TERMINATION`, `_TIMESTEP`, `_ENERGY`, `_HOURGLASS`, `_SHELL`, `_SOLID`, `_CONTACT`, `_ACCURACY`, `_BULK_VISCOSITY`, `_OUTPUT`, `_UNITS`, `_IMPLICIT_GENERAL`, `_DYNAMIC_RELAXATION` |
| Outputs | `*DATABASE_` ASCII files (glstat, matsum, nodout, secforc, rcforc ...), `_BINARY_...`, `_HISTORY_...`, `_CROSS_SECTION_...` |
| Definitions | `*DEFINE_CURVE`, `_TABLE`, `_COORDINATE_...`, `_VECTOR`, `_BOX`, `_TRANSFORMATION` |

## 2. Model table and time step

`model_summary` gives every part with its element count, section,
element formulation, thickness, material, density, mass and centre of
gravity, and the total. Solid volumes are the ones the solver uses
(one-point for under-integrated formulations, so a coarse sphere weighs
what it weighs in the run, not what the true sphere would). Lumped masses, `*ELEMENT_MASS_PART` and
`*ELEMENT_INERTIA` are included; `*PART_INERTIA` replaces a rigid
part's mass and centre with the given ones. The unit system is taken
from `*CONTROL_UNITS` or guessed from the material densities and
moduli; give `unit_system=` to be sure.

`time_steps` estimates every element's time step the way the solver
does for shells and solids (characteristic length over sound speed,
times TSSFAC) and, with negative `DT2MS`, the mass that mass scaling
would add. Rigid parts and materials whose elastic constants are not
read here are counted as not estimated.

## 3. Checks

`check_deck` gives one sheet:

| Group | Check | Fails when |
| --- | --- | --- |
| Reading | Include files, parameters | A file or a parameter is missing (other reading notes warn) |
| IDs | Duplicate IDs | The same part, section, material, curve, set, node or element ID is defined twice, also across include files and after include offsets |
| References | Missing sections, materials, curves, sets ... | A card refers to an ID that is not defined |
| Model | Parts without elements | Warns |
| Model | Shell thickness, density | A shell part has no thickness, or a part has no density |
| Model | Degenerate elements | A shell has zero area or a solid zero or negative volume |
| Model | Free nodes | Info only |
| Contacts | Contacts, parts in a contact | Warns without any contact, and for deformable parts in no part or part-set contact (info only when other contacts use segment or node sets) |
| Contacts | Spot welds | Warns when weld elements (`*MAT_100` parts) have no tied or spot weld contact |
| Time step | Smallest step, mass scaling | Info; mass scaling warns above 5 % added mass (`mass_scaling_limit=`) |
| Unused | Sections, materials, curves, sets | Info only |

## 4. Load case and outputs

`load_case` lists what the run will do: end time, time step control,
energy flags, initial velocities (with km/h when the units are known),
walls, prescribed motions, gravity, contacts and outputs.

`output_requirements(deck, analyses)` checks the outputs against what
crashmetrics' own analyses read afterwards:

| Analysis | Needs |
| --- | --- |
| `quality` (model quality sheet) | glstat, matsum, sleout when there are contacts, `*CONTROL_ENERGY` with HGEN, SLNTEN (and RWEN with walls) 2 |
| `load_paths` | matsum, secforc and at least one cross section |
| `spot_welds` | swforc |
| `nodes` (HIC, intrusion, clearance) | nodout, history nodes, and an interval of at most 1 / (10 × CFC): 0.1 ms for CFC 1000 |
| `contacts` | rcforc |
| `walls` | rwforc |

An output written only to binout (`BINARY 2`) warns, since the ASCII
readers need the ASCII file or a converted binout.

## 5. Editing and design variants

Edits change only the fields they name, in the field's own format, and
keep every comment and every other line:

```python
dk.set_parameter(deck, "t_rail", 1.6)              # a *PARAMETER
dk.set_thickness(deck, 2001, 1.8, shared="copy")    # own section for this part
dk.set_material(deck, 2001, 12)
dk.set_end_time(deck, 120.0)
dk.set_initial_velocity(deck, speed=15.56)         # same direction
dk.prepare_outputs(deck, ["quality", "nodes"], dt=0.1, node_dt=0.01)
deck.write("loop13", only_modified=True)
```

A value given by a parameter cannot be changed in place (the error says
which parameter to change instead). A section shared by several parts
is not changed silently: `shared="all"` changes it for all of them,
`shared="copy"` gives the part its own copy.

`write_variants` writes one deck per row of a design from
`crashmetrics.doe` (or any names and rows), each read fresh from the
original files, with a `design.csv`:

```python
from crashmetrics.doe import latin_hypercube

design = latin_hypercube({"t_rail": (1.2, 2.0), "speed": (12.0, 16.0)}, 30)
dk.write_variants("model/main.k", design, "doe",
                  setters={"speed": lambda d, v: dk.set_initial_velocity(d, speed=v)})
```

## Example

```python
--8<-- "examples/35_keyword_deck.py"
```

Output:

```text
--8<-- "examples/expected/35_keyword_deck.txt"
```

## Tested with

- **Real decks (MIT licence, in the repository):** a ball dropped on a
  plate whose `d3hsp` from LS-DYNA R14.1.1 is also included: part
  masses, the model's centre of gravity and the smallest time step are
  the same as the solver printed; a tube crushed against a rigid wall;
  a small deck with one deliberate fault; a thermal-mechanical deck
  written by LS-PrePost 2024/R2 with `*PARAMETER_DUPLICATION`, titled
  curves and two missing mesh includes.
- **Write-back:** the decks written back unchanged are byte for byte
  the same as the originals; after edits only the edited lines differ.
- **Synthetic decks** for long, `%` and comma formats, parameters,
  local parameters and expressions, include paths and transforms,
  duplicates and missing references, contacts with `_ID` and `_MPP`
  cards, shared sections and design variants.
- **Checked locally, not included:** the full thermal deck above
  (20 276 nodes, 15 390 solids) and a 765 kB 2D impact deck written by
  LS-PrePost 4.9.9.

The card layouts were written from the keyword file format itself; no
code or documentation of other keyword readers was used. See the
[protocol notes](../protocol-notes.md#ls-dyna-keyword-decks) for the
interpretations.
