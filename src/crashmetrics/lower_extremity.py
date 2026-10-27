"""Lower-extremity injury criteria for crash test dummies.

Functions
---------
tibia_index
    Tibia Index (TI) from tibia bending moments and axial force.
femur_force_criterion
    Femur compressive force exceedance against a force-time limit.
tibia_compression
    Peak tibia compressive force (UN-ECE R94 tibia compression force
    criterion; Euro NCAP uses the Tibia Index).
knee_slider_displacement
    Knee slider displacement (Euro NCAP CP 005, Section 3.6.3).

Units are SI: forces in N, moments in N m, time in s. Filter the
channels first; Euro NCAP uses CFC 600 for tibia and femur loads.

Sign convention: by default compressive axial force is negative, as
in Euro NCAP, where the femur criterion uses the most negative femur
force and the Tibia Index is zero whenever Fz >= 0. Set
``compression_negative=False`` if your data uses positive compression.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics._channels import as_channels, window
from crashmetrics.acceleration import PeakResult, exceedance_check

__all__ = [
    "FEMUR_FORCE_LIMITS",
    "R94_TIBIA_COMPRESSION_LIMIT",
    "TIBIA_INDEX_CRITICAL_VALUES",
    "FemurForceResult",
    "TibiaIndexResult",
    "femur_force_criterion",
    "knee_slider_displacement",
    "tibia_compression",
    "tibia_index",
]

TIBIA_INDEX_CRITICAL_VALUES: dict[str, tuple[float, float]] = {
    "hybrid3_50": (225.0, 35_900.0),
    "hybrid3_05": (114.0, 22_900.0),
    "hybrid3_95": (306.0, 44_100.0),
    "thor_50": (225.0, 35_900.0),
}
"""Critical resultant moment (N m) and critical compressive force (N).

Source: Euro NCAP Data Acquisition and Injury Calculation protocol
(CP 005, v1.4.1, 2026). Check the values against the protocol version
you assess to.
"""

FEMUR_FORCE_LIMITS: dict[str, tuple[tuple[float, float], ...]] = {
    "r94_hybrid3_50": ((0.0, 9_070.0), (10.0, 7_580.0)),
}
"""Femur compressive force-time limits as (duration in ms, force in N).

