# Test-versus-CAE correlation

Module: `crashmetrics.correlation`.

How well does the simulation match the test? Overlaying curves and
judging by eye is subjective and does not scale to hundreds of
channels. This module rates a CAE signal against a test signal with one
number between 0 (no match) and 1 (identical), using:

- **ISO/TS 18571:2024**: the ISO objective rating for vehicle safety
  signals (corridor, phase, magnitude, slope), with a grade from
  *excellent* to *poor*.
- **CC rating**: corridor plus cross-correlation (phase, size, shape),
  the method of Gehre et al. (2009) that is widely used for dummy and
  human body model validation.
- **Classic error measures**: peak and peak-time errors, RMSE, the
  correlation coefficient, Sprague & Geers and Russell errors.

All three take the same inputs, and `compare` runs them together.

## Step 1: prepare the two signals

```python
from crashmetrics.signals import cfc_filter

test = cfc_filter(t_test, head_ax_test, cfc=180)
cae = cfc_filter(t_cae, head_ax_cae, cfc=180)
```

- **Same quantity, unit, sign convention and filter class** for both
  signals: the rating cannot tell a filter or sign mistake from a model
  error.
- **Same time zero** (T0). The time bases may differ: test data at
  20 kHz and CAE output at 10 kHz is fine. Both are resampled to a
  common 0.1 ms grid (the 10 kHz the standard assumes) over the
  interval they share.
- The **reference** is the signal you trust (the test), the
  **comparison** the one being rated. The ratings are not symmetric:
  corridors are sized from the reference.

## Step 2: choose the interval of evaluation

```python
from crashmetrics.correlation import iso18571

r = iso18571(t_test, test, cae, comparison_time=t_cae, t_start=0.0, t_end=0.13)
```

Without `t_start` and `t_end`, the whole common interval is used. Choose
the interval to cover the event and little else: a long quiet tail
where both signals are near zero inflates the corridor score. Use the
same interval for every model version you compare.

## Step 3: read the ISO/TS 18571 rating

```python
r.rating, r.grade                  # 0.897, 'good'
r.corridor, r.phase, r.magnitude, r.slope
r.time_shift_ms                    # +1.8: the CAE is 1.8 ms late
```

| Score | Weight | What it measures |
| --- | --- | --- |
| Corridor Z | 0.4 | Share of the curve inside corridors around the test: inner ±5 %, outer ±50 % of the test's absolute maximum (quadratic in between) |
| Phase E_P | 0.2 | Time shift with the best correlation; 1 for no shift, 0 at 20 % of the interval |
| Magnitude E_M | 0.2 | Amplitude error after removing the shift and aligning the curves with dynamic time warping; 0 at 50 % error |
| Slope E_S | 0.2 | Error of the smoothed derivative (shape and rise rates); 0 at 200 % error |

| Grade | Overall rating R |
| --- | --- |
| excellent | R > 0.94 |
| good | 0.80 < R ≤ 0.94 |
| fair | 0.58 < R ≤ 0.80 |
| poor | R ≤ 0.58 |

The sub-scores tell you *what* to fix: a low phase score with a high
magnitude score points to timing (contact, belt slack, airbag
deployment); a low magnitude score to stiffness or mass; a low slope
score to the shape of the loading.

!!! info "Verified against an independent implementation"
    The ISO/TS 18571 rating reproduces the open-source
    `objective-rating-metrics` package of the Vehicle Safety Institute,
    TU Graz, to machine precision on 40 crash-like signal pairs,
    including time-warping ties on flat signals. The test suite checks
    five of these cases.

## Step 4: the CC rating and the error measures

```python
from crashmetrics.correlation import cc_rating, error_measures

c = cc_rating(t_test, test, cae, comparison_time=t_cae, t_end=0.13)
c.rating, c.corridor, c.phase, c.size, c.shape

e = error_measures(t_test, test, cae, comparison_time=t_cae, t_end=0.13)
e.peak_error, e.peak_time_error_ms, e.nrmse, e.sprague_geers_comprehensive
```

