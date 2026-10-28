"""Head injury criteria: DAMAGE, BrIC and the frontal loading phase.

Functions:

- `damage`, `damage_from_acceleration`: DAMAGE brain strain criterion
  (Euro NCAP THOR head assessment).
- `external_force`: Euro NCAP external head force used to end the DAMAGE
  window.
- `bric`: Brain Injury Criterion (Takhounts et al. 2013; US NCAP
  research).
- `loading_phase_end`: End of the loading phase in frontal tests (Euro
  NCAP CP 005).

HIC and the 3 ms clip are in `crashmetrics.pedestrian` and
`crashmetrics.acceleration`.

Units: time in s, angular velocity in rad/s, angular acceleration in
rad/s^2, head linear acceleration in g, force in N. Angular quantities
are in the SAE J211 head coordinate system.

DAMAGE
------
Euro NCAP CP 005 (Data Acquisition and Injury Calculation v1.4.1,
Section 3.1.3) and TB 035 define DAMAGE (Gabler, Crandall and Panzer
2019) as a 3-degree-of-freedom mass-spring-damper system driven by head
angular acceleration::

    [m]{d''} + [c]{d'} + [k]{d} = [m]{u''},   [c] = a1 [k]
    DAMAGE = beta * max_t |d(t)|

with m = 1 kg per axis, kxx = 32142, kyy = 23493, kzz = 16935, kxy = 0,
kyz = 0, kxz = 1636.3 N/m, a1 = 5.9148 ms and beta = 2.9903 1/m.

Implementation details follow the reference implementation by the
model's developers (UVA Center for Applied Biomechanics,
github.com/UVA-CAB/DAMAGE, version 2.0, BSD licence):

- the k values are springs of a network: each axis has a spring to
  ground (kxx, kyy, kzz) and the axes are coupled by kxy, kyz, kxz, so
  the stiffness matrix is ``[[kxx+kxy+kxz, -kxy, -kxz], [-kxy,
  kxy+kyy+kyz, -kyz], [-kxz, -kyz, kxz+kyz+kzz]]``;
- the z component of the SAE J211 angular acceleration is reversed in
  sign before it is applied;
- the system is solved with the Newmark average-acceleration method.

Euro NCAP specifies CFC 60 head angular velocity as the input; it is
differentiated here with second-order central differences. The window
runs from T0 for at most 200 ms and ends earlier when the external
force ``-4.2 kg * a_head,x + F_neck,upper,x`` drops below -500 N.
"""

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics._channels import as_channels, window

__all__ = [
    "BRIC_CRITICAL_VELOCITIES",
    "DAMAGE_PARAMETERS",
    "BricResult",
    "DamageParameters",
    "DamageResult",
    "bric",
    "damage",
    "damage_from_acceleration",
    "external_force",
    "loading_phase_end",
]

STANDARD_G = 9.81
"""m/s^2 per g, as used by Euro NCAP."""


@dataclass(frozen=True)
class DamageParameters:
    """Parameters of the DAMAGE model (Euro NCAP CP 005, Section 3.1.3)."""

    kxx: float = 32142.0
    kyy: float = 23493.0
    kzz: float = 16935.0
    kxy: float = 0.0
    kyz: float = 0.0
    kxz: float = 1636.3
    """Spring stiffnesses, N/m (unit masses of 1 kg)."""
    a1: float = 5.9148e-3
    """Stiffness-proportional damping coefficient, s ([c] = a1 [k])."""
    beta: float = 2.9903
    """Scale factor, 1/m."""
    head_mass: float = 4.2
    """Head mass for the external force end condition, kg."""
    external_force_limit: float = -500.0
    """The window ends when the external force drops below this, N."""
    max_duration: float = 0.2
    """Longest evaluation window from T0, s."""

    def stiffness_matrix(self) -> NDArray[np.float64]:
        """Stiffness matrix of the spring network, N/m."""
        return np.array([
            [self.kxx + self.kxy + self.kxz, -self.kxy, -self.kxz],
            [-self.kxy, self.kxy + self.kyy + self.kyz, -self.kyz],
            [-self.kxz, -self.kyz, self.kxz + self.kyz + self.kzz],
        ])


DAMAGE_PARAMETERS = DamageParameters()


@dataclass(frozen=True)
class DamageResult:
    """Result of a DAMAGE calculation."""

    value: float
    """DAMAGE (dimensionless)."""
    time: float
    """Time of the maximum, s."""
    start: float
    """Start of the evaluation window (T0), s."""
    end: float
    """End of the evaluation window, s."""
    end_reason: str
    """``"max duration"``, ``"external force"`` or ``"end of record"``."""
    time_history: NDArray[np.float64]
    """Times of the evaluation window, s."""
    displacement: NDArray[np.float64]
    """Model displacement (n, 3) over the window, m (model axes, z
    reversed relative to SAE J211)."""


