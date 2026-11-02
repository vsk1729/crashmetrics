"""Material data for LS-DYNA material cards.

- `crashmetrics.materials.tensile`: read tensile tests (CSV, text,
  ``.xlsx``), clean the curve (fracture cut, smoothing, toe correction)
  and get the tensile properties (E, Rp0.2, Rm, Ag, A).
- `crashmetrics.materials.corrections`: Lüders plateau (ReH, ReL, Ae)
  and its replacement for a card; machine compliance correction.
- `crashmetrics.materials.specimens`: mean curve of several specimens
  and the scatter of their properties.
- `crashmetrics.materials.hardening`: true stress-strain, necking,
  effective plastic strain, hardening laws (Swift, Voce, Hockett-Sherby,
  Swift-Voce) and the extrapolated ``*MAT_024`` curve; n and K values.
- `crashmetrics.materials.rate`: Cowper-Symonds and Johnson-Cook rate
  fits, strain-rate tables (``*DEFINE_TABLE``) and their checks.

Units: stress MPa, force N, length mm, strain dimensionless.
"""

from crashmetrics.materials.corrections import (
    LudersPlateau,
    correct_compliance,
    luders_plateau,
    smooth_luders,
)
from crashmetrics.materials.hardening import (
    LAWS,
    HardeningCurve,
    HardeningFit,
    NeckingPoint,
    NValue,
    TrueCurve,
    compare_fits,
    extrapolate_curve,
    fit_hardening,
    n_value,
    necking_point,
    plastic_curve,
    true_curve,
)
from crashmetrics.materials.rate import (
    UNIT_SYSTEMS,
    CowperSymonds,
    JohnsonCookRate,
    RateCheck,
    RateTable,
    fit_cowper_symonds,
    fit_johnson_cook_rate,
    rate_table_from_curves,
    rate_table_from_model,
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
    "LAWS",
    "UNIT_SYSTEMS",
    "CowperSymonds",
    "HardeningCurve",
    "HardeningFit",
    "JohnsonCookRate",
    "LudersPlateau",
    "MeanCurve",
    "NValue",
    "NeckingPoint",
    "PropertyScatter",
    "RateCheck",
    "RateTable",
    "TensileProperties",
    "TensileTest",
    "TrueCurve",
    "clean_tensile",
    "compare_fits",
    "correct_compliance",
    "extrapolate_curve",
    "fit_cowper_symonds",
    "fit_hardening",
    "fit_johnson_cook_rate",
    "luders_plateau",
    "mean_curve",
    "n_value",
    "necking_point",
    "plastic_curve",
    "property_scatter",
    "rate_table_from_curves",
    "rate_table_from_model",
    "read_tensile",
    "scatter_summary",
    "smooth_luders",
    "tensile_properties",
    "true_curve",
]
