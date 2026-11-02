# Failure with GISSMO: fracture tests to *MAT_ADD_DAMAGE_GISSMO

Module: `crashmetrics.materials.gissmo` (NumPy only).

FAIL in `*MAT_024` is one plastic strain for every stress state. Sheet
steels and aluminium alloys break at very different strains in shear,
uniaxial tension, plane strain and biaxial tension, and the strain an
element reaches before it breaks depends on its size. GISSMO
(Neukamm, Feucht and Haufe) is the LS-DYNA damage model for this; it is
added to the material with `*MAT_ADD_DAMAGE_GISSMO` (same MID). This
module calibrates it from fracture tests, writes the card with its
curves, and reads and checks existing cards.

| Step | Functions |
| --- | --- |
| Stress states: triaxiality, Lode parameter, major / minor strains | `TRIAXIALITY`, `triaxiality_from_strain_ratio`, `plane_stress_strains`, `lode_parameter`, `average_triaxiality` |
| Fracture tests with their loading paths | `FractureTest` |
| Failure curve (LCSDG): Hosford-Coulomb, Johnson-Cook or tabulated | `fit_failure_curve`, `FailureFit` |
| Instability curve (ECRIT) from the forming limit curve | `instability_from_flc` |
| Element size regularisation (LCREGD), first estimate | `regularization_estimate`, `RegularizationCurve` |
| Damage, instability and stress fading along a path | `integrate_damage`, `GissmoCard.damage` |
| The card in any unit system, with checks | `GissmoCard`, `GissmoCard.check`, `GissmoCard.keyword` |
| `*MAT_024` and GISSMO in one include file | `Mat024.write(..., damage=card)` |
| Read and check existing GISSMO cards | `read_keyword`, `KeywordDeck.damage`, `check_gissmo` |

Strains are equivalent plastic strains, element sizes in **mm**, strain
rates in **1/s**; the unit system is chosen only when writing.

## How GISSMO works

```text
dD = n · D^(1 − 1/n) · dεp / εf(η)        element fails at D = 1
dF = n · F^(1 − 1/n) · dεp / εcrit(η)     F = 1: coupling starts, D_crit = D at that moment
σ* = σ · (1 − ((D − D_crit) / (1 − D_crit))^m)   once D ≥ D_crit
```

| Symbol | Meaning | Card field |
| --- | --- | --- |
| η = σm / σvm | Stress triaxiality | |
| εf(η) | Failure strain | LCSDG (curve) |
| n | Damage exponent | DMGEXP |
| εcrit(η) | Critical strain: onset of instability (necking) | ECRIT (curve or constant) |
| D_crit | Damage where the stress starts to fade | DCRIT, if ECRIT is 0 |
| m | Fading exponent | FADEXP |

Integrating the first line gives `D^(1/n) = ∫ dεp / εf(η)` along the
path. Under constant triaxiality `D = (εp / εf)^n`, so the element
breaks at `εp = εf` whatever `n` is. `n` only shapes how D grows, and so
`D_crit` and the fading. That is why the failure curve can be fitted
first, without `n`.

Without ECRIT, coupling starts at D = DCRIT; with both 0 there is no
fading at all and elements fail at full stress.

## Stress states

| Test | Strain ratio β = ε2/ε1 | Triaxiality η | Lode parameter |
| --- | --- | --- | --- |
| Uniaxial compression | (−2) | −1/3 | −1 |
| Shear | −1 | 0 | 0 |
| Uniaxial tension | −1/2 | 1/3 | 1 |
| Plane strain tension | 0 | 1/√3 = 0.577 | 0 |
| Equibiaxial tension | 1 | 2/3 | −1 |

```python
from crashmetrics.materials import (
    TRIAXIALITY, lode_parameter, plane_stress_strains, triaxiality_from_strain_ratio,
)

TRIAXIALITY["plane_strain"]                      # 0.577
triaxiality_from_strain_ratio([-0.5, 0.0, 1.0])  # 1/3, 0.577, 2/3
eta, eps_eq = plane_stress_strains(major=[0.30, 0.20], minor=[-0.15, 0.0])
```