def external_force(
    head_ax_g: ArrayLike, neck_fx: ArrayLike, head_mass: float = 4.2
) -> NDArray[np.float64]:
    """Euro NCAP external head force: ``-M_head * a_head,x + F_neck,upper,x``.

    ``head_ax_g`` is the head x acceleration in g (converted with
    9.81 m/s^2 per g) and ``neck_fx`` the upper neck shear force in N.
    """
    ax = np.asarray(head_ax_g, dtype=float)
    fx = np.asarray(neck_fx, dtype=float)
    return -head_mass * ax * STANDARD_G + fx


def _newmark(
    t: NDArray[np.float64], forcing: NDArray[np.float64], params: DamageParameters
) -> NDArray[np.float64]:
    """Newmark average-acceleration solution from rest (unit masses)."""
    k = params.stiffness_matrix()
    c = params.a1 * k
    eye = np.eye(3)
    n = len(t)
    x = np.zeros((n, 3))
    v = np.zeros((n, 3))
    a = np.zeros((n, 3))
    a[0] = forcing[0]  # M a0 = F0 - C v0 - K x0 with x0 = v0 = 0
    inverse_cache: dict[float, NDArray[np.float64]] = {}
    for i in range(1, n):
        h = float(t[i] - t[i - 1])
        key = round(h, 15)
        if key not in inverse_cache:
            inverse_cache[key] = np.linalg.inv(eye + 0.5 * h * c + 0.25 * h * h * k)
        rhs = (
            forcing[i]
            - c @ (v[i - 1] + 0.5 * h * a[i - 1])
            - k @ (x[i - 1] + h * v[i - 1] + 0.25 * h * h * a[i - 1])
        )
        a[i] = inverse_cache[key] @ rhs
        v[i] = v[i - 1] + 0.5 * h * (a[i - 1] + a[i])
        x[i] = x[i - 1] + h * v[i - 1] + 0.25 * h * h * (a[i - 1] + a[i])
    return x


def damage_from_acceleration(
    time: ArrayLike,
    alpha_x: ArrayLike,
    alpha_y: ArrayLike,
    alpha_z: ArrayLike,
    t0: float | None = None,
    head_ax_g: ArrayLike | None = None,
    neck_fx: ArrayLike | None = None,
    params: DamageParameters = DAMAGE_PARAMETERS,
) -> DamageResult:
    """DAMAGE from head angular acceleration (rad/s^2, SAE J211 axes).

    Parameters
    ----------
    time:
        1D time array in s.
    alpha_x, alpha_y, alpha_z:
        Head angular acceleration in rad/s^2.
    t0:
        Start of the evaluation (T0), s; the first sample by default.
        The model starts from rest at T0.
    head_ax_g, neck_fx:
        Optional head x acceleration (g) and upper neck Fx (N). If both
        are given, the window ends when `external_force` first
        drops below -500 N after T0 (Euro NCAP frontal impacts).
    params:
        Model parameters; the Euro NCAP values by default.

    Returns
    -------
    DamageResult
    """
    t, (ax, ay, az) = as_channels(time, alpha_x, alpha_y, alpha_z)
    start = float(t[0]) if t0 is None else float(t0)
    if not math.isfinite(start):
        raise ValueError("t0 must be finite.")
    if start >= t[-1]:
        raise ValueError("t0 must be before the end of the record.")
    end = start + params.max_duration
    reason = "max duration"

    if (head_ax_g is None) != (neck_fx is None):
        raise ValueError("Give both head_ax_g and neck_fx, or neither.")
    if head_ax_g is not None and neck_fx is not None:
        _, (hx, nfx) = as_channels(t, head_ax_g, neck_fx)
        force = external_force(hx, nfx, params.head_mass)
        below = np.flatnonzero((t > start) & (force < params.external_force_limit))
        if below.size and t[below[0]] < end:
            end = float(t[below[0]])
            reason = "external force"
    if end > t[-1]:
        end = float(t[-1])
        reason = "end of record"

    tw, (wx, wy, wz) = window(t, [ax, ay, az], start, end, min_samples=2)
    # Model axes: the z component of SAE J211 acceleration is reversed,
    # as in the developers' reference implementation.
    forcing = np.column_stack((wx, wy, -wz))
    displacement = _newmark(tw, forcing, params)
    magnitude = np.linalg.norm(displacement, axis=1)
    index = int(np.argmax(magnitude))
    return DamageResult(
        value=float(params.beta * magnitude[index]),
        time=float(tw[index]),
        start=float(tw[0]),
        end=float(tw[-1]),
        end_reason=reason,
        time_history=tw,
        displacement=displacement,
    )


