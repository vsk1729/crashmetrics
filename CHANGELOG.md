# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/).

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

[0.3.0]: https://github.com/vsk1729/crashmetrics/compare/03d71b7...main
[0.2.0]: https://github.com/vsk1729/crashmetrics/compare/80a5615...03d71b7
[0.1.0]: https://github.com/vsk1729/crashmetrics/tree/80a5615