For plane stress, von Mises and proportional loading:

```text
η    = (1 + β) / (√3 · √(1 + β + β²))
εeq  = 2/√3 · ε1 · √(1 + β + β²)
θ̄    = 1 − (2/π) · arccos(−27/2 · η · (η² − 1/3))
```

`plane_stress_strains` turns DIC fracture strains or FLC points into
(triaxiality, equivalent strain). In plane stress the Lode parameter
follows from η; for solid elements it does not, which this module does
not cover.

## Fracture tests and their paths

Triaxiality changes while a specimen loads: a dogbone is uniaxial up to
necking and then moves towards plane strain in the neck, and a notch
changes as it thins. So a fracture strain belongs to a path, not to a
point. Take the path from a simulation of the test (the element where
the crack starts, fine mesh) or from DIC, from the start of plasticity
to fracture:

```python
from crashmetrics.materials import FractureTest

tests = [
    FractureTest("shear", 0.51, triaxiality=0.05),          # proportional
    FractureTest("dogbone", 0.519,
                 path_strain=eps_p, path_triaxiality=eta),  # with its path
    FractureTest("notch R5", 0.452, path_strain=e2, path_triaxiality=eta2,
                 weight=2.0),
    ...
]
```

A test with a path gets its strain-weighted average triaxiality
(`average_triaxiality`) for tables and the tabulated fit; the fits
themselves integrate the damage along the whole path. The path must end
at the fracture strain.

## Failure curve (LCSDG)

```python
from crashmetrics.materials import fit_failure_curve

hc = fit_failure_curve(tests)                      # Hosford-Coulomb
jc = fit_failure_curve(tests, "johnson_cook")
print(hc.summary())                                # tests, predicted, error
hc([0.0, 1/3, 0.577, 2/3])                         # failure strains
```

The residual of a test is `ln ∫ dεp / εf(η)` along its path: zero when
the curve makes D reach 1 exactly at the measured fracture. For a
proportional test it is the log of measured over curve strain.
Weighted least squares (Levenberg-Marquardt), NumPy only.

| Model | Failure strain | Fitted | Tests | Notes |
| --- | --- | --- | --- | --- |
| `"hosford_coulomb"` | `b (1 + c)^(1/n) [Hosford_a(η) + c (2η + f1 + f3)]^(−1/n)` | a, b, c (n = 0.1, `hc_exponent=`) | 3 or more | Minimum near plane strain; `b` is the fracture strain in uniaxial and equibiaxial tension |
| `"johnson_cook"` | `d1 + d2 exp(d3 η)` | d1, d2, d3 | 3 or more | Monotonic: no plane-strain minimum |
| `"tabulated"` | Linear through one point per test | — | 1 or more | Points adjusted until each path reaches D = 1 at its fracture; constant beyond the ends |

In the Hosford-Coulomb model, `Hosford_a = {½[(f1 − f2)^a + (f2 − f3)^a
+ (f1 − f3)^a]}^(1/a)`, with the Lode functions `f1 = ⅔ cos(π/6 (1 −
θ̄))`, `f2 = ⅔ cos(π/6 (3 + θ̄))` and `f3 = −⅔ cos(π/6 (1 + θ̄))`. The
model has the plane-strain minimum that sheet metals show; Johnson-Cook
cannot follow it (example 29: up to 22 % error at plane strain).

!!! warning "Compression is extrapolated"
    The tests usually cover shear to equibiaxial tension. Below shear
    the curve is the model's extrapolation, and the card writes it from
    η = −2/3 (`triaxiality_range=`); LS-DYNA holds the end values beyond.
    Check those values, especially in crush zones.

## Instability (ECRIT) from the forming limit curve

```python
from crashmetrics.materials import instability_from_flc

eta_c, eps_c = instability_from_flc(major=[0.36, 0.22, 0.14, 0.17, 0.21],
                                    minor=[-0.20, -0.10, 0.0, 0.08, 0.15])
```