**CC rating** = 0.5 × corridor + 0.5 × cross-correlation, where the
cross-correlation rating combines:

- **phase**: 1 for a shift up to 1 % of the interval, 0 from 12 %;
- **size**: ratio of the smaller to the larger signal energy (∑x²);
- **shape**: the normalised cross-correlation at the best shift.

!!! warning "Check the settings against the tool your project uses"
    The method is published (Gehre, Gades and Wernicke, ESV 2009) and is
    best known from PDB's CORA tool. `cc_rating` is an independent
    implementation, not affiliated with PDB. Settings of this method
    differ between tools and versions and are often customised; the
    defaults in `CCParameters` are the commonly cited values and have
    not been checked against PDB's manual. If your project compares
    with another tool, rate a few channels with both, set
    `CCParameters` to match, and report the settings with the scores.
    Automatic intervals and standard-deviation corridors (offered by
    some tools) are not implemented.

**Error measures** (0 is perfect for the errors, 1 for the correlation):

| Measure | Meaning |
| --- | --- |
| `peak_error` | (\|peak CAE\| − \|peak test\|) / \|peak test\|: +0.10 means the CAE peak is 10 % high |
| `peak_time_error_ms` | CAE peak time minus test peak time |
| `rmse`, `nrmse`, `mae`, `max_error` | Point-by-point differences; `nrmse` is the RMSE divided by the test's absolute maximum |
| `correlation`, `r_squared` | Pearson correlation and coefficient of determination, without a time shift |
| `sprague_geers_*` | Magnitude M, phase P and comprehensive C = √(M² + P²) (Sprague & Geers 2004) |
| `russell_*` | Magnitude, phase and comprehensive error (Russell 1997) |

## Step 5: all at once, many channels, many model versions

```python
from crashmetrics.correlation import compare

c = compare(t_test, test, cae, comparison_time=t_cae, t_end=0.13, channel="head (v1)")
print(c.summary())
```

```text
head (v1): ISO 18571 0.897 (good; corridor 0.901, phase 0.930, magnitude 0.951, slope 0.800, shift +1.8 ms)
head (v1): CC rating 0.922 (corridor 0.901, phase 0.963, size 0.870, shape 0.996)
head (v1): Errors: peak +11.8% at +0.9 ms, NRMSE 0.075, Sprague & Geers C 0.084
```

For a model version with many channels, rate each channel and report
the mean (and the worst channel). ISO/TS 18571 rates one signal pair; it
does not prescribe how to combine channels, so state your weighting.

## Correlation as features for ML

The ratings are numbers like any other criterion, so they fit straight
into a [feature table](ml-features.md), for example to track model
quality across versions or to learn which design changes move the
model away from the test:

```python
from crashmetrics.features import feature_table, flatten

def extract(cae):
    return [flatten(compare(t_test, test[ch], cae[ch], comparison_time=t_cae),
                    prefix=f"{ch}.") for ch in test]

rows = feature_table(model_versions, extract, id_column="model")
# columns: head.iso.rating, head.iso.phase, head.cc.size, head.errors.peak_error, ...
```

## Complete example

A sled test with head, chest and pelvis accelerations against three
model versions, with different time bases:

```python
--8<-- "examples/12_test_cae_correlation.py"
```

Output:

```text
--8<-- "examples/expected/12_test_cae_correlation.txt"
```

## References

- ISO/TS 18571:2024, *Road vehicles — Objective rating metric for
  non-ambiguous signals* (and the 2014 first edition).
- C. Gehre, H. Gades, P. Wernicke: *Objective rating of signals using
  test and simulation responses*, ESV 2009, paper 09-0407 (the corridor
  and cross-correlation method).
- L. E. Schwer: *Validation metrics for response histories:
  perspectives and case studies*, Engineering with Computers 23 (2007),
  covering the Sprague & Geers and Russell measures.
