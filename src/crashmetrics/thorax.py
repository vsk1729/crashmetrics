"""Chest and abdomen criteria for frontal impact dummies.

Functions
---------
chest_deflection
    Hybrid III chest deflection (Euro NCAP CP 005, Section 3.4.1).
viscous_criterion
    Viscous criterion VC (CP 005, Section 3.4.6).
thor_rib_displacement, thor_chest_deflection
    THOR 3D rib displacement from IR-TRACC length and angles, and Rmax
    over the four chest locations (CP 005, Section 3.4.2).
thor_abdomen_deflection
    THOR abdominal rib displacement (CP 005, Section 3.5.2).
cti, cti_from_signals
    Combined Thoracic Index (NHTSA research; not a Euro NCAP criterion).

Units: time in s, deflection and displacement in mm, IR-TRACC angles in
degrees (or radians with ``degrees=False``), VC in m/s, acceleration in
g. Filter deflections and IR-TRACC channels with CFC 180.

Deflection sign: Euro NCAP evaluates the Hybrid III chest deflection as
``max(Dchest(t))``, i.e. with compression positive. If your channel is
negative in compression, pass ``compression_negative=True``.
"""

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics._channels import as_channels, uniform_step, window
from crashmetrics.acceleration import PeakResult, clip_3ms

__all__ = [
    "CTI_INTERCEPTS",
    "THOR_IR_TRACC_OFFSET",
    "VC_CONSTANTS",
    "AbdomenResult",
    "CtiResult",
    "RibDisplacement",
    "ThorChestResult",
    "VCResult",
    "chest_deflection",
    "cti",
    "cti_from_signals",
    "thor_abdomen_deflection",
    "thor_chest_deflection",
    "thor_rib_displacement",
    "viscous_criterion",
]

FloatArray = NDArray[np.float64]


def _signed(deflection: FloatArray, compression_negative: bool) -> FloatArray:
    return -deflection if compression_negative else deflection


def chest_deflection(
    time: ArrayLike,
    deflection: ArrayLike,
    compression_negative: bool = False,
    t_start: float | None = None,
    t_end: float | None = None,
) -> PeakResult:
    """Hybrid III chest deflection, ``Dchest = max(Dchest(t))``, in mm.

    Parameters
    ----------
    time:
        1D time array in s.
    deflection:
        Chest deflection in mm (CFC 180).
    compression_negative:
        True if compression is negative in ``deflection``.
    t_start, t_end:
        Optional evaluation window, s.
    """
    t, (d,) = as_channels(time, deflection)
    t, (d,) = window(t, [_signed(d, compression_negative)], t_start, t_end)
    i = int(np.argmax(d))
    return PeakResult(value=float(d[i]), time=float(t[i]))


VC_CONSTANTS: dict[str, tuple[float, float]] = {
    "hybrid3_50": (1.3, 0.229),
    "hybrid3_05": (1.3, 0.187),
    "hybrid3_95": (1.3, 0.254),
    "worldsid_50": (1.0, 0.170),
    "es2": (1.0, 0.140),
}
"""Viscous criterion (scale factor sf, Dconstant in m) from Euro NCAP
CP 005, Section 3.4.6; ES-2 rib VC from AIS-197 Annexure IV, 4.1.2."""


@dataclass(frozen=True)
class VCResult:
    """Result of a viscous criterion calculation."""

    value: float
    """Largest VC, m/s."""
    time: float
    history: FloatArray
    """VC at each sample, m/s (NaN at the first and last two samples,
    where the five-point velocity is not defined)."""
    velocity: FloatArray
    """Deflection velocity V(t), m/s."""


