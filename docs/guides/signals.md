# Signals, HIC and the 3 ms clip

Module: `crashmetrics.signals`, `crashmetrics.acceleration`,
`crashmetrics.pedestrian` (HIC).

## 1. Filter: `cfc_filter`

```python
from crashmetrics.signals import cfc_filter

a_filtered = cfc_filter(t, a_raw, cfc=1000)    # 60, 180, 600 or 1000
```

- Implements the SAE J211-1 Appendix C filter: a 2-pole Butterworth
  low-pass run forward and backward, so it adds no phase shift.
- Needs uniformly sampled data and a sample rate above 2 × 2.0775 × CFC
  (about 4.2 kHz for CFC 1000); otherwise it raises an error.
- Each end is padded by odd reflection (`pad_ms`, 10 ms by default) to
  reduce start-up transients.

The tests check the gain against the J211 corridor for CFC 60, 180, 600
and 1000.

## 2. Resultant: `resultant`

```python
from crashmetrics.signals import resultant

a_res = resultant(ax_f, ay_f, az_f)     # two or three filtered components
```

!!! warning "Filter first"
    Always filter the components, then form the resultant. A filtered
    resultant can dip below zero and will be rejected by `calculate_hic`.

## 3. Resample irregular output: `resample_uniform`

```python
from crashmetrics.signals import resample_uniform

t_u, a_u = resample_uniform(t, a, sample_rate=20_000.0)   # Hz
```

Linear interpolation onto a uniform grid. Use a rate high enough for the
CFC you apply next.

## 4. HIC: `calculate_hic`

\[
\mathrm{HIC} = \max_{t_1, t_2}\left[(t_2 - t_1)
\left(\frac{1}{t_2 - t_1}\int_{t_1}^{t_2} a(t)\,dt\right)^{2.5}\right],
\qquad t_2 - t_1 \le 15\ \mathrm{ms}
\]

```python
from crashmetrics.pedestrian import calculate_hic

hic = calculate_hic(t, a_res, window_ms=15.0)     # HIC15; 36.0 for HIC36
hic.value, hic.start_time, hic.end_time
```

- Acceleration is the resultant in g, time in s.
- The integral uses the trapezoidal rule on a refined grid
  (`resolution_ms=0.1` by default); `examples/hic_convergence.py` shows
  the effect of the resolution.
- If the record is shorter than the window, a warning is issued and the
  whole record is used.

## 5. Peak and 3 ms clip

```python
from crashmetrics.acceleration import clip_3ms, peak

peak(t, a_res)                     # PeakResult(value, time)
clip_3ms(t, a_res)                 # cumulative 3 ms, g
clip_3ms(t, a_res, mode="continuous")
clip_3ms(t, a_res, duration_ms=5)  # any duration
```

The 3 ms clip is the highest level the signal reaches or exceeds for
3 ms:

- `mode="cumulative"` (default): 3 ms in total, possibly over several
  separate intervals. Exact for the linearly interpolated signal.
- `mode="continuous"`: 3 ms in one interval; never higher than the
  cumulative value.

Euro NCAP's "A3ms" is the cumulative definition.

## 6. Exceedance curves and force–duration limits

A force–duration (exceedance) curve gives, for each force level, how long
the signal stays at or above it. Regulations such as UN R94 limit the
neck and femur forces this way.

```python
from crashmetrics.acceleration import exceedance_check, exceedance_duration, exceedance_level

exceedance_duration(t, fz, level=2000.0)          # ms at or above 2 kN
exceedance_level(t, fz, duration_ms=35.0)         # level held for 35 ms

limit = ((0.0, 3300.0), (35.0, 2900.0), (60.0, 1100.0))   # (ms, N)
check = exceedance_check(t, fz, limit, direction="positive")
check.utilisation, check.passed, check.critical_duration_ms
```

`direction` chooses which part of the signal is assessed: `"positive"`,
`"negative"` (e.g. compression stored as negative force) or
`"absolute"`. `utilisation` above 1 means the limit is exceeded.

## Complete example

```python
--8<-- "examples/01_signals_hic.py"
```

Output:

```text
--8<-- "examples/expected/01_signals_hic.txt"
```
