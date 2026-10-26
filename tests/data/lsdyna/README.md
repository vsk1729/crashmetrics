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
- `cold_start/d3hsp_excerpt`: sections of
  `skills/lsdyna-kfile/template_build/cold_start/d3hsp` (run header,
  keyword counts, problem size and control cards 8 and 9, element death
  settings, mass properties to the end of the file). The Ansys legal
  notice and copyright lines were left out and the host name replaced
  with `HOSTNAME`.
