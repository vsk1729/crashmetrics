"""Energy and force-displacement metrics.

Functions:

- `integrate_acceleration`: Velocity and displacement from an
  acceleration time history.
- `absorbed_energy`: Cumulative energy absorbed along a
  force-displacement curve.
- `crush_metrics`: Peak force, mean force, energy, crush force
  efficiency and specific energy absorption of a crush response.
- `kinetic_energy`: Kinetic energy of a mass.

Units
-----
These functions do not convert units: use a consistent system. A few
useful combinations:

- force in kN and displacement in mm give energy in J
- force in N and displacement in m give energy in J
- acceleration in mm/ms^2 and time in ms give velocity in mm/ms (m/s)
  and displacement in mm

Use ``crashmetrics.signals.to_g`` and ``to_seconds`` to convert
inputs first if needed. All integrals use the trapezoidal rule.
"""

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "CrushResult",
    "absorbed_energy",
    "crush_metrics",
    "integrate_acceleration",
    "kinetic_energy",
]


def _pair(x, y, x_name, y_name):
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)

    if xa.ndim != 1 or ya.ndim != 1:
        raise ValueError(f"{x_name} and {y_name} must be 1D arrays.")
    if len(xa) != len(ya) or len(xa) < 2:
        raise ValueError(
            f"{x_name} and {y_name} must have equal lengths and contain "
            "at least two samples."
        )
    if not np.all(np.isfinite(xa)) or not np.all(np.isfinite(ya)):
        raise ValueError("Inputs must contain only finite values.")
    return xa, ya


def _cumulative_trapezoid(x, y, initial=0.0):
    increments = 0.5 * (y[:-1] + y[1:]) * np.diff(x)
    return initial + np.concatenate(([0.0], np.cumsum(increments)))


