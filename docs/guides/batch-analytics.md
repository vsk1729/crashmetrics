# Batch runs, analytics and ML

!!! tip "Building a training set?"
    [Features for machine learning](ml-features.md) does the loop below
    for you: `feature_table` adds signal shape features, design
    parameters and per-run error handling.

crashmetrics returns plain numbers and small dataclasses, so results
drop straight into tables. This page shows how to process many runs (a
DOE, a variant study, a test series) into one results table for
analytics, dashboards or machine-learning models.

## The pattern

```python
import csv
from pathlib import Path

rows = []
for run in sorted(Path("doe").iterdir()):           # one folder per run
    t, ax, ay, az = load_headform(run)              # your loader
    a = resultant(*(cfc_filter(t, c, cfc=1000) for c in (ax, ay, az)))
    hic = calculate_hic(t, a)
    rows.append({
        "run": run.name,
        "hic15": hic.value,
        "peak_g": peak(t, a).value,
        "clip_3ms_g": clip_3ms(t, a),
        "colour": hic_colour(hic.value),
    })

with open("results.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
```

For LS-DYNA runs, a `load_headform` built on `read_nodout` is in
[Loading your data](../getting-started/loading-data.md#ls-dyna-ascii-output),
and `read_run(run)` reads every ASCII file of a run (rcforc, secforc,
sbtout ...) in one call; see [LS-DYNA ASCII output](lsdyna-ascii.md).

Three habits make this robust:

1. **One row per run, one column per quantity**: easy to filter, plot
   and join with design parameters.
2. **Keep the design parameters in the same row** (thickness,
   stiffness, clearance, variant name): the table is then directly a
   training set.
3. **Catch failures per run** so one bad file does not stop the batch:

    ```python
    try:
        ...
    except ValueError as error:
        rows.append({"run": run.name, "error": str(error)})
    ```

## Results as dictionaries

Every result object is a dataclass:

```python
from dataclasses import asdict

asdict(calculate_hic(t, a))          # {'value': ..., 'start_time': ..., 'end_time': ...}
asdict(nij(t, fz, my, fx=fx))        # includes the category and per-category maxima
```

Scores nest further, e.g. `mpdb.occupants["driver"].regions["chest_abdomen"].points`;
pick the fields you want into your row.

## Analytics with pandas

```python
import pandas as pd

df = pd.read_csv("results.csv")
df.describe()                                            # spread of every criterion
df.sort_values("hic15", ascending=False).head(10)       # worst runs
df.pivot(index="stiffness", columns="clearance_mm", values="hic15")
df.groupby("colour").size()                              # colour distribution
df.corr(numeric_only=True)["hic15"]                      # what drives HIC
```

Export to Excel for a report with `df.to_excel("results.xlsx")`
(needs `openpyxl`).

## Data for surrogate and ML models

With design parameters and results in one table, a surrogate is a few
lines. A linear fit with NumPy:

```python
import numpy as np

X = df[["stiffness", "clearance_mm"]].to_numpy()
y = df["hic15"].to_numpy()
coef, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(y)), X]), y, rcond=None)
```

or any scikit-learn model:

```python
from sklearn.ensemble import RandomForestRegressor

model = RandomForestRegressor().fit(X, y)
model.predict([[1.1, 80.0]])
```

Because the criteria are computed the same way for every run (and for
test and CAE alike), the labels are consistent, which matters more for
a model than the choice of algorithm.

## Complete example

A 12-run DOE over bonnet stiffness and under-bonnet clearance, written to
CSV, with correlations and a linear surrogate:

```python
--8<-- "examples/10_batch_analytics.py"
```

Output:

```text
--8<-- "examples/expected/10_batch_analytics.txt"
```
