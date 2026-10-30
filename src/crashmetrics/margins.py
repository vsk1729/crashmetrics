"""Distance to performance limits, as continuous targets for ML models.

NCAP points and colour bands jump in steps, which regression models
learn badly. The distance of each criterion to its limits is continuous,
so it is a better training target; apply the scoring rules to the
prediction afterwards.

For a criterion value v with higher performance limit HPL and lower
performance limit LPL:

- ``position = (v - HPL) / (LPL - HPL)``: 0 at the HPL, 1 at the LPL,
  negative inside the full-points region, above 1 beyond the LPL.
- ``margin_lpl = (LPL - v) / LPL``: share of the LPL still available
  (1 at zero, 0 at the LPL, negative beyond). For a single limit (a
  regulation limit) this is the safety margin.
- ``margin_hpl = (HPL - v) / HPL``: the same for the HPL.
- ``sliding = clip(1 - position, 0, 1)``: the linear sliding-scale
  fraction (1 at or below the HPL, 0 at or beyond the LPL), as used by
  Bharat NCAP and older Euro NCAP protocols.

Values are compared by magnitude (``|v|``).

Functions:

- `margin`, `margins`: For any limits (a `Limit`, an ``(hpl, lpl)``
  pair or a single limit).
- `euroncap_margins`: Euro NCAP 2026 frontal limits of a dummy.
- `margin_features`: Flat dict for `crashmetrics.features.feature_table`.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from crashmetrics.frontal_scoring import Limit, _limits_for

__all__ = [
    "Margin",
    "euroncap_margins",
    "margin",
    "margin_features",
    "margins",
]

LimitLike = Limit | tuple[float | None, float] | float


@dataclass(frozen=True)
class Margin:
    """Distance of one criterion value to its limits."""

    name: str
    value: float
    hpl: float | None
    lpl: float
    position: float | None
    """(v - HPL) / (LPL - HPL); None without an HPL."""
    margin_lpl: float
    margin_hpl: float | None
    sliding: float
    """Linear sliding-scale fraction 0..1 (without an HPL: 1 below the
    LPL, else 0)."""


def _as_limit(limit: LimitLike) -> tuple[float | None, float]:
    if isinstance(limit, Limit):
        return limit.hpl, limit.lpl
    if isinstance(limit, tuple):
        hpl, lpl = limit
        return (None if hpl is None else float(hpl)), float(lpl)
    return None, float(limit)


def margin(name: str, value: float, limit: LimitLike) -> Margin:
    """Margin of one value to a limit (`Limit`, ``(hpl, lpl)`` or one limit)."""
    hpl, lpl = _as_limit(limit)
    v = abs(float(value))
    if not math.isfinite(v):
        raise ValueError(f"{name}: value must be finite.")
    if not math.isfinite(lpl) or lpl <= 0:
        raise ValueError(f"{name}: the limit must be positive.")
    if hpl is not None and not 0 <= hpl < lpl:
        raise ValueError(f"{name}: need 0 <= HPL < LPL.")
    margin_lpl = (lpl - v) / lpl
    if hpl is None:
        return Margin(name, v, None, lpl, None, margin_lpl, None,
                      1.0 if v < lpl else 0.0)
    position = (v - hpl) / (lpl - hpl)
    margin_hpl = (hpl - v) / hpl if hpl > 0 else None
    sliding = float(np.clip(1.0 - position, 0.0, 1.0))
    return Margin(name, v, hpl, lpl, position, margin_lpl, margin_hpl, sliding)


def margins(values: Mapping[str, float], limits: Mapping[str, LimitLike]
            ) -> dict[str, Margin]:
    """`margin` for every value that has a limit (others are skipped)."""
    return {name: margin(name, v, limits[name]) for name, v in values.items()
            if name in limits}


def euroncap_margins(dummy: str, values: Mapping[str, float], speed: int = 50
                     ) -> dict[str, Margin]:
    """Margins to the Euro NCAP 2026 frontal limits of a dummy
    (`crashmetrics.frontal_scoring.DUMMY_LIMITS`; chest limits by
    speed). Values without a limit for that dummy are skipped."""
    return margins(values, _limits_for(dummy, speed))


def margin_features(result: Mapping[str, Margin], prefix: str = "",
                    fields: tuple[str, ...] = ("position", "margin_lpl", "sliding")
                    ) -> dict[str, float]:
    """Flatten margins into ``{"<prefix><criterion>.<field>": value}``.

    Fields that are None (no HPL) become NaN, so feature tables keep
    their columns.
    """
    out: dict[str, float] = {}
    for name, m in result.items():
        for f in fields:
            v = getattr(m, f)
            out[f"{prefix}{name}.{f}"] = math.nan if v is None else float(v)
    return out
