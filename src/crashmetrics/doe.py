"""Design of experiments: sample design variables for CAE studies.

Functions:

- `latin_hypercube`: Latin hypercube sample (random, space-filling).
- `halton`: Halton low-discrepancy sequence (deterministic).
- `full_factorial`: Every combination of the given levels.
- `morris_design`: Trajectories for Morris elementary-effects screening
  (analysed with `crashmetrics.sensitivity.morris_effects`).
- `lsdyna_parameters`: ``*PARAMETER`` keyword text for one run, to
  include in an LS-DYNA deck.

Every sampler returns a `Design`: variable names, bounds, the sample in
the unit cube and in physical units, and ``rows()`` for
`crashmetrics.features.feature_table` / ``write_csv``.

Random designs take ``seed`` (an int or a ``numpy.random.Generator``)
so a study can be repeated exactly.
"""

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "Design",
    "full_factorial",
    "halton",
    "latin_hypercube",
    "lsdyna_parameters",
    "morris_design",
]

Bounds = Mapping[str, tuple[float, float]]
Seed = int | np.random.Generator | None


@dataclass(frozen=True)
class Design:
    """A sample of design variables."""

    names: tuple[str, ...]
    bounds: tuple[tuple[float, float], ...]
    unit: NDArray[np.float64]
    """Sample in the unit cube, shape ``(n_runs, n_variables)``."""
    values: NDArray[np.float64]
    """Sample in physical units (bounds applied)."""
    method: str

    def __len__(self) -> int:
        return len(self.values)

    def column(self, name: str) -> NDArray[np.float64]:
        """Values of one variable."""
        return self.values[:, self.names.index(name)]

    def rows(self, prefix: str = "run", start: int = 1, digits: int = 3
             ) -> list[dict[str, float | str]]:
        """One dict per run: ``{"run": "run001", name: value, ...}``."""
        return [{"run": f"{prefix}{i:0{digits}d}",
                 **{n: float(v) for n, v in zip(self.names, row, strict=True)}}
                for i, row in enumerate(self.values, start=start)]


Pairs = tuple[tuple[float, float], ...]


def _check_bounds(bounds: Bounds) -> tuple[tuple[str, ...], Pairs]:
    if not bounds:
        raise ValueError("Give at least one design variable.")
    names = tuple(bounds)
    pairs = []
    for name in names:
        low, high = (float(b) for b in bounds[name])
        if not (math.isfinite(low) and math.isfinite(high) and low < high):
            raise ValueError(f"{name}: bounds must be finite with low < high.")
        pairs.append((low, high))
    return names, tuple(pairs)


def _scale(unit: NDArray[np.float64], bounds: Sequence[tuple[float, float]]
           ) -> NDArray[np.float64]:
    low = np.array([b[0] for b in bounds])
    high = np.array([b[1] for b in bounds])
    return low + unit * (high - low)


def _rng(seed: Seed) -> np.random.Generator:
    if isinstance(seed, np.random.Generator):
        return seed
    return np.random.default_rng(seed)


def latin_hypercube(bounds: Bounds, n: int, seed: Seed = None,
                    centered: bool = False) -> Design:
    """Latin hypercube sample of ``n`` runs.

    Each variable's range is cut into ``n`` equal strata and every
    stratum is used exactly once, in random order. The point within a
    stratum is random, or its centre with ``centered=True``.
    """
    names, pairs = _check_bounds(bounds)
    if n < 1:
        raise ValueError("n must be at least 1.")
    rng = _rng(seed)
    d = len(names)
    offset = np.full((n, d), 0.5) if centered else rng.random((n, d))
    strata = np.column_stack([rng.permutation(n) for _ in range(d)])
    unit = (strata + offset) / n
    return Design(names, pairs, unit, _scale(unit, pairs), "latin_hypercube")


_PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61,
           67, 71, 73, 79, 83, 89, 97)


def _radical_inverse(i: int, base: int) -> float:
    result, f = 0.0, 1.0 / base
    while i > 0:
        i, digit = divmod(i, base)
        result += digit * f
        f /= base
    return result


