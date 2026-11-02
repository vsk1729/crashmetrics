"""Hardening curve for ``*MAT_024``: true stress, necking, plastic strain,
extrapolation.

``*MAT_PIECEWISE_LINEAR_PLASTICITY`` needs true stress against effective
plastic strain, from the yield point to large strains (crash elements
reach 50-100 % plastic strain), while a tensile test gives a valid curve
only up to necking. The steps:

- `true_curve`: engineering -> true stress-strain, ``eps = ln(1 + e)``,
  ``sigma = s (1 + e)``, valid up to necking.
- `necking_point`: necking at the maximum engineering stress (Considère:
  ``d sigma / d eps = sigma``), located between samples.
- `plastic_curve`: true stress against effective plastic strain
  ``eps_p = eps - sigma / E`` from the yield point to necking: the
  measured part of the card curve.
- `fit_hardening`: Swift, Voce, Hockett-Sherby and Swift-Voce laws fitted
  to it, with the fit error and the Considère check at necking;
  `compare_fits` shows how far the laws part beyond necking.
- `extrapolate_curve`: measured curve up to necking, the chosen law
  beyond it.
- `n_value`: strain-hardening exponent n and strength coefficient K
  (Hollomon fit ``sigma = K eps^n``).

Units: stress MPa, strain dimensionless; laws use true stress and
effective plastic strain.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics.materials.tensile import TensileTest, tensile_properties

__all__ = [
    "LAWS",
    "HardeningCurve",
    "HardeningFit",
    "NValue",
    "NeckingPoint",
    "TrueCurve",
    "compare_fits",
    "extrapolate_curve",
    "fit_hardening",
    "n_value",
    "necking_point",
    "plastic_curve",
    "true_curve",
]

FloatArray = NDArray[np.float64]


# --- True stress-strain and necking -------------------------------------------


@dataclass(frozen=True)
class TrueCurve:
    """True stress-strain curve up to necking."""

    strain: FloatArray
    """True (logarithmic) strain, ``ln(1 + e)``."""
    stress: FloatArray
    """True stress ``s (1 + e)``, MPa (constant volume)."""


def true_curve(test: TensileTest, *, after_necking: bool = False) -> TrueCurve:
    """True stress and strain from the engineering curve.

    The conversion assumes uniform deformation at constant volume, which
    holds up to necking (the maximum engineering stress). Points after
    necking are dropped unless ``after_necking=True`` (then they are
    only nominal: the real strain in the neck is larger).
    """
    e, s = test.strain, test.stress
    if np.any(e <= -1.0):
        raise ValueError("Engineering strain must be above -1.")
    end = len(e) if after_necking else int(np.argmax(s)) + 1
    return TrueCurve(np.log1p(e[:end]), s[:end] * (1.0 + e[:end]))


@dataclass(frozen=True)
class NeckingPoint:
    """Onset of necking (diffuse necking, maximum force)."""

    engineering_strain: float
    engineering_stress: float
    """Rm, MPa."""
    true_strain: float
    true_stress: float
    """MPa."""
    considere_ratio: float
    """``(d sigma / d eps) / sigma`` of the true curve around necking
    (linear fit over the window); about 1 by the Considère criterion.
    Far from 1: the maximum is poorly defined (noise, few points)."""


def necking_point(test: TensileTest, *, window: float = 0.02) -> NeckingPoint:
    """Necking at the maximum engineering stress.

    The maximum is located between samples by a parabola through the
    points within ``window`` engineering strain around the largest stress
    (default 2 %, that is ±1 %), which also averages out noise on the
    flat top. The Considère ratio is the slope of the true curve over the
    same points divided by the true stress there.
    """
    if not 0 < window < 0.5:
        raise ValueError("window must be an engineering strain between 0 and 0.5.")
    e, s = test.strain, test.stress
    i = int(np.argmax(s))
    sel = np.flatnonzero(np.abs(e - e[i]) <= window / 2)
    if len(sel) < 5:
        raise ValueError("Fewer than 5 points within window of the maximum stress; "
                         "widen window.")
    a, b, c = np.polyfit(e[sel], s[sel], 2)
    e_n = float(-b / (2 * a)) if a < 0 else float(e[i])
    if not e[sel[0]] <= e_n <= e[sel[-1]]:
        e_n = float(e[i])
    s_n = float(np.polyval((a, b, c), e_n))
    t = np.log1p(e[sel])
    sig = s[sel] * (1 + e[sel])
    slope = float(np.polyfit(t, sig, 1)[0])
    true_stress = s_n * (1 + e_n)
    return NeckingPoint(e_n, s_n, math.log1p(e_n), true_stress, slope / true_stress)


# --- Plastic curve -------------------------------------------------------------


@dataclass(frozen=True)
class HardeningCurve:
    """True stress against effective plastic strain: the ``*MAT_024``
    hardening curve (LCSS)."""

    plastic_strain: FloatArray
    """Effective plastic strain, starting at 0."""
    stress: FloatArray
    """True stress, MPa; the first value is the yield stress."""
    modulus: float
    """Young's modulus used for the plastic strain, MPa."""
    necking_strain: float
    """Plastic strain at necking: measured data up to here."""
    name: str = ""
    info: Mapping[str, object] = field(default_factory=dict)

    @property
    def yield_stress(self) -> float:
        """First stress of the curve (SIGY of the card), MPa."""
        return float(self.stress[0])


