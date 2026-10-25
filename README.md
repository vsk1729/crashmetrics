# CrashMetrics

Python tools for automotive crash engineering calculations.

**Development status:** Alpha — not validated for regulatory compliance.

## Features

Available now:

- Head Injury Criterion (HIC), for example HIC15 and HIC36, via `crashmetrics.pedestrian.calculate_hic`
- Signal processing in `crashmetrics.signals`: SAE J211 CFC filtering (`cfc_filter`), resultants (`resultant`), unit conversion (`to_g`, `to_seconds`) and uniform resampling (`resample_uniform`)

Planned (not yet implemented):

- Acceleration time-history metrics such as peak and 3 ms clip (`crashmetrics.acceleration`)
- Energy and force–displacement metrics (`crashmetrics.energy`)

## Installation

The package is not yet published on PyPI. Install it from GitHub:

```bash
python -m pip install "git+https://github.com/vsk1729/crashmetrics.git"
```

For development, clone the repository and install it in editable mode with the test tools:

```bash
git clone https://github.com/vsk1729/crashmetrics.git
cd crashmetrics
python -m pip install -e ".[dev]"
python -m pytest
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

If the output interval is not uniform, use
`resample_uniform(t, a, sample_rate)` before filtering.

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

## Units and numerical method

- Time input: seconds
- Acceleration input: non-negative resultant magnitude in g
- HIC window: milliseconds
- Numerical integration: trapezoidal rule on a refined, linearly interpolated time grid

Results depend on the selected grid resolution and the numerical method.

If the record is shorter than `window_ms`, `calculate_hic` issues a `UserWarning` and evaluates HIC over the available duration. Make sure the record contains the whole impact.

## Engineering disclaimer

This software is an engineering calculation aid. Users must independently validate numerical results and confirm that input processing, filtering, sampling, and calculation methods match the applicable assessment protocol. The software does not certify regulatory compliance.

## License

MIT. See the LICENSE file.