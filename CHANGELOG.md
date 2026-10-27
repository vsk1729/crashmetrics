# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/).

## [0.7.0] - Unreleased

### Added

- Frontal impact dummy criteria for the Hybrid III and THOR, following
  Euro NCAP CP 005 v1.4.1 unless noted:
  - `crashmetrics.head`: DAMAGE from angular velocity or acceleration
    (`damage`, `damage_from_acceleration`) with the Euro NCAP window
    (T0, 200 ms, external force below -500 N), BrIC (`bric`; Takhounts
    et al. 2013) and `loading_phase_end`.
  - `crashmetrics.neck`: `occipital_condyle_moment`, `neck_loads`
    (shear, tension, compression, extension and flexion moments),
    `neck_force_criterion` with the UN-ECE R94 tension and shear
    force-duration limits, and Nij (`nij`; FMVSS 208 intercepts).
  - `crashmetrics.thorax`: `chest_deflection`, `viscous_criterion`,
    THOR `thor_rib_displacement` / `thor_chest_deflection` (Rmax),
    `thor_abdomen_deflection`, and CTI (`cti`, `cti_from_signals`;
    Eppinger et al. 1999).
  - `crashmetrics.pelvis`: THOR `acetabulum_force` and
    `iliac_force_drop`.
  - `crashmetrics.lower_extremity`: `tibia_compression` (with the R94
    limit) and `knee_slider_displacement`.
- `crashmetrics.frontal_scoring`: Euro NCAP frontal scoring to the
  Crash Protection Frontal Impact Protocol v1.1 (2026-2028) and CP 007
  v1.1: colour bands from HPL / LPL (`colour_band`), limits for the
  Hybrid III 5th / 50th / 95th, THOR 50th, Q6 and Q10, body region and
  dummy scores with occupant modifiers (`score_dummy`), and the MPDB
  (`score_mpdb`) and full width (`score_fwdb`) test scores with
  full-scale modifiers and the compatibility penalty;
  `damage_modifier` and `compatibility_percentages`.
- `crashmetrics.acceleration.exceedance_check`: checks any signal
  against a force-duration (exceedance) limit, for positive, negative or
  absolute values.

### Changed

- `femur_force_criterion` uses `exceedance_check`; results are
  unchanged.

## [0.6.0] - 2026-10-26

### Added

- `crashmetrics.d3hsp` (also in `crashmetrics.lsdyna`): `read_d3hsp` /
  `parse_d3hsp` for LS-DYNA d3hsp files: run information, termination
  status, warnings and errors, model size, echoed settings, keyword
  counts, part masses, smallest time steps, timing and memory. Built and
  tested on real LS-DYNA R14.1 and R16.1 SMP files; MPP-tolerant.
- Energy checks: part names from the matsum legend and per-part added
  mass (`+mass=`) in `PartEnergies` and `PartResult`; the summary lists
  the parts with the most added mass.
- Real LS-DYNA R14.1 test data (glstat, matsum, d3hsp excerpt) from the
  MIT-licensed K-agent project, with attribution.

### Changed

- The d3hsp test file now holds only the machine-readable lines the
  reader uses; LS-DYNA's descriptive text was removed (67 KB -> 11 KB).
- README: trademarks and non-affiliation notice.

### Fixed

