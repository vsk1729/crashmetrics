# HIC accuracy and performance

Module: `crashmetrics.pedestrian.hic` (`calculate_hic`).

HIC is a maximum over all intervals `[t1, t2]` no longer than the window
(15 or 36 ms):

```text
HIC = max (t2 - t1) * [ 1 / (t2 - t1) * integral of a(t) dt from t1 to t2 ] ^ 2.5
```

Protocols define this formula but not how to search for the maximum.
`calculate_hic` offers two methods. Both treat the record as linearly
interpolated between samples, and both integrate that signal exactly.

| Method | End points searched | Result | Use |
| --- | --- | --- | --- |
| `"grid"` (default) | A uniform grid (`resolution_ms`, 0.1 ms by default), the samples and the points one window before them | Lower bound of the exact value, usually within 0.05 % | Everyday post-processing, batch runs |
| `"exact"` | Continuous: any `t1`, `t2` | The maximum for the interpolated signal, to rounding | Reference values, verification, tie-breaking near a limit |

```python
from crashmetrics.pedestrian import calculate_hic

calculate_hic(t, a_res)                     # grid search, 0.1 ms
calculate_hic(t, a_res, method="exact")     # exact maximum
```

## How the exact method works

On each pair of linear segments the integral is a quadratic in `t1` and
`t2`, so HIC is smooth there and its maximum is one of:

1. an **interior stationary point**, where
   `a(t1) = a(t2) = 0.6 * (integral / duration)`;
2. a **window-length** interval (`t2 - t1` equal to the window), where
   `a(t1) = a(t2)`;
3. an interval starting or ending at the **record limits**;
4. a corner of these cases (a sample or a sample one window away).

On linear segments every condition reduces to a quadratic equation,
solved in closed form. Candidate segment pairs are pruned by a
branch-and-bound bound (an upper limit of HIC from the largest
acceleration and the integral over a block), seeded with the grid
result, so long records stay fast.

## Verification

- **Closed forms.** Constant acceleration gives `window * a^2.5`. A
  symmetric triangle of peak `P` and half width `T` has its optimum at
  the interval of half width `4T/7` around the peak, with
  `HIC = (8T/7) (5P/7)^2.5`. The exact method reproduces both to
  `1e-10` and finds the end points to `1e-12` s.
- **Independent searches.** On random piecewise-linear signals, the
  exact value was never below the grid result, a brute-force search of
  all pairs of a 0.01 ms grid, or a multistart Nelder-Mead optimisation
  (40 signals during development, 8 in the test suite).
- **Consistency.** The value equals HIC recomputed independently from
  the returned `start_time` and `end_time`.

The tests are in `tests/test_hic_exact.py` and
`tests/test_hic_reference.py`.

## Accuracy of the grid search

Relative shortfall of the grid search against the exact HIC15, for
pulses sampled at 10 kHz (the last one is a real LS-DYNA nodout of a
helmeted Hybrid III head drop, CFC 1000):

| Pulse | Exact HIC15 | 0.4 ms | 0.2 ms | 0.1 ms | 0.05 ms |
| --- | --- | --- | --- | --- | --- |
| Half-sine 120 g, 10 ms | 653.94 | 2.3e-4 | 2.3e-4 | 2.3e-4 | 1.1e-7 |
| Triangle 90 g, 8 ms | 151.47 | 2.7e-5 | 2.7e-5 | 2.7e-5 | 2.7e-5 |
| Double peak 70 + 95 g | 255.21 | 4.2e-4 | 4.2e-4 | 4.2e-4 | 3.7e-6 |
| Long low pulse 45 g, 30 ms | 156.71 | 0 | 0 | 0 | 0 |
| Helmet drop (real nodout) | 194.62 | 7.4e-5 | 7.4e-5 | 7.4e-5 | 7.4e-5 |

- At 10 kHz the samples are themselves candidates, so resolutions of
  0.1 ms and coarser give the same result; a finer grid adds points
  between the samples.
- On smooth pulses the shortfall is below 0.05 %, far below test
  scatter. On rough random signals with few samples it reached 0.6 %.
- The grid result is always a lower bound: if it is just under a limit,
  the exact value may be just over it. Use `method="exact"` there.

## Run time

A half-sine pulse in records of different length, Python 3.13 on one
core of a 2.1 GHz Xeon (indicative only):

| Samples | Sample rate | Grid, 0.1 ms | Exact |
| --- | --- | --- | --- |
| 1 500 | 10 kHz | 0.01 s | 0.02 s |
| 6 000 | 20 kHz | 0.09 s | 0.13 s |
| 100 000 | 100 kHz | 0.08 s | 0.5 s |
| 250 000 | 500 kHz | 0.04 s | 8 s |

The grid search is vectorised over the interval length; version 0.15.0
needed 5.4 s for 100 000 samples. Records of more than 20 000 samples
that are over four times as dense as the grid use the grid points only
as candidates (the integral stays exact), so very long, densely sampled
records stay fast. The exact method needs memory in proportion to the
record (about 70 MB for 250 000 samples).

## Reproduce

```bash
python examples/hic_convergence.py
```

```python
--8<-- "examples/hic_convergence.py"
```

## References

- J. Versace (1971). A review of the severity index. SAE 710881.
- SAE J1727. Injury Calculations Guidelines.
