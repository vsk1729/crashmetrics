"""Strain-rate dependence for ``*MAT_024``: fits, rate tables, checks.

Crash structures deform at 10-1000 /s, where steels are 10-30 % stronger
than in a quasi-static test. ``*MAT_PIECEWISE_LINEAR_PLASTICITY`` takes
the rate effect in one of two ways:

- **Cowper-Symonds** (fields C and P of the card): the whole curve scaled
  by ``1 + (rate / C)^(1/P)``. `fit_cowper_symonds` fits C and P to
  tests at several rates.
- **A rate table** (LCSS pointing to a ``*DEFINE_TABLE``): one hardening
  curve per strain rate. `rate_table_from_curves` builds it from tests,
  `rate_table_from_model` from a static curve and a fitted rate law;
  `RateTable.keyword` writes the ``*DEFINE_TABLE`` and its curves.

`fit_johnson_cook_rate` fits the Johnson-Cook rate term
``1 + c ln(rate / rate0)`` as an alternative law, and
`RateTable.check` finds the table errors that make simulations noisy or
wrong: crossing curves, rates not increasing, softening curves, rates
LS-DYNA would read in the wrong form.

Units: strain rate in 1/s, stress in MPa (true stress, effective plastic
strain). `RateTable.keyword` converts to the model's unit system.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics.materials.hardening import HardeningCurve, _levenberg_marquardt

__all__ = [
    "UNIT_SYSTEMS",
    "CowperSymonds",
    "JohnsonCookRate",
    "RateCheck",
    "RateTable",
    "fit_cowper_symonds",
    "fit_johnson_cook_rate",
    "rate_table_from_curves",
    "rate_table_from_model",
]

FloatArray = NDArray[np.float64]

UNIT_SYSTEMS: dict[str, tuple[float, float]] = {
    "mm-ms-kg": (1e-3, 1e-3),
    "mm-s-t": (1.0, 1.0),
    "mm-s-kg": (1e3, 1.0),
    "m-s-kg": (1e6, 1.0),
}
"""LS-DYNA unit system -> (stress per MPa, time per s). Stress units:
GPa in mm-ms-kg, MPa in mm-s-t, kPa in mm-s-kg, Pa in m-s-kg; strain
rates are divided by the time factor (1/s -> 1/ms in mm-ms-kg)."""


# --- Rate laws ----------------------------------------------------------------


def _rate_points(curves: Mapping[float, HardeningCurve], strains: Sequence[float] |
                 None, reference: float | None) -> tuple[float, FloatArray, FloatArray,
                                                         FloatArray]:
    """Reference rate, and (rate, ratio to the reference) at common strains."""
    if len(curves) < 2:
        raise ValueError("Give curves at two or more strain rates.")
    rates = sorted(curves)
    if any(r <= 0 for r in rates):
        raise ValueError("Strain rates must be positive (1/s).")
    ref = rates[0] if reference is None else reference
    if ref not in curves:
        raise ValueError(f"No curve at the reference rate {ref}.")
    limit = min(float(c.necking_strain) for c in curves.values())
    if strains is None:
        strains = [0.0, *np.linspace(0.02, 0.9 * limit, 5)] if limit > 0.03 \
            else [0.0, 0.5 * limit]
    pts = np.asarray(strains, dtype=float)
    if np.any(pts < 0) or np.any(pts > limit + 1e-12):
        raise ValueError(f"strains must be within the measured range 0-{limit:.4f} "
                         "(the smallest necking strain).")
    base = np.interp(pts, curves[ref].plastic_strain, curves[ref].stress)
    r: list[float] = []
    q: list[float] = []
    e: list[float] = []
    for rate in rates:
        if rate == ref:
            continue
        s = np.interp(pts, curves[rate].plastic_strain, curves[rate].stress)
        r.extend([rate] * len(pts))
        q.extend(s / base)
        e.extend(pts)
    return ref, np.array(r), np.array(q), np.array(e)


@dataclass(frozen=True)
class CowperSymonds:
    """Cowper-Symonds rate law ``sigma = sigma_static (1 + (rate / C)^(1/P))``."""

    c: float
    """C, 1/s (divide by 1000 for an mm-ms-kg card)."""
    p: float
    """P, -."""
    reference_rate: float
    """Rate of the curve used as reference, 1/s."""
    rms: float
    """RMS error of the stress ratio over the fitted points."""
    points: int

    def factor(self, rate: ArrayLike) -> FloatArray:
        """``1 + (rate / C)^(1/P)``: dynamic over static stress."""
        r = np.asarray(rate, dtype=float)
        if np.any(r < 0):
            raise ValueError("rate must be >= 0.")
        return np.asarray(1.0 + (r / self.c) ** (1.0 / self.p))

    def ratio(self, rate: ArrayLike) -> FloatArray:
        """Stress at ``rate`` over stress at the reference rate."""
        return np.asarray(self.factor(rate) / self.factor(self.reference_rate))


def fit_cowper_symonds(
    curves: Mapping[float, HardeningCurve],
    *,
    strains: Sequence[float] | None = None,
    reference_rate: float | None = None,
) -> CowperSymonds:
    """Fit Cowper-Symonds C and P to hardening curves at several rates.

    ``curves`` maps strain rate (1/s) to the plastic curve of that test
    (`crashmetrics.materials.plastic_curve`). The stress of each curve
    over the reference curve (the lowest rate unless
    ``reference_rate``) is taken at ``strains`` (plastic; default the
    yield point and five strains up to 90 % of the smallest necking
    strain), and C and P are fitted to these ratios by least squares,
    accounting for the reference rate not being zero.

    The ``*MAT_024`` C and P scale the whole curve by the same factor at
    every strain; if the measured ratio changes much with strain, a rate
    table (`rate_table_from_curves`) represents the tests better.
    """
    ref, r, q, _ = _rate_points(curves, strains, reference_rate)
    if np.all(q <= 1.0):
        raise ValueError("No curve is stronger than the reference: no rate effect "
                         "to fit.")
    # Start: ln(q - 1) ~ (1/P) (ln rate - ln C), ignoring the reference rate.
    ok = q > 1.0 + 1e-6
    if int(ok.sum()) >= 2 and len(set(r[ok])) >= 2:
        slope, icpt = np.polyfit(np.log(r[ok]), np.log(q[ok] - 1.0), 1)
        p0 = 1.0 / slope if slope > 0 else 5.0
        c0 = math.exp(-icpt * p0) if slope > 0 else 40.0
    else:
        p0, c0 = 5.0, float(np.max(r))

    def residual(z: FloatArray) -> FloatArray:
        c, p = math.exp(z[0]), math.exp(z[1])
        with np.errstate(over="ignore", invalid="ignore"):
            model = (1 + (r / c) ** (1 / p)) / (1 + (ref / c) ** (1 / p))
        out = model - q
        return np.where(np.isfinite(out), out, 1e3)

    z = _levenberg_marquardt(residual, np.log([max(c0, 1e-12), min(max(p0, 0.05),
                                                                    1e3)]))
    res = residual(z)
    return CowperSymonds(float(math.exp(z[0])), float(math.exp(z[1])), float(ref),
                         float(np.sqrt(np.mean(res ** 2))), len(q))


@dataclass(frozen=True)
class JohnsonCookRate:
    """Johnson-Cook rate term ``sigma = sigma_ref (1 + c ln(rate / rate0))``."""

    c: float
    reference_rate: float
    """rate0, 1/s: the rate of the reference curve."""
    rms: float
    points: int

    def ratio(self, rate: ArrayLike) -> FloatArray:
        """Stress at ``rate`` over stress at the reference rate (1 below
        the reference rate, as the usual cut-off)."""
        r = np.asarray(rate, dtype=float)
        if np.any(r <= 0):
            raise ValueError("rate must be positive.")
        return np.asarray(1.0 + self.c * np.maximum(np.log(r / self.reference_rate),
                                                    0.0))

    def factor(self, rate: ArrayLike) -> FloatArray:
        """Same as `ratio` (the reference curve is the static curve)."""
        return self.ratio(rate)


def fit_johnson_cook_rate(
    curves: Mapping[float, HardeningCurve],
    *,
    strains: Sequence[float] | None = None,
    reference_rate: float | None = None,
) -> JohnsonCookRate:
    """Fit the Johnson-Cook rate constant c (least squares through the
    origin of ``ratio - 1`` against ``ln(rate / rate0)``). Arguments as
    `fit_cowper_symonds`."""
    ref, r, q, _ = _rate_points(curves, strains, reference_rate)
    x = np.log(r / ref)
    c = float(np.sum(x * (q - 1.0)) / np.sum(x * x))
    res = 1.0 + c * x - q
    return JohnsonCookRate(c, float(ref), float(np.sqrt(np.mean(res ** 2))), len(q))


# --- Rate table ------------------------------------------------------------------


def _grid(strain_max: float, points: int) -> FloatArray:
    """0, then geometric spacing: dense near yield, where the curve bends."""
    return np.concatenate(([0.0], np.geomspace(strain_max / 500.0, strain_max,
                                               points - 1)))


@dataclass(frozen=True)
class RateCheck:
    """Result of `RateTable.check`."""

    issues: tuple[str, ...]
    """Errors: the table would give wrong or noisy results."""
    warnings: tuple[str, ...]
    """Points to review."""

    @property
    def passed(self) -> bool:
        return not self.issues

    def summary(self) -> str:
        lines = ["Rate table check: " + ("passed" if self.passed else "FAILED")]
        lines += [f"  error: {i}" for i in self.issues]
        lines += [f"  warning: {w}" for w in self.warnings]
        return "\n".join(lines)


@dataclass(frozen=True)
class RateTable:
    """Hardening curves at several strain rates on one plastic strain grid."""

    rates: FloatArray
    """Strain rates, 1/s, increasing."""
    plastic_strain: FloatArray
    stress: FloatArray
    """True stress, MPa, shape (rates, strains)."""
    info: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        rates = np.asarray(self.rates, dtype=float)
        strain = np.asarray(self.plastic_strain, dtype=float)
        stress = np.asarray(self.stress, dtype=float)
        if stress.shape != (len(rates), len(strain)):
            raise ValueError("stress must have shape (rates, strains).")
        object.__setattr__(self, "rates", rates)
        object.__setattr__(self, "plastic_strain", strain)
        object.__setattr__(self, "stress", stress)

    def curve(self, rate: float) -> FloatArray:
        """Stress at one of the table's rates, MPa."""
        hits = np.flatnonzero(np.isclose(self.rates, rate, rtol=1e-9))
        if not len(hits):
            raise ValueError(f"No curve at rate {rate}; rates: {self.rates.tolist()}.")
        return np.asarray(self.stress[int(hits[0])])

    def check(self, *, log_rates: bool = False,
              unit_system: str = "mm-s-t") -> RateCheck:
        """Check the table as LS-DYNA would use it.

        Errors: rates not strictly increasing; a curve below the curve
        of a lower rate at any strain (crossing curves give a negative
        rate sensitivity and noisy, mesh-dependent results); a curve not
        starting at zero plastic strain; with ``log_rates`` a first rate
        whose natural log is not negative in the model's time unit
        (LS-DYNA then reads all values as plain rates). Warnings:
        softening (stress decreasing along a curve), widely spaced rates
        in a linear table, a first rate above 0.01 /s.
        """
        issues: list[str] = []
        warnings: list[str] = []
        r = self.rates
        if np.any(np.diff(r) <= 0):
            issues.append("rates are not strictly increasing")
        if self.plastic_strain[0] != 0.0:
            issues.append("the curves do not start at zero plastic strain")
        for k in range(1, len(r)):
            lower = self.stress[k] < self.stress[k - 1] - 1e-9 * np.abs(
                self.stress[k - 1])
            if np.any(lower):
                at = self.plastic_strain[lower]
                span = (f"{at.min():.4g}" if at.min() == at.max()
                        else f"{at.min():.4g}-{at.max():.4g}")
                issues.append(f"curve at {r[k]:g} /s is below the curve at "
                              f"{r[k - 1]:g} /s at plastic strain {span} "
                              "(curves cross)")
        for k in range(len(r)):
            if np.any(np.diff(self.stress[k]) < -1e-9 * np.abs(self.stress[k][1:])):
                warnings.append(f"curve at {r[k]:g} /s softens (stress decreases)")
        if log_rates:
            _, t = UNIT_SYSTEMS[unit_system]
            first = math.log(r[0] * t)
            if first >= 0:
                issues.append(f"first ln(rate) is {first:.3g} (not negative): "
                              "LS-DYNA would read the values as plain rates")
        elif len(r) > 2 and np.max(r[1:] / np.maximum(r[:-1], 1e-300)) > 100:
            warnings.append("rates more than 100x apart in a linear table: LS-DYNA "
                            "interpolates linearly in rate between them; consider "
                            "log_rates=True")
        if r[0] > 0.01:
            warnings.append(f"lowest rate {r[0]:g} /s: no quasi-static curve")
        return RateCheck(tuple(issues), tuple(warnings))

    def keyword(
        self,
        table_id: int,
        *,
        unit_system: str = "mm-s-t",
        log_rates: bool = False,
        first_curve_id: int | None = None,
        title: str = "",
    ) -> str:
        """``*DEFINE_TABLE`` followed by its ``*DEFINE_CURVE`` cards.

        Rates are converted to the model's time unit and stresses to its
        stress unit (`UNIT_SYSTEMS`); with ``log_rates`` the table holds
        ``ln(rate)``. The curves get IDs ``first_curve_id`` (default
        ``table_id + 1``) upward and follow the table directly, as
        LS-DYNA requires. Reference the table as LCSS of ``*MAT_024``
        (and leave C and P at zero).
        """
        if unit_system not in UNIT_SYSTEMS:
            raise ValueError(f"Unknown unit_system; known: {list(UNIT_SYSTEMS)}.")
        result = self.check(log_rates=log_rates, unit_system=unit_system)
        if not result.passed:
            raise ValueError("The rate table has errors:\n" + result.summary())
        s_scale, t_scale = UNIT_SYSTEMS[unit_system]
        rates = self.rates * t_scale
        values = np.log(rates) if log_rates else rates
        first = table_id + 1 if first_curve_id is None else first_curve_id
        lines = ["*DEFINE_TABLE_TITLE" if title else "*DEFINE_TABLE"]
        if title:
            lines.append(title[:80])
        lines += ["$#    tbid       sfa      offa", f"{table_id:10d}{1.0:10.1f}"
                  f"{0.0:10.1f}", "$#             value"]
        lines += [f"{v:20.8g}" for v in values]
        for k, rate in enumerate(self.rates):
            lines += ["*DEFINE_CURVE_TITLE", f"strain rate {rate:g} /s",
                      "$#    lcid      sidr       sfa       sfo      offa      offo",
                      f"{first + k:10d}{0:10d}{1.0:10.1f}{1.0:10.1f}{0.0:10.1f}"
                      f"{0.0:10.1f}",
                      "$#                a1                  o1"]
            lines += [f"{e:20.8g}{s * s_scale:20.8g}"
                      for e, s in zip(self.plastic_strain, self.stress[k])]
        return "\n".join(lines) + "\n"


