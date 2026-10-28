"""Vehicle crash pulse metrics.

Functions:

- `olc`: Occupant Load Criterion (OLC).
- `pulse_summary`: Velocity change, time to zero velocity, maximum
  displacement, rebound and deceleration of a crash pulse.

Inputs are in SI units: time in s, acceleration in m/s^2, velocity
in m/s. The acceleration is the vehicle (or barrier) longitudinal
acceleration in its direction of travel, so it is negative while the
vehicle decelerates, and velocity is ``v0 + integral(acceleration)``.
The record should start at the time of first contact (T0), when the
velocity is ``v0``. Filter the acceleration first if your protocol
requires it (Euro NCAP uses CFC 180 for the MPDB OLC).
"""

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

__all__ = ["OLCResult", "PulseSummary", "olc", "pulse_summary"]

OLC_GRAVITY = 9.81
"""Value of g in m/s^2 used by Euro NCAP to express OLC in g."""


class _Kinematics:
    """Vehicle velocity and displacement from an acceleration pulse.

    Acceleration is taken as piecewise linear between samples, so the
    velocity is integrated exactly with the trapezoidal rule. Between
    samples the velocity is treated as linear and the displacement as
    the matching quadratic, so displacement is the exact integral of
    the sampled velocity.
    """

    def __init__(self, time, acceleration, v0):
        t = np.asarray(time, dtype=float)
        a = np.asarray(acceleration, dtype=float)

        if t.ndim != 1 or a.ndim != 1:
            raise ValueError("time and acceleration must be 1D arrays.")
        if len(t) != len(a) or len(t) < 2:
            raise ValueError(
                "time and acceleration must have equal lengths and "
                "contain at least two samples."
            )
        if not np.all(np.isfinite(t)) or not np.all(np.isfinite(a)):
            raise ValueError("Inputs must contain only finite values.")
        if np.any(np.diff(t) <= 0):
            raise ValueError("Time values must be strictly increasing.")
        if not math.isfinite(v0) or v0 <= 0:
            raise ValueError("v0 must be positive and finite (in m/s).")

        dt = np.diff(t)
        v = v0 + np.concatenate(([0.0], np.cumsum(0.5 * (a[:-1] + a[1:]) * dt)))
        s = np.concatenate(([0.0], np.cumsum(0.5 * (v[:-1] + v[1:]) * dt)))

        self.t, self.a, self.v, self.s, self.v0 = t, a, v, s, float(v0)

    def at(self, time):
        """Velocity and displacement at any time within the record."""
        t, v, s = self.t, self.v, self.s
        k = int(np.clip(np.searchsorted(t, time, side="right") - 1, 0, len(t) - 2))
        tau = time - t[k]
        h = t[k + 1] - t[k]
        slope = (v[k + 1] - v[k]) / h
        return v[k] + slope * tau, s[k] + v[k] * tau + 0.5 * slope * tau**2


def _first_root(f, t, values):
    """First time where f changes from negative to >= 0, by bisection.

    ``values`` holds f at the sample times ``t``. Returns None if f
    stays negative over the record.
    """
    reached = np.flatnonzero(values >= 0)
    if reached.size == 0:
        return None
    k = int(reached[0])
    if k == 0:
        return float(t[0])

    low, high = float(t[k - 1]), float(t[k])
    for _ in range(200):
        middle = 0.5 * (low + high)
        if middle in (low, high):
            break
        if f(middle) >= 0:
            high = middle
        else:
            low = middle
    return high


@dataclass(frozen=True)
class OLCResult:
    """Result of an OLC calculation."""

    value: float
    """OLC in g (m/s^2 divided by ``gravity``)."""

    value_si: float
    """OLC in m/s^2."""

    t1: float
    """End of the free-flight phase, in seconds from the record start."""

    t2: float
    """End of the restraint phase, in seconds from the record start."""


