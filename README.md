# CrashMetrics

Python tools for automotive crash engineering calculations.

**Development status:** Alpha — not validated for regulatory compliance.

## Features

- Head Injury Criterion (HIC), for example HIC15 and HIC36, via `crashmetrics.pedestrian.calculate_hic`
- Signal processing in `crashmetrics.signals`: SAE J211 CFC filtering (`cfc_filter`), resultants (`resultant`), unit conversion (`to_g`, `to_seconds`) and uniform resampling (`resample_uniform`)
- Acceleration metrics in `crashmetrics.acceleration`: peak value and time (`peak`) and the 3 ms clip, cumulative or continuous (`clip_3ms`)
- Vehicle pulse metrics in `crashmetrics.pulse`: Occupant Load Criterion (`olc`) and a pulse summary with delta-V, time to zero velocity, maximum displacement, rebound and deceleration (`pulse_summary`)
- Lower-extremity criteria in `crashmetrics.lower_extremity`: Tibia Index (`tibia_index`) and femur compressive force against a force–time limit (`femur_force_criterion`)
- Generic exceedance helpers in `crashmetrics.acceleration`: `exceedance_level` and `exceedance_duration`
- Energy and force–displacement metrics in `crashmetrics.energy`: velocity and displacement from acceleration (`integrate_acceleration`), cumulative absorbed energy (`absorbed_energy`), crush summary with peak and mean force, crush force efficiency and specific energy absorption (`crush_metrics`), and `kinetic_energy`

## Installation

The package is not yet published on PyPI. Install it from GitHub:

```bash
python -m pip install "git+https://github.com/vsk1729/crashmetrics.git"
```

Requires Python 3.10 or later and NumPy 1.24 or later.

## Example

```python
from crashmetrics.pedestrian import calculate_hic

time = [0.0, 0.005, 0.010, 0.015]
acceleration = [10.0, 10.0, 10.0, 10.0]

result = calculate_hic(
    time,
    acceleration,
    window_ms=15.0,
)

print(result.value)
print(result.duration_ms)
```

### From LS-DYNA output to HIC15

For a headform model in the mm-ms-kg unit system, with axis
accelerations `ax`, `ay`, `az` in mm/ms² and `time_ms` in ms
(uniformly sampled):

```python
from crashmetrics.pedestrian import calculate_hic
from crashmetrics.signals import cfc_filter, resultant, to_g, to_seconds

t = to_seconds(time_ms, "ms")

# Filter each component with CFC 1000, then form the resultant.
components_g = [
    cfc_filter(t, to_g(a, "mm/ms^2"), cfc=1000) for a in (ax, ay, az)
]
a_res = resultant(*components_g)

hic15 = calculate_hic(t, a_res, window_ms=15.0)
print(f"HIC15 = {hic15.value:.0f} over {hic15.duration_ms:.2f} ms")
```

The same filtered resultant gives the peak and the 3 ms clip:

```python
from crashmetrics.acceleration import clip_3ms, peak

a_peak = peak(t, a_res)
print(f"Peak = {a_peak.value:.1f} g at {a_peak.time * 1000:.2f} ms")
print(f"3 ms clip = {clip_3ms(t, a_res):.1f} g")
```

If the output interval is not uniform, use
`resample_uniform(t, a, sample_rate)` before filtering.

### Energy and crush metrics

For a crash box or rail with force in kN and crush in mm (energy in J):

```python
from crashmetrics.energy import absorbed_energy, crush_metrics

energy_curve = absorbed_energy(crush_mm, force_kN)  # J at each sample

result = crush_metrics(crush_mm, force_kN, mass=1.2, max_displacement=150.0)
print(f"Energy {result.energy:.0f} J, mean force {result.mean_force:.1f} kN")
print(f"Peak {result.peak_force:.1f} kN at {result.peak_force_displacement:.1f} mm")
print(f"CFE {result.crush_force_efficiency:.2f}, SEA {result.specific_energy_absorption:.0f} J/kg")
```

`max_displacement` evaluates the metrics over a fixed stroke. Mean
force is net energy divided by crush distance and CFE is mean force
divided by peak force, so always report the stroke with them.

From a vehicle or impactor acceleration pulse (mm/ms² and ms give
m/s and mm):

```python
from crashmetrics.energy import integrate_acceleration, kinetic_energy

velocity, displacement = integrate_acceleration(time_ms, accel_mm_ms2, v0=15.6)
print(f"Dynamic crush {displacement.max():.0f} mm")
print(f"Initial kinetic energy {kinetic_energy(1200.0, 15.6) / 1000:.1f} kJ")
```

The energy functions do not convert units; use a consistent system.
Integration amplifies sensor offset and drift, so check the input
pulse before integrating test data.

### Occupant Load Criterion and pulse summary

Inputs are SI (s, m/s², m/s). The acceleration is the vehicle's
longitudinal acceleration in its direction of travel, so it is
negative while decelerating, and the record starts at T0:

