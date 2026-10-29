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

## LS-DYNA ASCII output

crashmetrics reads the LS-DYNA ASCII files itself: `nodout`, `rcforc`,
`sleout`, `secforc`, `rwforc`, `sbtout`, `deforc`, `jntforc`, `abstat`,
`rbdout`, `spcforc` and `swforc` (see
[LS-DYNA ASCII output](../guides/lsdyna-ascii.md)), and `glstat`,
`matsum` and `d3hsp` for the [energy checks](../guides/lsdyna-energy.md).

A headform or head CG node from `nodout`, ready for HIC (LS-DYNA writes
at the first step after each output time, so resample before
filtering):

```python
from pathlib import Path

from crashmetrics.lsdyna import read_nodout
from crashmetrics.signals import resample_uniform, to_g, to_seconds


def load_headform(run, node=1001):
    """Time (s) and x, y, z acceleration (g) of a node in an LS-DYNA nodout (mm, ms)."""
    nodout = read_nodout(Path(run) / "nodout", ids=[node])
    t = to_seconds(nodout.time, "ms")
    axes = [to_g(nodout.channel(f"{c}_acceleration"), "mm/ms^2") for c in "xyz"]
    resampled = [resample_uniform(t, a, sample_rate=10_000.0) for a in axes]
    return resampled[0][0], *(a for _, a in resampled)


t, ax, ay, az = load_headform("run01")
```

Every ASCII file of a run at once, or as CSV for Excel:

```python
from crashmetrics.lsdyna import read_run

run = read_run("run01")                          # {"nodout": ..., "rcforc": ..., ...}
wall_force = run["rwforc"].channel("normal_force", 1)
```

```bash
crashmetrics-ascii run01 --csv tables
```

Curves exported from LS-PrePost or other post-processors as two-column
text (time, value) load directly:

```python
t_ms, ax = np.loadtxt("headform_ax.txt", comments=("#", "$"), unpack=True)
```

!!! note "binout"
    For binary `binout` files, read the variables with a binout reader
    such as the BSD-licensed `lasso-python` package, then pass the arrays
    to crashmetrics; the channel names of the ASCII readers are the
    binout variable names. Or write ASCII output instead
    (`*DATABASE_<NAME>` with `BINARY = 1` or `3`).

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
