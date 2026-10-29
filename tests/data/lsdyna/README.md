# LS-DYNA test data

Real LS-DYNA output used to test the readers in `crashmetrics.lsdyna`,
`crashmetrics.lsdyna_ascii` and `crashmetrics.d3hsp`. Only files under
the MIT licence are included, each with its licence file.

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
  the mass summary, memory, the smallest time steps table, termination
  lines and timing. All descriptive text printed by LS-DYNA (banner,
  legal notice, option descriptions, notes, mass property blocks) was
  removed and the host name replaced with `HOSTNAME`.

## `helmet/`

From [pranavduraisamy/helmet-fit-bayes-opt](https://github.com/pranavduraisamy/helmet-fit-bayes-opt),
commit `3dc519cb1d2976313aa48c84b034253353aded2e`, MIT licence (see
`helmet/LICENSE`, Copyright (c) 2026 Pranav D). A helmet fit study on
the LSTC 50th percentile Hybrid III model, LS-DYNA R16.0 SMP single
precision, mm, ms, kg, kN.

- `drop/nodout`: unchanged copy of `bo-runs/run0/drop/nodout` (head
  centre of gravity node 22626, drop test).
- `pendulum/secforc`: unchanged copy of `bo-runs/run0/pendulum/secforc`
  (upper neck section, pendulum test).

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
  [qd-cae/qd-cae-python](https://github.com/qd-cae/qd-cae-python)
  test data (`secforc`, `sleout`, `swforc`),
  [hu-shuhan/editOpeniGame](https://github.com/hu-shuhan/editOpeniGame)
  (`rcforc`, `sleout`, `spcforc`) and
  [PallavME/binout-extraction-lassodyna](https://github.com/PallavME/binout-extraction-lassodyna)
  (a full-width frontal crash with a THOR dummy: `abstat`, `deforc`,
  `swforc`).
- All 36 runs of the helmet study: HIC, BrIC and neck moment from the
  readers' arrays equal `master.csv` to 1e-15.

LS-DYNA is a trademark of its owner. This project is not affiliated with
or endorsed by Ansys.
