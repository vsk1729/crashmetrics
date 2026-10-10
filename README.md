# CrashMetrics

Python tools for automotive crash engineering calculations.

**Development status:** Alpha — not validated for regulatory compliance.

## Features

- Head Injury Criterion (HIC) calculations
- Acceleration time-history analysis
- Planned energy and force–displacement metrics

## Installation

```bash
python -m pip install crashmetrics
```

The package is under development. Install from source if a public release is not yet available.

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

## Engineering disclaimer

This software is an engineering calculation aid. Users must independently validate numerical results and confirm that input processing, filtering, sampling, and calculation methods match the applicable assessment protocol. The software does not certify regulatory compliance.

## License

MIT. See the LICENSE file.