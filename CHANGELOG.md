# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `crashmetrics.bncap_cop`: Bharat NCAP child occupant protection
  (AIS-197 Annexure V, 49 points): Q1.5 and Q3 dynamic scores in the
  ODB frontal and MDB side tests with all penalties (ejection, forward
  facing Q1.5, head contact with the vehicle, no recommendation), CRS
  installation (CRSi, installation list and recommended seats, halving;
  reproduces the standard's worked example 9.143), vehicle based
  assessments (13 points; two-seaters 10) and the COP total and stars.
- `crashmetrics.bncap_rating`: safety assist qualifiers (Annexure VI:
  pedestrian AIS-100, SBR AIS-145, ESC, side head protection with pole
  test and fitment share by publication year) as the highest allowed
  adult star level, and `bncap_rating` for the complete adult and child
  rating with what is missing for the next star. Guide "Bharat NCAP
  child occupant and complete rating", protocol notes and example
  `16_bharat_ncap_cop_rating.py`.

- `crashmetrics.side_scoring`: Euro NCAP 2026 side impact (Crash
  Protection Side Impact Protocol v1.1): AE-MDB (WorldSID 50th, Q10,
  Q6; 15 points) and pole (10 points) with colour bands, hard-contact
  rule, automatic shoulder and VC modifiers, airbag and test modifiers
  (doors, head protection zone, rollover); far side (10 points) with
  head excursion zones (`far_side_zone`), capping limits, pelvis/lumbar
  modifier, robustness, occupant-to-occupant and the disqualification
  rules (17-point near side threshold, structural or restraint
  failure); `score_side` for the 35-point total. Guide "Euro NCAP side
  and far side", protocol notes and example `15_euroncap_side.py`.

## [0.11.0] - 2026-10-29

### Added

- `crashmetrics.homologation`: pass/fail compliance checks per
  requirement, with clause, limit and utilisation, for UN R94 / AIS-098
  (05 series; occupant and vehicle, neck and femur force-duration
  curves from time histories), UN R95 / AIS-099 (ES-2) and UN R135
  (01 series, WorldSID; lower spine from the time history), and
  post-crash electrical safety (R94 and R137 5.2.8: voltage, energy,
  physical protection and isolation per high-voltage bus, electrolyte,
  REESS retention, fire). Unmeasured requirements are reported as not
  assessed. Guide "Homologation compliance", protocol notes and
  example `14_homologation.py`.

- `crashmetrics.intrusion`: `intrusion` (displacement of a point
  relative to the global system, one reference node, or a best-fit
  vehicle frame of three or more nodes that removes translation and
  rotation; dynamic and static values, overall and along a direction;
  reference fit error), `intrusions` (many points), `node_distance`
  (closing, opening and remaining space between two points) and
  `node_track`. Works on CAE time histories and on before/after test
  measurements. Guide "Intrusion measurement", protocol notes and
  example `13_intrusion.py`, which feeds the Bharat NCAP steering
  column, A-pillar and pedal modifiers.

### Changed

- **Renamed** `cora`, `CORAParameters` and `CORAResult` to `cc_rating`,
  `CCParameters` and `CCResult` (corridor and cross-correlation
  rating), `Comparison.cora` to `Comparison.cc` and the
  `cora_parameters` argument of `compare` to `cc_parameters`. The
  results are unchanged. The method is the published one of Gehre et
  al. (2009); the new names avoid implying a link to PDB's CORA tool.
- Disclaimer: ISO and PDB added to the organisations crashmetrics is not
  affiliated with, and the sources of the correlation methods stated.

## [0.10.0] - 2026-10-28

### Added

- `crashmetrics.features` for analytics and machine learning:
  `signal_features` (peaks, timing, rise time, pulse width, impulse,
  energy centroid, number of impacts, frequency content of any channel),
  `head_features` and `pulse_features` (criteria plus shape),
  `flatten` (any result object, however nested, as flat columns),
  `feature_table` (one row per run with design parameters; failing runs
  recorded in an `error` column), and `write_csv`, `to_dataframe` and
  `to_matrix` for CSV, pandas and NumPy. Guide "Features for machine
  learning" and example `11_ml_features.py`.
- `crashmetrics.correlation` for test-versus-CAE correlation:
  `iso18571` (ISO/TS 18571:2024 corridor, phase, magnitude and slope
  scores, overall rating and grade; verified against TU Graz's
  `objective-rating-metrics` to machine precision), `cora` (corridor
  and cross-correlation phase, size and shape ratings; the defaults are
  the commonly cited CORA 3.6 values, not yet checked against the
  official manual, so check them against your CORA version and set
  `CORAParameters` to match), `error_measures` (peak and peak-time errors, RMSE,
  NRMSE, correlation, R², Sprague & Geers, Russell), `compare` (all
  three, with a text summary) and `resample_pair` (signals with
  different time bases). Guide "Test-versus-CAE correlation", protocol
  notes and example `12_test_cae_correlation.py`.
- `CITATION.cff`, so GitHub shows "Cite this repository" and papers can
  cite the package; a test keeps its version in step with the package.

### Changed

- The Euro NCAP legform and Flex-PLI scores and the Bharat NCAP region
  scores share one sliding-scale implementation. `bncap.sliding_points`
  now gives the same, more detailed error messages as
  `pedestrian.sliding_scale`; results are unchanged.
- Test and release workflows use the current GitHub Actions versions
  (Node 24).

## [0.9.1] - 2026-10-28

### Added

- Documentation site (<https://vsk1729.github.io/crashmetrics/>): getting
  started, units and sign conventions, ten step-by-step guides, protocol
  notes listing every interpretation, and the API reference generated
  from the docstrings. Built on every pull request and published to
  GitHub Pages from `main`.
- Ten runnable examples in `examples/`, one per topic, with their
  expected output; the test suite checks that output.
- `docs` optional dependencies (`pip install -e ".[docs]"`).

### Changed

- The README is now a short overview that links to the documentation.
- Module docstrings use Markdown lists and tables so they render in the
  API reference.

### Fixed

- `bncap.curve_points` reported a duration of 0 ms when the curve scored
  full points; it now reports the duration at the peak level.

## [0.9.0] - 2026-10-27

### Added

- AIS-100 pedestrian compliance checks (`crashmetrics.pedestrian`):
  Flex-PLI to bumper (Rev.1, 2024) and legacy legform (original
  edition) limits, upper legform to bumper, `bumper_legform` (which test
  applies by lower bumper height), the 264 mm relaxation width, and the
  HIC1000 / HIC1700 zone area and test rules.
- Flex-PLI: `assessment_interval` (AIS-100 Rev.1 3.2 / UN GTR 9),
  `flexpli_peaks`, and Euro NCAP (v10.0.5, 2014-2022) Flex-PLI point and
  grid scores (`flexpli_point_score`, `flexpli_score`).

## [0.8.0] - 2026-10-27

### Added

- `crashmetrics.frontal_scoring`: Euro NCAP frontal scoring to the
  Crash Protection Frontal Impact Protocol v1.1 (2026-2028) and CP 007
  v1.1: colour bands from HPL / LPL (`colour_band`), limits for the
  Hybrid III 5th / 50th / 95th, THOR 50th, Q6 and Q10, body region and
  dummy scores with occupant modifiers (`score_dummy`), and the MPDB
  (`score_mpdb`) and full width (`score_fwdb`) test scores with
  full-scale modifiers; the CP 007 compatibility penalty
  (`compatibility_penalty`, checked against its worked examples),
  `damage_modifier`, and the protocol's modifier tables. The full width
  test uses the 35 km/h chest limits.
- `crashmetrics.bncap`: Bharat NCAP adult occupant protection scoring to
  AIS-197: sliding scales, exceedance-curve scoring of neck shear,
  neck tension and femur compression, ODB frontal and MDB side test
  scores with modifiers and capping, the pole test check, the AOP star
  rating with its caps and the child occupant star thresholds.
- `crashmetrics.side`: ES-2 rib deflection and VC (worst rib), total
  abdominal force and pubic symphysis force; `"es2"` VC constants.

## [0.7.0] - 2026-10-27

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

[Unreleased]: https://github.com/vsk1729/crashmetrics/compare/v0.11.0...main
[0.11.0]: https://github.com/vsk1729/crashmetrics/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/vsk1729/crashmetrics/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/vsk1729/crashmetrics/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/vsk1729/crashmetrics/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/vsk1729/crashmetrics/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/vsk1729/crashmetrics/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/vsk1729/crashmetrics/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/vsk1729/crashmetrics/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/vsk1729/crashmetrics/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/vsk1729/crashmetrics/compare/03d71b7...v0.3.0
[0.2.0]: https://github.com/vsk1729/crashmetrics/compare/80a5615...03d71b7
[0.1.0]: https://github.com/vsk1729/crashmetrics/tree/80a5615
