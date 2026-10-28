"""Pelvis criteria for frontal impact dummies.

Functions:

- `acetabulum_force`: THOR resultant acetabulum force while Fx is
  compressive (Euro NCAP CP 005, Section 3.6.2).
- `iliac_force_drop`: Iliac force drop, a submarining indicator (CP 005,
  Section 3.6.1; Hybrid III 5th female and THOR).

Units: time in s, force in N. Filter with CFC 600.
"""

import math

import numpy as np
from numpy.typing import ArrayLike

from crashmetrics._channels import as_channels, window
from crashmetrics.acceleration import PeakResult

__all__ = ["acetabulum_force", "iliac_force_drop"]


def acetabulum_force(
    time: ArrayLike,
    fx: ArrayLike,
    fy: ArrayLike,
    fz: ArrayLike,
    compression_negative: bool = True,
    t_start: float | None = None,
    t_end: float | None = None,
) -> PeakResult:
    """THOR acetabulum force (Euro NCAP CP 005, Section 3.6.2).

    ``F = max(sqrt(Fx^2 + Fy^2 + Fz^2))`` over the time intervals where
    the acetabulum Fx is compressive. Returns 0 (at the first sample) if
    Fx is never compressive.

    Parameters
    ----------
    time:
        1D time array in s.
    fx, fy, fz:
        Acetabulum forces, N.
    compression_negative:
        True if compressive Fx is negative (as for the Euro NCAP femur,
        whose compression is negative). CP 005 does not state the sign;
        check it against your channel polarity.
    t_start, t_end:
        Optional evaluation window, s.
    """
    t, channels = as_channels(time, fx, fy, fz)
    t, (x, y, z) = window(t, channels, t_start, t_end)
    compressive = x < 0 if compression_negative else x > 0
    resultant = np.where(compressive, np.sqrt(x**2 + y**2 + z**2), 0.0)
    i = int(np.argmax(resultant))
    return PeakResult(value=float(resultant[i]), time=float(t[i]))


def iliac_force_drop(
    time: ArrayLike,
    force: ArrayLike,
    interval: float = 0.001,
    loaded_negative: bool = True,
    t_start: float | None = None,
    t_end: float | None = None,
) -> PeakResult:
    """Iliac force drop (Euro NCAP CP 005, Section 3.6.1).

    ``IFD = max(IFD(t))`` with ``IFD(t) = F(t + 1 ms) - F(t)``, the
    iliac force F at ``t + interval`` taken by linear interpolation.

    Parameters
    ----------
    time:
        1D time array in s.
    force:
        Iliac force Fx, N.
    interval:
        Look-ahead interval, s (1 ms in CP 005).
    loaded_negative:
        True if the iliac force is negative under belt load, so that a
        sudden unloading (the belt sliding off the iliac crest) gives a
        positive IFD, as the CP 005 formula implies. If your channel is
        positive under load, pass False and the force is reversed.
    t_start, t_end:
        Optional window for t, s.

    Returns
    -------
    PeakResult
        Largest drop in N and the time t at which it starts.
    """
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("interval must be positive and finite.")
    t, (f,) = as_channels(time, force)
    f = f if loaded_negative else -f
    ahead = t + interval
    valid = ahead <= t[-1] + 1e-9 * interval  # allow for rounding of t + interval
    if not np.any(valid):
        raise ValueError("The record is shorter than the interval.")
    drop = np.full_like(f, -np.inf)
    drop[valid] = np.interp(ahead[valid], t, f) - f[valid]
    tw, (dw,) = window(t, [drop], t_start, t_end)
    if not np.any(np.isfinite(dw)):
        raise ValueError("No sample in the window has t + interval in the record.")
    i = int(np.argmax(dw))
    return PeakResult(value=float(dw[i]), time=float(tw[i]))