def rate_table_from_model(
    curve: HardeningCurve,
    law: CowperSymonds | JohnsonCookRate,
    rates: Sequence[float],
    *,
    points: int = 50,
    strain_max: float | None = None,
) -> RateTable:
    """Rate table from the reference curve scaled by a fitted rate law.

    ``curve`` is the (extrapolated) curve at the law's reference rate;
    each rate's curve is ``curve * law.ratio(rate)``. The curves are
    resampled at ``points`` plastic strains up to ``strain_max``
    (default: the end of ``curve``), denser near yield.
    """
    if points < 3:
        raise ValueError("points must be at least 3.")
    end = float(curve.plastic_strain[-1]) if strain_max is None else strain_max
    if not 0 < end <= curve.plastic_strain[-1] + 1e-12:
        raise ValueError("strain_max must be within the curve; extrapolate it first.")
    grid = _grid(end, points)
    base = np.interp(grid, curve.plastic_strain, curve.stress)
    r = np.sort(np.asarray(rates, dtype=float))
    stress = np.array([base * float(law.ratio(rate)[()]) for rate in r])
    return RateTable(r, grid, stress, {"source": f"{type(law).__name__} law",
                                       "reference": curve.name})


def rate_table_from_curves(
    curves: Mapping[float, HardeningCurve],
    *,
    points: int = 50,
    strain_max: float | None = None,
) -> RateTable:
    """Rate table from one (extrapolated) curve per strain rate.

    Every curve is interpolated at ``points`` plastic strains up to
    ``strain_max`` (default: the end of the shortest curve). Check the
    result (`RateTable.check`): curves fitted separately easily cross
    after necking.
    """
    if not curves:
        raise ValueError("Give at least one curve.")
    if points < 3:
        raise ValueError("points must be at least 3.")
    end = min(float(c.plastic_strain[-1]) for c in curves.values())
    if strain_max is not None:
        if not 0 < strain_max <= end + 1e-12:
            raise ValueError(f"strain_max must be within all curves (<= {end:.4g}).")
        end = strain_max
    grid = _grid(end, points)
    r = np.array(sorted(curves), dtype=float)
    stress = np.array([np.interp(grid, curves[rate].plastic_strain,
                                 curves[rate].stress) for rate in sorted(curves)])
    return RateTable(r, grid, stress, {"source": "curves"})