Each FLC point becomes (triaxiality, equivalent strain). The curve is
then extended with constant values to −1/3 and 2/3, because an FLC only
covers uniaxial to equibiaxial tension. The FLC is the onset of local
necking, which is what ECRIT means for sheets. Below uniaxial tension
(shear) the FLC says nothing, so the constant extension is a choice to
check. `instability=` also takes a constant (for example the necking
strain), or None with `dcrit=` instead.

## Element size regularisation (LCREGD)

```python
from crashmetrics.materials import regularization_estimate

reg = regularization_estimate([1.0, 2.5, 5.0, 10.0], reference_size=0.5,
                              necking_strain=0.12, fracture_strain=float(hc(1/3)),
                              neck_length=1.0)                       # mm
reg(2.5)                                                             # 0.522
```

```text
ε(h)   = εn + (εf − εn) · min(1, L / h)        L: neck length ≈ sheet thickness
factor = ε(h) / ε(reference size)
```

The reference size is the element size of the test simulations that
gave the paths: the failure curve belongs to it, so its factor is 1.
This is a **first estimate**. Refine it by simulating the tensile test
with each element size and adjusting until each one fails at the
measured elongation.

!!! warning "One curve regularises every stress state"
    LCREGD scales the failure strain only, not ECRIT, and the same factor
    applies in shear, where no neck forms. `GissmoCard.check` warns from
    the element size at which the regularised failure strain falls
    below the critical strain, because those elements fail without
    fading. LS-DYNA reduces the regularisation in shear and biaxial
    tension with SHRF and BIAXF, and newer versions accept
    triaxiality-dependent factors (an LCREGD table). crashmetrics passes
    SHRF and BIAXF through as given and writes only the curve form.

FADEXP can also depend on element size:
`fadexp=([0.5, 2.5, 5.0], [2.0, 4.0, 6.0])` is written as a curve with
a negative FADEXP.

## Damage along a path

```python
import numpy as np
from crashmetrics.materials import integrate_damage

e = np.linspace(0.0, 0.5, 501)
h = card.damage(e, np.full_like(e, 1/3), element_size=2.5)   # the card's curves
h = integrate_damage(e, eta, hc, dmgexp=2.0, instability=0.25, fadexp=3.0)
h.fracture_strain, h.coupling_strain, h.critical_damage
h.damage, h.instability, h.fading                            # along the path
```

The integration is exact for a piecewise-linear path. `fading` is the
stress factor `σ*/σ`: 1 before coupling, 0 at failure. Use it to see
what a card does to one element before running a model.

## The card

```python
from crashmetrics.materials import GissmoCard, Mat024

card = GissmoCard(mid=800, failure=hc, instability=(eta_c, eps_c),
                  dmgexp=2.0, fadexp=3.0, regularization=reg,
                  rate_scaling=([0.001, 1.0, 100.0], [1.0, 1.05, 1.1]))
errors, warnings = card.check()
print(card.keyword("mm-ms-kg"))                        # card and curves
mat.write("dp800.k", "mm-ms-kg", damage=card)          # with the *MAT_024
```

| Field | From | Written |
| --- | --- | --- |
| MID | `mid` | Must match the `*MAT_024` (`Mat024.write` refuses another MID) |
| DTYP | `dtyp` | 1 (default): damage coupled, element fails at D = 1; 0: damage only |
| REFSZ | `refsz` (mm) | Converted to model length; 0: none |
| NUMFIP | `numfip` | As given (1) |
| LCSDG | `failure` | Curve (triaxiality, failure strain): a fit sampled at `points` (41) over `triaxiality_range` (−2/3 to 2/3), or the arrays as given |
| ECRIT | `instability` | −curve ID for a curve, the value for a constant, 0 for None |
| DMGEXP, DCRIT | `dmgexp`, `dcrit` | As given; DCRIT is used by LS-DYNA only with ECRIT 0 |
| FADEXP | `fadexp` | The value, or −curve ID for (element size, exponent) |
| LCREGD | `regularization` | Curve (element size in model length, factor) |
| LCSRS | `rate_scaling` | Curve (strain rate, factor), ln(rate) in model time by default (`log_rates=False` for rates); negative ID when the factor should not scale ECRIT (`scale_instability_with_rate=False`) |
| SHRF, BIAXF | `shrf`, `biaxf` | As given; not modelled by `failure_strain`, `damage` or `check` |
| INSTF, and card 3 fields after BIAXF | — | Left blank (LS-DYNA defaults) |