def plastic_curve(
    test: TensileTest,
    *,
    start: Literal["offset", "zero"] = "offset",
    offset: float = 0.002,
    modulus: float | None = None,
) -> HardeningCurve:
    """True stress against effective plastic strain, yield to necking.

    ``eps_p = ln(1 + e) - sigma / E`` with ``E`` fitted on the curve
    (`crashmetrics.materials.tensile_properties`) unless ``modulus`` is
    given.

    - ``start="offset"`` (default): the curve starts at the offset yield
      point (plastic strain ``offset``, 0.2 % for Rp0.2), and the plastic
      strain is counted from there, so the first point is
      ``(0, yield stress)`` as ``*MAT_024`` expects. The gradual
      elastic-plastic transition below Rp0.2 is left out.
    - ``start="zero"``: the plastic strain as computed, from the first
      point where it becomes positive (the curve starts at the end of
      the linear part).

    Points where the plastic strain does not increase (noise) are
    dropped. Clean the curve first (`clean_tensile`), and handle a Lüders
    plateau (`smooth_luders`).
    """
    if start not in ("offset", "zero"):
        raise ValueError('start must be "offset" or "zero".')
    E = modulus if modulus is not None else tensile_properties(test).modulus
    if not (math.isfinite(E) and E > 0):
        raise ValueError("modulus must be positive.")
    tc = true_curve(test)
    ep = tc.strain - tc.stress / E
    origin = offset if start == "offset" else 0.0
    # Start after the last point at or below the origin, so noise in the
    # elastic part (plastic strain jittering around zero) is skipped.
    threshold = max(origin, 1e-6)
    below = np.flatnonzero(ep <= threshold)
    if not len(below):
        raise ValueError("The curve starts in the plastic range; clean it first.")
    j = int(below[-1]) + 1
    if j >= len(ep):
        raise ValueError("The curve has no plastic strain before necking.")
    # Interpolate the start point where eps_p crosses the origin.
    w = (origin - ep[j - 1]) / (ep[j] - ep[j - 1])
    s0 = float(tc.stress[j - 1] + w * (tc.stress[j] - tc.stress[j - 1]))
    p = np.concatenate(([0.0], ep[j:] - origin))
    s = np.concatenate(([s0], tc.stress[j:]))
    keep = np.concatenate(([True], p[1:] > np.maximum.accumulate(p)[:-1]))
    p, s = p[keep], s[keep]
    if len(p) < 4:
        raise ValueError("Fewer than 4 points between yield and necking.")
    return HardeningCurve(p, s, float(E), float(p[-1]), test.name,
                          {"start": start, "offset": origin})


