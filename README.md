# CrashMetrics

Python tools for automotive crash engineering calculations.

**Development status:** Alpha — not validated for regulatory compliance.

## Features

Available now:

- Head Injury Criterion (HIC), for example HIC15 and HIC36, via `crashmetrics.pedestrian.calculate_hic`

Planned (not yet implemented):

- Signal processing: SAE J211 CFC filtering, resultants, unit conversion (`crashmetrics.signals`)
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