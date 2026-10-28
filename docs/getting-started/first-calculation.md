# Your first calculation

This page walks through a complete calculation: from three raw headform
acceleration channels to HIC15, the peak acceleration and the 3 ms clip.
The same steps apply to any acceleration-based criterion.

## Step 1: get the data into arrays

crashmetrics works on NumPy arrays (or lists): one array of time values
and one array per channel, all the same length. Here we make a synthetic
headform impact in the LS-DYNA mm-ms-kg unit system:

```python
import numpy as np

time_ms = np.arange(0.0, 30.0, 0.01)                     # ms, 100 kHz
pulse = np.where(time_ms < 12.0, np.sin(np.pi * time_ms / 12.0) ** 2, 0.0)
ax = -1.15 * pulse                                       # mm/ms^2
az = 0.55 * pulse
ay = np.zeros_like(time_ms)
```

With your own data, see [Loading your data](loading-data.md).

## Step 2: convert to seconds and g

All crashmetrics functions take **time in seconds**. Head criteria take
**acceleration in g**. The converters know the common unit systems:

```python
from crashmetrics.signals import to_g, to_seconds

t = to_seconds(time_ms, "ms")
components_g = [to_g(a, "mm/ms^2") for a in (ax, ay, az)]
```

| LS-DYNA unit system | Acceleration unit | Time unit |
| --- | --- | --- |
| mm, ms, kg | `"mm/ms^2"` | `"ms"` |
| mm, s, tonne | `"mm/s^2"` | `"s"` |
| m, s, kg | `"m/s^2"` | `"s"` |

## Step 3: filter each channel

Test data and CAE output must be filtered with the channel frequency
class (CFC) the protocol gives: CFC 1000 for head accelerations.
**Filter each axis first, then form the resultant**; never filter a
resultant (its magnitude cannot be filtered like a signed signal).

```python
from crashmetrics.signals import cfc_filter, resultant

filtered = [cfc_filter(t, a, cfc=1000) for a in components_g]
a_res = resultant(*filtered)
```

!!! tip "Sample rate"
    The CFC filter needs uniformly sampled data and a sample rate above
    about 4.2 × CFC (4.2 kHz for CFC 1000). If your output interval is
    irregular, resample first with `resample_uniform`.

## Step 4: compute the criteria

```python
from crashmetrics.acceleration import clip_3ms, peak
from crashmetrics.pedestrian import calculate_hic, hic_colour

hic = calculate_hic(t, a_res, window_ms=15.0)
print(hic.value, hic.start_time, hic.end_time)   # HIC15 and its window (s)
print(hic_colour(hic.value))                     # Euro NCAP headform colour

print(peak(t, a_res).value)                      # peak, g
print(clip_3ms(t, a_res))                        # 3 ms clip, g (cumulative)
```

## The complete example

This is `examples/01_signals_hic.py` from the repository. It adds sensor
noise and also shows how to resample irregular output:

```python
--8<-- "examples/01_signals_hic.py"
```

Output:

```text
--8<-- "examples/expected/01_signals_hic.txt"
```

## Results are dataclasses

Every function returns a plain number or a small dataclass with named
fields, so results are easy to print, store or tabulate:

```python
from dataclasses import asdict

asdict(hic)        # {'value': ..., 'start_time': ..., 'end_time': ...}
```

Next: [load your own test or CAE data](loading-data.md).
