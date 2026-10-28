"""Neck injury criteria for frontal impact dummies.

Functions:

- `occipital_condyle_moment`: Upper neck moment transferred to the
  occipital condyle.
- `neck_loads`: Peak shear, tension, compression and extension / flexion
  moments (Euro NCAP CP 005, Sections 3.2.1, 3.2.3 and 3.2.5).
- `nij`: Neck injury criterion Nij (FMVSS 208; not a Euro NCAP
  criterion).
- `neck_force_criterion`: Neck force against a force-duration limit
  (UN-ECE R94).

Units: time in s, force in N, moment in N m, distance in m.

Sign convention (SAE J211, as in Euro NCAP and FMVSS 208): Fz positive
in tension; My and the occipital condyle moment positive in flexion;
Fx positive when the head moves rearward relative to the torso.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics._channels import as_channels, window
from crashmetrics.acceleration import (
    ExceedanceCheckResult,
    PeakResult,
    exceedance_check,
)

__all__ = [
    "FMVSS208_NECK_FORCE_LIMITS",
    "NECK_FORCE_LIMITS",
    "NIJ_INTERCEPTS",
    "OC_DISTANCE_HYBRID3",
    "R94_NECK_EXTENSION_LIMIT",
    "NeckLoads",
    "NijIntercepts",
    "NijResult",
    "neck_force_criterion",
    "neck_loads",
    "nij",
    "occipital_condyle_moment",
]

OC_DISTANCE_HYBRID3 = 0.01778
"""Distance from the upper neck load cell to the occipital condyle, m,
for all Hybrid III sizes (Euro NCAP CP 005, Section 3.2.1)."""


def occipital_condyle_moment(
    my: ArrayLike, fx: ArrayLike, d: float = OC_DISTANCE_HYBRID3
) -> NDArray[np.float64]:
    """Moment at the occipital condyle: ``M_OCy = My - Fx * d``.

    Parameters
    ----------
    my:
        Upper neck moment My, N m.
    fx:
        Upper neck shear force Fx, N.
    d:
        Load cell to occipital condyle distance, m (0.01778 m for the
        Hybrid III). The THOR upper neck moment is used without this
        correction in Euro NCAP.
    """
    m = np.asarray(my, dtype=float)
    f = np.asarray(fx, dtype=float)
    if m.shape != f.shape:
        raise ValueError("my and fx must have the same shape.")
    if not math.isfinite(d):
        raise ValueError("d must be finite.")
    return m - f * d


@dataclass(frozen=True)
class NeckLoads:
    """Peak neck loads over the evaluation window."""

    shear_positive: PeakResult
    """Largest Fx (head rearward), N."""
    shear_negative: PeakResult
    """Largest -Fx (head forward), N, as a positive magnitude."""
    tension: PeakResult
    """Largest Fz (tension), N."""
    compression: PeakResult
    """Largest -Fz (compression), N, as a positive magnitude."""
    extension_moment: PeakResult
    """Extension moment ``abs(min(M))``, N m (M = M_OCy for the Hybrid
    III, the upper neck My for the THOR)."""
    flexion_moment: PeakResult
    """Largest M (flexion), N m."""
    moment: NDArray[np.float64]
    """Moment time history used (M_OCy or My), N m."""

    @property
    def shear(self) -> PeakResult:
        """Larger of the two shear magnitudes."""
        a, b = self.shear_positive, self.shear_negative
        return a if a.value >= b.value else b


def _peak(t: NDArray[np.float64], values: NDArray[np.float64]) -> PeakResult:
    i = int(np.argmax(values))
    return PeakResult(value=float(values[i]), time=float(t[i]))


def neck_loads(
    time: ArrayLike,
    fx: ArrayLike,
    fz: ArrayLike,
    my: ArrayLike,
    dummy: Literal["hybrid3", "thor"] = "hybrid3",
    oc_distance: float | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
) -> NeckLoads:
    """Peak upper neck loads (Euro NCAP CP 005, Sections 3.2.1-3.2.5).

    Parameters
    ----------
    time:
        1D time array in s.
    fx, fz:
        Upper neck shear and axial force, N (filter CFC 1000).
    my:
        Upper neck moment, N m (filter CFC 600).
    dummy:
        ``"hybrid3"``: the moment is moved to the occipital condyle,
        ``M_OCy = My - Fx * d``. ``"thor"``: My is used directly.
    oc_distance:
        Override of d for the Hybrid III, m (default 0.01778 m).
    t_start, t_end:
        Evaluation window, s; for frontal impacts Euro NCAP considers the
        loading phase (see `crashmetrics.head.loading_phase_end`).

    Notes
    -----
    Peaks that never occur in the window (e.g. no compression) are 0.
    The extension moment follows Euro NCAP's ``abs(min(M))``.
    """
    if dummy not in ("hybrid3", "thor"):
        raise ValueError("dummy must be 'hybrid3' or 'thor'.")
    t, channels = as_channels(time, fx, fz, my)
    t, (fx_a, fz_a, my_a) = window(t, channels, t_start, t_end)
    if dummy == "hybrid3":
        d = OC_DISTANCE_HYBRID3 if oc_distance is None else oc_distance
        moment = occipital_condyle_moment(my_a, fx_a, d)
    else:
        if oc_distance is not None:
            raise ValueError("oc_distance only applies to the Hybrid III.")
        moment = my_a

    zero = np.zeros_like(t)
    i_min = int(np.argmin(moment))
    return NeckLoads(
        shear_positive=_peak(t, np.maximum(fx_a, zero)),
        shear_negative=_peak(t, np.maximum(-fx_a, zero)),
        tension=_peak(t, np.maximum(fz_a, zero)),
        compression=_peak(t, np.maximum(-fz_a, zero)),
        extension_moment=PeakResult(
            value=float(abs(moment[i_min])), time=float(t[i_min])
        ),
        flexion_moment=_peak(t, np.maximum(moment, zero)),
        moment=moment,
    )


@dataclass(frozen=True)
class NijIntercepts:
    """Nij critical intercepts: forces in N, moments in N m."""

    tension: float
    compression: float
    flexion: float
    extension: float


NIJ_INTERCEPTS: dict[str, NijIntercepts] = {
    "hybrid3_50": NijIntercepts(6806.0, 6160.0, 310.0, 135.0),
    "hybrid3_05": NijIntercepts(4287.0, 3880.0, 155.0, 67.0),
}
"""FMVSS 208 in-position intercepts: Hybrid III 50th male (S6.6(a)(3))
and 5th female (S15.3.6(a)(3)). Pass your own for other dummies or
out-of-position tests."""

FMVSS208_NECK_FORCE_LIMITS: dict[str, tuple[float, float]] = {
    "hybrid3_50": (4170.0, 4000.0),
    "hybrid3_05": (2620.0, 2520.0),
}
"""FMVSS 208 peak upper neck (tension, compression) limits, N
(S6.6(b)-(c) and S15.3.6(b)-(c))."""


@dataclass(frozen=True)
class NijResult:
    """Result of an Nij calculation."""

    value: float
    """Largest Nij of the four categories."""
    category: str
    """Category of the largest value: ``"NTE"``, ``"NTF"``, ``"NCE"``
    or ``"NCF"`` (tension/compression, extension/flexion)."""
    time: float
    categories: dict[str, float]
    """Largest value of each category (0 if it never occurs)."""
    history: NDArray[np.float64]
    """Nij at each sample (of whichever category applies)."""


def nij(
    time: ArrayLike,
    fz: ArrayLike,
    my: ArrayLike,
    fx: ArrayLike | None = None,
    dummy: str = "hybrid3_50",
    intercepts: NijIntercepts | None = None,
    oc_distance: float = OC_DISTANCE_HYBRID3,
    t_start: float | None = None,
    t_end: float | None = None,
) -> NijResult:
    """Neck injury criterion Nij (FMVSS 208, S6.6 and S15.3.6).

    ``Nij = Fz/Fzc + M_OCy/Myc`` at each instant, with the intercept for
    tension or compression and for flexion or extension chosen by the
    signs of Fz and M_OCy, giving the four categories NTE, NTF, NCE and
    NCF. The FMVSS 208 limit is 1.0. Filter forces and moments with
    CFC 600 for Nij.

    Parameters
    ----------
    time:
        1D time array in s.
    fz:
        Upper neck axial force, N (tension positive).
    my:
        Upper neck moment, N m (flexion positive).
    fx:
        Upper neck shear force, N. If given, the moment is moved to the
        occipital condyle (``My - Fx * oc_distance``); if None, ``my``
        is taken as already at the occipital condyle.
    dummy:
        Key of `NIJ_INTERCEPTS`, used if ``intercepts`` is None.
    intercepts:
        Custom intercepts.
    oc_distance:
        Load cell to occipital condyle distance, m.
    t_start, t_end:
        Optional evaluation window, s.
    """
    if intercepts is None:
        if dummy not in NIJ_INTERCEPTS:
            known = ", ".join(sorted(NIJ_INTERCEPTS))
            raise ValueError(f"Unknown dummy {dummy!r}. Known: {known}.")
        intercepts = NIJ_INTERCEPTS[dummy]
    for name in ("tension", "compression", "flexion", "extension"):
        value = getattr(intercepts, name)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Intercept {name} must be positive and finite.")

    if fx is None:
        t, channels = as_channels(time, fz, my)
        t, (fz_a, moment) = window(t, channels, t_start, t_end)
    else:
        t, channels = as_channels(time, fz, my, fx)
        t, (fz_a, my_a, fx_a) = window(t, channels, t_start, t_end)
        moment = occipital_condyle_moment(my_a, fx_a, oc_distance)

    tension = fz_a >= 0
    flexion = moment >= 0
    force_term = np.where(tension, fz_a / intercepts.tension,
                          -fz_a / intercepts.compression)
    moment_term = np.where(flexion, moment / intercepts.flexion,
                           -moment / intercepts.extension)
    history = force_term + moment_term

    masks = {
        "NTE": tension & ~flexion,
        "NTF": tension & flexion,
        "NCE": ~tension & ~flexion,
        "NCF": ~tension & flexion,
    }
    categories = {
        name: float(np.max(history[mask])) if np.any(mask) else 0.0
        for name, mask in masks.items()
    }
    i = int(np.argmax(history))
    category = next(name for name, mask in masks.items() if mask[i])
    return NijResult(
        value=float(history[i]),
        category=category,
        time=float(t[i]),
        categories=categories,
        history=history,
    )


NECK_FORCE_LIMITS: dict[str, tuple[tuple[float, float], ...]] = {
    "r94_tension": ((0.0, 3300.0), (35.0, 2900.0), (60.0, 1100.0)),
    "r94_shear": ((0.0, 3100.0), (25.0, 1500.0), (35.0, 1500.0), (45.0, 1100.0)),
}
"""UN-ECE R94 neck force-duration limits, (duration in ms, force in N),
Hybrid III 50th male: tension 3.3 kN at 0 ms, 2.9 kN at 35 ms, 1.1 kN at
60 ms; shear 3.1 kN at 0 ms, 1.5 kN from 25 to 35 ms, 1.1 kN at 45 ms.
Linear between points, constant after the last one. Euro NCAP used the
same curves as the lower performance limits of its ODB test (Assessment
Protocol - Adult Occupant Protection v8.0, Section 3.1.2)."""

R94_NECK_EXTENSION_LIMIT = 57.0
"""UN-ECE R94 neck extension bending moment limit, N m (Hybrid III
50th male)."""


def neck_force_criterion(
    time: ArrayLike,
    force: ArrayLike,
    limit: str | Sequence[tuple[float, float]] = "r94_tension",
    mode: Literal["cumulative", "continuous"] = "cumulative",
    direction: Literal["positive", "negative", "absolute"] | None = None,
) -> ExceedanceCheckResult:
    """Check a neck force against a force-duration limit.

    Parameters
    ----------
    time:
        1D time array in s.
    force:
        Upper neck Fz for tension, Fx for shear, N.
    limit:
        Key of `NECK_FORCE_LIMITS` or (duration ms, force N) points.
    mode:
        ``"cumulative"`` or ``"continuous"`` duration; check which your
        regulation requires.
    direction:
        Part of the force assessed. Defaults: ``"positive"`` (tension)
        for ``"r94_tension"`` and ``"absolute"`` (either direction) for
        ``"r94_shear"``; ``"positive"`` for custom limits.
    """
    if isinstance(limit, str):
        if limit not in NECK_FORCE_LIMITS:
            known = ", ".join(sorted(NECK_FORCE_LIMITS))
            raise ValueError(f"Unknown limit {limit!r}. Known: {known}.")
        if direction is None:
            direction = "absolute" if limit == "r94_shear" else "positive"
        points: Sequence[tuple[float, float]] = NECK_FORCE_LIMITS[limit]
    else:
        points = limit
        direction = direction or "positive"
    return exceedance_check(time, force, points, mode, direction)
