"""Shared scoring helpers (internal)."""

from __future__ import annotations

import math


def linear_fraction(value: float, higher: float, lower: float) -> float:
    """Return the linear sliding-scale fraction of ``value``.

    1 at or below the higher performance limit, 0 at or above the lower
    performance limit, linear in between. Used by the Euro NCAP legform
    and Flex-PLI scores and by the Bharat NCAP region scores.
    """
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"value must be finite, got {value!r}.")
    if not (math.isfinite(higher) and math.isfinite(lower)) or lower <= higher:
        raise ValueError(
            "The lower performance limit must be finite and greater than "
            "the higher performance limit."
        )
    if v <= higher:
        return 1.0
    if v >= lower:
        return 0.0
    return (lower - v) / (lower - higher)
