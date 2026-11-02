"""Material data for LS-DYNA material cards.

- `crashmetrics.materials.tensile`: read tensile tests (CSV, text,
  ``.xlsx``), clean the curve (fracture cut, smoothing, toe correction)
  and get the tensile properties (E, Rp0.2, Rm, Ag, A).
- `crashmetrics.materials.corrections`: Lüders plateau (ReH, ReL, Ae)
  and its replacement for a card; machine compliance correction.
- `crashmetrics.materials.specimens`: mean curve of several specimens
  and the scatter of their properties.

Units: stress MPa, force N, length mm, strain dimensionless.
"""

from crashmetrics.materials.corrections import (
    LudersPlateau,
    correct_compliance,
    luders_plateau,
    smooth_luders,
)
from crashmetrics.materials.specimens import (
    MeanCurve,
    PropertyScatter,
    mean_curve,
    property_scatter,
    scatter_summary,
)
from crashmetrics.materials.tensile import (
    TensileProperties,
    TensileTest,
    clean_tensile,
    read_tensile,
    tensile_properties,
)

__all__ = [
    "LudersPlateau",
    "MeanCurve",
    "PropertyScatter",
    "TensileProperties",
    "TensileTest",
    "clean_tensile",
    "correct_compliance",
    "luders_plateau",
    "mean_curve",
    "property_scatter",
    "read_tensile",
    "scatter_summary",
    "smooth_luders",
    "tensile_properties",
]