# --- Hardening laws -------------------------------------------------------------

Law = Callable[[FloatArray, FloatArray], FloatArray]


def _swift(p: FloatArray, x: FloatArray) -> FloatArray:
    k, e0, n = x
    return np.asarray(k * (e0 + p) ** n)


def _voce(p: FloatArray, x: FloatArray) -> FloatArray:
    s0, q, b = x
    return np.asarray(s0 + q * (1.0 - np.exp(-b * p)))


def _hockett_sherby(p: FloatArray, x: FloatArray) -> FloatArray:
    s0, ss, a, m = x
    return np.asarray(ss - (ss - s0) * np.exp(-a * p ** m))


def _swift_voce(p: FloatArray, x: FloatArray) -> FloatArray:
    alpha = x[0]
    return np.asarray(alpha * _swift(p, x[1:4]) + (1 - alpha) * _voce(p, x[4:7]))


LAWS: dict[str, str] = {
    "swift": "sigma = K (eps0 + eps_p)^n",
    "voce": "sigma = sigma0 + Q (1 - exp(-beta eps_p))",
    "hockett_sherby": "sigma = sigma_s - (sigma_s - sigma0) exp(-a eps_p^m)",
    "swift_voce": "sigma = alpha Swift + (1 - alpha) Voce",
}
"""Hardening laws of `fit_hardening` (true stress, effective plastic
strain). Swift keeps hardening (power law); Voce and Hockett-Sherby
saturate; Swift-Voce lies between."""

_PARAMS = {
    "swift": ("K", "eps0", "n"),
    "voce": ("sigma0", "Q", "beta"),
    "hockett_sherby": ("sigma0", "sigma_s", "a", "m"),
    "swift_voce": ("alpha", "K", "eps0", "n", "sigma0", "Q", "beta"),
}
_FUNCS: dict[str, Law] = {"swift": _swift, "voce": _voce,
                          "hockett_sherby": _hockett_sherby,
                          "swift_voce": _swift_voce}


def _to_params(law: str, z: FloatArray) -> FloatArray:
    """Unconstrained variables -> physical parameters (positivity, alpha in
    [0, 1], sigma_s > sigma0)."""
    if law == "hockett_sherby":
        s0, ds, a, m = np.exp(z)
        return np.array([s0, s0 + ds, a, m])
    if law == "swift_voce":
        alpha = 1.0 / (1.0 + math.exp(-float(z[0])))
        return np.concatenate(([alpha], np.exp(z[1:])))
    return np.exp(z)


def _to_vars(law: str, x: Sequence[float]) -> FloatArray:
    if law == "hockett_sherby":
        s0, ss, a, m = x
        return np.log([s0, max(ss - s0, 1e-9), a, m])
    if law == "swift_voce":
        alpha = min(max(x[0], 1e-6), 1 - 1e-6)
        return np.concatenate(([math.log(alpha / (1 - alpha))], np.log(x[1:])))
    return np.log(np.asarray(x, dtype=float))


def _levenberg_marquardt(residual: Callable[[FloatArray], FloatArray],
                         z0: FloatArray, iterations: int = 300) -> FloatArray:
    """Small Levenberg-Marquardt least-squares solver (numeric Jacobian)."""
    z = np.asarray(z0, dtype=float)
    r = residual(z)
    cost = float(r @ r)
    lam = 1e-3
    for _ in range(iterations):
        jac = np.empty((len(r), len(z)))
        for k in range(len(z)):
            h = 1e-6 * (1.0 + abs(z[k]))
            dz = z.copy()
            dz[k] += h
            jac[:, k] = (residual(dz) - r) / h
        g = jac.T @ r
        a = jac.T @ jac
        improved = converged = False
        for _ in range(20):
            try:
                step = np.linalg.solve(a + lam * np.diag(np.diag(a) + 1e-12), -g)
            except np.linalg.LinAlgError:
                lam *= 10.0
                continue
            r_new = residual(z + step)
            new_cost = float(r_new @ r_new)
            if np.isfinite(new_cost) and new_cost < cost:
                z, r = z + step, r_new
                converged = cost - new_cost < 1e-14 * max(cost, 1e-300)
                cost = new_cost
                lam = max(lam / 3.0, 1e-12)
                improved = True
                break
            lam *= 4.0
        if not improved or converged:
            break
    return z


