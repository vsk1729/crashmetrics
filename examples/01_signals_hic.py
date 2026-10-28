"""Example 1: from raw headform accelerations to HIC15, peak and 3 ms clip.

A synthetic headform impact in the LS-DYNA mm-ms-kg unit system
(accelerations in mm/ms^2, time in ms), with a little measurement noise.
Steps: convert units, CFC 1000 filter each axis, form the resultant,
then compute HIC15, the peak and the 3 ms clip.
"""

import numpy as np

from crashmetrics.acceleration import clip_3ms, peak
from crashmetrics.pedestrian import calculate_hic, hic_colour
from crashmetrics.signals import (
      cfc_filter,
      resample_uniform,
      resultant,
      to_g,
      to_seconds,
)

# --- 1. Input data (replace with your own channels) -------------------------
time_ms = np.arange(0.0, 30.0, 0.01)                     # 100 kHz sampling
pulse = np.where(time_ms < 12.0, np.sin(np.pi * time_ms / 12.0) ** 2, 0.0)
rng = np.random.default_rng(1)
ax = -1.15 * pulse + 0.01 * rng.standard_normal(time_ms.size)   # mm/ms^2
az = 0.55 * pulse + 0.01 * rng.standard_normal(time_ms.size)
ay = 0.01 * rng.standard_normal(time_ms.size)

# --- 2. Units: seconds and g -------------------------------------------------
t = to_seconds(time_ms, "ms")
components_g = [to_g(a, "mm/ms^2") for a in (ax, ay, az)]

# --- 3. Filter each axis with CFC 1000, then the resultant --------------------
filtered = [cfc_filter(t, a, cfc=1000) for a in components_g]
a_res = resultant(*filtered)

# --- 4. Head criteria ---------------------------------------------------------
hic = calculate_hic(t, a_res, window_ms=15.0)
a_peak = peak(t, a_res)
print(f"HIC15        : {hic.value:.0f} ({hic.start_time * 1000:.2f} to "
      f"{hic.end_time * 1000:.2f} ms) -> Euro NCAP colour {hic_colour(hic.value)}")
print(f"Peak         : {a_peak.value:.1f} g at {a_peak.time * 1000:.2f} ms")
print(f"3 ms clip    : {clip_3ms(t, a_res):.1f} g (cumulative)")
print(f"3 ms clip    : {clip_3ms(t, a_res, mode='continuous'):.1f} g (continuous)")

# --- 5. Non-uniform output? Resample before filtering -------------------------
t_irregular = np.unique(np.concatenate([t[::7], t[3::11]]))
a_irregular = np.interp(t_irregular, t, components_g[0])
t_uniform, a_uniform = resample_uniform(t_irregular, a_irregular, sample_rate=20_000.0)
print(f"Resampled    : {t_irregular.size} irregular samples -> "
      f"{t_uniform.size} samples at 20 kHz")
