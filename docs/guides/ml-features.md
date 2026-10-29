# Features for machine learning

Module: `crashmetrics.features`.

A model is only as good as its training table. `crashmetrics.features`
turns every run into one row of numbers: the injury criteria as targets
or labels, the shape of each signal as features, and the design
parameters alongside. Because every run goes through the same, protocol
-correct calculation, test and CAE rows are consistent with each other.

Only NumPy is needed. pandas is used by `to_dataframe` if it is
installed; any ML library (scikit-learn, XGBoost, PyTorch) takes the
output of `to_matrix` directly.

## Step 1: features of one signal

`signal_features` describes the shape of any channel: an acceleration,
a force, a deflection, a moment.

```python
from crashmetrics.features import signal_features

f = signal_features(t, chest_deflection, prefix="chest_")
f["chest_peak_abs"], f["chest_rise_ms"], f["chest_width50_ms"]
```

| Feature | Meaning |
| --- | --- |
| `max`, `min`, `peak_abs` | Largest, smallest and largest absolute value |
| `t_max_ms`, `t_min_ms`, `t_peak_abs_ms` | When they occur, ms from the first sample |
| `mean`, `rms`, `std` | Time-averaged level and spread over the record |
| `integral`, `abs_integral` | Area under the signal (for an acceleration in m/s² this is the velocity change) |
| `onset_ms`, `end_ms`, `active_ms` | First and last time above 5 % of the peak, and the time between |
| `rise_ms` | 10 % to 90 % rise time before the peak |
| `width50_ms` | Total time above half the peak |
| `excursions50` | Separate excursions above half the peak: 1 for a single pulse, 2 or more for multiple impacts (for example bottoming out) |
| `centroid_ms`, `energy50_ms` | Time centroid of the signal energy, and when half of it has accumulated (early or late loading) |
| `dominant_hz`, `spectral_centroid_hz` | Strongest frequency and power-weighted mean frequency |

Timing and width features use the magnitude, so they do not depend on
the channel's sign convention. A feature that cannot be defined (the
rise time of an all-zero channel) is `nan`, and every call returns the
same columns in the same order.

!!! tip "Filter first"
    Pass filtered channels (CFC 1000 for head accelerations, CFC 180 or
    60 for pulses and so on). Raw noise inflates the peak, rise and
    frequency features.

## Step 2: criteria plus shape for a load case

The load-case extractors combine the criteria with the shape features:

```python
from crashmetrics.features import head_features, pulse_features

head_features(t, a_resultant_g)
# {'head_hic15': 654.1, 'head_hic15_t1_ms': 6.65, 'head_hic15_t2_ms': 13.35,
#  'head_hic36': ..., 'head_a3ms': 106.9, 'head_peak_g': 120.0,
#  'head_t_peak_ms': 10.0, 'head_colour': 'yellow', 'head_rise_ms': ..., ...}

pulse_features(t, accel_x_ms2, v0=50 / 3.6)
# {'pulse_olc_g': ..., 'pulse_delta_v': ..., 'pulse_restitution': ...,
#  'pulse_max_crush_mm': ..., 'pulse_peak_decel_g': ..., 'pulse_rise_ms': ...}
```

- `head_colour` is the Euro NCAP headform colour of HIC15, a ready-made
  label for classification models.
- `head_hic36` is `nan` if the record is shorter than 36 ms (no warning
  per run).
- For any other criterion, put its result object in the row: `flatten`
  (next step) turns it into columns.

## Step 3: any result object as columns

`flatten` turns a result, however nested, into a flat dict:

```python
from crashmetrics.features import flatten

flatten(nij(t, fz, my, fx=fx), prefix="nij.")
# {'nij.value': 0.36, 'nij.category': 'NTE', ...}

flatten(score_mpdb(...))     # about 350 columns, for example
# 'points', 'occupants.driver.points',
# 'occupants.driver.regions.head_neck.points',
# 'occupants.driver.regions.head_neck.band', ...
```

Dataclasses and dicts are walked recursively, short tuples get index
keys, and NumPy arrays (time histories) are left out, so every value is
a single number, string, bool or `None`.

## Step 4: one row per run

`feature_table` runs your extractor on every run:

```python
from crashmetrics.features import feature_table, head_features
from crashmetrics.signals import cfc_filter, resultant


def extract(folder):
    t, ax, ay, az = load_headform(folder)          # your loader
    a = resultant(*(cfc_filter(t, c, cfc=1000) for c in (ax, ay, az)))
    return head_features(t, a)


runs = {p.name: p for p in sorted(Path("doe").iterdir())}
params = {"run01": {"thickness": 0.7, "clearance_mm": 65}, ...}
rows = feature_table(runs, extract, params=params)
```

- `runs` is a dict `{name: input}` or a list of `(name, input)` pairs;
  the input is whatever your extractor takes (a folder, a file, arrays).
  For LS-DYNA run folders, `load_headform` can be the `read_nodout`
  loader in [Loading your data](../getting-started/loading-data.md#ls-dyna-ascii-output),
  and `read_run(folder)` gives contact, section, belt and airbag
  channels for more features ([LS-DYNA ASCII output](lsdyna-ascii.md)).
- `params` adds the design parameters to each row, so the table is
  directly a training set.
- The extractor may return a dict, a result object or a list of them
  (for example head, neck and chest features of the same run).
- A run that raises an exception does not stop the batch: its row gets
  an `error` column (`"ValueError: signal must contain only finite
  values."`). Use `on_error="raise"` while developing the extractor.

## Step 5: to CSV, pandas or a model

```python
from crashmetrics.features import to_dataframe, to_matrix, write_csv

write_csv(rows, "features.csv")             # all columns, missing cells empty

df = to_dataframe(rows)                     # needs pandas
df[df.error.isna()].describe()

names, X = to_matrix([r for r in rows if "error" not in r])
y = X[:, names.index("head_hic15")]
```

`to_matrix` keeps the numeric columns (bools as 0/1, missing values as
`nan`), or the columns you name, in that order. Then, for example with
scikit-learn:

```python
from sklearn.ensemble import RandomForestRegressor

inputs = ["thickness", "clearance_mm", "speed_kph"]
_, X = to_matrix(good_rows, inputs)
model = RandomForestRegressor().fit(X, y)
```

## Good practice for crash training data

1. **Remove failed and suspicious runs before training.** Check the
   `error` column, and the LS-DYNA energy checks and termination status
   ([LS-DYNA energy checks](lsdyna-energy.md)) for CAE runs.
2. **Keep targets out of the inputs.** If you predict HIC15, do not
   train on HIC36, the 3 ms clip or the peak of the same signal: they
   are other views of the target.
3. **Hold out runs** (or whole design variants) to check a model. With
   few runs, a physically shaped model (for example a power law in log
   space, as in the example) usually beats a flexible one.
4. **Same pipeline for test and CAE.** Filter classes, units and time
   zero must match, otherwise the model learns the difference between
   the sources.

## Complete example

Sixteen headform runs over stiffness, clearance and speed, plus one
broken run. The script builds the feature table, writes it to CSV, looks
at the labels and correlations, and fits a surrogate checked on held-out
runs:

```python
--8<-- "examples/11_ml_features.py"
```

Output:

```text
--8<-- "examples/expected/11_ml_features.txt"
```

The fitted speed exponent comes out near 5. That is what physics
expects: acceleration grows with speed squared and HIC with acceleration
to the power 2.5.
