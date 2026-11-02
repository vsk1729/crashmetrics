"""Material data for LS-DYNA material cards.

- `crashmetrics.materials.tensile`: read tensile tests (CSV, text,
  ``.xlsx``), clean the curve (fracture cut, smoothing, toe correction)
  and get the tensile properties (E, Rp0.2, Rm, Ag, A).

Units: stress MPa, force N, length mm, strain dimensionless.
"""

from crashmetrics.materials.tensile import (
    TensileProperties,
    TensileTest,
    clean_tensile,
    read_tensile,
    tensile_properties,
)

__all__ = [
    "TensileProperties",
    "TensileTest",
    "clean_tensile",
    "read_tensile",
    "tensile_properties",
]