def _start_swift(p: FloatArray, s: FloatArray) -> list[float]:
    best: tuple[float, list[float]] = (math.inf, [1.0, 0.01, 0.2])
    for e0 in np.logspace(-5, -0.5, 60):
        n, ln_k = np.polyfit(np.log(e0 + p), np.log(s), 1)
        if n <= 0:
            continue
        sse = float(np.sum((math.exp(ln_k) * (e0 + p) ** n - s) ** 2))
        if sse < best[0]:
            best = (sse, [math.exp(ln_k), float(e0), float(n)])
    return best[1]


def _start_voce(p: FloatArray, s: FloatArray) -> list[float]:
    best: tuple[float, list[float]] = (math.inf, [float(s[0]), 1.0, 10.0])
    for b in np.logspace(-0.5, 3, 80):
        basis = np.column_stack((np.ones_like(p), 1.0 - np.exp(-b * p)))
        (s0, q), *_ = np.linalg.lstsq(basis, s, rcond=None)
        if s0 <= 0 or q <= 0:
            continue
        sse = float(np.sum((basis @ np.array([s0, q]) - s) ** 2))
        if sse < best[0]:
            best = (sse, [float(s0), float(q), float(b)])
    return best[1]


def _start_hockett_sherby(p: FloatArray, s: FloatArray) -> list[float]:
    best: tuple[float, list[float]] = (math.inf, [float(s[0]), float(s[-1]) * 1.2,
                                                  5.0, 0.7])
    for m in np.linspace(0.3, 1.5, 13):
        for a in np.logspace(-0.5, 2.5, 40):
            e = np.exp(-a * p ** m)
            basis = np.column_stack((1.0 - e, e))           # sigma_s, sigma0
            (ss, s0), *_ = np.linalg.lstsq(basis, s, rcond=None)
            if s0 <= 0 or ss <= s0:
                continue
            sse = float(np.sum((basis @ np.array([ss, s0]) - s) ** 2))
            if sse < best[0]:
                best = (sse, [float(s0), float(ss), float(a), float(m)])
    return best[1]


@dataclass(frozen=True)
class HardeningFit:
    """A hardening law fitted to the measured plastic curve."""

    law: str
    params: dict[str, float]
    rms: float
    """Root-mean-square stress error over the fitted points, MPa."""
    r2: float
    fit_range: tuple[float, float]
    """Plastic strain range of the fit."""
    considere_ratio: float
    """``(d sigma / d eps_true) / sigma`` of the law at the necking
    strain: 1 if the law reproduces the onset of necking. Below 1: the
    law hardens too little there (necking too early in a simulation of
    the test); above 1: too much."""
    _x: tuple[float, ...] = field(repr=False, default=())

    def stress(self, plastic_strain: ArrayLike) -> FloatArray:
        """Stress of the law at the given plastic strains, MPa."""
        p = np.asarray(plastic_strain, dtype=float)
        if np.any(p < 0):
            raise ValueError("Plastic strain must be >= 0.")
        return _FUNCS[self.law](p, np.asarray(self._x))

    def slope(self, plastic_strain: float) -> float:
        """d sigma / d eps_p of the law, MPa (central difference)."""
        h = max(1e-7, 1e-5 * plastic_strain)
        lo = max(plastic_strain - h, 0.0)
        hi = plastic_strain + h
        return float((self.stress(hi) - self.stress(lo))[()] / (hi - lo))


