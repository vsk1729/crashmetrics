"""HIC numerical convergence: the grid search against the exact maximum.

For several pulse shapes, HIC15 from the grid search at different
resolutions is compared with the exact maximum over continuous end
points (``method="exact"``), and both are timed on long records.
Run times depend on the computer; the relative errors do not.
"""

import time
from pathlib import Path

import numpy as np

from crashmetrics.lsdyna import read_nodout
from crashmetrics.pedestrian import calculate_hic
from crashmetrics.signals import cfc_filter, resample_uniform

t = np.arange(0.0, 0.05, 1e-4)                  # 10 kHz, like CAE output


def half_sine(peak, start, width):
    phase = (t - start) / width
    return np.where((phase > 0) & (phase < 1), peak * np.sin(np.pi * phase), 0.0)


def helmet_drop():
    """Real LS-DYNA nodout: helmeted Hybrid III head CG, CFC 1000 (tests/data)."""
    data = Path(__file__).resolve().parents[1] / "tests/data/lsdyna/helmet/drop/nodout"
    n = read_nodout(data)
    axes = []
    for c in "xyz":
        tu, au = resample_uniform(n.time / 1000, n.channel(f"{c}_acceleration")
                                  * 1000 / 9.80665, 10_000.0)
        axes.append(cfc_filter(tu, au, 1000))
    return tu, np.sqrt(sum(x * x for x in axes))


pulses = {
    "half-sine 120 g, 10 ms": (t, half_sine(120.0, 0.005, 0.010)),
    "triangle 90 g, 8 ms": (t, np.interp(t, [0.0, 0.010, 0.014, 0.018, 0.05],
                                         [0.0, 0.0, 90.0, 0.0, 0.0])),
    "double peak 70 + 95 g": (t, half_sine(70.0, 0.004, 0.006)
                              + half_sine(95.0, 0.012, 0.007)),
    "long low pulse 45 g, 30 ms": (t, half_sine(45.0, 0.005, 0.030)),
    "helmet drop (real nodout)": helmet_drop(),
}

resolutions = (0.4, 0.2, 0.1, 0.05)
print("HIC numerical convergence study")
print("Relative error of the grid search vs the exact HIC15")
print(f"{'pulse':28} {'exact HIC15':>11} "
      + " ".join(f"{r:>7} ms" for r in resolutions))
for name, (tt, aa) in pulses.items():
    exact = calculate_hic(tt, aa, method="exact").value
    errors = [(exact - calculate_hic(tt, aa, resolution_ms=r).value) / exact
              for r in resolutions]
    print(f"{name:28} {exact:11.2f} " + " ".join(f"{e:10.1e}" for e in errors))

print("\nRun time, half-sine pulse in records of different length (indicative)")
print(f"{'samples':>9} {'rate':>8} {'grid 0.1 ms':>12} {'exact':>9}")
for duration, rate in ((0.15, 10e3), (0.3, 20e3), (1.0, 100e3), (0.5, 500e3)):
    tt = np.arange(0.0, duration, 1.0 / rate)
    aa = 120.0 * np.where((tt > 0.02) & (tt < 0.03), np.sin(np.pi * (tt - 0.02) / 0.01),
                          0.0)
    timings = []
    for method in ("grid", "exact"):
        start = time.perf_counter()
        calculate_hic(tt, aa, method=method)
        timings.append(time.perf_counter() - start)
    print(f"{len(tt):9d} {rate / 1000:6.0f} kHz "
          f"{timings[0]:10.3f} s {timings[1]:7.3f} s")
