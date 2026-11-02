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
- `crashmetrics.materials.card`: the ``*MAT_PIECEWISE_LINEAR_PLASTICITY``
  card with its curve or table in any LS-DYNA unit system; simple
  failure strain.
- `crashmetrics.materials.gissmo`: failure with GISSMO: stress states,
  failure curve fits from fracture tests (Hosford-Coulomb, Johnson-Cook,
  tabulated), instability from the forming limit, element size
  regularisation, damage along a path, ``*MAT_ADD_DAMAGE_GISSMO``.
- `crashmetrics.materials.keyword`: read existing ``*MAT_024`` and
  ``*MAT_ADD_DAMAGE_GISSMO`` cards with their curves and tables, check
  them, convert their unit system, compare two cards.
- `crashmetrics.materials.verify`: single-element tension test deck and
  the comparison of its result with the card.
- `crashmetrics.materials.library`: summary table of cards and a
  material library (JSON with provenance).

Units: stress MPa, force N, length mm, strain dimensionless.
"""

from crashmetrics.materials.card import (
    DENSITY_SCALE,
    Mat024,
    failure_strain,
    fracture_strain,
    keyword_number,
)
from crashmetrics.materials.corrections import (
    LudersPlateau,
    correct_compliance,
    luders_plateau,
    smooth_luders,
)
from crashmetrics.materials.gissmo import (
    FAILURE_MODELS,
    TRIAXIALITY,
    DamageHistory,
    FailureFit,
    FractureTest,
    GissmoCard,
    RegularizationCurve,
    average_triaxiality,
    fit_failure_curve,
    instability_from_flc,
    integrate_damage,
    lode_parameter,
    plane_stress_strains,
    regularization_estimate,
    triaxiality_from_strain_ratio,
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
from crashmetrics.materials.keyword import (
    CardCheck,
    CardComparison,
    GissmoKeyword,
    KeywordCurve,
    KeywordDeck,
    KeywordTable,
    Mat024Keyword,
    check_gissmo,
    check_keyword,
    compare_cards,
    convert_keyword,
    guess_unit_system,
    read_keyword,
)
from crashmetrics.materials.library import (
    MaterialLibrary,
    card_summary,
    summary_markdown,
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
from crashmetrics.materials.verify import (
    SingleElementCheck,
    compare_tension,
    single_element_deck,
    verify_single_element,
)

__all__ = [
    "DENSITY_SCALE",
    "FAILURE_MODELS",
    "LAWS",
    "TRIAXIALITY",
    "UNIT_SYSTEMS",
    "CardCheck",
    "CardComparison",
    "CowperSymonds",
    "DamageHistory",
    "FailureFit",
    "FractureTest",
    "GissmoCard",
    "GissmoKeyword",
    "HardeningCurve",
    "HardeningFit",
    "JohnsonCookRate",
    "KeywordCurve",
    "KeywordDeck",
    "KeywordTable",
    "LudersPlateau",
    "Mat024",
    "Mat024Keyword",
    "MaterialLibrary",
    "MeanCurve",
    "NValue",
    "NeckingPoint",
    "PropertyScatter",
    "RateCheck",
    "RateTable",
    "RegularizationCurve",
    "SingleElementCheck",
    "TensileProperties",
    "TensileTest",
    "TrueCurve",
    "average_triaxiality",
    "card_summary",
    "check_gissmo",
    "check_keyword",
    "clean_tensile",
    "compare_cards",
    "compare_fits",
    "compare_tension",
    "convert_keyword",
    "correct_compliance",
    "extrapolate_curve",
    "failure_strain",
    "fit_cowper_symonds",
    "fit_failure_curve",
    "fit_hardening",
    "fit_johnson_cook_rate",
    "fracture_strain",
    "guess_unit_system",
    "instability_from_flc",
    "integrate_damage",
    "keyword_number",
    "lode_parameter",
    "luders_plateau",
    "mean_curve",
    "n_value",
    "necking_point",
    "plane_stress_strains",
    "plastic_curve",
    "property_scatter",
    "rate_table_from_curves",
    "rate_table_from_model",
    "read_keyword",
    "read_tensile",
    "regularization_estimate",
    "scatter_summary",
    "single_element_deck",
    "smooth_luders",
    "summary_markdown",
    "tensile_properties",
    "triaxiality_from_strain_ratio",
    "true_curve",
    "verify_single_element",
]