def damage(
    time: ArrayLike,
    omega_x: ArrayLike,
    omega_y: ArrayLike,
    omega_z: ArrayLike,
    t0: float | None = None,
    head_ax_g: ArrayLike | None = None,
    neck_fx: ArrayLike | None = None,
    params: DamageParameters = DAMAGE_PARAMETERS,
) -> DamageResult:
    """DAMAGE from head angular velocity (rad/s, SAE J211 axes).

    This is the Euro NCAP input: filter the angular velocity with CFC 60
    first (`crashmetrics.signals.cfc_filter`). It is differentiated
    with second-order central differences over the whole record; see
    `damage_from_acceleration` for the other parameters.
    """
    t, (wx, wy, wz) = as_channels(time, omega_x, omega_y, omega_z, min_samples=3)
    return damage_from_acceleration(
        t, np.gradient(wx, t), np.gradient(wy, t), np.gradient(wz, t),
        t0=t0, head_ax_g=head_ax_g, neck_fx=neck_fx, params=params,
    )


BRIC_CRITICAL_VELOCITIES: dict[str, tuple[float, float, float]] = {
    "average": (66.25, 56.45, 42.87),
    "mps": (66.30, 53.80, 41.50),
    "csdm": (66.20, 59.10, 44.25),
}
"""Critical angular velocities (x, y, z) in rad/s from Takhounts et al.
(2013), Table 3: CSDM-based, MPS-based and their average. The average
is the set used with the MPS-based risk curves (and by US NCAP
research); the paper states the values apply to all dummies."""


@dataclass(frozen=True)
class BricResult:
    """Result of a BrIC calculation."""

    value: float
    peaks: tuple[float, float, float]
    """Peak absolute angular velocity per axis, rad/s."""
    critical: tuple[float, float, float]
    """Critical angular velocities used, rad/s."""


def bric(
    time: ArrayLike,
    omega_x: ArrayLike,
    omega_y: ArrayLike,
    omega_z: ArrayLike,
    critical: str | tuple[float, float, float] = "average",
    t_start: float | None = None,
    t_end: float | None = None,
) -> BricResult:
    """Brain Injury Criterion (Takhounts et al. 2013).

    ``BrIC = sqrt((wx/wxC)^2 + (wy/wyC)^2 + (wz/wzC)^2)`` with the peak
    absolute angular velocity of each axis, wherever it occurs in time.
    BrIC is not a Euro NCAP criterion (Euro NCAP uses DAMAGE).

    Parameters
    ----------
    time:
        1D time array in s.
    omega_x, omega_y, omega_z:
        Head angular velocity in rad/s.
    critical:
        Key of `BRIC_CRITICAL_VELOCITIES` or (wxC, wyC, wzC).
    t_start, t_end:
        Optional evaluation window, s.
    """
    if isinstance(critical, str):
        if critical not in BRIC_CRITICAL_VELOCITIES:
            known = ", ".join(sorted(BRIC_CRITICAL_VELOCITIES))
            raise ValueError(f"Unknown critical set {critical!r}. Known: {known}.")
        crit = BRIC_CRITICAL_VELOCITIES[critical]
    else:
        crit = (float(critical[0]), float(critical[1]), float(critical[2]))
    if any(not math.isfinite(c) or c <= 0 for c in crit):
        raise ValueError("Critical velocities must be positive and finite.")

    t, channels = as_channels(time, omega_x, omega_y, omega_z)
    _, channels = window(t, channels, t_start, t_end)
    peaks = tuple(float(np.max(np.abs(w))) for w in channels)
    value = math.sqrt(sum((p / c) ** 2 for p, c in zip(peaks, crit)))
    return BricResult(value=value, peaks=peaks, critical=crit)  # type: ignore[arg-type]


def loading_phase_end(time: ArrayLike, head_ax: ArrayLike) -> float:
    """End of the loading phase in a frontal test (Euro NCAP CP 005).

    The time at which the filtered head x acceleration crosses zero
    after its minimum (most negative) peak, interpolated linearly
    between samples. Returns the last time if it does not cross zero
    again, or if the acceleration never goes negative.
    """
    t, (ax,) = as_channels(time, head_ax)
    minimum = int(np.argmin(ax))
    if ax[minimum] >= 0:
        return float(t[-1])
    after = np.flatnonzero(ax[minimum:] >= 0)
    if after.size == 0:
        return float(t[-1])
    i = minimum + int(after[0])
    fraction = (0.0 - ax[i - 1]) / (ax[i] - ax[i - 1])
    return float(t[i - 1] + fraction * (t[i] - t[i - 1]))
