"""Several specimens of one material: mean curve and scatter.

- `mean_curve`: the mean engineering stress-strain curve of several
  tests, with standard deviation, minimum and maximum at each strain;
  `MeanCurve.as_test` continues the material-card chain with it.
- `property_scatter`: mean, standard deviation and coefficient of
  variation of the tensile properties (E, Rp0.2, Rm, Ag, A).

Clean the curves first (`crashmetrics.materials.clean_tensile`): with
the toe removed they all start at the origin, so they are aligned.

Units: stress MPa, strain dimensionless.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from crashmetrics.materials.tensile import TensileTest, tensile_properties

__all__ = ["MeanCurve", "PropertyScatter", "mean_curve", "property_scatter",
           "scatter_summary"]

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class MeanCurve:
    """Mean of several engineering stress-strain curves on one strain grid."""

    strain: FloatArray
    mean: FloatArray
    """Mean stress, MPa."""
    std: FloatArray
    """Sample standard deviation of the stress, MPa (0 for one test)."""
    minimum: FloatArray
    maximum: FloatArray
    names: tuple[str, ...]

    @property
    def count(self) -> int:
        """Number of tests."""
        return len(self.names)

    def as_test(self, name: str = "mean") -> TensileTest:
        """The mean curve as a `TensileTest`."""
        return TensileTest(self.strain, self.mean, name,
                           {"mean_of": list(self.names)})


def _increasing(test: TensileTest) -> tuple[FloatArray, FloatArray]:
    """Points where the strain increases (noise can step it back)."""
    e, s = test.strain, test.stress
    keep = np.concatenate(([True], e[1:] > np.maximum.accumulate(e)[:-1]))
    return e[keep], s[keep]


def mean_curve(
    tests: Sequence[TensileTest],
    *,
    points: int = 300,
    strain_max: float | None = None,
) -> MeanCurve:
    """Mean curve of several tests on a common strain grid.

    Each curve is interpolated linearly at ``points`` strains from 0 to
    ``strain_max`` (default: the end of the shortest curve, so every
    test contributes at every strain). Averaging after necking mixes
    different local strains; for a card, use the mean up to the
    uniform elongation and extrapolate from there.
    """
    if len(tests) < 1:
        raise ValueError("Give at least one test.")
    if points < 3:
        raise ValueError("points must be at least 3.")
    curves = [_increasing(t) for t in tests]
    if any(e[0] > 1e-9 for e, _ in curves):
        raise ValueError("Every curve must start at zero strain; clean them first "
                         "(clean_tensile with toe correction).")
    end = min(float(e[-1]) for e, _ in curves)
    if strain_max is not None:
        if not 0 < strain_max <= end:
            raise ValueError(f"strain_max must be in (0, {end:.4g}], the end of "
                             "the shortest curve.")
        end = strain_max
    grid = np.linspace(0.0, end, points)
    stack = np.array([np.interp(grid, e, s) for e, s in curves])
    std = stack.std(axis=0, ddof=1) if len(tests) > 1 else np.zeros(points)
    return MeanCurve(grid, stack.mean(axis=0), std, stack.min(axis=0),
                     stack.max(axis=0), tuple(t.name for t in tests))


@dataclass(frozen=True)
class PropertyScatter:
    """Statistics of one tensile property over several tests."""

    values: tuple[float, ...]
    mean: float
    std: float
    """Sample standard deviation (0 for one test)."""
    minimum: float
    maximum: float

    @property
    def cv(self) -> float:
        """Coefficient of variation, std / mean."""
        return self.std / self.mean if self.mean else float("nan")


_PROPERTIES = {
    "modulus": ("E", 1e-3, "GPa"),
    "yield_strength": ("Rp", 1.0, "MPa"),
    "tensile_strength": ("Rm", 1.0, "MPa"),
    "uniform_elongation": ("Ag", 100.0, "%"),
    "elongation_after_fracture": ("A", 100.0, "%"),
}


def property_scatter(
    tests: Sequence[TensileTest], **options: object
) -> dict[str, PropertyScatter]:
    """Scatter of E, Rp, Rm, Ag and A over several tests.

    ``options`` go to `crashmetrics.materials.tensile_properties`
    (``modulus_window``, ``offset`` ...). Use `scatter_summary` for a
    text table.
    """
    if not tests:
        raise ValueError("Give at least one test.")
    props = [tensile_properties(t, **options) for t in tests]  # type: ignore[arg-type]
    out = {}
    for name in _PROPERTIES:
        v = np.array([float(getattr(p, name)) for p in props])
        out[name] = PropertyScatter(tuple(v.tolist()), float(v.mean()),
                                    float(v.std(ddof=1)) if len(v) > 1 else 0.0,
                                    float(v.min()), float(v.max()))
    return out


def scatter_summary(scatter: Mapping[str, PropertyScatter]) -> str:
    """Text table of `property_scatter` (mean, std, CV, min, max)."""
    lines = [f"{'':5} {'mean':>9} {'std':>8} {'CV':>7} {'min':>9} {'max':>9}"]
    for name, (label, scale, unit) in _PROPERTIES.items():
        if name not in scatter:
            continue
        p = scatter[name]
        lines.append(f"{label:5} {p.mean * scale:9.2f} {p.std * scale:8.2f} "
                     f"{p.cv * 100:6.2f}% {p.minimum * scale:9.2f} "
                     f"{p.maximum * scale:9.2f}  {unit}")
    return "\n".join(lines)

