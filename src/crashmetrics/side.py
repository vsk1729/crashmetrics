"""Side impact criteria for the ES-2 dummy (AIS-197 / Bharat NCAP, UN R95).

Functions
---------
es2_rib_deflection
    Largest deflection of the three ribs (upper, middle, lower).
es2_rib_vc
    Largest viscous criterion of the three ribs (sf 1.0, D 0.140 m).
es2_abdominal_force
    Peak of the sum of the front, middle and rear abdominal forces.
pubic_symphysis_force
    Peak lateral pubic symphysis force (magnitude).

Units: time in s, deflection in mm, force in N, VC in m/s. Filter rib
deflections with CFC 180 and forces with CFC 600 (AIS-197 Annexure IV,
Section 4.1).
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

from crashmetrics._channels import as_channels, window
from crashmetrics.acceleration import PeakResult
from crashmetrics.thorax import viscous_criterion

__all__ = [
    "RibResult",
    "es2_abdominal_force",
    "es2_rib_deflection",
    "es2_rib_vc",
    "pubic_symphysis_force",
]

_RIBS = ("upper", "middle", "lower")


@dataclass(frozen=True)
class RibResult:
    """Worst of the three ES-2 ribs."""

    value: float
    rib: str
    """``"upper"``, ``"middle"`` or ``"lower"``."""
    time: float
    per_rib: dict[str, float]


def es2_rib_deflection(
    time: ArrayLike,
    upper: ArrayLike,
    middle: ArrayLike,
    lower: ArrayLike,
    t_start: float | None = None,
    t_end: float | None = None,
) -> RibResult:
    """Greatest rib deflection of the three ribs, mm (compression positive)."""
    t, ribs = as_channels(time, upper, middle, lower)
    t, ribs = window(t, ribs, t_start, t_end)
    peaks = {}
    times = {}
    for name, d in zip(_RIBS, ribs):
        i = int(np.argmax(d))
        peaks[name], times[name] = float(d[i]), float(t[i])
    worst = max(peaks, key=lambda k: peaks[k])
    return RibResult(peaks[worst], worst, times[worst], peaks)


def es2_rib_vc(
    time: ArrayLike,
    upper: ArrayLike,
    middle: ArrayLike,
    lower: ArrayLike,
    t_start: float | None = None,
    t_end: float | None = None,
) -> RibResult:
    """Greatest rib viscous criterion, m/s: ``VC = V * D / 0.140`` per rib."""
    results = {
        name: viscous_criterion(time, d, dummy="es2", t_start=t_start, t_end=t_end)
        for name, d in zip(_RIBS, (upper, middle, lower))
    }
    worst = max(results, key=lambda k: results[k].value)
    return RibResult(results[worst].value, worst, results[worst].time,
                     {k: r.value for k, r in results.items()})


def es2_abdominal_force(
    time: ArrayLike,
    front: ArrayLike,
    middle: ArrayLike,
    rear: ArrayLike,
    t_start: float | None = None,
    t_end: float | None = None,
) -> PeakResult:
    """Peak total abdominal force: max of the sum of the three load cells, N.

    Pass the forces with loading positive.
    """
    t, forces = as_channels(time, front, middle, rear)
    t, forces = window(t, forces, t_start, t_end)
    total = forces[0] + forces[1] + forces[2]
    i = int(np.argmax(total))
    return PeakResult(value=float(total[i]), time=float(t[i]))


def pubic_symphysis_force(
    time: ArrayLike,
    fy: ArrayLike,
    t_start: float | None = None,
    t_end: float | None = None,
) -> PeakResult:
    """Peak lateral pubic symphysis force magnitude ``max |Fy|``, N."""
    t, (f,) = as_channels(time, fy)
    t, (f,) = window(t, [f], t_start, t_end)
    i = int(np.argmax(np.abs(f)))
    return PeakResult(value=float(abs(f[i])), time=float(t[i]))