def halton(bounds: Bounds, n: int, skip: int = 1) -> Design:
    """Halton sequence of ``n`` runs (bases 2, 3, 5, ... per variable).

    Deterministic and evenly spread; good for up to about 10 variables.
    ``skip`` leaves out the first points (the default drops the origin).
    """
    names, pairs = _check_bounds(bounds)
    if n < 1:
        raise ValueError("n must be at least 1.")
    if len(names) > len(_PRIMES):
        raise ValueError(f"At most {len(_PRIMES)} variables.")
    unit = np.array([[_radical_inverse(i, _PRIMES[j]) for j in range(len(names))]
                     for i in range(skip, skip + n)])
    return Design(names, pairs, unit, _scale(unit, pairs), "halton")


def full_factorial(levels: Mapping[str, Sequence[float]]) -> Design:
    """Every combination of the given levels per variable.

    The last variable changes fastest. ``unit`` holds the levels mapped
    to 0..1 within each variable's range.
    """
    if not levels:
        raise ValueError("Give at least one design variable.")
    names = tuple(levels)
    lists = []
    for name in names:
        given = [float(v) for v in levels[name]]
        if not given or not all(math.isfinite(v) for v in given):
            raise ValueError(f"{name}: give finite levels.")
        lists.append(given)
    values = np.array(list(itertools.product(*lists)), dtype=float)
    pairs = tuple((min(v), max(v)) for v in lists)
    span = np.array([max(h - lo, 1e-300) for lo, h in pairs])
    unit = (values - np.array([p[0] for p in pairs])) / span
    return Design(names, pairs, unit, values, "full_factorial")


def morris_design(bounds: Bounds, trajectories: int = 10, levels: int = 4,
                  seed: Seed = None) -> Design:
    """Trajectories for Morris elementary-effects screening.

    Each trajectory has ``k + 1`` runs (k variables): a random start on a
    ``levels``-level grid, then one variable at a time moved by
    ``delta = levels / (2 (levels - 1))`` (Morris 1991). Runs are
    ordered trajectory by trajectory; analyse the outputs with
    `crashmetrics.sensitivity.morris_effects`.
    """
    names, pairs = _check_bounds(bounds)
    if levels < 2 or levels % 2:
        raise ValueError("levels must be an even number >= 2.")
    if trajectories < 1:
        raise ValueError("trajectories must be at least 1.")
    rng = _rng(seed)
    k = len(names)
    delta = levels / (2.0 * (levels - 1))
    grid = np.arange(levels) / (levels - 1)
    starts = grid[grid <= 1.0 - delta + 1e-12]
    points = []
    for _ in range(trajectories):
        x = rng.choice(starts, size=k)
        up = rng.random(k) < 0.5
        x = np.where(up, x, x + delta)              # downward steps start high
        order = rng.permutation(k)
        traj = [x.copy()]
        for j in order:
            x = x.copy()
            x[j] = x[j] + delta if up[j] else x[j] - delta
            traj.append(x)
        points.extend(traj)
    unit = np.clip(np.array(points), 0.0, 1.0)
    return Design(names, pairs, unit, _scale(unit, pairs), f"morris:{levels}")


def _field(value: float) -> str:
    """A number in at most 10 characters for a fixed-format card."""
    for digits in range(10, 0, -1):
        text = f"{value:.{digits}g}"
        if not any(c in text for c in ".eEn"):           # mark it as a real
            text += ".0" if len(text) <= 8 else "."
        if len(text) <= 10:
            return text
    raise ValueError(f"{value} does not fit a 10-character field.")  # pragma: no cover


def lsdyna_parameters(values: Mapping[str, float], title: str = "") -> str:
    """``*PARAMETER`` cards defining real parameters for one run.

    Names must be at most 7 characters (LS-DYNA fields are 10
    characters wide, the first holding the type ``R``). Put the result in
    a file included by the deck (``*INCLUDE``) and refer to the
    parameters as ``&name``.
    """
    lines = ["*KEYWORD", "*PARAMETER"]
    if title:
        lines.insert(1, f"$ {title}")
    lines.append("$#   prmr1      val1")
    for name, value in values.items():
        if not name or len(name) > 7 or not name[0].isalpha() or not name.isascii():
            raise ValueError(f"Parameter name {name!r} must be 1-7 ASCII characters "
                             "starting with a letter.")
        v = float(value)
        if not math.isfinite(v):
            raise ValueError(f"{name}: value must be finite.")
        lines.append(f"R {name:<7} {_field(v):>10}")
    lines.append("*END")
    return "\n".join(lines) + "\n"