def viscous_criterion(
    time: ArrayLike,
    deflection: ArrayLike,
    dummy: str = "hybrid3_50",
    scale_factor: float | None = None,
    d_constant: float | None = None,
    compression_negative: bool = False,
    t_start: float | None = None,
    t_end: float | None = None,
) -> VCResult:
    """Viscous criterion (Euro NCAP CP 005, Section 3.4.6).

    ``VC(t) = sf * V(t) * C(t)`` with ``C(t) = D(t) / Dconstant`` and::

        V(t) = [8 (D(t+1) - D(t-1)) - (D(t+2) - D(t-2))] / (12 dt)

    Parameters
    ----------
    time:
        Uniformly sampled 1D time array in s.
    deflection:
        Chest (or rib) deflection in mm, CFC 180; compression positive
        unless ``compression_negative`` is True.
    dummy:
        Key of :data:`VC_CONSTANTS`; used unless both ``scale_factor``
        and ``d_constant`` (m) are given.
    t_start, t_end:
        Optional window for the maximum, s (the velocity is computed on
        the whole record).
    """
    if scale_factor is None or d_constant is None:
        if scale_factor is not None or d_constant is not None:
            raise ValueError("Give both scale_factor and d_constant, or neither.")
        if dummy not in VC_CONSTANTS:
            known = ", ".join(sorted(VC_CONSTANTS))
            raise ValueError(f"Unknown dummy {dummy!r}. Known: {known}.")
        scale_factor, d_constant = VC_CONSTANTS[dummy]
    finite = math.isfinite(scale_factor) and math.isfinite(d_constant)
    if not finite or d_constant <= 0:
        raise ValueError("scale_factor must be finite and d_constant positive.")

    t, (d_mm,) = as_channels(time, deflection, min_samples=5)
    dt = uniform_step(t)
    d = _signed(d_mm, compression_negative) / 1000.0  # m

    velocity = np.full_like(d, np.nan)
    velocity[2:-2] = (8.0 * (d[3:-1] - d[1:-3]) - (d[4:] - d[:-4])) / (12.0 * dt)
    history = scale_factor * velocity * d / d_constant

    keep = np.isfinite(history)
    if t_start is not None:
        keep &= t >= t_start
    if t_end is not None:
        keep &= t <= t_end
    if not np.any(keep):
        raise ValueError("No VC values in the evaluation window.")
    candidates = np.where(keep, history, -np.inf)
    i = int(np.argmax(candidates))
    return VCResult(value=float(history[i]), time=float(t[i]),
                    history=history, velocity=velocity)


THOR_IR_TRACC_OFFSET = 15.65
"""Offset delta of the THOR chest IR-TRACCs, mm: +15.65 for the upper
and -15.65 for the lower ribs (Euro NCAP CP 005, Section 3.4.2)."""


@dataclass(frozen=True)
class RibDisplacement:
    """3D displacement of one THOR IR-TRACC location, mm."""

    dx: FloatArray
    dy: FloatArray
    dz: FloatArray
    resultant: FloatArray
    peak: float
    """Largest resultant displacement, mm."""
    time: float


def _angles(phi: ArrayLike, degrees: bool) -> FloatArray:
    a = np.asarray(phi, dtype=float)
    return np.radians(a) if degrees else a


def _reference_index(t: FloatArray, reference_time: float | None) -> int:
    if reference_time is None:
        return 0
    before = np.flatnonzero(t <= reference_time)
    if before.size == 0:
        raise ValueError("reference_time is before the first sample.")
    return int(before[-1])


def thor_rib_displacement(
    time: ArrayLike,
    length: ArrayLike,
    phi_y: ArrayLike,
    phi_z: ArrayLike,
    location: Literal["upper", "lower"] | None = None,
    delta: float | None = None,
    degrees: bool = True,
    reference_time: float | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
) -> RibDisplacement:
    """THOR chest rib 3D displacement (Euro NCAP CP 005, Section 3.4.2).

    ::

        Dx(t) = delta sin(phi_y) + R cos(phi_z) cos(phi_y) - Dx(0)
        Dy(t) = R sin(phi_z) - Dy(0)
        Dz(t) = delta cos(phi_y) - R cos(phi_z) sin(phi_y) - Dz(0)

    Parameters
    ----------
    time:
        1D time array in s.
    length:
        IR-TRACC length R(t), mm (CFC 180).
    phi_y, phi_z:
        IR-TRACC rotations (CFC 180), degrees unless ``degrees=False``.
    location:
        ``"upper"`` (delta = +15.65 mm) or ``"lower"`` (-15.65 mm);
        or give ``delta`` in mm.
    reference_time:
        Time of the initial position (the displacement "prior to
        activation"); the first sample by default.
    t_start, t_end:
        Optional window for the peak, s.
    """
    if delta is None:
        if location not in ("upper", "lower"):
            raise ValueError("Give location 'upper' or 'lower', or delta.")
        delta = THOR_IR_TRACC_OFFSET if location == "upper" else -THOR_IR_TRACC_OFFSET
    elif location is not None:
        raise ValueError("Give location or delta, not both.")

    t, (r, py, pz) = as_channels(time, length, phi_y, phi_z)
    py, pz = _angles(py, degrees), _angles(pz, degrees)
    x = delta * np.sin(py) + r * np.cos(pz) * np.cos(py)
    y = r * np.sin(pz)
    z = delta * np.cos(py) - r * np.cos(pz) * np.sin(py)
    i0 = _reference_index(t, reference_time)
    dx, dy, dz = x - x[i0], y - y[i0], z - z[i0]
    resultant = np.sqrt(dx**2 + dy**2 + dz**2)

    tw, (rw,) = window(t, [resultant], t_start, t_end)
    i = int(np.argmax(rw))
    return RibDisplacement(dx=dx, dy=dy, dz=dz, resultant=resultant,
                           peak=float(rw[i]), time=float(tw[i]))


