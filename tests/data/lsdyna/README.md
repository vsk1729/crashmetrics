# LS-DYNA test data

Real LS-DYNA output used to test the readers in `crashmetrics.lsdyna`
and `crashmetrics.d3hsp`.

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

LS-DYNA is a trademark of its owner. This project is not affiliated with
or endorsed by Ansys.
