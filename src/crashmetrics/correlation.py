"""Test-versus-CAE correlation: ISO/TS 18571, CC rating and error measures.

Rate how well a computed signal (usually CAE) matches a reference signal
(usually a physical test) with one number between 0 and 1, and its
sub-scores.

Functions:

- `iso18571`: ISO/TS 18571:2024 objective rating (corridor, phase,
  magnitude, slope) and its grade (excellent, good, fair, poor).
- `cc_rating`: Corridor and cross-correlation (CC) rating: a corridor
  score plus phase, size and shape from the cross-correlation.
- `error_measures`: RMSE, normalised RMSE, peak and peak-time errors,
  correlation coefficient, Sprague & Geers and Russell errors.
- `compare`: All three at once; `flatten` turns the result into
  columns for a feature table.
- `resample_pair`: Put two signals on one uniform time grid over their
  common interval.

Conventions:

- `reference` is the signal you trust (the test), `comparison` the one
  being rated (CAE). The ratings are not symmetric: corridors are sized
  from the reference.
- Signals may have different time bases; they are linearly resampled to
  ``dt`` (default 0.1 ms, the 10 kHz that ISO/TS 18571 assumes) over the
  common interval, or over ``t_start`` to ``t_end``.
- Filter both signals the same way (same CFC) before rating them.
- A positive time shift means the comparison signal is late.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "CCParameters",
    "CCResult",
    "Comparison",
    "ErrorMeasures",
    "ISO18571Parameters",
    "ISO18571Result",
    "cc_rating",
    "compare",
    "error_measures",
    "iso18571",
    "iso18571_grade",
    "resample_pair",
]

Array = NDArray[np.float64]

_trapz: Callable[..., Any] = getattr(np, "trapezoid", None) or getattr(np, "trapz")


# --- Common time base --------------------------------------------------------


def _as_signal(time: ArrayLike, signal: ArrayLike, name: str) -> tuple[Array, Array]:
    t = np.asarray(time, dtype=float)
    x = np.asarray(signal, dtype=float)
    if t.ndim != 1 or x.ndim != 1 or len(t) != len(x) or len(t) < 2:
        raise ValueError(f"{name}: time and signal must be 1D arrays of equal "
                         "length with at least two samples.")
    if not (np.all(np.isfinite(t)) and np.all(np.isfinite(x))):
        raise ValueError(f"{name}: inputs must contain only finite values.")
    if np.any(np.diff(t) <= 0):
        raise ValueError(f"{name}: time values must be strictly increasing.")
    return t, x


def resample_pair(
    time: ArrayLike,
    reference: ArrayLike,
    comparison: ArrayLike,
    comparison_time: ArrayLike | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
    dt: float = 1e-4,
) -> tuple[Array, Array, Array]:
    """Return both signals on one uniform time grid.

    Parameters
    ----------
    time:
        Time of the reference signal, s.
    reference, comparison:
        The two signals.
    comparison_time:
        Time of the comparison signal, s, if it differs from ``time``.
    t_start, t_end:
        Interval of evaluation, s. Default: the interval both signals
        cover.
    dt:
        Time step of the common grid, s (default 0.1 ms = 10 kHz).

    Returns
    -------
    t, reference, comparison
        The grid from ``t_start`` in steps of ``dt`` up to ``t_end``,
        and both signals linearly interpolated onto it.
    """
    t_r, r = _as_signal(time, reference, "reference")
    t_c, c = _as_signal(t_r if comparison_time is None else comparison_time,
                        comparison, "comparison")
    if not (math.isfinite(dt) and dt > 0):
        raise ValueError("dt must be positive.")
    lo = max(t_r[0], t_c[0])
    hi = min(t_r[-1], t_c[-1])
    start = lo if t_start is None else float(t_start)
    end = hi if t_end is None else float(t_end)
    tol = 1e-9 * max(1.0, abs(end))
    if start < lo - tol or end > hi + tol:
        raise ValueError(
            f"The interval {start:g} to {end:g} s is not covered by both "
            f"signals (common interval {lo:g} to {hi:g} s)."
        )
    n = int(math.floor((end - start) / dt + 1e-9)) + 1
    if n < 10:
        raise ValueError("The interval of evaluation needs at least 10 samples.")
    t = start + dt * np.arange(n, dtype=float)
    ref_u: Array = np.interp(t, t_r, r)
    comp_u: Array = np.interp(t, t_c, c)
    return t, ref_u, comp_u


# --- Shared pieces ---------------------------------------------------------


def _corridor_score(ref: Array, comp: Array, a0: float, b0: float, k: float,
                    norm: float) -> float:
    """Average corridor score: 1 inside the inner corridor, 0 outside the
    outer one, ((outer - d) / (outer - inner))^k between."""
    if norm <= 0:
        raise ValueError("The reference signal is zero over the interval; "
                         "give a norm for the corridor width.")
    inner, outer = a0 * norm, b0 * norm
    d = np.abs(ref - comp)
    score = np.clip((outer - d) / (outer - inner), 0.0, 1.0) ** k
    score[d < inner] = 1.0
    score[d > outer] = 0.0
    return float(score.mean())


def _pearson(a: Array, b: Array) -> float:
    a = a - a.mean()
    b = b - b.mean()
    den = math.sqrt(float(a @ a) * float(b @ b))
    return float(a @ b) / den if den > 0 else -math.inf


def _uncentred(a: Array, b: Array) -> float:
    den = math.sqrt(float(a @ a) * float(b @ b))
    return float(a @ b) / den if den > 0 else -math.inf


def _best_shift(ref: Array, comp: Array, max_shift: int,
                measure: Callable[[Array, Array], float]) -> tuple[int, float]:
    """Shift (samples, positive = comparison late) with the highest
    correlation. Shifts are tried from small to large, the late direction
    first, and only a strictly higher value replaces the best one, so the
    smallest shift wins a tie."""
    best, best_shift = measure(ref, comp), 0
    for m in range(1, max_shift + 1):
        late = measure(ref[:-m], comp[m:])
        if late > best:
            best, best_shift = late, m
        early = measure(ref[m:], comp[:-m])
        if early > best:
            best, best_shift = early, -m
    return best_shift, best


def _apply_shift(ref: Array, comp: Array, shift: int) -> tuple[Array, Array]:
    if shift > 0:
        return ref[:-shift], comp[shift:]
    if shift < 0:
        return ref[-shift:], comp[:shift]
    return ref, comp


# --- ISO/TS 18571 ----------------------------------------------------------


@dataclass(frozen=True)
class ISO18571Parameters:
    """Parameters of ISO/TS 18571; the defaults are the standard's values.
    Change them only for studies of the metric itself."""

    a0: float = 0.05
    """Inner corridor half width, fraction of the reference's absolute
    maximum."""
    b0: float = 0.50
    """Outer corridor half width, fraction of the absolute maximum."""
    k_z: float = 2.0
    """Corridor exponent."""
    max_shift: float = 0.2
    """Maximum allowable time shift, fraction of the interval (eps_P*)."""
    k_p: float = 1.0
    """Phase exponent."""
    max_magnitude_error: float = 0.5
    """Maximum allowable magnitude error (eps_M*)."""
    k_m: float = 1.0
    """Magnitude exponent."""
    max_slope_error: float = 2.0
    """Maximum allowable slope error (eps_S*)."""
    k_s: float = 1.0
    """Slope exponent."""
    dtw_window: float = 0.1
    """Dynamic time warping window, fraction of the signal length
    (ISO/TS 18571:2024)."""
    w_z: float = 0.4
    """Weight of the corridor score."""
    w_p: float = 0.2
    """Weight of the phase score."""
    w_m: float = 0.2
    """Weight of the magnitude score."""
    w_s: float = 0.2
    """Weight of the slope score."""


@dataclass(frozen=True)
class ISO18571Result:
    """ISO/TS 18571 rating of a comparison signal against a reference."""

    rating: float
    """Overall rating R, 0 to 1."""
    grade: str
    """``"excellent"`` (R > 0.94), ``"good"`` (> 0.80), ``"fair"``
    (> 0.58) or ``"poor"``."""
    corridor: float
    """Corridor score Z."""
    phase: float
    """Phase score E_P."""
    magnitude: float
    """Magnitude score E_M."""
    slope: float
    """Slope score E_S."""
    time_shift_ms: float
    """Time shift with the highest correlation, ms (positive: the
    comparison is late)."""
    correlation: float
    """Pearson correlation at that shift."""
    magnitude_error: float
    """Magnitude error after the shift and time warping."""
    slope_error: float
    """Slope error after the shift."""
    t_start: float
    """Start of the interval of evaluation, s."""
    t_end: float
    """End of the interval of evaluation, s."""
    n_points: int
    """Number of samples in the interval."""


def iso18571_grade(rating: float) -> str:
    """Return the ISO/TS 18571 grade of an overall rating:
    excellent (R > 0.94), good (0.80 < R <= 0.94), fair
    (0.58 < R <= 0.80) or poor (R <= 0.58)."""
    if not math.isfinite(rating):
        raise ValueError("rating must be finite.")
    if rating > 0.94:
        return "excellent"
    if rating > 0.80:
        return "good"
    if rating > 0.58:
        return "fair"
    return "poor"


def _dtw_warp(x: Array, y: Array, window: float) -> tuple[Array, Array]:
    """Warp two equal-length signals with dynamic time warping.

    Local cost (x_i - y_j)^2; steps (1, 0), (0, 1) and (1, 1) with equal
    weights; Sakoe-Chiba band |i - j| < ceil(window * n). The accumulated
    cost is built one anti-diagonal at a time (cells i + j = s depend
    only on diagonals s - 1 and s - 2), which is vectorised and gives
    exactly the sums of the cell-by-cell recurrence. On equal costs the
    backtracking prefers the (1, 0) step, then (0, 1), then (1, 1).
    Returns the signals repeated along the optimal path.
    """
    n = len(x)
    w = max(int(math.ceil(window * n)) - 1, 0)       # |i - j| <= w
    width = 2 * w + 1
    inf = math.inf
    acc = np.full((n, width), inf)                    # acc[i, j - i + w]

    def gather(i: NDArray[np.intp], k: NDArray[np.intp]) -> Array:
        ok = (i >= 0) & (k >= 0) & (k < width)
        out = np.full(len(i), inf)
        out[ok] = acc[i[ok], k[ok]]
        return out

    acc[0, w] = (x[0] - y[0]) ** 2
    for s in range(1, 2 * n - 1):
        i_lo = max(0, s - (n - 1), (s - w + 1) // 2)
        i_hi = min(n - 1, s, (s + w) // 2)
        rows = np.arange(i_lo, i_hi + 1)
        cols = s - rows
        band = cols - rows + w
        previous = np.minimum(
            np.minimum(gather(rows - 1, band + 1),       # (i-1, j)
                       gather(rows, band - 1)),          # (i, j-1)
            gather(rows - 1, band),                      # (i-1, j-1)
        )
        acc[rows, band] = (x[rows] - y[cols]) ** 2 + previous

    def at(i: int, j: int) -> float:
        k = j - i + w
        return float(acc[i, k]) if i >= 0 and j >= 0 and 0 <= k < width else inf

    i = j = n - 1
    path_i, path_j = [i], [j]
    while i > 0 or j > 0:
        options = ((at(i - 1, j), i - 1, j),
                   (at(i, j - 1), i, j - 1),
                   (at(i - 1, j - 1), i - 1, j - 1))
        _, i, j = min(options, key=lambda o: o[0])    # first minimum wins
        path_i.append(i)
        path_j.append(j)
    pi, pj = np.array(path_i[::-1]), np.array(path_j[::-1])
    return x[pi], y[pj]


def _smoothed_slope(x: Array, dt: float) -> Array:
    """Central-difference derivative smoothed with a centred nine-point
    moving average (1, 3, 5 and 7 points at the ends)."""
    d = np.gradient(x, dt)
    out = np.convolve(d, np.ones(9) / 9.0, mode="same")
    for k, size in enumerate((1, 3, 5, 7)):
        if size <= len(d):
            out[k] = d[:size].mean()
            out[-k - 1] = d[-size:].mean()
    return out


def _l1_error(comp: Array, ref: Array, what: str) -> float:
    den = float(np.abs(ref).sum())
    if den == 0:
        raise ValueError(f"The reference {what} is zero over the interval.")
    return float(np.abs(comp - ref).sum()) / den


def _score(error: float, limit: float, k: float) -> float:
    if error <= 0:
        return 1.0
    if error >= limit:
        return 0.0
    return ((limit - error) / limit) ** k


def iso18571(
    time: ArrayLike,
    reference: ArrayLike,
    comparison: ArrayLike,
    comparison_time: ArrayLike | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
    dt: float = 1e-4,
    parameters: ISO18571Parameters | None = None,
) -> ISO18571Result:
    """Return the ISO/TS 18571 objective rating of two signals.

    Parameters
    ----------
    time:
        Time of the reference signal, s.
    reference:
        Reference signal (usually the test), any unit.
    comparison:
        Signal to rate (usually CAE), same unit.
    comparison_time:
        Time of the comparison signal if it differs from ``time``.
    t_start, t_end:
        Interval of evaluation, s. Default: the interval both signals
        cover. Choose it to contain the event and little else: long
        quiet tails raise the corridor score.
    dt:
        Time step the signals are resampled to (default 0.1 ms, the
        10 kHz the standard assumes).
    parameters:
        `ISO18571Parameters`; the default is the standard's values.

    Returns
    -------
    ISO18571Result

    Notes
    -----
    The procedure follows ISO/TS 18571:2024:

    1. **Corridor** Z: inner and outer corridors of half width
       ``a0`` and ``b0`` times the reference's absolute maximum; each
       sample scores 1 inside the inner corridor, 0 outside the outer
       one and ``((outer - d) / (outer - inner))^k_z`` between; Z is the
       average.
    2. **Phase** E_P: the comparison is shifted sample by sample, up to
       ``max_shift`` of the interval, and the shift with the highest
       Pearson correlation is kept (the smallest one on a tie). E_P
       falls linearly from 1 at no shift to 0 at ``max_shift``.
    3. **Magnitude** E_M: the shifted signals are aligned with dynamic
       time warping (squared-difference cost, window 10 % of the
       length); the error is ``sum|C - T| / sum|T|`` and E_M falls
       linearly from 1 at no error to 0 at 0.5.
    4. **Slope** E_S: central-difference derivatives of the shifted
       signals, smoothed with a nine-point moving average; the error is
       ``sum|C' - T'| / sum|T'|`` and E_S falls linearly to 0 at 2.0.
    5. **Rating** R = 0.4 Z + 0.2 E_P + 0.2 E_M + 0.2 E_S.

    The 2014 edition did not specify the warping window and computed the
    slope differently; ratings can differ slightly from 2014-based tools.
    """
    p = parameters or ISO18571Parameters()
    weights = p.w_z + p.w_p + p.w_m + p.w_s
    if not math.isclose(weights, 1.0, abs_tol=1e-9):
        raise ValueError(f"The weights must add up to 1, not {weights:g}.")
    t, ref, comp = resample_pair(time, reference, comparison, comparison_time,
                                 t_start, t_end, dt)
    n = len(t)

    corridor = _corridor_score(ref, comp, p.a0, p.b0, p.k_z,
                               float(np.abs(ref).max()))

    shift, rho = _best_shift(ref, comp, int(math.floor(n * p.max_shift)), _pearson)
    phase = _score(abs(shift), n * p.max_shift, p.k_p)
    ref_s, comp_s = _apply_shift(ref, comp, shift)

    comp_w, ref_w = _dtw_warp(comp_s, ref_s, p.dtw_window)
    mag_error = _l1_error(comp_w, ref_w, "signal")
    magnitude = _score(mag_error, p.max_magnitude_error, p.k_m)

    slope_error = _l1_error(_smoothed_slope(comp_s, dt), _smoothed_slope(ref_s, dt),
                            "slope")
    slope = _score(slope_error, p.max_slope_error, p.k_s)

    rating = p.w_z * corridor + p.w_p * phase + p.w_m * magnitude + p.w_s * slope
    return ISO18571Result(
        rating=rating,
        grade=iso18571_grade(rating),
        corridor=corridor,
        phase=phase,
        magnitude=magnitude,
        slope=slope,
        time_shift_ms=shift * dt * 1000.0,
        correlation=rho,
        magnitude_error=mag_error,
        slope_error=slope_error,
        t_start=float(t[0]),
        t_end=float(t[-1]),
        n_points=n,
    )


# --- Corridor and cross-correlation (CC) rating ---------------------------


@dataclass(frozen=True)
class CCParameters:
    """Parameters of the corridor and cross-correlation rating.

    The defaults are the values commonly cited for the published method
    (Gehre, Gades and Wernicke, ESV 2009). If your project compares
    results with another implementation, check its settings and set
    these to match. Names in parentheses are the parameter names
    commonly used for this method.
    """

    a0: float = 0.05
    """Inner corridor half width, fraction of the norm (A_0)."""
    b0: float = 0.50
    """Outer corridor half width (B_0)."""
    k_z: float = 2.0
    """Corridor exponent (K)."""
    int_min: float = 0.8
    """Minimum overlap of the shifted signals, fraction of the interval
    (INT_MIN); the largest shift is ``1 - int_min``."""
    d_min: float = 0.01
    """Time shift with full phase points, fraction of the interval
    (D_MIN)."""
    d_max: float = 0.12
    """Time shift with zero phase points (D_MAX)."""
    k_v: float = 1.0
    """Phase exponent (K_V)."""
    k_g: float = 1.0
    """Size exponent (K_G)."""
    k_p: float = 1.0
    """Shape (progression) exponent (K_P)."""
    w_phase: float = 1 / 3
    """Weight of the phase rating in the cross-correlation rating (G_V)."""
    w_size: float = 1 / 3
    """Weight of the size rating (G_G)."""
    w_shape: float = 1 / 3
    """Weight of the shape rating (G_P)."""
    w_corridor: float = 0.5
    """Weight of the corridor rating in the total (G_1)."""
    w_cross: float = 0.5
    """Weight of the cross-correlation rating in the total (G_2)."""
    norm: float | None = None
    """Corridor norm; default the reference's absolute maximum. Set it
    for small signals (for example a minimum displacement) so tiny
    absolute differences are not penalised."""


@dataclass(frozen=True)
class CCResult:
    """Corridor and cross-correlation rating of a comparison signal
    against a reference."""

    rating: float
    """Total rating, 0 to 1."""
    corridor: float
    """Corridor rating."""
    cross_correlation: float
    """Cross-correlation rating (weighted phase, size and shape)."""
    phase: float
    """Phase (time shift) rating."""
    size: float
    """Size rating: ratio of the smaller to the larger signal energy."""
    shape: float
    """Shape (progression) rating: the cross-correlation at the best
    shift."""
    time_shift_ms: float
    """Time shift with the highest cross-correlation, ms (positive: the
    comparison is late)."""
    correlation: float
    """Normalised cross-correlation at that shift."""
    t_start: float
    """Start of the interval of evaluation, s."""
    t_end: float
    """End of the interval of evaluation, s."""


def cc_rating(
    time: ArrayLike,
    reference: ArrayLike,
    comparison: ArrayLike,
    comparison_time: ArrayLike | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
    dt: float = 1e-4,
    parameters: CCParameters | None = None,
) -> CCResult:
    """Return the corridor and cross-correlation (CC) rating of two
    signals.

    Parameters
    ----------
    time, reference, comparison, comparison_time, t_start, t_end, dt:
        As for `iso18571`.
    parameters:
        `CCParameters`.

    Returns
    -------
    CCResult

    Notes
    -----
    1. **Corridor**: the same corridor method as ISO/TS 18571, sized
       from ``norm`` (default the reference's absolute maximum).
    2. **Cross-correlation**: the comparison is shifted by up to
       ``1 - int_min`` of the interval; the shift with the highest
       normalised cross-correlation
       ``K = sum(T C) / sqrt(sum T^2 sum C^2)`` over the overlap is kept.

       - Phase: 1 for a shift up to ``d_min`` of the interval, 0 from
         ``d_max``, ``((d_max - d) / (d_max - d_min))^k_v`` between.
       - Size: ``(smaller / larger)^k_g`` of the two signal energies
         ``sum x^2`` over the shifted overlap.
       - Shape: ``max(K, 0)^k_p``.
       - Cross-correlation rating: their weighted sum.
    3. **Total**: ``w_corridor * corridor + w_cross * cross``.

    An automatic interval of evaluation and standard-deviation corridors
    (offered by some tools) are not implemented: give ``t_start`` and
    ``t_end``.
    """
    p = parameters or CCParameters()
    if not math.isclose(p.w_phase + p.w_size + p.w_shape, 1.0, abs_tol=1e-9):
        raise ValueError("The phase, size and shape weights must add up to 1.")
    if not math.isclose(p.w_corridor + p.w_cross, 1.0, abs_tol=1e-9):
        raise ValueError("The corridor and cross-correlation weights must add "
                         "up to 1.")
    if not 0 <= p.d_min < p.d_max:
        raise ValueError("d_min must be below d_max.")
    t, ref, comp = resample_pair(time, reference, comparison, comparison_time,
                                 t_start, t_end, dt)
    n = len(t)
    norm = float(np.abs(ref).max()) if p.norm is None else float(p.norm)
    corridor = _corridor_score(ref, comp, p.a0, p.b0, p.k_z, norm)

    max_shift = int(math.floor(n * (1.0 - p.int_min)))
    shift, k = _best_shift(ref, comp, max_shift, _uncentred)
    if not math.isfinite(k):
        raise ValueError("A signal is zero over the interval.")
    ref_s, comp_s = _apply_shift(ref, comp, shift)

    duration = (n - 1) * dt
    delay = abs(shift) * dt
    lo, hi = p.d_min * duration, p.d_max * duration
    if delay <= lo:
        phase = 1.0
    elif delay >= hi:
        phase = 0.0
    else:
        phase = ((hi - delay) / (hi - lo)) ** p.k_v

    e_ref, e_comp = float(ref_s @ ref_s), float(comp_s @ comp_s)
    size = (min(e_ref, e_comp) / max(e_ref, e_comp)) ** p.k_g
    shape = max(k, 0.0) ** p.k_p

    cross = p.w_phase * phase + p.w_size * size + p.w_shape * shape
    return CCResult(
        rating=p.w_corridor * corridor + p.w_cross * cross,
        corridor=corridor,
        cross_correlation=cross,
        phase=phase,
        size=size,
        shape=shape,
        time_shift_ms=shift * dt * 1000.0,
        correlation=k,
        t_start=float(t[0]),
        t_end=float(t[-1]),
    )


# --- Error measures ---------------------------------------------------------


@dataclass(frozen=True)
class ErrorMeasures:
    """Classic error measures between a reference and a comparison."""

    rmse: float
    """Root mean square error, unit of the signals."""
    nrmse: float
    """RMSE divided by the reference's absolute maximum."""
    mae: float
    """Mean absolute error."""
    max_error: float
    """Largest absolute difference."""
    peak_reference: float
    """Reference value at its largest magnitude (signed)."""
    peak_comparison: float
    """Comparison value at its largest magnitude (signed)."""
    peak_error: float
    """``(|peak comparison| - |peak reference|) / |peak reference|``:
    +0.10 means the comparison peaks 10 % higher."""
    peak_time_error_ms: float
    """Time of the comparison's peak minus the reference's, ms."""
    correlation: float
    """Pearson correlation coefficient (no shift)."""
    r_squared: float
    """Coefficient of determination of the comparison as a prediction
    of the reference, ``1 - SS_res / SS_tot`` (can be negative)."""
    sprague_geers_magnitude: float
    """Sprague & Geers magnitude error M (0 for equal energy)."""
    sprague_geers_phase: float
    """Sprague & Geers phase error P, 0 to 1."""
    sprague_geers_comprehensive: float
    """Sprague & Geers comprehensive error C = sqrt(M^2 + P^2)."""
    russell_magnitude: float
    """Russell magnitude error RM."""
    russell_phase: float
    """Russell phase error RP (the same as Sprague & Geers P)."""
    russell_comprehensive: float
    """Russell comprehensive error RC = sqrt(pi/4 (RM^2 + RP^2))."""


def error_measures(
    time: ArrayLike,
    reference: ArrayLike,
    comparison: ArrayLike,
    comparison_time: ArrayLike | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
    dt: float = 1e-4,
) -> ErrorMeasures:
    """Return classic error measures between two signals.

    Arguments as for `iso18571`. The Sprague & Geers (2004) and Russell
    (1997) errors are computed from the integrals of ``m^2``, ``c^2``
    and ``m c`` over the interval (m: reference, c: comparison); 0 is a
    perfect match.
    """
    t, m, c = resample_pair(time, reference, comparison, comparison_time,
                            t_start, t_end, dt)
    diff = c - m
    norm = float(np.abs(m).max())
    if norm == 0:
        raise ValueError("The reference signal is zero over the interval.")
    i_m, i_c = int(np.argmax(np.abs(m))), int(np.argmax(np.abs(c)))

    mm = float(_trapz(m * m, t))
    cc = float(_trapz(c * c, t))
    mc = float(_trapz(m * c, t))
    if cc == 0:
        raise ValueError("The comparison signal is zero over the interval.")
    cos = max(-1.0, min(1.0, mc / math.sqrt(mm * cc)))
    phase = math.acos(cos) / math.pi
    sg_m = math.sqrt(cc / mm) - 1.0
    rel = (cc - mm) / math.sqrt(mm * cc)
    r_m = math.copysign(math.log10(1.0 + abs(rel)), rel)

    ss_tot = float(((m - m.mean()) ** 2).sum())
    return ErrorMeasures(
        rmse=float(np.sqrt(np.mean(diff**2))),
        nrmse=float(np.sqrt(np.mean(diff**2))) / norm,
        mae=float(np.mean(np.abs(diff))),
        max_error=float(np.abs(diff).max()),
        peak_reference=float(m[i_m]),
        peak_comparison=float(c[i_c]),
        peak_error=(abs(float(c[i_c])) - norm) / norm,
        peak_time_error_ms=float(t[i_c] - t[i_m]) * 1000.0,
        correlation=_pearson(m, c) if ss_tot > 0 else math.nan,
        r_squared=1.0 - float((diff**2).sum()) / ss_tot if ss_tot > 0 else math.nan,
        sprague_geers_magnitude=sg_m,
        sprague_geers_phase=phase,
        sprague_geers_comprehensive=math.hypot(sg_m, phase),
        russell_magnitude=r_m,
        russell_phase=phase,
        russell_comprehensive=math.sqrt(math.pi / 4.0 * (r_m**2 + phase**2)),
    )


# --- Everything at once --------------------------------------------------


@dataclass(frozen=True)
class Comparison:
    """`iso18571`, `cc_rating` and `error_measures` of one signal pair."""

    iso: ISO18571Result
    cc: CCResult
    errors: ErrorMeasures
    channel: str = field(default="")
    """Optional channel name."""

    def summary(self) -> str:
        """One line per method, for reports and logs."""
        name = f"{self.channel}: " if self.channel else ""
        iso, c, e = self.iso, self.cc, self.errors
        return (
            f"{name}ISO 18571 {iso.rating:.3f} ({iso.grade}; corridor "
            f"{iso.corridor:.3f}, phase {iso.phase:.3f}, magnitude "
            f"{iso.magnitude:.3f}, slope {iso.slope:.3f}, shift "
            f"{iso.time_shift_ms:+.1f} ms)\n"
            f"{name}CC rating {c.rating:.3f} (corridor {c.corridor:.3f}, phase "
            f"{c.phase:.3f}, size {c.size:.3f}, shape {c.shape:.3f})\n"
            f"{name}Errors: peak {e.peak_error:+.1%} at "
            f"{e.peak_time_error_ms:+.1f} ms, NRMSE {e.nrmse:.3f}, "
            f"Sprague & Geers C {e.sprague_geers_comprehensive:.3f}"
        )


def compare(
    time: ArrayLike,
    reference: ArrayLike,
    comparison: ArrayLike,
    comparison_time: ArrayLike | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
    dt: float = 1e-4,
    channel: str = "",
    iso_parameters: ISO18571Parameters | None = None,
    cc_parameters: CCParameters | None = None,
) -> Comparison:
    """Return the ISO/TS 18571 rating, the CC rating and the error
    measures of one signal pair, over the same interval.

    ``flatten(compare(...), prefix="head_")`` gives columns such as
    ``head_iso.rating`` and ``head_errors.peak_error`` for a feature
    table.
    """
    args = (time, reference, comparison, comparison_time, t_start, t_end, dt)
    return Comparison(
        iso=iso18571(*args, parameters=iso_parameters),
        cc=cc_rating(*args, parameters=cc_parameters),
        errors=error_measures(*args),
        channel=channel,
    )
