# LS-DYNA test data

Real LS-DYNA output and keyword decks used to test the readers in
`crashmetrics.lsdyna`, `crashmetrics.lsdyna_ascii`, `crashmetrics.d3hsp`
and `crashmetrics.deck`. Only files under the MIT licence are included,
each with its licence file.

## `kagent/`

From [LLK-LL/K-agent](https://github.com/LLK-LL/K-agent), commit
`ef4235c60f0e09619b3005346e5c6a0ec13653f4`, MIT licence (see
`kagent/LICENSE`, Copyright (c) 2026 K-agent contributors). LS-DYNA
R14.1.1 SMP single precision, 4 CPUs.

- `drop_e2e/glstat`, `drop_e2e/matsum`: unchanged copies of
  `skills/lsdyna-kfile/template_build/drop_e2e/`.
- `cold_start/d3hsp_minimal`: only the machine-readable lines of
  `skills/lsdyna-kfile/template_build/cold_start/d3hsp` that the reader
  uses: run information fields, command line, keyword counts (non-zero
  ones and two long names), selected model-size and control settings,
  the mass summary with the model's mass centre, memory, the smallest
  time steps table, termination
  lines and timing. All descriptive text printed by LS-DYNA (banner,
  legal notice, option descriptions, notes, mass property blocks) was
  removed and the host name replaced with `HOSTNAME`.
- `cold_start/ball_drop.k`, `mesh_plate.k`, `mesh_ball.k`: unchanged
  copies of the deck of that same run (fixed format, two include files).
  Its `d3hsp` gives the part masses, the mass centre and the smallest
  time step that `crashmetrics.deck.model_summary` and `time_steps`
  reproduce from the deck.
- `crash/crash.k`, `mesh_tube.k`: unchanged copies of
  `skills/lsdyna-kfile/templates/crash/` (a tube against a rigid wall:
  contact with an ID, part set, lumped masses, rigid wall, initial
  velocity, comment headers).

## `helmet/`

From [pranavduraisamy/helmet-fit-bayes-opt](https://github.com/pranavduraisamy/helmet-fit-bayes-opt),
commit `3dc519cb1d2976313aa48c84b034253353aded2e`, MIT licence (see
`helmet/LICENSE`, Copyright (c) 2026 Pranav D). A helmet fit study on
the LSTC 50th percentile Hybrid III model, LS-DYNA R16.0 SMP single
precision, mm, ms, kg, kN.

- `drop/nodout`: unchanged copy of `bo-runs/run0/drop/nodout` (head
  centre of gravity node 22626, drop test; also used to test the headform
  impact reading of `crashmetrics.pedestrian.clearance`).
- `pendulum/secforc`: unchanged copy of `bo-runs/run0/pendulum/secforc`
  (upper neck section, pendulum test).
- `pendulum_run1/secforc`: unchanged copy of `bo-runs/run1/pendulum/secforc`
  (the same test with helmet scale 1.025 and slack -6; used to compare two
  runs in `crashmetrics.loadpath`).

The study's `bo-runs/master.csv` gives, for run 0, HIC 195.2436, BrIC
0.38819 (drop) and a peak neck moment of 58.271 (pendulum), computed
from these files with its own parser.

## `pladebuk/`

From [node997/dyna_pladebuk](https://github.com/node997/dyna_pladebuk),
commit `cd28eeb4dbe79ffc147e5743cf803f448dcc5dae`, MIT licence (see
`pladebuk/LICENSE`, Copyright (c) 2026 node997). LS-DYNA R14.0 SMP
double precision.

- `rcforc`, `spcforc`: unchanged copies of `Plade_300_150_4/BB/rcforc`
  and `Plade_300_150_4/BB/spcforc` (contact labels `SURFA` / `SURFB`,
  mortar contact legend).
- `binout`, `glstat`, `matsum`: unchanged copies of
  `Plade_300_150_4/BB/binout`, `glstat` and `matsum` of the same run
  (LS-DYNA R14.0 SMP double precision, revision 515). The binout holds
  glstat, matsum, rcforc, spcforc and tprint; its values are compared
  with the ASCII files in `tests/test_binout.py`.
- `deck/main.k`, `deck/MAT_CWM355.k`: unchanged copies of the main deck
  and its material include, written by LS-PrePost 2024/R2 (4.11.14):
  `*PARAMETER_DUPLICATION`, many control cards, titled curves, thermal
  contacts with IDs. The two large mesh includes (`geometry.k`,
  `boundary.k`, 3.5 MB) are not copied, so the deck tests also cover
  include files that are not found.

## `lsprepost_mcp/`

From [lwz20210407/LS-PrePost-MCP](https://github.com/lwz20210407/LS-PrePost-MCP),
commit `892aca96a2b01ea7c2bc97635c2decc225a1f566`, MIT licence (see
`lsprepost_mcp/LICENSE`, Copyright (c) 2026 LS-PrePost-MCP contributors).

- `impact.k`, `impact_mesh.k`, `impact_broken.k`: unchanged copies of
  `tests/l3/fixtures/`: a block above a plate in mm-t-s, and the same
  deck with one deliberate fault (part 2 refers to section 3, which
  does not exist), which `crashmetrics.deck.check_deck` reports.

## Checked locally, not included

The ASCII readers were also checked against these public files, which
are not under the MIT licence (or have no licence) and so are not
copied here; every value was compared with a second, independent
parser:

- [jascott4427/PILLARS-LSDyna](https://github.com/jascott4427/PILLARS-LSDyna)
  (R13.1.1): `nodout`, `rcforc`, `sleout`, `spcforc`, `swforc`,
  `abstat`.
- [praveenvenky110395/LS-DYNA-Crimping-Simulation](https://github.com/praveenvenky110395/LS-DYNA-Crimping-Simulation)
  (R16.1): `rcforc`, `sleout`.
- MPP binout files converted with LS-DYNA's `l2a`:
  binout files in [qd-cae/qd-cae-python](https://github.com/qd-cae/qd-cae-python)
  (`secforc`, `sleout`, `swforc`; they sit in the repository's copy of
  LSTC's lsda library, so their licence is unclear),
  [hu-shuhan/editOpeniGame](https://github.com/hu-shuhan/editOpeniGame)
  (`rcforc`, `sleout`, `spcforc`) and
  [PallavME/binout-extraction-lassodyna](https://github.com/PallavME/binout-extraction-lassodyna)
  (a full-width frontal crash with a THOR dummy: `abstat`, `deforc`,
  `swforc`).
- A crush test of a hat section, the large binout in the same
  qd-cae-python folder (licence unclear, see above): `matsum` (9 parts,
  3201 states) and `secforc` (one section, unevenly spaced MPP output),
  read with `crashmetrics.loadpath`: energy ranking, automatic load axis
  (y) and sign, CFC 60 / 180 filtering after resampling.
- `crashmetrics.spotweld` on the `swforc` of the full-width frontal crash
  above (394 connections of three types, 32 failed, 30 of them in one
  burst) and of the PILLARS bolted joint (one spot weld beam, no
  failure).
- `crashmetrics.quality` on whole run folders: the K-agent ball drop
  (all files), the PILLARS bolted joint, the crimping run (very heavy
  mass scaling) and the pladebuk run (a `glstat` with one state:
  reported as unreadable).
- All 36 runs of the helmet study: HIC, BrIC and neck moment from the
  readers' arrays equal `master.csv` to 1e-15.
- `crashmetrics.binout` on four more runs (not copied: too large or no
  licence): the MIT 2D impact
  [saudbinayed/binout](https://github.com/saudbinayed/binout) (81 MB,
  LS-DYNA R11 single precision: nodout, elout, glstat, matsum, ncforc);
  an MPP bolted joint run (R12, four files, 1000 states, ten outputs) in
  [hu-shuhan/editOpeniGame](https://github.com/hu-shuhan/editOpeniGame);
  an MPP frontal crash's swforc, jntforc, deforc and abstat (R9.3.1) in
  [PallavME/binout-extraction-lassodyna](https://github.com/PallavME/binout-extraction-lassodyna)
  (only its binout data files were used). Coordinates equal initial
  coordinates plus displacements, energy totals equal their parts, and
  every symbol table agrees with its records. The ASCII files LS-DYNA's
  `l2a` converter wrote from these binouts (see above) were compared
  with the reader's output: the same numbers to the printed digits.
- `crashmetrics.deck` on the full pladebuk deck (20 276 nodes, 15 390
  solids, four files) and on the MIT deck
  [`plane_strain_impact.k`](https://github.com/saudbinayed/binout)
  (765 kB, LS-PrePost V4.9.9, m-s-kg, 2D contact kept unchanged; not
  copied for its size); the K-agent drop test deck (`drop_e2e`): masses
  and mass centre equal its `d3hsp` (block 2.512E-04, centre z 10.110008),
  smallest time step 8.4091E-07.

LS-DYNA is a trademark of its owner. This project is not affiliated with
or endorsed by Ansys.
