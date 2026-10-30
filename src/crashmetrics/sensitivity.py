"""Sensitivity ranking of design variables.

Which design variables drive an output (HIC, chest deflection, a
score)? Three standard measures, all NumPy only:

- `rank_correlation`: Spearman rank correlation of each variable with
  the output. Works with any sample (DOE, test series, random runs);
  catches monotonic effects.
- `partial_rank_correlation`: partial rank correlation (PRCC): the
  rank correlation after removing the (rank-linear) effect of the other
  variables, so a strong variable does not hide a weaker one. Used for
  the ranking.
- `regression_coefficients`: standardised regression coefficients
  (SRC) of a linear fit, and its R². Shows the share of each variable
  when the response is close to linear (R² near 1).
- `morris_effects`: Morris elementary effects (mu*, sigma) from a
  `crashmetrics.doe.morris_design`: a cheap screening that also flags
  non-linear or interacting variables (large sigma).

`rank_sensitivity` runs the first three on a table of runs and returns
the variables ranked by importance.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics.doe import Design

__all__ = [
    "MorrisEffect",
    "SensitivityRanking",
    "morris_effects",
    "partial_rank_correlation",
    "rank_correlation",
    "rank_sensitivity",
    "regression_coefficients",
]


def _ranks(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """Ranks 1..n with ties given their average rank."""
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    sorted_x = x[order]
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and sorted_x[j + 1] == sorted_x[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def _matrix(inputs: Mapping[str, ArrayLike], output: ArrayLike
            ) -> tuple[list[str], NDArray[np.float64], NDArray[np.float64]]:
    names = list(inputs)
    if not names:
        raise ValueError("Give at least one input.")
    y = np.asarray(output, dtype=float)
    x = np.column_stack([np.asarray(inputs[n], dtype=float) for n in names])
    if y.ndim != 1 or x.shape[0] != y.shape[0]:
        raise ValueError("Every input must have one value per output value.")
    keep = np.isfinite(y) & np.all(np.isfinite(x), axis=1)
    x, y = x[keep], y[keep]
    if len(y) < len(names) + 2:
        raise ValueError(f"Need at least {len(names) + 2} complete runs; "
                         f"got {len(y)}.")
    return names, x, y


def _corr(a: NDArray[np.float64], b: NDArray[np.float64]) -> float:
    sa, sb = a.std(), b.std()
    if sa == 0 or sb == 0:
        return 0.0
    return float(np.mean((a - a.mean()) * (b - b.mean())) / (sa * sb))


def rank_correlation(inputs: Mapping[str, ArrayLike], output: ArrayLike
                     ) -> dict[str, float]:
    """Spearman rank correlation (-1..1) of each input with the output.

    Runs with a missing (NaN) input or output are left out. A constant
    input gets 0.
    """
    names, x, y = _matrix(inputs, output)
    ry = _ranks(y)
    return {n: _corr(_ranks(x[:, j]), ry) for j, n in enumerate(names)}


def partial_rank_correlation(inputs: Mapping[str, ArrayLike], output: ArrayLike
                             ) -> dict[str, float]:
    """Partial rank correlation coefficient (PRCC, -1..1) of each input.

    Inputs and output are rank-transformed; for each input, the ranks of
    that input and of the output are regressed on the ranks of the other
    inputs, and the residuals are correlated.
    """
    names, x, y = _matrix(inputs, output)
    rx = np.column_stack([_ranks(x[:, j]) for j in range(len(names))])
    ry = _ranks(y)
    out = {}
    for j, name in enumerate(names):
        others = np.column_stack([np.ones(len(ry)), np.delete(rx, j, axis=1)])
        res_x = rx[:, j] - others @ np.linalg.lstsq(others, rx[:, j], rcond=None)[0]
        res_y = ry - others @ np.linalg.lstsq(others, ry, rcond=None)[0]
        out[name] = _corr(res_x, res_y)
    return out


def regression_coefficients(inputs: Mapping[str, ArrayLike], output: ArrayLike
                            ) -> tuple[dict[str, float], float]:
    """Standardised regression coefficients and R² of a linear fit.

    SRC_i = b_i sd(x_i) / sd(y). With independent inputs, SRC_i² is the
    share of the output variance explained by input i (they sum to R²).
    """
    names, x, y = _matrix(inputs, output)
    sx, sy = x.std(axis=0), y.std()
    if sy == 0:
        return dict.fromkeys(names, 0.0), 0.0
    use = sx > 0
    z = (x[:, use] - x[:, use].mean(axis=0)) / sx[use]
    zy = (y - y.mean()) / sy
    beta, *_ = np.linalg.lstsq(z, zy, rcond=None)
    fitted = z @ beta
    r2 = 1.0 - float(np.sum((zy - fitted) ** 2) / np.sum(zy ** 2))
    src = dict.fromkeys(names, 0.0)
    for name, b in zip([n for n, u in zip(names, use, strict=True) if u], beta,
                       strict=True):
        src[name] = float(b)
    return src, r2


@dataclass(frozen=True)
class SensitivityRanking:
    """Sensitivity of one output to the design variables."""

    output: str
    spearman: dict[str, float]
    prcc: dict[str, float]
    src: dict[str, float]
    r2: float
    """R² of the linear fit behind the SRC."""

    @property
    def ranking(self) -> list[str]:
        """Variables from most to least important (by |PRCC|)."""
        return sorted(self.prcc, key=lambda n: -abs(self.prcc[n]))

    def summary(self) -> str:
        """A ranked text table."""
        width = max([len(n) for n in self.prcc] + [8]) + 2
        lines = [f"Sensitivity of {self.output} (linear fit R² {self.r2:.2f}):",
                 f"  {'variable':{width}} {'PRCC':>7} {'Spearman':>9} {'SRC':>7}"]
        def r2d(v: float) -> float:
            return round(v, 2) + 0.0                      # no "-0.00"

        for n in self.ranking:
            lines.append(f"  {n:{width}} {r2d(self.prcc[n]):+7.2f} "
                         f"{r2d(self.spearman[n]):+9.2f} {r2d(self.src[n]):+7.2f}")
        return "\n".join(lines)


def rank_sensitivity(
    rows: Sequence[Mapping[str, object]],
    inputs: Sequence[str],
    output: str,
) -> SensitivityRanking:
    """Rank design variables for one output from a table of runs.

    ``rows`` are dicts such as `crashmetrics.features.feature_table`
    output or `crashmetrics.doe.Design.rows` joined with results; rows
    without a numeric output (failed runs) are left out.
    """
    def num(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return math.nan
        return float(value)

    data = {n: [num(r.get(n)) for r in rows] for n in inputs}
    y = [num(r.get(output)) for r in rows]
    spearman = rank_correlation(data, y)
    prcc = partial_rank_correlation(data, y)
    src, r2 = regression_coefficients(data, y)
    return SensitivityRanking(output, spearman, prcc, src, r2)


@dataclass(frozen=True)
class MorrisEffect:
    """Morris elementary effects of one variable (in output units per
    unit-cube step: comparable between variables)."""

    name: str
    mu: float
    """Mean effect (signed)."""
    mu_star: float
    """Mean absolute effect: the importance measure (Campolongo et al. 2007)."""
    sigma: float
    """Standard deviation of the effects: non-linearity or interactions."""


def morris_effects(design: Design, output: ArrayLike) -> list[MorrisEffect]:
    """Elementary effects from a `crashmetrics.doe.morris_design`.

    ``output`` has one value per run of the design, in run order.
    Returns the variables sorted by ``mu_star`` (largest first).
    """
    y = np.asarray(output, dtype=float)
    k = len(design.names)
    if y.shape != (len(design),):
        raise ValueError("Give one output value per design run.")
    if len(design) % (k + 1):
        raise ValueError("The design is not made of Morris trajectories.")
    effects: dict[int, list[float]] = {j: [] for j in range(k)}
    for start in range(0, len(design), k + 1):
        xs = design.unit[start:start + k + 1]
        ys = y[start:start + k + 1]
        for step in range(k):
            dx = xs[step + 1] - xs[step]
            moved = np.flatnonzero(np.abs(dx) > 1e-12)
            if len(moved) != 1:
                raise ValueError("Each step of a trajectory must move one variable.")
            j = int(moved[0])
            if np.isfinite(ys[step + 1]) and np.isfinite(ys[step]):
                effects[j].append(float((ys[step + 1] - ys[step]) / dx[j]))
    result = []
    for j, name in enumerate(design.names):
        e = np.array(effects[j])
        if len(e) == 0:
            result.append(MorrisEffect(name, math.nan, math.nan, math.nan))
            continue
        result.append(MorrisEffect(name, float(e.mean()), float(np.abs(e).mean()),
                                   float(e.std(ddof=1)) if len(e) > 1 else 0.0))
    return sorted(result, key=lambda m: -m.mu_star if math.isfinite(m.mu_star) else 0)
