"""Example 12: test-versus-CAE correlation with ISO/TS 18571 and the CC rating.

A sled test measured head, chest and pelvis accelerations at 20 kHz.
Three CAE model versions wrote the same channels at 10 kHz, starting
2 ms later. Each channel is rated with ISO/TS 18571, the corridor and
cross-correlation (CC) rating and classic error measures, the model
versions are ranked, and the ratings go into a feature table (synthetic
data).
"""

import numpy as np

from crashmetrics.correlation import compare
from crashmetrics.features import feature_table, flatten
from crashmetrics.signals import cfc_filter

rng = np.random.default_rng(12)
t_test = np.arange(0.0, 0.15, 5e-5)                     # test: 20 kHz
t_cae = np.arange(0.002, 0.15, 1e-4)                    # CAE: 10 kHz


def pulse(t, amp, start, width):
    phase = (t - start) / width
    return np.where((phase > 0) & (phase < 1), amp * np.sin(np.pi * phase), 0.0)


def channels(t, scale=1.0, delay=0.0, width=1.0, rebound=1.0):
    """Head, chest and pelvis x-acceleration in g."""
    return {
        "head": pulse(t, 55 * scale, 0.030 + delay, 0.060 * width)
        - pulse(t, 12 * rebound, 0.090 + delay, 0.030),
        "chest": pulse(t, 42 * scale, 0.025 + delay, 0.065 * width),
        "pelvis": pulse(t, 38 * scale, 0.020 + delay, 0.055 * width)
        + pulse(t, 10 * scale, 0.072 + delay, 0.020),
    }


# --- 1. Test (with sensor noise) and three model versions --------------------
test = {name: cfc_filter(t_test, x + rng.normal(0, 1.0, t_test.size), cfc=180)
        for name, x in channels(t_test).items()}
models = {
    "v1 baseline": channels(t_cae, scale=1.12, delay=0.004, width=0.92),
    "v2 belt": channels(t_cae, scale=1.04, delay=0.002, width=0.97),
    "v3 belt+seat": channels(t_cae, scale=1.01, delay=0.0005, width=1.0,
                             rebound=0.85),
}
models = {v: {n: cfc_filter(t_cae, x, cfc=180) for n, x in ch.items()}
          for v, ch in models.items()}

# --- 2. One channel in detail -------------------------------------------------
# Different time bases are fine: both signals are resampled to 10 kHz over
# the interval they share (here 2 to 150 ms), or over t_start..t_end.
c = compare(t_test, test["head"], models["v1 baseline"]["head"],
            comparison_time=t_cae, t_end=0.13, channel="head (v1)")
print(c.summary())

# --- 3. Every channel and model version --------------------------------------
print(f"\n{'model':13} {'channel':7} {'ISO':>6} {'grade':10} {'Z':>5} {'E_P':>5} "
      f"{'E_M':>5} {'E_S':>5} {'shift':>6} {'CC':>6} {'peak':>7}")
for version, cae in models.items():
    ratings = []
    for name in ("head", "chest", "pelvis"):
        r = compare(t_test, test[name], cae[name], comparison_time=t_cae, t_end=0.13)
        i = r.iso
        ratings.append(i.rating)
        print(f"{version:13} {name:7} {i.rating:6.3f} {i.grade:10} {i.corridor:5.2f} "
              f"{i.phase:5.2f} {i.magnitude:5.2f} {i.slope:5.2f} "
              f"{i.time_shift_ms:+5.1f}ms {r.cc.rating:6.3f} "
              f"{r.errors.peak_error:+7.1%}")
    print(f"{version:13} {'mean':7} {np.mean(ratings):6.3f}\n")

# --- 4. Ratings as features: one row per model version ----------------------
def extract(cae):
    return [flatten(compare(t_test, test[n], cae[n], comparison_time=t_cae,
                            t_end=0.13), prefix=f"{n}.") for n in test]


rows = feature_table(models, extract, id_column="model")
ratings = [k for k in rows[0] if k.endswith(("iso.rating", "cc.rating"))]
print(f"Feature table: {len(rows)} rows x {len(rows[0])} columns, e.g.",
      ", ".join(ratings[:3]), "...")
best = max(rows, key=lambda r: r["head.iso.rating"] + r["chest.iso.rating"]
           + r["pelvis.iso.rating"])
print("Best correlated model version:", best["model"])
