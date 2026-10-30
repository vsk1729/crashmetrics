"""Probabilistic ratings: how likely is a score or a star rating?

A crash test or simulation gives one result, but the same design scatters
from test to test (dummy positioning, material, airbag timing) and a
surrogate model has its own error. `monte_carlo` varies the inputs of
any scoring function and reports the spread of its outputs, so a result
can be stated as "84 % chance of 5 stars" or "HIC below 700 with 97 %
probability" instead of one number.

Inputs scatter by:

- `normal`: absolute standard deviation (``normal(25.0)`` for HIC);
- `relative`: coefficient of variation (``relative(0.08)``: 8 %);
- `uniform`: plus or minus a range around the nominal value;
- `scale`: a multiplier around 1 (e.g. for a whole time history).

Functions:

- `monte_carlo`: Sample the inputs and run the function; returns a
  `MonteCarloResult` with probabilities, distributions and percentiles.
- `star_probabilities`: Probability of each star rating.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "MonteCarloResult",
    "Scatter",
    "monte_carlo",
    "normal",
    "relative",
    "scale",
    "star_probabilities",
    "uniform",
]


@dataclass(frozen=True)
class Scatter:
    """Scatter of one input around its nominal value."""

    kind: str
    """``normal``, ``relative``, ``uniform`` or ``scale``."""
    size: float
    nonnegative: bool = True
    """Clip samples at zero (criteria values are magnitudes)."""

    def sample(self, nominal: float, n: int, rng: np.random.Generator
               ) -> NDArray[np.float64]:
        if self.kind == "normal":
            x = nominal + self.size * rng.standard_normal(n)
        elif self.kind == "relative":
            x = nominal * (1.0 + self.size * rng.standard_normal(n))
        elif self.kind == "uniform":
            x = nominal + self.size * (2.0 * rng.random(n) - 1.0)
        elif self.kind == "scale":
            x = 1.0 + self.size * rng.standard_normal(n)
        else:
            raise ValueError(f"Unknown scatter kind {self.kind!r}.")
        return np.maximum(x, 0.0) if self.nonnegative else x


def _size(value: float, name: str) -> float:
    v = float(value)
    if not math.isfinite(v) or v < 0:
        raise ValueError(f"{name} must be finite and >= 0.")
    return v


def normal(sd: float, nonnegative: bool = True) -> Scatter:
    """Normal scatter with an absolute standard deviation."""
    return Scatter("normal", _size(sd, "sd"), nonnegative)


def relative(cv: float, nonnegative: bool = True) -> Scatter:
    """Normal scatter with a relative standard deviation (0.05 = 5 %)."""
    return Scatter("relative", _size(cv, "cv"), nonnegative)


def uniform(half_range: float, nonnegative: bool = True) -> Scatter:
    """Uniform scatter: nominal plus or minus ``half_range``."""
    return Scatter("uniform", _size(half_range, "half_range"), nonnegative)


def scale(cv: float) -> Scatter:
    """A multiplier around 1 with relative standard deviation ``cv``; use
    with nominal 1.0 to scale signals or groups of values together."""
    return Scatter("scale", _size(cv, "cv"), True)


@dataclass(frozen=True)
class MonteCarloResult:
    """Inputs and outputs of a Monte Carlo study."""

    inputs: dict[str, NDArray[np.float64]]
    """Sampled inputs (nominal values repeated for inputs without scatter)."""
    outputs: dict[str, NDArray[np.float64]]
    """One array per output (``"value"`` if the function returns a number)."""
    nominal: dict[str, float]
    """Outputs of the nominal (unscattered) inputs."""

    def __len__(self) -> int:
        return len(next(iter(self.outputs.values())))

    def rows(self) -> list[dict[str, float]]:
        """One dict per sample with inputs and outputs, e.g. for
        `crashmetrics.sensitivity.rank_sensitivity` or a CSV file."""
        names = {**self.inputs, **self.outputs}
        return [{k: float(v[i]) for k, v in names.items()} for i in range(len(self))]

    def _get(self, output: str | None) -> NDArray[np.float64]:
        if output is None:
            if len(self.outputs) != 1:
                raise ValueError(f"Name the output: {', '.join(self.outputs)}.")
            return next(iter(self.outputs.values()))
        if output not in self.outputs:
            raise KeyError(f"No output {output!r}; outputs: {', '.join(self.outputs)}.")
        return self.outputs[output]

    def probability(self, output: str | None = None, *, at_least: float | None = None,
                    below: float | None = None, equals: float | None = None) -> float:
        """Share of samples meeting a condition, e.g.
        ``probability("stars", at_least=5)`` or ``probability("hic15", below=700)``."""
        y = self._get(output)
        given = [c is not None for c in (at_least, below, equals)]
        if sum(given) != 1:
            raise ValueError("Give exactly one of at_least, below, equals.")
        if at_least is not None:
            hit = y >= at_least
        elif below is not None:
            hit = y < below
        else:
            hit = y == equals
        return float(np.mean(hit))

    def distribution(self, output: str | None = None) -> dict[float, float]:
        """Probability of each distinct value (for discrete outputs such
        as stars), sorted by value."""
        y = self._get(output)
        values, counts = np.unique(y, return_counts=True)
        return {float(v): float(c) / len(y)
                for v, c in zip(values, counts, strict=True)}

    def percentiles(self, output: str | None = None,
                    q: Sequence[float] = (5.0, 50.0, 95.0)) -> dict[float, float]:
        """Percentiles of an output."""
        y = self._get(output)
        return {float(p): float(v) for p, v in zip(q, np.percentile(y, q), strict=True)}

    def summary(self, outputs: Sequence[str] | None = None) -> str:
        """Nominal value, mean and 5 / 50 / 95 % percentiles per output."""
        names = list(outputs) if outputs is not None else list(self.outputs)
        width = max(len(n) for n in names) + 2
        lines = [f"Monte Carlo, {len(self)} samples",
                 f"  {'output':{width}} {'nominal':>9} {'mean':>9} {'p5':>9} "
                 f"{'p50':>9} {'p95':>9}"]
        for n in names:
            y = self.outputs[n]
            p = np.percentile(y, (5, 50, 95))
            lines.append(f"  {n:{width}} {self.nominal[n]:9.4g} {y.mean():9.4g} "
                         f"{p[0]:9.4g} {p[1]:9.4g} {p[2]:9.4g}")
        return "\n".join(lines)


def monte_carlo(
    func: Callable[[dict[str, float]], float | Mapping[str, float]],
    nominal: Mapping[str, float],
    scatter: Mapping[str, Scatter],
    n: int = 1000,
    seed: int | np.random.Generator | None = None,
) -> MonteCarloResult:
    """Run ``func`` on ``n`` scattered copies of the inputs.

    Parameters
    ----------
    func:
        Takes a dict of input values and returns a number or a dict of
        numbers (e.g. ``{"points": 26.1, "stars": 4}``).
    nominal:
        Nominal value of every input.
    scatter:
        Scatter of the inputs that vary (others stay nominal).
    n:
        Number of samples.
    seed:
        Random seed or generator, for repeatable results.
    """
    unknown = set(scatter) - set(nominal)
    if unknown:
        raise ValueError(f"Scatter given for unknown inputs: {sorted(unknown)}.")
    if n < 2:
        raise ValueError("n must be at least 2.")
    rng = seed if isinstance(seed, np.random.Generator) else np.random.default_rng(seed)
    inputs = {name: (scatter[name].sample(float(v), n, rng) if name in scatter
                     else np.full(n, float(v)))
              for name, v in nominal.items()}

    def call(values: dict[str, float]) -> dict[str, float]:
        out = func(values)
        if isinstance(out, Mapping):
            return {k: float(v) for k, v in out.items()}
        return {"value": float(out)}

    nominal_out = call({k: float(v) for k, v in nominal.items()})
    rows = [call({k: float(inputs[k][i]) for k in inputs}) for i in range(n)]
    outputs = {k: np.array([r[k] for r in rows]) for k in nominal_out}
    return MonteCarloResult(inputs, outputs, nominal_out)


def star_probabilities(result: MonteCarloResult, output: str = "stars",
                       max_stars: int = 5) -> dict[int, float]:
    """Probability of each star rating 0..``max_stars``."""
    dist = result.distribution(output)
    return {s: dist.get(float(s), 0.0) for s in range(max_stars + 1)}