def olc(
    time: ArrayLike,
    acceleration: ArrayLike,
    v0: float,
    free_flight: float = 0.065,
    restraint: float = 0.235,
    gravity: float = OLC_GRAVITY,
) -> OLCResult:
    """Return the Occupant Load Criterion (OLC) of a crash pulse.

    Parameters
    ----------
    time:
        1D time array in s, starting at T0.
    acceleration:
        1D vehicle longitudinal acceleration in m/s^2, negative while
        decelerating (see the module notes).
    v0:
        Vehicle velocity at the first sample, in m/s.
    free_flight:
        Free-flight distance of the virtual occupant, in m.
    restraint:
        Restraint-phase distance of the virtual occupant, in m.
    gravity:
        Value of g used to express OLC in g. Euro NCAP uses 9.81.

    Returns
    -------
    OLCResult

    Notes
    -----
    A virtual occupant initially moves at ``v0`` without restraint
    (free flight) until it has moved ``free_flight`` relative to the
    vehicle, at time ``t1``. It then decelerates uniformly at the OLC
    until its velocity equals the vehicle velocity at ``t2``, having
    moved a further ``restraint`` relative to the vehicle. With
    ``V(t)`` the vehicle velocity and ``S(t)`` its displacement:

    - ``v0 * t1 - S(t1) = free_flight``
    - ``(v0 + V(t2)) / 2 * (t2 - t1) - (S(t2) - S(t1)) = restraint``
    - ``OLC = (v0 - V(t2)) / (t2 - t1)``

    This follows the Euro NCAP definition (Data Acquisition and
    Injury Calculation protocol, MPDB OLC). Both times are solved by
    bisection to floating-point precision.
    """
    for name, value in (
        ("free_flight", free_flight),
        ("restraint", restraint),
        ("gravity", gravity),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite.")

    k = _Kinematics(time, acceleration, v0)
    t0 = k.t[0]

    def free_flight_gap(t):
        return k.v0 * (t - t0) - k.at(t)[1] - free_flight

    t1 = _first_root(
        free_flight_gap, k.t, k.v0 * (k.t - t0) - k.s - free_flight
    )
    if t1 is None:
        raise ValueError(
            "The virtual occupant does not complete the free-flight phase "
            "within the record. Check that the acceleration is negative "
            "while the vehicle decelerates and that the record is long "
            "enough."
        )

    s1 = k.at(t1)[1]

    def restraint_gap(t):
        vt, st = k.at(t)
        return 0.5 * (k.v0 + vt) * (t - t1) - (st - s1) - restraint

    after = k.t > t1
    candidate_t = np.concatenate(([t1], k.t[after]))
    candidate_values = (
        0.5 * (k.v0 + np.concatenate(([k.at(t1)[0]], k.v[after])))
        * (candidate_t - t1)
        - (np.concatenate(([s1], k.s[after])) - s1)
        - restraint
    )
    t2 = _first_root(restraint_gap, candidate_t, candidate_values)
    if t2 is None or t2 <= t1:
        raise ValueError(
            "The virtual occupant does not complete the restraint phase "
            "within the record. Use a longer record."
        )

    value_si = (k.v0 - k.at(t2)[0]) / (t2 - t1)
    return OLCResult(
        value=value_si / gravity,
        value_si=value_si,
        t1=float(t1 - t0),
        t2=float(t2 - t0),
    )


@dataclass(frozen=True)
class PulseSummary:
    """Summary of a vehicle crash pulse. SI units throughout."""

    v0: float
    """Initial velocity, m/s."""

    final_velocity: float
    """Velocity at the end of the record, m/s (negative if rebounding)."""

    delta_v: float
    """Velocity change over the record, ``v0 - final_velocity``, m/s."""

    time_to_zero_velocity: float | None
    """First time the velocity reaches zero, s; None if it never does."""

    max_displacement: float
    """Maximum displacement from the start (dynamic crush into a rigid
    barrier), m."""

    time_of_max_displacement: float
    """Time of the maximum displacement, s."""

    rebound_velocity: float
    """Largest rearward velocity reached, m/s; zero without rebound."""

    restitution: float
    """``rebound_velocity / v0``."""

    peak_deceleration: float
    """Largest deceleration (largest negative acceleration), m/s^2."""

    mean_deceleration: float | None
    """``v0 / time_to_zero_velocity``, m/s^2; None if velocity never
    reaches zero."""


def pulse_summary(
    time: ArrayLike, acceleration: ArrayLike, v0: float
) -> PulseSummary:
    """Summarise a vehicle crash pulse.

    Parameters
    ----------
    time:
        1D time array in s, starting at T0.
    acceleration:
        1D vehicle longitudinal acceleration in m/s^2, negative while
        decelerating.
    v0:
        Vehicle velocity at the first sample, in m/s.

    Returns
    -------
    PulseSummary
        Times are measured from the first sample.

    Notes
    -----
    The maximum displacement is the vehicle's own displacement from
    the start; it equals dynamic crush only for an impact into a
    fixed rigid barrier.
    """
    k = _Kinematics(time, acceleration, v0)
    t0 = k.t[0]

    def velocity_gap(t):
        return -k.at(t)[0]

    t_zero = _first_root(velocity_gap, k.t, -k.v)

    # Displacement peaks where the (piecewise-linear) velocity crosses
    # from positive to non-positive, or at a sample. Check both.
    index = int(np.argmax(k.s))
    t_max, s_max = float(k.t[index]), float(k.s[index])
    crossings = np.flatnonzero((k.v[:-1] > 0) & (k.v[1:] <= 0))
    for c in crossings:
        h = k.t[c + 1] - k.t[c]
        t_cross = k.t[c] + h * k.v[c] / (k.v[c] - k.v[c + 1])
        s_cross = float(k.at(t_cross)[1])
        if s_cross > s_max:
            t_max, s_max = float(t_cross), s_cross

    rebound = max(0.0, -float(np.min(k.v)))

    return PulseSummary(
        v0=k.v0,
        final_velocity=float(k.v[-1]),
        delta_v=k.v0 - float(k.v[-1]),
        time_to_zero_velocity=None if t_zero is None else float(t_zero - t0),
        max_displacement=s_max,
        time_of_max_displacement=float(t_max - t0),
        rebound_velocity=rebound,
        restitution=rebound / k.v0,
        peak_deceleration=max(0.0, -float(np.min(k.a))),
        mean_deceleration=(
            None if t_zero is None else k.v0 / float(t_zero - t0)
        ),
    )