- **Curve IDs** start at `first_curve_id` (default MID + 2000) and go up
  in steps of 100: failure, instability, regularisation, fading, rate
  (only those present). See `card.curve_ids()`.
- **Units:** only element sizes and strain rates have units. Sizes are
  written in m for m-s-kg and in mm otherwise; rates in 1/ms for
  mm-ms-kg and in 1/s otherwise.
- `keyword` refuses a card with errors; `check` returns them:

| Errors | Warnings |
| --- | --- |
| Failure or critical strain zero or negative; triaxiality not increasing; fading exponents, regularisation or rate factors not positive; rates not increasing; curve IDs colliding | Failure curve not covering shear to equibiaxial tension; critical strain at or above the failure strain (no fading there); from some element size, at or above the regularised failure strain; DMGEXP below 1; regularisation rising with element size; no coupling at all |

## Existing GISSMO cards

```python
from crashmetrics.materials import check_gissmo, read_keyword

deck = read_keyword("supplier.k")
deck.gissmo[800]                        # the fields as written (model units)
card = deck.damage(800)                 # GissmoCard in mm and 1/s
for result in check_gissmo(deck):
    print(result.summary())
```

`read_keyword` reads `*MAT_ADD_DAMAGE_GISSMO` and its `_TITLE` form in
fixed, long or comma format. The unit system comes from
`unit_system=`, else from the `*MAT_024` with the same MID, else
mm-ms-kg is assumed and flagged. `check_gissmo` adds the deck-level
checks to `GissmoCard.check`:

- missing curves;
- tables (Lode- or temperature-dependent LCSDG, a table LCREGD), which
  are not read;
- no `*MAT_024` with the MID;
- DMGEXP or FADEXP left blank;
- fields given as parameters.

GISSMO inside `*MAT_ADD_EROSION` (the older form) is noted, not read.

## Complete example

A DP800 sheet with five fracture tests (synthetic: a known
Hosford-Coulomb curve with 2-3 % scatter), Hosford-Coulomb against
Johnson-Cook, ECRIT from the FLC, a regularisation estimate, the damage
of a 2.5 mm shell, and the include file read back and checked:

```python
--8<-- "examples/29_gissmo_failure.py"
```

Output:

```text
--8<-- "examples/expected/29_gissmo_failure.txt"
```

The card check flags a real issue: with one LCREGD curve, 2.5 mm
elements in shear and around uniaxial and equibiaxial tension fail
before their stress fades. In the uniaxial element itself coupling still
starts at 0.282, just before failure at 0.308.

## References

- F. Neukamm, M. Feucht, A. Haufe (2009). Considering damage history in
  crashworthiness simulations. *7th European LS-DYNA Conference*,
  Salzburg.
- S. J. Marcadet, D. Mohr (2016). Critical hardening rate model for
  predicting path-dependent ductile fracture. *International Journal of
  Fracture* 200, 77-98. (The Hosford-Coulomb criterion and the Lode
  functions f1, f2, f3.)
- C. C. Roth, D. Mohr (2016). Ductile fracture experiments with locally
  proportional loading histories. *International Journal of Plasticity*
  79.
- G. R. Johnson, W. H. Cook (1985). Fracture characteristics of three
  metals subjected to various strains, strain rates, temperatures and
  pressures. *Engineering Fracture Mechanics* 21(1), 31-48.
- Y. Bai, T. Wierzbicki (2008). A new model of metal plasticity and
  fracture with pressure and Lode dependence. *International Journal of
  Plasticity* 24(6), 1071-1096.
- DYNAmore / Ansys (2020). GISSMO update (LCREGD as a curve or a table
  of element size).
