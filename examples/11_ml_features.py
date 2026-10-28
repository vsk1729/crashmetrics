"""Example 11: an ML-ready feature table from many runs.

Sixteen headform runs over bonnet stiffness, under-bonnet clearance and
impact speed (synthetic data). `feature_table` runs one extractor per
run, joins the design parameters, records a failing run instead of
stopping, and the table goes to CSV, pandas or a NumPy matrix for a
model.
"""

from itertools import product

import numpy as np

from crashmetrics.features import (
    feature_table,
    flatten,
    head_features,
    to_matrix,
    write_csv,
)
from crashmetrics.signals import cfc_filter, resultant

t = np.arange(0.0, 0.04, 2e-5)                          # s, 50 kHz
rng = np.random.default_rng(11)


def simulate(stiffness, clearance_mm, speed_kph):
    """Toy headform model: x and z accelerations in g."""
    duration = 0.012 / np.sqrt(stiffness)
    scale = (speed_kph / 40.0) ** 2
    a = 95.0 * stiffness * scale * np.where(
        t < duration, np.sin(np.pi * t / duration), 0.0)
    if clearance_mm < 70.0:                             # second hit on the engine
        hit = np.clip((t - 0.6 * duration) / 0.002, 0.0, 1.0)
        a = a + (70.0 - clearance_mm) * 6.0 * scale * np.sin(np.pi * hit)
    a = a + rng.normal(0.0, 2.0, t.size)                # sensor noise
    return 0.9 * a, 0.436 * a


# --- 1. The runs and their design parameters ----------------------------------
runs, params = {}, {}
levels = product([0.8, 1.0, 1.2, 1.4], [50.0, 80.0], [35.0, 40.0])
for i, (stiffness, clearance, speed) in enumerate(levels, start=1):
    name = f"run{i:02d}"
    runs[name] = simulate(stiffness, clearance, speed)
    params[name] = {"stiffness": stiffness, "clearance_mm": clearance,
                    "speed_kph": speed}
runs["run17"] = (np.full(t.size, np.nan), np.zeros(t.size))   # a broken channel
params["run17"] = {"stiffness": 1.0, "clearance_mm": 80.0, "speed_kph": 40.0}


# --- 2. One extractor for one run: filter, resultant, features ---------------
def extract(channels):
    ax, az = channels
    a = resultant(cfc_filter(t, ax, cfc=1000), cfc_filter(t, az, cfc=1000))
    return head_features(t, a)


rows = feature_table(runs, extract, params=params)
columns = write_csv(rows, "crashmetrics_features.csv")
print(f"{len(rows)} runs x {len(columns)} columns -> crashmetrics_features.csv")
print("Columns:", ", ".join(columns[:7]), "...", ", ".join(columns[-3:]))
print("Failed  :", [(r["run"], r["error"]) for r in rows if "error" in r])

# --- 3. A quick look at the table ---------------------------------------------
print(f"\n{'run':6} {'stiff':>5} {'clear':>5} {'kph':>4} {'HIC15':>6} "
      f"{'rise ms':>7} {'width ms':>8} {'centroid':>8}  colour")
good = [r for r in rows if "error" not in r]
for r in good[::3]:
    print(f"{r['run']:6} {r['stiffness']:5.1f} {r['clearance_mm']:5.0f} "
          f"{r['speed_kph']:4.0f} {r['head_hic15']:6.0f} {r['head_rise_ms']:7.2f} "
          f"{r['head_width50_ms']:8.2f} {r['head_centroid_ms']:8.2f}  "
          f"{r['head_colour']}")
labels = [r["head_colour"] for r in good]
print("Colour counts:", {c: labels.count(c) for c in sorted(set(labels))})

# --- 4. Which signal features go with HIC15? ---------------------------------
names, x = to_matrix(good)
y = x[:, names.index("head_hic15")]
criteria = ("head_hic", "head_a3ms", "head_peak_g")    # criteria, not shape
amplitude = ("head_mean", "head_rms", "head_std", "head_integral",
             "head_abs_integral", "head_min")
shape = [n for n in names if n.startswith("head_")
         and not n.startswith(criteria) and n not in amplitude]
corr = {n: np.corrcoef(x[:, names.index(n)], y)[0, 1] for n in shape
        if np.std(x[:, names.index(n)]) > 0}
top = sorted(corr.items(), key=lambda item: -abs(item[1]))[:4]
print("\nStrongest shape features vs HIC15:",
      ", ".join(f"{n} {c:+.2f}" for n, c in top))

# --- 5. A surrogate from the design parameters, checked on held-out runs ------
# HIC grows roughly as acceleration^2.5, so fit log(HIC) (a power law);
# with acceleration ~ speed^2 the speed exponent should come out near 5.
design = ["stiffness", "clearance_mm", "speed_kph"]
_, xd = to_matrix(good, design)
features = np.column_stack(
    [np.ones(len(y)), np.log(xd[:, 0]), xd[:, 1], np.log(xd[:, 2])])
test = np.arange(len(y)) % 4 == 0                       # every 4th run held out
coef, *_ = np.linalg.lstsq(features[~test], np.log(y[~test]), rcond=None)
pred = np.exp(features[test] @ coef)
r2 = 1 - np.sum((y[test] - pred) ** 2) / np.sum((y[test] - y[test].mean()) ** 2)
print(f"Surrogate log(HIC15) ~ log(stiffness) + clearance + log(speed): "
      f"exponents {coef[1]:.2f} (stiffness), {coef[3]:.2f} (speed)")
print(f"Checked on {int(test.sum())} held-out runs: R^2 = {r2:.2f}, "
      f"mean error {np.mean(np.abs(y[test] - pred)):.0f} HIC")

# --- 6. Any result object becomes columns with flatten() ---------------------
print("\nflatten(features of run01) has", len(flatten(rows[0])), "columns;",
      "nested scores give keys like 'occupants.driver.regions.head_neck.points'")

# With pandas:
#   from crashmetrics.features import to_dataframe
#   df = to_dataframe(rows)
#   df.groupby("head_colour").mean(numeric_only=True)