def _fit_law(law: str, p: FloatArray, s: FloatArray, starts: Mapping[str,
             list[float]]) -> FloatArray:
    if law == "swift_voce":
        x0 = [0.5, *starts["swift"], *starts["voce"]]
        best = (math.inf, x0)
        for alpha in np.linspace(0.0, 1.0, 21):
            x = [alpha, *starts["swift"], *starts["voce"]]
            sse = float(np.sum((_swift_voce(p, np.array(x)) - s) ** 2))
            if sse < best[0]:
                best = (sse, x)
        x0 = best[1]
    else:
        x0 = starts[law]
    scale = float(np.max(s))

    def residual(z: FloatArray) -> FloatArray:
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            r = (_FUNCS[law](p, _to_params(law, z)) - s) / scale
        return np.where(np.isfinite(r), r, 1e6)

    return _to_params(law, _levenberg_marquardt(residual, _to_vars(law, x0)))


def fit_hardening(
    curve: HardeningCurve,
    laws: Sequence[str] = ("swift", "voce", "hockett_sherby", "swift_voce"),
    *,
    fit_range: tuple[float, float] | None = None,
) -> dict[str, HardeningFit]:
    """Fit hardening laws (`LAWS`) to the measured plastic curve.

    Parameters
    ----------
    curve:
        From `plastic_curve`.
    laws:
        Laws to fit.
    fit_range:
        Plastic strain range (default: the whole curve, yield to
        necking). Starting above the yield region (for example at 0.02)
        often extrapolates better when the transition after yield is
        not of the law's shape.

    Returns
    -------
    dict
        Law name -> `HardeningFit` with parameters, RMS error (MPa), R²
        and the Considère ratio at necking.
    """
    unknown = set(laws) - set(LAWS)
    if unknown:
        raise ValueError(f"Unknown laws {sorted(unknown)}; known: {list(LAWS)}.")
    p, s = curve.plastic_strain, curve.stress
    lo, hi = fit_range if fit_range is not None else (0.0, float(p[-1]))
    sel = (p >= lo) & (p <= hi)
    if int(sel.sum()) < 5:
        raise ValueError("Fewer than 5 points in fit_range.")
    p_fit, s_fit = p[sel], s[sel]
    starts = {"swift": _start_swift(p_fit, s_fit), "voce": _start_voce(p_fit, s_fit)}
    if "hockett_sherby" in laws:
        starts["hockett_sherby"] = _start_hockett_sherby(p_fit, s_fit)
    out = {}
    for law in laws:
        x = _fit_law(law, p_fit, s_fit, starts)
        model = _FUNCS[law](p_fit, x)
        resid = model - s_fit
        total = float(np.sum((s_fit - s_fit.mean()) ** 2))
        fit = HardeningFit(law, dict(zip(_PARAMS[law], map(float, x))),
                           float(np.sqrt(np.mean(resid ** 2))),
                           1.0 - float(np.sum(resid ** 2)) / total if total else 1.0,
                           (float(lo), float(hi)), math.nan, tuple(map(float, x)))
        # Considère with respect to true strain: d eps = d eps_p (1 + h / E).
        h = fit.slope(curve.necking_strain)
        sig = float(fit.stress(curve.necking_strain)[()])
        ratio = h / (1.0 + h / curve.modulus) / sig
        out[law] = HardeningFit(fit.law, fit.params, fit.rms, fit.r2, fit.fit_range,
                                ratio, fit._x)
    return out


def compare_fits(
    fits: Mapping[str, HardeningFit],
    strains: Sequence[float] = (0.1, 0.2, 0.5, 1.0),
) -> str:
    """Text table: fit error, Considère ratio and stress of each law at
    ``strains`` (plastic). The laws agree up to necking and part beyond
    it; the spread at large strain is what the choice of law decides."""
    head = (f"{'law':15} {'RMS MPa':>8} {'R2':>8} {'Considere':>9} "
            + " ".join(f"{'@' + format(e, 'g'):>8}" for e in strains))
    lines = [head]
    for name, f in fits.items():
        values = " ".join(f"{float(f.stress(e)[()]):8.1f}" for e in strains)
        lines.append(f"{name:15} {f.rms:8.2f} {f.r2:8.5f} {f.considere_ratio:9.3f} "
                     f"{values}")
    return "\n".join(lines)