```python
from crashmetrics.pulse import olc, pulse_summary
from crashmetrics.signals import cfc_filter

a = cfc_filter(t, accel_x_m_s2, cfc=180)   # Euro NCAP uses CFC 180 for OLC
result = olc(t, a, v0=50 / 3.6)
print(f"OLC = {result.value:.1f} g (t1 = {result.t1*1000:.1f} ms, t2 = {result.t2*1000:.1f} ms)")

summary = pulse_summary(t, a, v0=50 / 3.6)
print(f"delta-V {summary.delta_v:.2f} m/s, max displacement {summary.max_displacement*1000:.0f} mm")
```

`olc` follows the Euro NCAP definition (Data Acquisition and Injury
Calculation protocol): a virtual occupant moves 65 mm in free flight,
then decelerates uniformly over a further 235 mm until it matches the
vehicle velocity. The OLC is that deceleration, expressed in g using
9.81 m/s² as Euro NCAP does (change with `gravity`). The tests check it
against the closed-form solution for constant deceleration and against
an independent numerical formulation.

### Tibia Index and femur force

Forces in N, moments in N m, compression negative by default (Euro
NCAP convention):

```python
from crashmetrics.lower_extremity import femur_force_criterion, tibia_index

ti = tibia_index(t, mx_upper, my_upper, fz_upper, dummy="hybrid3_50")
print(f"TI upper = {ti.value:.2f}")

femur = femur_force_criterion(t, fz_femur, limit="r94_hybrid3_50")
print(f"Peak {femur.peak_compression/1000:.2f} kN, utilisation {femur.utilisation:.2f}, passed {femur.passed}")
```

- `tibia_index`: `TI = |MR/MRc| + |Fz/Fzc|` while the tibia is in
  compression, zero otherwise, with `MR = sqrt(Mx² + My²)`. Critical
  values for Hybrid III 50th, 5th, 95th and THOR are taken from Euro
  NCAP CP 005 (`TIBIA_INDEX_CRITICAL_VALUES`); you can also pass your
  own.
- `femur_force_criterion`: builds the exceedance curve (force reached
  or exceeded versus duration) and compares it with a force–time limit.
  `"r94_hybrid3_50"` is the UN-ECE R94 limit of 9.07 kN at 0 ms falling
  to 7.58 kN at 10 ms and longer; you can pass your own points. The
  default `mode="cumulative"` adds up separate intervals; use
  `mode="continuous"` if your regulation requires a single interval.

Check all constants against the protocol version you assess to.

### 3 ms clip

`clip_3ms` returns the highest level that the signal reaches or
exceeds for 3 ms (change with `duration_ms`):

- `mode="cumulative"` (default): 3 ms in total, possibly over several
  separate intervals. Computed exactly for the linearly interpolated
  signal.
- `mode="continuous"`: 3 ms in a single interval. Never higher than
  the cumulative value.

Check which definition your assessment protocol requires.

### CFC filter

`cfc_filter` implements the SAE J211-1 Appendix C digital filter: a
2-pole Butterworth low-pass run forward and backward, giving a
phaseless 4-pole response. The tests check the gain against the J211
corridor points for CFC 60, 180, 600 and 1000 (flat to the CFC
frequency, about −3 dB at 1.65 × CFC). The sample rate must exceed
2 × 2.0775 × CFC (about 4.2 kHz for CFC 1000).

Each end of the signal is padded by odd reflection (`pad_ms`, default
10 ms) to reduce start-up transients. This padding choice is part of
this package, not of J211; confirm it matches your protocol.

## HIC units and numerical method

- Time input: seconds
- Acceleration input: non-negative resultant magnitude in g
- HIC window: milliseconds
- Numerical integration: trapezoidal rule on a refined, linearly interpolated time grid

Results depend on the selected grid resolution and the numerical method.

If the record is shorter than `window_ms`, `calculate_hic` issues a `UserWarning` and evaluates HIC over the available duration. Make sure the record contains the whole impact.

## Development

Clone the repository and install it in editable mode with the
development tools (pytest, ruff, mypy, build):

```bash
git clone https://github.com/vsk1729/crashmetrics.git
cd crashmetrics
python -m pip install -e ".[dev]"
```

Run the same checks as CI before opening a pull request:

```bash
python -m pytest      # tests
ruff check .          # lint
mypy                  # type check
```

`examples/hic_convergence.py` shows how the HIC result changes with
`resolution_ms`; run it after changing the HIC algorithm.

The version is set only in `src/crashmetrics/__init__.py`. Record
user-visible changes in [CHANGELOG.md](CHANGELOG.md).

## Engineering disclaimer

This software is an engineering calculation aid. Users must independently validate numerical results and confirm that input processing, filtering, sampling, and calculation methods match the applicable assessment protocol. The software does not certify regulatory compliance.

## License

MIT. See the LICENSE file.