def integrate_acceleration(
    time: ArrayLike,
    acceleration: ArrayLike,
    v0: float = 0.0,
    x0: float = 0.0,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Integrate acceleration to velocity and displacement.

    Parameters
    ----------
    time:
        Strictly increasing 1D time array.
    acceleration:
        1D acceleration in units consistent with ``time``, for example
        m/s^2 with s, or mm/ms^2 with ms. Do not pass values in g;
        multiply by 9.80665 (m/s^2) first.
    v0:
        Initial velocity.
    x0:
        Initial displacement.

    Returns
    -------
    tuple of numpy.ndarray
        ``(velocity, displacement)``, each the same length as ``time``.

    Notes
    -----
    Velocity is the cumulative trapezoidal integral of acceleration;
    displacement is the cumulative trapezoidal integral of velocity.
    Integration amplifies sensor offset and drift: a small constant
    error in acceleration grows linearly in velocity and
    quadratically in displacement.
    """
    t, a = _pair(time, acceleration, "time", "acceleration")
    if np.any(np.diff(t) <= 0):
        raise ValueError("Time values must be strictly increasing.")
    if not math.isfinite(v0) or not math.isfinite(x0):
        raise ValueError("v0 and x0 must be finite.")

    velocity = _cumulative_trapezoid(t, a, initial=v0)
    displacement = _cumulative_trapezoid(t, velocity, initial=x0)
    return velocity, displacement


def absorbed_energy(
    displacement: ArrayLike, force: ArrayLike
) -> NDArray[np.float64]:
    """Cumulative energy along a force-displacement curve.

    Parameters
    ----------
    displacement:
        1D displacement (crush), in the order the samples were
        recorded. It need not be monotonic: during unloading the
        displacement decreases and the energy drops by the work
        returned.
    force:
        1D force, positive in the loading (crushing) direction.

    Returns
    -------
    numpy.ndarray
        Energy at each sample, starting at zero, in force x length
        units (kN x mm = J).
    """
    d, f = _pair(displacement, force, "displacement", "force")
    return _cumulative_trapezoid(d, f)


@dataclass(frozen=True)
class CrushResult:
    """Metrics of a crush (force-displacement) response."""

    energy: float
    """Net energy absorbed, force x length (kN x mm = J)."""

    crush_distance: float
    """Maximum displacement reached, relative to the first sample."""

    peak_force: float
    peak_force_displacement: float
    """Displacement at which the peak force occurs (first occurrence)."""

    mean_force: float
    """Energy divided by crush distance."""

    crush_force_efficiency: float
    """Mean force divided by peak force (CFE). NaN if peak force <= 0."""

    specific_energy_absorption: float | None
    """Energy divided by absorber mass (SEA), or None without a mass."""


def _cut_at_displacement(d, f, limit):
    """Truncate at the first point where displacement reaches limit."""
    reached = np.flatnonzero(d >= limit)
    if reached.size == 0:
        raise ValueError(
            f"Displacement never reaches max_displacement={limit:g} "
            f"(maximum is {np.max(d):g})."
        )
    k = int(reached[0])
    if k == 0:
        raise ValueError("max_displacement must exceed the first displacement.")
    if d[k] == limit:
        return d[: k + 1], f[: k + 1]

    fraction = (limit - d[k - 1]) / (d[k] - d[k - 1])
    f_limit = f[k - 1] + fraction * (f[k] - f[k - 1])
    return (
        np.append(d[:k], limit),
        np.append(f[:k], f_limit),
    )


def crush_metrics(
    displacement: ArrayLike,
    force: ArrayLike,
    mass: float | None = None,
    max_displacement: float | None = None,
) -> CrushResult:
    """Summarise a crush response from its force-displacement curve.

    Parameters
    ----------
    displacement:
        1D displacement (crush) in recording order.
    force:
        1D force, positive in the crushing direction.
    mass:
        Optional absorber mass, for specific energy absorption. Use
        units that give the SEA you want, for example J with kg.
    max_displacement:
        Optional stroke limit. The curve is cut, with linear
        interpolation, where the displacement first reaches this
        value, for example to evaluate metrics over an effective
        stroke.

    Returns
    -------
    CrushResult

    Notes
    -----
    Mean force is the net absorbed energy divided by the crush
    distance, and the crush force efficiency (CFE) is the mean force
    divided by the peak force. Both depend on the stroke over which
    they are evaluated, so state the stroke when reporting them.
    """
    d, f = _pair(displacement, force, "displacement", "force")

    if mass is not None and (not math.isfinite(mass) or mass <= 0):
        raise ValueError("mass must be positive and finite.")

    if max_displacement is not None:
        if not math.isfinite(max_displacement):
            raise ValueError("max_displacement must be finite.")
        d, f = _cut_at_displacement(d, f, max_displacement)

    crush_distance = float(np.max(d) - d[0])
    if crush_distance <= 0:
        raise ValueError("Displacement must increase to give a crush distance.")

    energy = float(_cumulative_trapezoid(d, f)[-1])
    peak_index = int(np.argmax(f))
    peak_force = float(f[peak_index])
    mean_force = energy / crush_distance

    return CrushResult(
        energy=energy,
        crush_distance=crush_distance,
        peak_force=peak_force,
        peak_force_displacement=float(d[peak_index]),
        mean_force=mean_force,
        crush_force_efficiency=(
            mean_force / peak_force if peak_force > 0 else float("nan")
        ),
        specific_energy_absorption=(
            energy / mass if mass is not None else None
        ),
    )


def kinetic_energy(
    mass: float, velocity: ArrayLike
) -> float | NDArray[np.float64]:
    """Return the kinetic energy ``0.5 * mass * velocity**2``.

    Works element-wise on arrays. With mass in kg and velocity in m/s
    (equal to mm/ms) the result is in J.
    """
    v = np.asarray(velocity, dtype=float)
    if not math.isfinite(mass) or mass < 0:
        raise ValueError("mass must be non-negative and finite.")
    result = 0.5 * mass * v**2
    return float(result) if result.ndim == 0 else result