def extrapolate_curve(
    curve: HardeningCurve,
    fit: HardeningFit,
    *,
    strain_max: float = 1.0,
    points: int = 40,
    continuous: bool = True,
) -> HardeningCurve:
    """Measured curve up to necking, the fitted law beyond.

    ``points`` law points are spaced from the necking strain to
    ``strain_max`` (plastic). With ``continuous=True`` the law is
    shifted by the small stress difference at necking so the curve has
    no step there.
    """
    if strain_max <= curve.necking_strain:
        raise ValueError("strain_max must be above the necking strain "
                         f"({curve.necking_strain:.4f}).")
    if points < 2:
        raise ValueError("points must be at least 2.")
    tail = np.linspace(curve.necking_strain, strain_max, points + 1)[1:]
    shift = 0.0
    if continuous:
        shift = float(curve.stress[-1] - fit.stress(curve.necking_strain)[()])
    stress = np.concatenate((curve.stress, fit.stress(tail) + shift))
    strain = np.concatenate((curve.plastic_strain, tail))
    info = {**curve.info, "extrapolation": {"law": fit.law, "params": fit.params,
                                            "from": curve.necking_strain,
                                            "to": strain_max, "shift": shift}}
    return HardeningCurve(strain, stress, curve.modulus, curve.necking_strain,
                          curve.name, info)


# --- n-value ----------------------------------------------------------------------


@dataclass(frozen=True)
class NValue:
    """Hollomon fit ``sigma = K eps^n`` of the true curve."""

    n: float
    """Strain-hardening exponent."""
    k: float
    """Strength coefficient K, MPa."""
    r2: float
    """R² of the log-log fit."""
    strain_range: tuple[float, float]
    """Engineering strain range used."""
    points: int


def n_value(
    test: TensileTest,
    *,
    strain_range: tuple[float, float | None] = (0.10, None),
    strain: Literal["total", "plastic"] = "total",
    modulus: float | None = None,
) -> NValue:
    """Strain-hardening exponent n and strength coefficient K.

    Least-squares line through ``ln(true stress)`` against
    ``ln(true strain)`` over an engineering strain range (default from
    10 % to the uniform elongation Ag, "n10-Ag"; give for example
    ``(0.10, 0.20)`` for n10-20). ``strain="plastic"`` uses the true
    plastic strain (elastic part removed with ``modulus`` or the fitted
    E) instead of the total true strain; ISO 10275 and ASTM E646 give the
    exact definitions for certificates.
    """
    lo, hi = strain_range
    e, s = test.strain, test.stress
    peak = int(np.argmax(s))
    hi_value = float(e[peak]) if hi is None else float(hi)
    if not 0 < lo < hi_value:
        raise ValueError(f"Invalid strain range ({lo}, {hi_value:.4g}); the upper "
                         "end defaults to Ag.")
    sel = (e >= lo) & (e <= hi_value) & (np.arange(len(e)) <= peak)
    if int(sel.sum()) < 5:
        raise ValueError("Fewer than 5 points in the strain range.")
    t = np.log1p(e[sel])
    sig = s[sel] * (1 + e[sel])
    if strain == "plastic":
        E = modulus if modulus is not None else tensile_properties(test).modulus
        t = t - sig / E
    elif strain != "total":
        raise ValueError('strain must be "total" or "plastic".')
    x, y = np.log(t), np.log(sig)
    n, ln_k = np.polyfit(x, y, 1)
    resid = y - (n * x + ln_k)
    total = float(np.sum((y - y.mean()) ** 2))
    return NValue(float(n), float(math.exp(ln_k)),
                  1.0 - float(np.sum(resid ** 2)) / total if total else 1.0,
                  (float(lo), hi_value), int(sel.sum()))