@dataclass(frozen=True)
class ThorChestResult:
    """THOR chest deflection over the four IR-TRACC locations."""

    rmax: float
    """Largest resultant rib displacement of the four locations, mm."""
    location: str
    """Location of Rmax: ``"upper_left"``, ``"upper_right"``,
    ``"lower_left"`` or ``"lower_right"``."""
    time: float
    ribs: dict[str, RibDisplacement]


def thor_chest_deflection(
    time: ArrayLike,
    upper_left: tuple[ArrayLike, ArrayLike, ArrayLike],
    upper_right: tuple[ArrayLike, ArrayLike, ArrayLike],
    lower_left: tuple[ArrayLike, ArrayLike, ArrayLike],
    lower_right: tuple[ArrayLike, ArrayLike, ArrayLike],
    degrees: bool = True,
    reference_time: float | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
) -> ThorChestResult:
    """THOR Rmax: the largest resultant displacement of the four chest
    IR-TRACCs (Euro NCAP CP 005, Section 3.4.2).

    Each location is ``(R, phi_y, phi_z)``: length in mm and angles in
    degrees (radians with ``degrees=False``).
    """
    ribs = {}
    for name, channels in (
        ("upper_left", upper_left), ("upper_right", upper_right),
        ("lower_left", lower_left), ("lower_right", lower_right),
    ):
        r, py, pz = channels
        ribs[name] = thor_rib_displacement(
            time, r, py, pz, location="upper" if name.startswith("upper") else "lower",
            degrees=degrees, reference_time=reference_time,
            t_start=t_start, t_end=t_end,
        )
    worst = max(ribs, key=lambda k: ribs[k].peak)
    return ThorChestResult(rmax=ribs[worst].peak, location=worst,
                           time=ribs[worst].time, ribs=ribs)


@dataclass(frozen=True)
class AbdomenResult:
    """THOR abdominal rib displacement (left and right)."""

    value: float
    """Largest abdominal compression, ``max(-Dx(t))`` over both sides,
    mm (R decreasing under compression)."""
    side: str
    """``"left"`` or ``"right"``."""
    time: float
    max_dx: float
    """``max(Dx(t))`` over both sides as printed in Euro NCAP CP 005;
    equal to the compression only if your R channel increases under
    compression."""
    dx: dict[str, FloatArray]
    """Dx(t) for each side, mm."""