- glstat labels that wrap onto a second line ("number of shell elements
  that" / "reached the minimum time step") are read as one label.

## [0.5.0] - 2026-10-26

### Added

- Euro NCAP legform scoring in `crashmetrics.pedestrian` for the 2026
  and 2023 protocols:
  - `sliding_scale`, `round_score` and `leg_colour`
  - `apli_point_score` and `apli_score`: femur (worst femur bending
    moment) and knee/tibia (lower of tibia moment and MCL elongation)
    points
  - `upper_legform_point_score` and `upper_legform_score`: pelvis points
    from the sum of forces
  - `upper_legform_alpha` and `upper_legform_energy`: impact angle,
    nominal energy, test velocity and the 160 J rule
  - untested grid points filled by symmetry and the worst adjacent
    result per body region, with asymmetric points and the 10 % energy
    rule
- `vru_score`: total passive VRU crash protection points (20 in 2026,
  36 in 2023).
- `crashmetrics.energy_check`: solver-agnostic energy checks for any
  load case: energy ratio, hourglass / internal energy, negative contact
  energy, system damping, added mass, eroded energy, and per-part
  hourglass and negative internal energy, with configurable
  `EnergyLimits` and a text summary.
- `crashmetrics.lsdyna`: glstat and matsum ASCII readers (label-based,
  Fortran exponents) and `check_run`.
- `crashmetrics-energy` command: checks one or more run directories,
  exit code 0 (pass), 1 (fail) or 2 (unreadable).

## [0.4.0] - 2026-10-26

### Added

- `crashmetrics.pedestrian` headform grid scoring for Euro NCAP 2026
  (Crash Protection - VRU Impacts v1.1, head maximum 10 points, A-pillar
  rewards) and 2023 (VRU Assessment Protocol v11.4, 18 points):
  `hic_colour`, `verification_colour` (10 % tolerance),
  `correction_factor` and `headform_score`, with blue, default red and
  A-pillar points and the 100 % cap.

## [0.3.0] - 2026-10-25

### Added

- `crashmetrics.pulse`: Occupant Load Criterion (`olc`) following the
  Euro NCAP definition, and `pulse_summary` (delta-V, time to zero
  velocity, maximum displacement, rebound, restitution, peak and mean
  deceleration).
- `crashmetrics.lower_extremity`: `tibia_index` with Euro NCAP critical
  values for Hybrid III 50th/5th/95th and THOR, and
  `femur_force_criterion` against force-time limits, including the
  UN-ECE R94 Hybrid III 50th limit.
- `crashmetrics.acceleration.exceedance_level` and
  `exceedance_duration`, generalising the 3 ms clip to any duration
  and signal.
- Release workflow publishing to TestPyPI (manual run) and PyPI (GitHub
  release) with Trusted Publishing.

### Fixed

- LICENSE now contains the complete MIT licence text, including the
  limitation of liability clause, and is included in the distributions.

## [0.2.0] - 2026-10-25

### Added

- `crashmetrics.signals`: SAE J211 CFC filter (`cfc_filter`),
  `resultant`, unit conversion (`to_g`, `to_seconds`) and
  `resample_uniform`.
- `crashmetrics.acceleration`: `peak` and the 3 ms clip (`clip_3ms`),
  cumulative or continuous.
- `crashmetrics.energy`: `integrate_acceleration`, `absorbed_energy`,
  `crush_metrics` (energy, mean and peak force, CFE, SEA, stroke limit)
  and `kinetic_energy`.
- `HICResult.start_time_ms` and `end_time_ms`, and `PeakResult.time_ms`.
- Type hints on the public API and a `py.typed` marker.
- CI on Python 3.10–3.13 and NumPy 1.24, with ruff and mypy checks.

### Changed

- `calculate_hic` no longer raises `ValueError` when the record is
  shorter than `window_ms`. It issues a `UserWarning` and evaluates
  HIC over the available duration.
- The package version is defined once, in `crashmetrics.__version__`.

### Fixed

- The test suite no longer needs NumPy 2.0 (`np.trapezoid`), matching
  the declared `numpy>=1.24` requirement.
- README no longer lists unimplemented features or a PyPI install.

## [0.1.0]

### Added

- `crashmetrics.pedestrian.calculate_hic` for HIC on a refined,
  linearly interpolated time grid.

[0.6.0]: https://github.com/vsk1729/crashmetrics/compare/v0.5.0...main
[0.5.0]: https://github.com/vsk1729/crashmetrics/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/vsk1729/crashmetrics/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/vsk1729/crashmetrics/compare/03d71b7...v0.3.0
[0.2.0]: https://github.com/vsk1729/crashmetrics/compare/80a5615...03d71b7
[0.1.0]: https://github.com/vsk1729/crashmetrics/tree/80a5615
