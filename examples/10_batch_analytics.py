"""Example 10: batch processing a DOE into a results table (CSV, pandas, ML).

Each design variant (here: bonnet stiffness and under-bonnet clearance)
gives a headform acceleration. The loop computes the criteria for every
run and writes one row per run, ready for analytics, dashboards or as a
training set for a surrogate / machine-learning model.
"""

import csv
from dataclasses import asdict
from itertools import product

import numpy as np

from crashmetrics.acceleration import clip_3ms, peak
from crashmetrics.pedestrian import calculate_hic, hic_colour
from crashmetrics.signals import cfc_filter, resultant

t = np.arange(0.0, 0.03, 2e-5)                          # s, 50 kHz


def headform_pulse(stiffness, clearance_mm):
    """Toy model: stiffer bonnets peak higher; small clearance bottoms out."""
    duration = 0.012 / np.sqrt(stiffness)
    a = 95.0 * stiffness * np.where(t < duration, np.sin(np.pi * t / duration), 0.0)
    if clearance_mm < 70.0:                             # second hit on the engine
        hit = np.clip((t - 0.6 * duration) / 0.002, 0.0, 1.0)
        a = a + (70.0 - clearance_mm) * 6.0 * np.sin(np.pi * hit)
    return 0.9 * a, 0.436 * a                           # x and z components, g


rows = []
for stiffness, clearance in product([0.8, 1.0, 1.2, 1.4], [50.0, 70.0, 90.0]):
    # Filter each component, then form the resultant (never filter a resultant).
    ax, az = headform_pulse(stiffness, clearance)
    a = resultant(cfc_filter(t, ax, cfc=1000), cfc_filter(t, az, cfc=1000))
    hic = calculate_hic(t, a)
    rows.append({
        "stiffness": stiffness,
        "clearance_mm": clearance,
        "hic15": round(hic.value, 1),
        "hic_window_ms": round((hic.end_time - hic.start_time) * 1000, 2),
        "peak_g": round(peak(t, a).value, 1),
        "clip_3ms_g": round(clip_3ms(t, a), 1),
        "colour": hic_colour(hic.value),
    })

# --- 1. Write the table ---------------------------------------------------------
with open("crashmetrics_doe_results.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print(f"Wrote {len(rows)} runs to crashmetrics_doe_results.csv")
print(f"{'stiffness':>9} {'clearance':>9} {'HIC15':>7} "
      f"{'peak g':>7} {'3 ms g':>7}  colour")
for r in rows:
    print(f"{r['stiffness']:9.1f} {r['clearance_mm']:9.0f} {r['hic15']:7.0f} "
          f"{r['peak_g']:7.1f} {r['clip_3ms_g']:7.1f}  {r['colour']}")

# --- 2. Quick analytics with numpy (pandas works the same way) ---------------
x = np.array([[r["stiffness"], r["clearance_mm"]] for r in rows])
y = np.array([r["hic15"] for r in rows])
for i, name in enumerate(["stiffness", "clearance_mm"]):
    print(f"Correlation of HIC15 with {name:12s}: {np.corrcoef(x[:, i], y)[0, 1]:+.2f}")
coef, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(y)), x]), y, rcond=None)
print(f"Linear surrogate: HIC15 = {coef[0]:.0f} {coef[1]:+.0f} x stiffness "
      f"{coef[2]:+.1f} x clearance_mm")

# --- 3. Every result object is a dataclass: asdict() gives a plain dict -------
ax, az = headform_pulse(1.0, 90.0)
a = resultant(cfc_filter(t, ax, cfc=1000), cfc_filter(t, az, cfc=1000))
result = calculate_hic(t, a)
print({key: round(value, 5) for key, value in asdict(result).items()})

# With pandas installed:
#   import pandas as pd
#   df = pd.read_csv("crashmetrics_doe_results.csv")
#   df.pivot(index="stiffness", columns="clearance_mm", values="hic15")
