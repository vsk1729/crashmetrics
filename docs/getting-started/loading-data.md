# Loading your data

crashmetrics does not need a special file format: any time array and
channel arrays work. This page shows the common ways to get them.

## CSV or text files

A CSV file with a header row and one column per channel:

```text
time_ms,head_ax,head_ay,head_az
0.00,0.0012,-0.0003,0.0007
0.01,0.0015,-0.0001,0.0009
...
```

```python
import numpy as np

data = np.genfromtxt("headform_run01.csv", delimiter=",", names=True)
time_ms = data["time_ms"]
ax, ay, az = data["head_ax"], data["head_ay"], data["head_az"]
```

With pandas:

```python
import pandas as pd

df = pd.read_csv("headform_run01.csv")
time_ms = df["time_ms"].to_numpy()
ax = df["head_ax"].to_numpy()
```

Excel works the same way with `pd.read_excel("file.xlsx", sheet_name="Sheet1")`
(needs `openpyxl`).

## LS-DYNA ASCII output (nodout, xy curves)

Curves exported from LS-PrePost or other post-processors as two-column
text (time, value) load directly:

```python
t_ms, ax = np.loadtxt("headform_ax.txt", comments=("#", "$"), unpack=True)
```

For data written in blocks (for example `nodout`), extract the node's
rows with your post-processor or a short script, then pass the arrays.
crashmetrics reads LS-DYNA **energy** output (`glstat`, `matsum`,
`d3hsp`) itself; see [LS-DYNA energy checks](../guides/lsdyna-energy.md).

!!! note "binout"
    For binary `binout` files, read the variables with a binout reader
    such as the BSD-licensed `lasso-python` package, then pass the arrays
    to crashmetrics.

## Physical test data

Test labs deliver channels as ISO-MME (ISO/TS 13499) or as CSV / Excel
exports. Export the channels you need with their time base, then load
them as above. Make sure you know:

- whether the channels are already filtered (and with which CFC);
- the sign convention of each channel (SAE J211 in Euro NCAP);
- where time zero (T0, first contact) is.

## Check the data before you calculate

```python
import numpy as np

t = time_ms / 1000.0
print("samples:", t.size, " duration:", t[-1] - t[0], "s")
print("sample rate:", 1.0 / np.median(np.diff(t)), "Hz")
print("uniform:", np.allclose(np.diff(t), np.diff(t)[0], rtol=1e-3))
print("finite:", np.all(np.isfinite(ax)))
```

If the time step is not uniform, resample before filtering:

```python
from crashmetrics.signals import resample_uniform

t_uniform, ax_uniform = resample_uniform(t, ax, sample_rate=20_000.0)
```

## Many runs at once

Put each run in its own folder (or name files by run), loop over them
and collect one row of results per run. The
[batch and analytics guide](../guides/batch-analytics.md) shows the full
pattern with a results table.

Next: [units, signs and filters](conventions.md).