The limit is linear between points and constant after the last one.
``"r94_hybrid3_50"`` is the UN-ECE R94 femur force criterion for the
Hybrid III 50th male: 9.07 kN at 0 ms falling to 7.58 kN at 10 ms and
longer. Check the values, and whether durations are cumulative or
continuous, against the regulation you assess to.
"""


@dataclass(frozen=True)
class TibiaIndexResult:
    """Result of a Tibia Index calculation."""

    value: float
    """Maximum Tibia Index over the record (dimensionless)."""

    time: float
    """Time of the maximum, in seconds."""

    history: NDArray[np.float64]
    """Tibia Index at each sample."""


def tibia_index(
    time: ArrayLike,
    mx: ArrayLike,
    my: ArrayLike,
    fz: ArrayLike,
    dummy: str | None = None,
    critical_moment: float | None = None,
    critical_force: float | None = None,
    compression_negative: bool = True,
) -> TibiaIndexResult:
    """Return the Tibia Index (TI).

    Parameters
    ----------
    time:
        1D time array in s.
    mx, my:
        Tibia bending moments in N m (upper or lower tibia).
    fz:
        Tibia axial force in N.
    dummy:
        Key of :data:`TIBIA_INDEX_CRITICAL_VALUES`, for example
        ``"hybrid3_50"``. Give either this or both critical values.
    critical_moment:
        Critical resultant bending moment in N m.
    critical_force:
        Critical compressive force in N.
    compression_negative:
        True if compression is negative in ``fz`` (Euro NCAP).

    Returns
    -------
    TibiaIndexResult

    Notes
    -----
    At each sample, with ``MR = sqrt(Mx**2 + My**2)``::

        TI = |MR / MR_c| + |Fz / Fz_c|   while the tibia is in compression
        TI = 0                            otherwise

    as defined by Euro NCAP. Calculate it separately for the upper and
    lower tibia of each leg and report the highest value your protocol
    asks for.
    """
    if dummy is not None:
        if critical_moment is not None or critical_force is not None:
            raise ValueError(
                "Give either dummy or critical_moment and critical_force."
            )
        if dummy not in TIBIA_INDEX_CRITICAL_VALUES:
            known = ", ".join(sorted(TIBIA_INDEX_CRITICAL_VALUES))
            raise ValueError(f"Unknown dummy {dummy!r}. Known: {known}.")
        critical_moment, critical_force = TIBIA_INDEX_CRITICAL_VALUES[dummy]
    elif critical_moment is None or critical_force is None:
        raise ValueError(
            "Give dummy, or both critical_moment and critical_force."
        )

    for name, value in (
        ("critical_moment", critical_moment),
        ("critical_force", critical_force),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite.")

    t, (mx_a, my_a, fz_a) = as_channels(time, mx, my, fz)

    resultant_moment = np.hypot(mx_a, my_a)
    in_compression = fz_a < 0 if compression_negative else fz_a > 0

    history = np.where(
        in_compression,
        np.abs(resultant_moment / critical_moment)
        + np.abs(fz_a / critical_force),
        0.0,
    )
    index = int(np.argmax(history))
    return TibiaIndexResult(
        value=float(history[index]),
        time=float(t[index]),
        history=history,
    )


@dataclass(frozen=True)
class FemurForceResult:
    """Result of a femur force criterion check."""

    peak_compression: float
    """Largest compressive force, in N (positive)."""

    peak_time: float
    """Time of the peak compression, in seconds."""

    utilisation: float
    """Largest ratio of the exceedance curve to the limit; a value
    above 1 means the limit is exceeded."""

    critical_duration_ms: float
    """Duration (ms) at which the utilisation is largest."""

    passed: bool
    """True if ``utilisation <= 1``."""

    levels: NDArray[np.float64]
    """Compressive force levels (N) of the exceedance curve, highest
    first."""

    durations_ms: NDArray[np.float64]
    """Time (ms) the compression is at or above each level."""


def femur_force_criterion(
    time: ArrayLike,
    fz: ArrayLike,
    limit: str | tuple[tuple[float, float], ...] = "r94_hybrid3_50",
    mode: Literal["cumulative", "continuous"] = "cumulative",
    compression_negative: bool = True,
) -> FemurForceResult:
    """Check femur compressive force against a force-time limit.

    Parameters
    ----------
    time:
        1D time array in s.
    fz:
        Femur axial force in N.
    limit:
        Key of :data:`FEMUR_FORCE_LIMITS`, or a sequence of
        (duration in ms, force in N) points starting at 0 ms, with
        increasing duration and non-increasing force. The limit is
        linear between points and constant afterwards.
    mode:
        ``"cumulative"`` or ``"continuous"`` exceedance duration; see
        :func:`crashmetrics.acceleration.exceedance_duration`. Check
        which your regulation requires.
    compression_negative:
        True if compression is negative in ``fz`` (Euro NCAP).

    Returns
    -------
    FemurForceResult

    Notes
    -----
    For each compressive force level ``F``, let ``D(F)`` be the time
    the compression is at or above ``F``. The limit is exceeded if
    ``F > limit(D(F))`` for some ``F``; the utilisation is the largest
    ``F / limit(D(F))``.

    In cumulative mode ``D`` is linear in ``F`` between sample values,
    so checking every sample value and every level where ``D`` meets a
    limit breakpoint is exact for the linearly interpolated signal. In
    continuous mode 2000 evenly spaced levels are added as well.
    """
    if isinstance(limit, str):
        if limit not in FEMUR_FORCE_LIMITS:
            known = ", ".join(sorted(FEMUR_FORCE_LIMITS))
            raise ValueError(f"Unknown limit {limit!r}. Known: {known}.")
        points: Sequence[tuple[float, float]] = FEMUR_FORCE_LIMITS[limit]
    else:
        points = limit

    t, (fz_a,) = as_channels(time, fz)
    result = exceedance_check(
        t, fz_a, points, mode,
        direction="negative" if compression_negative else "positive",
    )
    return FemurForceResult(
        peak_compression=result.peak,
        peak_time=result.peak_time,
        utilisation=result.utilisation,
        critical_duration_ms=result.critical_duration_ms,
        passed=result.passed,
        durations_ms=result.durations_ms,
        levels=result.levels,
    )


R94_TIBIA_COMPRESSION_LIMIT = 8000.0
"""UN-ECE R94 tibia compression force criterion (TCFC) limit, N."""


def tibia_compression(
    time: ArrayLike,
    fz: ArrayLike,
    compression_negative: bool = True,
    t_start: float | None = None,
    t_end: float | None = None,
) -> PeakResult:
    """Peak tibia compressive axial force ``|min(Fz)|``, N (positive).

    The UN-ECE R94 tibia compression force criterion (TCFC) is the
    compressive Fz transmitted axially on each tibia, limited to 8 kN
    (:data:`R94_TIBIA_COMPRESSION_LIMIT`). Euro NCAP has scored it in
    frontal tests alongside the Tibia Index (2 kN higher and 8 kN lower
    performance limit in the ODB, Assessment Protocol - Adult Occupant
    Protection v8.0, Section 3.1.5).
    """
    t, (f,) = as_channels(time, fz)
    t, (f,) = window(t, [f], t_start, t_end)
    compression = np.maximum(-f if compression_negative else f, 0.0)
    i = int(np.argmax(compression))
    return PeakResult(value=float(compression[i]), time=float(t[i]))


def knee_slider_displacement(
    time: ArrayLike,
    displacement: ArrayLike,
    t_start: float | None = None,
    t_end: float | None = None,
) -> PeakResult:
    """Knee slider displacement ``Dknee = |min(Dknee(t))|``, mm.

    Euro NCAP CP 005, Section 3.6.3 (filter CFC 180).
    """
    t, (d,) = as_channels(time, displacement)
    t, (d,) = window(t, [d], t_start, t_end)
    i = int(np.argmin(d))
    return PeakResult(value=float(abs(d[i])), time=float(t[i]))
