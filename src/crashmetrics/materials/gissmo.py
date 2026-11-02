"""Failure with GISSMO: calibration and ``*MAT_ADD_DAMAGE_GISSMO``.

GISSMO (Neukamm, Feucht, Haufe) accumulates damage along the loading
path of every integration point:

``dD = n D^(1 - 1/n) d eps_p / eps_f(eta)``,   failure at ``D = 1``

with ``eps_f(eta)`` the failure strain as a function of stress
triaxiality ``eta = sigma_m / sigma_vm`` (LCSDG) and ``n`` the damage
exponent (DMGEXP). An instability measure ``F`` accumulates the same way
against the critical strain ``eps_crit(eta)`` (ECRIT); when ``F`` reaches
1 the damage ``D_crit`` at that moment starts the stress fade-out

``sigma* = sigma (1 - ((D - D_crit) / (1 - D_crit))^m)``

with the fading exponent ``m`` (FADEXP). For any path,
``D^(1/n) = integral of d eps_p / eps_f(eta)``, so the strain at fracture
does not depend on ``n``; ``n`` shapes D and with it ``D_crit``.

This module:

- **Stress states** (plane stress, von Mises, proportional loading):
  `TRIAXIALITY` of the standard tests, `triaxiality_from_strain_ratio`,
  `plane_stress_strains` (major / minor strain -> triaxiality and
  equivalent strain, for forming limits and DIC), `lode_parameter`,
  `average_triaxiality`.
- **Failure curve**: `FractureTest` (a fracture point, optionally with
  its measured path) and `fit_failure_curve` with the Hosford-Coulomb,
  Johnson-Cook or a tabulated model, fitted so that D reaches 1 exactly
  at the measured fracture of every test.
- **Instability curve** from a forming limit curve
  (`instability_from_flc`) or the necking strain.
- **Regularisation**: `regularization_estimate` (first estimate of the
  element size factors LCREGD), `RegularizationCurve`.
- `integrate_damage`: D, F and the stress fading factor along any path
  (for checks and plots).
- `GissmoCard`: the ``*MAT_ADD_DAMAGE_GISSMO`` card with its curves in
  any unit system, with checks; add it to a ``*MAT_024`` include with
  ``Mat024.write(..., damage=card)``.

Strains are equivalent plastic strains; element sizes in mm; strain
rates in 1/s.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics.materials.card import keyword_number
from crashmetrics.materials.hardening import _levenberg_marquardt
from crashmetrics.materials.rate import UNIT_SYSTEMS
from crashmetrics.materials.verify import LENGTH_SCALE

__all__ = [
    "FAILURE_MODELS",
    "TRIAXIALITY",
    "DamageHistory",
    "FailureFit",
    "FractureTest",
    "GissmoCard",
    "RegularizationCurve",
    "average_triaxiality",
    "fit_failure_curve",
    "instability_from_flc",
    "integrate_damage",
    "lode_parameter",
    "plane_stress_strains",
    "regularization_estimate",
    "triaxiality_from_strain_ratio",
]

FloatArray = NDArray[np.float64]

TRIAXIALITY: dict[str, float] = {
    "uniaxial_compression": -1.0 / 3.0,
    "shear": 0.0,
    "uniaxial": 1.0 / 3.0,
    "plane_strain": 1.0 / math.sqrt(3.0),
    "equibiaxial": 2.0 / 3.0,
}
"""Stress triaxiality of the standard plane-stress states (von Mises)."""


# --- Stress states -----------------------------------------------------------


def triaxiality_from_strain_ratio(beta: ArrayLike) -> FloatArray:
    """Triaxiality of proportional plane-stress loading with strain ratio
    ``beta = eps2 / eps1`` (von Mises, plastic incompressibility):
    ``(1 + beta) / (sqrt(3) sqrt(1 + beta + beta^2))``. -0.5 uniaxial
    (1/3), 0 plane strain (0.577), 1 equibiaxial (2/3), -1 shear (0)."""
    b = np.asarray(beta, dtype=float)
    return np.asarray((1.0 + b) / (math.sqrt(3.0) * np.sqrt(1.0 + b + b * b)))


def plane_stress_strains(major: ArrayLike, minor: ArrayLike
                         ) -> tuple[FloatArray, FloatArray]:
    """Triaxiality and equivalent plastic strain from major and minor
    in-plane (true, plastic) strains of proportional plane-stress
    loading, for example points of a forming limit curve or DIC fracture
    strains: ``eps_eq = 2 / sqrt(3) eps1 sqrt(1 + beta + beta^2)``."""
    e1 = np.asarray(major, dtype=float)
    e2 = np.asarray(minor, dtype=float)
    if np.any(e1 <= 0) or np.any(e2 > e1):
        raise ValueError("Need major > 0 and minor <= major.")
    beta = e2 / e1
    eq = 2.0 / math.sqrt(3.0) * e1 * np.sqrt(1.0 + beta + beta * beta)
    return triaxiality_from_strain_ratio(beta), np.asarray(eq)


def lode_parameter(triaxiality: ArrayLike) -> FloatArray:
    """Normalised Lode angle parameter of plane stress,
    ``1 - (2/pi) arccos(-27/2 eta (eta^2 - 1/3))``: 1 uniaxial tension,
    0 shear and plane strain, -1 equibiaxial tension (clipped outside
    -2/3 to 2/3, where plane stress is not possible)."""
    eta = np.asarray(triaxiality, dtype=float)
    xi = np.clip(-13.5 * eta * (eta * eta - 1.0 / 3.0), -1.0, 1.0)
    return np.asarray(1.0 - 2.0 / math.pi * np.arccos(xi))


def average_triaxiality(plastic_strain: ArrayLike, triaxiality: ArrayLike) -> float:
    """Strain-weighted average triaxiality of a path,
    ``(1 / eps_f) integral eta d eps_p`` (trapezoidal rule)."""
    e = np.asarray(plastic_strain, dtype=float)
    t = np.asarray(triaxiality, dtype=float)
    if e.shape != t.shape or len(e) < 2 or np.any(np.diff(e) < 0):
        raise ValueError("Need equal-length paths with non-decreasing strain.")
    span = e[-1] - e[0]
    if span <= 0:
        raise ValueError("The path has no plastic strain.")
    return float(np.sum(0.5 * (t[1:] + t[:-1]) * np.diff(e)) / span)


# --- Fracture tests and failure models ---------------------------------------


@dataclass(frozen=True)
class FractureTest:
    """One fracture test: equivalent plastic strain at fracture and its
    stress state.

    Give ``triaxiality`` for proportional loading (or the average), or
    the measured / simulated path (``path_strain``, ``path_triaxiality``
    from the start of plasticity to fracture), which the fit integrates.
    """

    name: str
    fracture_strain: float
    triaxiality: float | None = None
    path_strain: FloatArray | None = None
    path_triaxiality: FloatArray | None = None
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.fracture_strain > 0:
            raise ValueError(f"{self.name}: fracture_strain must be positive.")
        if (self.path_strain is None) != (self.path_triaxiality is None):
            raise ValueError(f"{self.name}: give both path arrays or neither.")
        if self.path_strain is not None and self.path_triaxiality is not None:
            e = np.asarray(self.path_strain, dtype=float)
            t = np.asarray(self.path_triaxiality, dtype=float)
            if e.shape != t.shape or len(e) < 2 or np.any(np.diff(e) < 0):
                raise ValueError(f"{self.name}: path arrays must have equal length "
                                 "(>= 2) and non-decreasing strain.")
            if abs(e[-1] - self.fracture_strain) > 1e-6 * self.fracture_strain:
                raise ValueError(f"{self.name}: the path must end at the fracture "
                                 "strain.")
            object.__setattr__(self, "path_strain", e)
            object.__setattr__(self, "path_triaxiality", t)
            if self.triaxiality is None:
                object.__setattr__(self, "triaxiality", average_triaxiality(e, t))
        elif self.triaxiality is None:
            raise ValueError(f"{self.name}: give triaxiality or a path.")
        if self.weight <= 0:
            raise ValueError(f"{self.name}: weight must be positive.")

    @property
    def eta(self) -> float:
        """(Average) triaxiality."""
        assert self.triaxiality is not None
        return float(self.triaxiality)


def _hosford_coulomb(eta: FloatArray, a: float, b: float, c: float, n: float
                     ) -> FloatArray:
    th = lode_parameter(eta)
    f1 = 2.0 / 3.0 * np.cos(math.pi / 6.0 * (1.0 - th))
    f2 = 2.0 / 3.0 * np.cos(math.pi / 6.0 * (3.0 + th))
    f3 = -2.0 / 3.0 * np.cos(math.pi / 6.0 * (1.0 + th))
    hosford = (0.5 * (np.abs(f1 - f2) ** a + np.abs(f2 - f3) ** a
                      + np.abs(f1 - f3) ** a)) ** (1.0 / a)
    bracket = np.maximum(hosford + c * (2.0 * eta + f1 + f3), 1e-12)
    return np.asarray(b * (1.0 + c) ** (1.0 / n) * bracket ** (-1.0 / n))


FAILURE_MODELS: dict[str, str] = {
    "hosford_coulomb": "b (1 + c)^(1/n) [Hosford_a(eta) + c (2 eta + f1 + f3)]^(-1/n)",
    "johnson_cook": "d1 + d2 exp(d3 eta)",
    "tabulated": "piecewise linear through the tests, constant beyond",
}
"""Failure strain models of `fit_failure_curve`. Hosford-Coulomb (Roth
and Mohr) in plane stress, with the Lode parameter from the triaxiality:
``b`` is the fracture strain in uniaxial and equibiaxial tension, ``a``
the Hosford exponent, ``c`` the friction coefficient, ``n`` fixed (0.1
by default)."""


@dataclass(frozen=True)
class FailureFit:
    """A failure curve eps_f(eta) fitted to fracture tests."""

    model: str
    params: dict[str, float]
    tests: tuple[FractureTest, ...]
    predicted: tuple[float, ...]
    """Fracture strain the curve predicts for each test (D = 1 on its
    path)."""
    _table: tuple[tuple[float, ...], tuple[float, ...]] = field(default=((), ()),
                                                              repr=False)

    def __call__(self, triaxiality: ArrayLike) -> FloatArray:
        """Failure strain at the given triaxialities."""
        eta = np.asarray(triaxiality, dtype=float)
        p = self.params
        if self.model == "hosford_coulomb":
            return _hosford_coulomb(eta, p["a"], p["b"], p["c"], p["n"])
        if self.model == "johnson_cook":
            return np.asarray(p["d1"] + p["d2"] * np.exp(p["d3"] * eta))
        x, y = self._table
        return np.asarray(np.interp(eta, x, y))

    @property
    def errors(self) -> FloatArray:
        """Relative error of the predicted fracture strain per test."""
        measured = np.array([t.fracture_strain for t in self.tests])
        return np.asarray(np.array(self.predicted) / measured - 1.0)

    def summary(self) -> str:
        """Table of the tests: triaxiality, measured and predicted fracture
        strain, error."""
        lines = [f"Failure curve: {self.model} "
                 + ", ".join(f"{k} {v:.4g}" for k, v in self.params.items()),
                 f"{'test':18} {'eta':>7} {'measured':>9} {'predicted':>9} "
                 f"{'error':>7}"]
        for t, pred, err in zip(self.tests, self.predicted, self.errors):
            lines.append(f"{t.name[:18]:18} {t.eta:7.3f} {t.fracture_strain:9.4f} "
                         f"{pred:9.4f} {err * 100:6.1f}%")
        return "\n".join(lines)


def _path(test: FractureTest) -> tuple[FloatArray, FloatArray]:
    if test.path_strain is not None and test.path_triaxiality is not None:
        return test.path_strain, test.path_triaxiality
    return (np.array([0.0, test.fracture_strain]),
            np.array([test.eta, test.eta]))


def _damage_integral(e: FloatArray, eta: FloatArray,
                     curve: Callable[[FloatArray], FloatArray]) -> FloatArray:
    """Cumulative ``integral d eps / eps_f(eta)`` along a path (= D^(1/n))."""
    inv = 1.0 / np.maximum(curve(eta), 1e-12)
    return np.concatenate(([0.0], np.cumsum(0.5 * (inv[1:] + inv[:-1]) * np.diff(e))))


def _strain_at_one(e: FloatArray, eta: FloatArray,
                   curve: Callable[[FloatArray], FloatArray]) -> float:
    """Strain where the integral reaches 1 (the path is extended with its
    last triaxiality if needed)."""
    integral = _damage_integral(e, eta, curve)
    if integral[-1] < 1.0:
        rest = (1.0 - integral[-1]) * float(curve(np.array([eta[-1]]))[0])
        return float(e[-1] + rest)
    k = int(np.searchsorted(integral, 1.0))
    w = (1.0 - integral[k - 1]) / (integral[k] - integral[k - 1])
    return float(e[k - 1] + w * (e[k] - e[k - 1]))


def fit_failure_curve(
    tests: Sequence[FractureTest],
    model: Literal["hosford_coulomb", "johnson_cook", "tabulated"] = "hosford_coulomb",
    *,
    hc_exponent: float = 0.1,
) -> FailureFit:
    """Fit a failure curve so that D reaches 1 at every test's fracture.

    The residual of a test is ``ln(integral d eps / eps_f(eta))`` along
    its path (proportional at its triaxiality if no path is given): 0
    when the curve predicts fracture exactly at the measured strain, and
    for proportional loading equal to the log of the measured over the
    curve's failure strain. Least squares (weighted), NumPy only.

    - ``"hosford_coulomb"``: a, b, c fitted, n = ``hc_exponent``; needs 3
      or more tests with different stress states.
    - ``"johnson_cook"``: d1, d2, d3 fitted; 3 or more tests.
    - ``"tabulated"``: one point per test at its (average) triaxiality,
      adjusted until each path reaches D = 1 at its fracture; linear
      between, constant beyond.
    """
    if model not in FAILURE_MODELS:
        raise ValueError(f"Unknown model; known: {list(FAILURE_MODELS)}.")
    if not tests:
        raise ValueError("Give at least one fracture test.")
    paths = [_path(t) for t in tests]
    w = np.sqrt(np.array([t.weight for t in tests]))

    if model == "tabulated":
        order = np.argsort([t.eta for t in tests])
        x = np.array([tests[i].eta for i in order])
        if np.any(np.diff(x) <= 0):
            raise ValueError("Tabulated fit needs tests at different triaxialities.")
        y = np.array([tests[i].fracture_strain for i in order])
        for _ in range(200):
            fit = FailureFit("tabulated", {}, tuple(tests), (), (tuple(x), tuple(y)))
            ratios = np.array([_damage_integral(paths[i][0], paths[i][1], fit)[-1]
                               for i in order])
            if np.max(np.abs(ratios - 1.0)) < 1e-10:
                break
            y = y * ratios
        params = {f"eta={xi:.4g}": float(yi) for xi, yi in zip(x, y)}
        fit = FailureFit("tabulated", params, tuple(tests), (),
                         (tuple(x), tuple(y)))
        pred = tuple(_strain_at_one(*p, fit) for p in paths)
        return FailureFit("tabulated", fit.params, tuple(tests), pred, fit._table)

    if len(tests) < 3:
        raise ValueError(f"{model} needs 3 or more fracture tests.")
    measured = np.array([t.fracture_strain for t in tests])
    etas = np.array([t.eta for t in tests])

    def make(z: FloatArray) -> Callable[[FloatArray], FloatArray]:
        if model == "hosford_coulomb":
            a, b, c = math.exp(z[0]), math.exp(z[1]), math.exp(z[2])
            return lambda eta: _hosford_coulomb(eta, a, b, c, hc_exponent)
        d1, d2, d3 = z
        return lambda eta: np.asarray(d1 + d2 * np.exp(d3 * eta))

    def residual(z: FloatArray) -> FloatArray:
        curve = make(z)
        out = []
        for e, eta in paths:
            values = curve(eta)
            if np.any(values <= 0) or not np.all(np.isfinite(values)):
                out.append(50.0)
                continue
            out.append(math.log(_damage_integral(e, eta, curve)[-1]))
        return np.asarray(out) * w

    if model == "hosford_coulomb":
        best = (math.inf, np.zeros(3))
        for a in (1.0, 1.25, 1.5, 1.75, 2.0):
            for c in (0.005, 0.02, 0.05, 0.1, 0.2):
                g = np.log(_hosford_coulomb(etas, a, 1.0, c, hc_exponent))
                ln_b = float(np.mean(np.log(measured) - g))
                z = np.log([a, math.exp(ln_b), c])
                cost = float(np.sum(residual(z) ** 2))
                if cost < best[0]:
                    best = (cost, z)
        z = _levenberg_marquardt(residual, best[1])
        a, b, c = np.exp(z)
        params = {"a": float(a), "b": float(b), "c": float(c), "n": hc_exponent}
    else:
        best = (math.inf, np.zeros(3))
        for d3 in np.linspace(-8.0, 8.0, 65):
            basis = np.column_stack((np.ones_like(etas), np.exp(d3 * etas)))
            (d1, d2), *_ = np.linalg.lstsq(basis / measured[:, None], np.ones_like(
                measured), rcond=None)
            z = np.array([d1, d2, d3])
            cost = float(np.sum(residual(z) ** 2))
            if cost < best[0]:
                best = (cost, z)
        z = _levenberg_marquardt(residual, best[1])
        params = {"d1": float(z[0]), "d2": float(z[1]), "d3": float(z[2])}
    fit = FailureFit(model, params, tuple(tests), ())
    pred = tuple(_strain_at_one(*p, fit) for p in paths)
    return FailureFit(model, params, tuple(tests), pred)


# --- Instability and regularisation ------------------------------------------


def instability_from_flc(major: ArrayLike, minor: ArrayLike, *,
                         extend_to: tuple[float, float] = (-1.0 / 3.0, 2.0 / 3.0)
                         ) -> tuple[FloatArray, FloatArray]:
    """Critical strain curve (ECRIT) from a forming limit curve.

    Each FLC point (true major and minor limit strains) becomes
    ``(triaxiality, equivalent strain)`` with `plane_stress_strains`; the
    curve is sorted by triaxiality and extended with constant values to
    ``extend_to`` (default -1/3 to 2/3), as an FLC covers only
    uniaxial to equibiaxial tension.
    """
    eta, eq = plane_stress_strains(major, minor)
    order = np.argsort(eta)
    x, y = eta[order], eq[order]
    if np.any(np.diff(x) <= 0):
        raise ValueError("FLC points must have different strain ratios.")
    lo, hi = extend_to
    if lo < x[0]:
        x, y = np.concatenate(([lo], x)), np.concatenate(([y[0]], y))
    if hi > x[-1]:
        x, y = np.concatenate((x, [hi])), np.concatenate((y, [y[-1]]))
    return x, y


@dataclass(frozen=True)
class RegularizationCurve:
    """Element size dependent factors on the failure strain (LCREGD)."""

    element_size: FloatArray
    """mm, increasing."""
    factor: FloatArray

    def __post_init__(self) -> None:
        h = np.asarray(self.element_size, dtype=float)
        f = np.asarray(self.factor, dtype=float)
        if h.shape != f.shape or len(h) < 2:
            raise ValueError("element_size and factor need equal length (>= 2).")
        if np.any(np.diff(h) <= 0) or np.any(h <= 0):
            raise ValueError("element_size must be positive and increasing.")
        if np.any(f <= 0):
            raise ValueError("factors must be positive.")
        object.__setattr__(self, "element_size", h)
        object.__setattr__(self, "factor", f)

    def __call__(self, size: float) -> float:
        """Factor at an element size (constant beyond the ends)."""
        return float(np.interp(size, self.element_size, self.factor))


def regularization_estimate(
    element_sizes: Sequence[float],
    *,
    reference_size: float,
    necking_strain: float,
    fracture_strain: float,
    neck_length: float,
) -> RegularizationCurve:
    """First estimate of the element size factors (LCREGD).

    An element larger than the neck (about the sheet thickness) averages
    the fracture strain in the neck with the uniform strain around:
    ``eps(h) = eps_n + (eps_f - eps_n) min(1, L / h)``; the factor is
    ``eps(h) / eps(reference_size)``, so it is 1 at the size the failure
    curve was calibrated for. Use it as the start of a mesh study (the
    tensile test simulated with each element size), not as the answer.
    """
    if not 0 <= necking_strain < fracture_strain:
        raise ValueError("Need 0 <= necking_strain < fracture_strain.")
    if reference_size <= 0 or neck_length <= 0:
        raise ValueError("reference_size and neck_length must be positive.")
    h = np.unique(np.asarray([*element_sizes, reference_size], dtype=float))

    def eps(size: FloatArray) -> FloatArray:
        return np.asarray(necking_strain + (fracture_strain - necking_strain)
                          * np.minimum(1.0, neck_length / size))

    return RegularizationCurve(h, eps(h) / eps(np.array([reference_size]))[0])


# --- Damage along a path -----------------------------------------------------


@dataclass(frozen=True)
class DamageHistory:
    """GISSMO quantities along a loading path."""

    plastic_strain: FloatArray
    damage: FloatArray
    """D."""
    instability: FloatArray
    """F (NaN without an instability curve or constant)."""
    fading: FloatArray
    """Stress factor ``1 - ((D - D_crit) / (1 - D_crit))^m`` after
    coupling starts, 1 before; 0 at failure."""
    critical_damage: float
    """D_crit (NaN if coupling never starts)."""
    coupling_strain: float
    """Plastic strain where coupling starts (F = 1), NaN if not reached."""
    fracture_strain: float
    """Plastic strain at D = 1, NaN if not reached on the path."""


def integrate_damage(
    plastic_strain: ArrayLike,
    triaxiality: ArrayLike,
    failure: Callable[[FloatArray], FloatArray] | float,
    *,
    dmgexp: float = 1.0,
    instability: Callable[[FloatArray], FloatArray] | float | None = None,
    dcrit: float = 0.0,
    fadexp: float = 1.0,
) -> DamageHistory:
    """D, F and the stress fading along a path, as GISSMO accumulates them.

    ``failure`` and ``instability`` are curves of triaxiality (for
    example a `FailureFit`, or a `GissmoCard` method) or constants.
    Without ``instability``, coupling starts at ``D = dcrit`` (0: no
    fading, brittle failure at D = 1). The integration is exact for the
    piecewise-linear path: ``D^(1/n) = integral d eps / eps_f``.
    """
    e = np.asarray(plastic_strain, dtype=float)
    eta = np.asarray(triaxiality, dtype=float)
    if e.shape != eta.shape or len(e) < 2 or np.any(np.diff(e) < 0):
        raise ValueError("Need equal-length paths with non-decreasing strain.")
    if dmgexp <= 0 or fadexp <= 0:
        raise ValueError("dmgexp and fadexp must be positive.")

    def as_curve(v: Callable[[FloatArray], FloatArray] | float
                 ) -> Callable[[FloatArray], FloatArray]:
        if callable(v):
            return v
        value = float(v)
        return lambda x: np.full_like(np.asarray(x, dtype=float), value)

    i_d = _damage_integral(e - e[0], eta, as_curve(failure))
    damage = np.minimum(i_d, 1.0) ** dmgexp
    if instability is not None:
        i_f = _damage_integral(e - e[0], eta, as_curve(instability))
        f_meas = np.minimum(i_f, 1.0) ** dmgexp
        reached = np.flatnonzero(i_f >= 1.0)
        if len(reached):
            k = int(reached[0])
            w = (1.0 - i_f[k - 1]) / (i_f[k] - i_f[k - 1]) if k else 0.0
            coupling = float(e[k - 1] + w * (e[k] - e[k - 1])) if k else float(e[0])
            dc = float((i_d[k - 1] + w * (i_d[k] - i_d[k - 1])) ** dmgexp) if k \
                else 0.0
        else:
            coupling, dc = math.nan, math.nan
    else:
        f_meas = np.full_like(e, math.nan)
        dc = dcrit if dcrit > 0 else math.nan
        target = dcrit ** (1.0 / dmgexp) if dcrit > 0 else math.inf
        coupling = math.nan
        if i_d[-1] >= target:
            k = int(np.searchsorted(i_d, target))
            w = (target - i_d[k - 1]) / (i_d[k] - i_d[k - 1]) if k else 0.0
            coupling = float(e[k - 1] + w * (e[k] - e[k - 1])) if k else float(e[0])
    fading = np.ones_like(e)
    if math.isfinite(dc) and dc < 1.0:
        active = damage >= dc
        fading[active] = 1.0 - ((damage[active] - dc) / (1.0 - dc)) ** fadexp
    fading[damage >= 1.0] = 0.0
    done = np.flatnonzero(i_d >= 1.0)
    if len(done):
        k = int(done[0])
        w = (1.0 - i_d[k - 1]) / (i_d[k] - i_d[k - 1]) if k else 0.0
        frac = float(e[k - 1] + w * (e[k] - e[k - 1])) if k else float(e[0])
    else:
        frac = math.nan
    return DamageHistory(e, damage, f_meas, fading, dc, coupling, frac)


# --- The card ----------------------------------------------------------------


def _ranges(x: FloatArray, mask: NDArray[np.bool_]) -> str:
    """The runs of ``x`` where ``mask`` holds, as "a to b, c"."""
    out = []
    i, n = 0, len(x)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and mask[j + 1]:
            j += 1
        out.append(f"{x[i]:.3g}" if i == j else f"{x[i]:.3g} to {x[j]:.3g}")
        i = j + 1
    return ", ".join(out)


def _curve_text(lcid: int, title: str, x: FloatArray, y: FloatArray) -> list[str]:
    n = keyword_number
    return (["*DEFINE_CURVE_TITLE", title[:80],
             "$#    lcid      sidr       sfa       sfo      offa      offo",
             f"{lcid:10d}{0:10d}" + n(1.0) + n(1.0) + n(0.0) + n(0.0),
             "$#                a1                  o1"]
            + [f"{a:20.8g}{o:20.8g}" for a, o in zip(x, y)])


@dataclass(frozen=True)
class GissmoCard:
    """One ``*MAT_ADD_DAMAGE_GISSMO`` card with its curves.

    ``failure`` and ``instability`` are given as (triaxiality, strain)
    arrays (or ``failure`` as a `FailureFit`, sampled on
    ``triaxiality_range``); ``instability`` may be a constant critical
    strain or None (then ``dcrit`` sets the coupling: 0 means none).
    ``fadexp`` is a constant or (element size mm, exponent) arrays.
    Element sizes in mm and strain rates in 1/s are converted on writing.
    Fields after LCREGD (card 2) and BIAXF (card 3) are left blank
    (LS-DYNA defaults); SHRF and BIAXF are passed through as given.
    """

    mid: int
    failure: tuple[FloatArray, FloatArray] | FailureFit
    instability: tuple[FloatArray, FloatArray] | float | None = None
    dmgexp: float = 1.0
    dcrit: float = 0.0
    fadexp: float | tuple[FloatArray, FloatArray] = 1.0
    regularization: RegularizationCurve | None = None
    rate_scaling: tuple[FloatArray, FloatArray] | None = None
    """(strain rates 1/s, factors on the failure strain)."""
    scale_instability_with_rate: bool = True
    dtyp: int = 1
    numfip: float = 1.0
    refsz: float = 0.0
    """Reference element size for extra damage output, mm (0: none)."""
    shrf: float = 0.0
    """LS-DYNA's reduction factor of the regularisation in shear (eta 0);
    written as given, not modelled here."""
    biaxf: float = 0.0
    """The same in equibiaxial tension (eta 2/3)."""
    triaxiality_range: tuple[float, float] = (-2.0 / 3.0, 2.0 / 3.0)
    points: int = 41
    first_curve_id: int | None = None
    """IDs of the curves from here up (default ``mid + 2000``)."""

    def __post_init__(self) -> None:
        if self.dtyp not in (0, 1):
            raise ValueError("dtyp must be 0 (damage only) or 1 (failure).")
        if self.dmgexp <= 0:
            raise ValueError("dmgexp must be positive.")
        if not 0 <= self.dcrit < 1:
            raise ValueError("dcrit must be in [0, 1).")
        if isinstance(self.fadexp, (int, float)) and self.fadexp <= 0:
            raise ValueError("fadexp must be positive.")
        lo, hi = self.triaxiality_range
        if not lo < hi or self.points < 3:
            raise ValueError("Need a triaxiality range lo < hi and points >= 3.")

    # Curves in engineering units ----------------------------------------------
    def failure_curve(self) -> tuple[FloatArray, FloatArray]:
        """(triaxiality, failure strain) as written to LCSDG."""
        if isinstance(self.failure, FailureFit):
            x = np.linspace(*self.triaxiality_range, self.points)
            return x, self.failure(x)
        x, y = (np.asarray(v, dtype=float) for v in self.failure)
        return x, y

    def instability_curve(self) -> tuple[FloatArray, FloatArray] | None:
        """(triaxiality, critical strain) as written to ECRIT, or None for a
        constant or no instability."""
        if self.instability is None or isinstance(self.instability, (int, float)):
            return None
        x, y = (np.asarray(v, dtype=float) for v in self.instability)
        return x, y

    def failure_strain(self, triaxiality: ArrayLike, element_size: float | None = None,
                       rate: float | None = None) -> FloatArray:
        """Failure strain the card gives (curve interpolated, constant
        beyond its ends; times the regularisation factor at
        ``element_size`` and the rate factor at ``rate``; SHRF and BIAXF
        not modelled)."""
        x, y = self.failure_curve()
        out = np.interp(np.asarray(triaxiality, dtype=float), x, y)
        if element_size is not None and self.regularization is not None:
            out = out * self.regularization(element_size)
        if rate is not None and self.rate_scaling is not None:
            out = out * float(np.interp(rate, *self.rate_scaling))
        return np.asarray(out)

    def critical_strain(self, triaxiality: ArrayLike) -> FloatArray | None:
        """Critical (instability) strain the card gives, or None."""
        eta = np.asarray(triaxiality, dtype=float)
        if self.instability is None:
            return None
        if isinstance(self.instability, (int, float)):
            return np.full_like(eta, float(self.instability))
        curve = self.instability_curve()
        assert curve is not None
        return np.asarray(np.interp(eta, *curve))

    def damage(self, plastic_strain: ArrayLike, triaxiality: ArrayLike, *,
               element_size: float | None = None) -> DamageHistory:
        """`integrate_damage` with this card's curves and parameters (a
        fading-exponent curve is read at ``element_size``, or at its first
        size when none is given)."""
        if isinstance(self.fadexp, (int, float)):
            m = float(self.fadexp)
        else:
            h, e = (np.asarray(v, dtype=float) for v in self.fadexp)
            m = float(np.interp(element_size if element_size is not None else h[0],
                                h, e))

        def fail(x: FloatArray) -> FloatArray:
            return self.failure_strain(x, element_size)

        def crit(x: FloatArray) -> FloatArray:
            out = self.critical_strain(x)
            assert out is not None
            return out

        inst: Callable[[FloatArray], FloatArray] | float | None = None
        if isinstance(self.instability, (int, float)):
            inst = float(self.instability)
        elif self.instability is not None:
            inst = crit
        return integrate_damage(plastic_strain, triaxiality, fail,
                                dmgexp=self.dmgexp, instability=inst,
                                dcrit=self.dcrit, fadexp=m)

    # IDs ----------------------------------------------------------------------
    def curve_ids(self) -> dict[str, int]:
        """IDs of the written curves: failure, instability, regularization,
        fading, rate (only those present)."""
        start = self.first_curve_id if self.first_curve_id is not None \
            else self.mid + 2000
        names = ["failure"]
        if self.instability_curve() is not None:
            names.append("instability")
        if self.regularization is not None:
            names.append("regularization")
        if not isinstance(self.fadexp, (int, float)):
            names.append("fading")
        if self.rate_scaling is not None:
            names.append("rate")
        return {name: start + 100 * i for i, name in enumerate(names)}

    # Checks -------------------------------------------------------------------
    def check(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """(errors, warnings) of the card.

        Errors: non-positive failure or critical strains; triaxiality not
        increasing; regularisation, fading or rate factors not positive.
        Warnings: failure curve not covering shear to equibiaxial tension
        (0 to 2/3); critical strain at or above the failure strain (no
        fading there: brittle failure under full stress), or, from some
        element size, at or above the regularised failure strain; DMGEXP
        below 1; regularisation factors rising with element size; no
        coupling at all (ECRIT and DCRIT 0).
        """
        issues: list[str] = []
        warnings: list[str] = []
        x, y = self.failure_curve()
        if np.any(np.diff(x) <= 0):
            issues.append("failure curve: triaxiality not strictly increasing")
        if np.any(y <= 0) or not np.all(np.isfinite(y)):
            issues.append("failure curve: failure strain zero, negative or not finite")
        if x[0] > 0.0 or x[-1] < 2.0 / 3.0 - 1e-9:
            warnings.append(f"failure curve covers triaxiality {x[0]:.3g} to "
                            f"{x[-1]:.3g}; LS-DYNA holds the end values beyond "
                            "(cover at least shear 0 to equibiaxial 2/3)")
        # Compare on a fine grid with both curves' points (kinks included).
        inst = self.instability_curve()
        grid = np.unique(np.concatenate((x, np.linspace(x[0], x[-1], 201),
                                         inst[0] if inst is not None else [])))
        grid = grid[(grid >= x[0]) & (grid <= x[-1])]
        fail = np.interp(grid, x, y)
        crit = self.critical_strain(grid)
        if crit is not None:
            if np.any(crit <= 0) or (inst is not None and np.any(inst[1] <= 0)):
                issues.append("instability: critical strain zero or negative")
            above = crit >= fail
            if np.any(above):
                warnings.append("critical strain at or above the failure strain at "
                                f"triaxiality {_ranges(grid, above)}: no fading there")
            elif self.regularization is not None:
                reg = self.regularization
                for size, factor in zip(reg.element_size, reg.factor):
                    low = crit >= fail * factor
                    if np.any(low):
                        warnings.append(
                            f"from element size {size:g} mm the regularised failure "
                            "strain is at or below the critical strain (triaxiality "
                            f"{_ranges(grid, low)}): no fading there"
                            + ("; SHRF / BIAXF not taken into account"
                               if self.shrf or self.biaxf else ""))
                        break
        elif self.dcrit == 0 and self.dtyp == 1:
            warnings.append("no instability and DCRIT 0: no stress fading, elements "
                            "fail at full stress")
        if self.dmgexp < 1:
            warnings.append(f"DMGEXP {self.dmgexp:g} below 1 (damage grows fastest "
                            "at the start)")
        if self.regularization is not None:
            f = self.regularization.factor
            if np.any(np.diff(f) > 1e-12):
                warnings.append("regularisation factors rise with element size "
                                "(usually they fall)")
        if not isinstance(self.fadexp, (int, float)):
            h, m = (np.asarray(v, dtype=float) for v in self.fadexp)
            if np.any(m <= 0) or np.any(np.diff(h) <= 0):
                issues.append("fading curve: sizes not increasing or exponents not "
                              "positive")
        if self.rate_scaling is not None:
            r, fac = (np.asarray(v, dtype=float) for v in self.rate_scaling)
            if np.any(np.diff(r) <= 0) or np.any(r <= 0) or np.any(fac <= 0):
                issues.append("rate scaling: rates not positive and increasing, or "
                              "factors not positive")
        ids = list(self.curve_ids().values())
        if len(set(ids)) != len(ids):
            issues.append("curve IDs collide")
        return tuple(issues), tuple(warnings)

    # Writing ------------------------------------------------------------------
    def keyword(self, unit_system: str = "mm-ms-kg", *, log_rates: bool = True) -> str:
        """The card and its curves in ``unit_system`` (element sizes and
        strain rates converted; strains and triaxialities have no unit).
        Raises if `check` finds errors."""
        if unit_system not in UNIT_SYSTEMS:
            raise ValueError(f"Unknown unit_system; known: {list(UNIT_SYSTEMS)}.")
        issues, _ = self.check()
        if issues:
            raise ValueError("GISSMO card errors: " + "; ".join(issues))
        n = keyword_number
        length = LENGTH_SCALE[unit_system]                 # mm per model unit
        _, t_scale = UNIT_SYSTEMS[unit_system]
        ids = self.curve_ids()
        ecrit = (-float(ids["instability"]) if "instability" in ids
                 else float(self.instability) if isinstance(self.instability,
                                                            (int, float)) else 0.0)
        if isinstance(self.fadexp, (int, float)):
            fade = float(self.fadexp)
        else:
            fade = -float(ids["fading"])
        lcsrs = 0
        if "rate" in ids:
            lcsrs = ids["rate"] if self.scale_instability_with_rate else -ids["rate"]
        lines = [
            "*MAT_ADD_DAMAGE_GISSMO",
            "$#     mid      dtyp     refsz    numfip",
            f"{self.mid:10d}" + n(float(self.dtyp)) + n(self.refsz / length)
            + n(self.numfip),
            "$#   lcsdg     ecrit    dmgexp     dcrit    fadexp    lcregd",
            f"{ids['failure']:10d}" + n(ecrit) + n(self.dmgexp) + n(self.dcrit)
            + n(fade) + f"{ids.get('regularization', 0):10d}",
            "$#   lcsrs      shrf     biaxf",
            f"{lcsrs:10d}" + n(self.shrf) + n(self.biaxf),
        ]
        lines += _curve_text(ids["failure"], f"GISSMO {self.mid} failure strain vs "
                             "triaxiality", *self.failure_curve())
        inst = self.instability_curve()
        if inst is not None:
            lines += _curve_text(ids["instability"], f"GISSMO {self.mid} critical "
                                 "strain vs triaxiality", *inst)
        if self.regularization is not None:
            lines += _curve_text(ids["regularization"], f"GISSMO {self.mid} "
                                 "regularisation vs element size",
                                 self.regularization.element_size / length,
                                 self.regularization.factor)
        if not isinstance(self.fadexp, (int, float)):
            h, m = (np.asarray(v, dtype=float) for v in self.fadexp)
            lines += _curve_text(ids["fading"], f"GISSMO {self.mid} fading exponent "
                                 "vs element size", h / length, m)
        if self.rate_scaling is not None:
            r, fac = (np.asarray(v, dtype=float) for v in self.rate_scaling)
            r = r * t_scale
            if log_rates:
                if math.log(r[0]) >= 0:
                    raise ValueError("ln of the first rate is not negative in this "
                                     "unit system; use log_rates=False")
                r = np.log(r)
            lines += _curve_text(ids["rate"], f"GISSMO {self.mid} failure strain "
                                 "factor vs strain rate", r, fac)
        return "\n".join(lines) + "\n"