def thor_abdomen_deflection(
    time: ArrayLike,
    left: tuple[ArrayLike, ArrayLike, ArrayLike],
    right: tuple[ArrayLike, ArrayLike, ArrayLike],
    degrees: bool = True,
    reference_time: float | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
) -> AbdomenResult:
    """THOR abdominal rib displacement (Euro NCAP CP 005, Section 3.5.2).

    ``Dx(t) = R(t) cos(phi_z(t)) cos(phi_y(t)) - Dx(0)`` for each side
    ``(R, phi_y, phi_z)``.

    CP 005 writes ``Drib = max(Dx(t))``. With R as the IR-TRACC length,
    which shortens under compression, Dx is negative in compression, so
    ``value`` reports the compression ``max(-Dx(t))``; ``max_dx`` keeps
    the protocol's literal ``max(Dx(t))``. Check which matches your
    channel polarity.
    """
    dx: dict[str, FloatArray] = {}
    best: tuple[float, str, float] | None = None
    max_dx = -math.inf
    for side, channels in (("left", left), ("right", right)):
        r, py, pz = channels
        t, (ra, pya, pza) = as_channels(time, r, py, pz)
        pya, pza = _angles(pya, degrees), _angles(pza, degrees)
        x = ra * np.cos(pza) * np.cos(pya)
        d = x - x[_reference_index(t, reference_time)]
        dx[side] = d
        tw, (dw,) = window(t, [d], t_start, t_end)
        i = int(np.argmax(-dw))
        if best is None or -dw[i] > best[0]:
            best = (float(-dw[i]), side, float(tw[i]))
        max_dx = max(max_dx, float(np.max(dw)))
    assert best is not None
    return AbdomenResult(value=max(best[0], 0.0), side=best[1], time=best[2],
                         max_dx=max_dx, dx=dx)


CTI_INTERCEPTS: dict[str, tuple[float, float]] = {
    "hybrid3_50": (90.0, 103.0),
    "hybrid3_05": (90.0, 84.0),
}
"""CTI intercepts (A_int in g, D_int in mm) from Eppinger et al. (1999),
Supplement: Development of Improved Injury Criteria for the Assessment of
Advanced Automotive Restraint Systems II, NHTSA, Table ES.3."""


def cti(
    acceleration: float,
    deflection: float,
    dummy: str = "hybrid3_50",
    intercepts: tuple[float, float] | None = None,
) -> float:
    """Combined Thoracic Index ``CTI = A/A_int + D/D_int``.

    Parameters
    ----------
    acceleration:
        Chest acceleration in g (normally the 3 ms clip of the resultant
        spine acceleration).
    deflection:
        Chest deflection in mm.
    dummy:
        Key of :data:`CTI_INTERCEPTS`, unless ``intercepts`` (A_int g,
        D_int mm) is given.
    """
    if intercepts is None:
        if dummy not in CTI_INTERCEPTS:
            known = ", ".join(sorted(CTI_INTERCEPTS))
            raise ValueError(f"Unknown dummy {dummy!r}. Known: {known}.")
        intercepts = CTI_INTERCEPTS[dummy]
    a_int, d_int = intercepts
    finite = math.isfinite(a_int) and math.isfinite(d_int)
    if not finite or a_int <= 0 or d_int <= 0:
        raise ValueError("Intercepts must be positive and finite.")
    if not (math.isfinite(acceleration) and math.isfinite(deflection)):
        raise ValueError("acceleration and deflection must be finite.")
    return acceleration / a_int + deflection / d_int


@dataclass(frozen=True)
class CtiResult:
    """Result of :func:`cti_from_signals`."""

    value: float
    acceleration: float
    """Acceleration used, g."""
    deflection: float
    """Deflection used, mm."""


def cti_from_signals(
    time: ArrayLike,
    chest_acceleration: ArrayLike,
    deflection: ArrayLike,
    dummy: str = "hybrid3_50",
    intercepts: tuple[float, float] | None = None,
    acceleration_measure: Literal["clip_3ms", "peak"] = "clip_3ms",
    compression_negative: bool = False,
) -> CtiResult:
    """CTI from the resultant chest acceleration (g) and deflection (mm).

    The acceleration is the cumulative 3 ms clip by default (the NHTSA
    report defines the acceleration intercept for the 3 ms clip of the
    spine acceleration), or the peak with ``acceleration_measure="peak"``.
    The deflection is the peak compression.
    """
    if acceleration_measure not in ("clip_3ms", "peak"):
        raise ValueError("acceleration_measure must be 'clip_3ms' or 'peak'.")
    t, (acc, d) = as_channels(time, chest_acceleration, deflection)
    a = (clip_3ms(t, acc) if acceleration_measure == "clip_3ms"
         else float(np.max(acc)))
    peak_d = float(np.max(_signed(d, compression_negative)))
    return CtiResult(
        value=cti(a, peak_d, dummy, intercepts), acceleration=a, deflection=peak_d
    )
