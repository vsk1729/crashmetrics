
"""Check HIC convergence as the refined time step decreases."""

import time

import numpy as np

from crashmetrics.pedestrian.hic import calculate_hic

# Synthetic crash pulse; this is not experimental vehicle data.
time_s = np.arange(0.0, 0.10001, 0.0005)

acceleration_g = 100.0 * np.sin(np.pi * time_s / 0.1)

print("HIC numerical convergence study")
print("-" * 65)
print(f"{'Resolution (ms)':>16} {'HIC':>14} {'Duration (ms)':>16} {'Runtime (s)':>13}")

for resolution_ms in (0.4, 0.2, 0.1, 0.05):
    start = time.perf_counter()

    result = calculate_hic(
        time_s,
        acceleration_g,
        window_ms=15.0,
        resolution_ms=resolution_ms,
    )

    elapsed = time.perf_counter() - start

    print(
        f"{resolution_ms:16.2f} "
        f"{result.value:14.4f} "
        f"{result.duration_ms:16.3f} "
        f"{elapsed:13.3f}"
    )
