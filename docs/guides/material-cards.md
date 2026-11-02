# Material cards: tensile tests to *MAT_024

Module: `crashmetrics.materials` (NumPy only).

The goal of this part of the package is the full path from a tensile
test to a checked LS-DYNA `*MAT_PIECEWISE_LINEAR_PLASTICITY`
(`*MAT_024`) card. It is built in steps; available now:

| Step | Functions | Status |
| --- | --- | --- |
| 1. Read the test (CSV, text, `.xlsx`; force-elongation or stress-strain) | `read_tensile`, `TensileTest` | ✅ |
| 2. Clean the curve (fracture cut, smoothing, toe correction) | `clean_tensile` | ✅ |
| 3. Tensile properties (E, Rp0.2, Rm, Ag, A) | `tensile_properties` | ✅ |
| 4. Lüders plateau: ReH, ReL, Ae; flat or removed for the card | `luders_plateau`, `smooth_luders` | ✅ |
| 5. Several specimens: mean curve and scatter | `mean_curve`, `property_scatter` | ✅ |
| 6. Machine compliance (cross-head strain) | `correct_compliance` | ✅ |
| 7. True stress-strain | `true_curve` | ✅ |
| 8. Necking (Considère) | `necking_point` | ✅ |
| 9. Effective plastic strain from the yield point | `plastic_curve` | ✅ |
| 10. Extrapolation: Swift, Voce, Hockett-Sherby, Swift-Voce | `fit_hardening`, `compare_fits`, `extrapolate_curve` | ✅ |
| 11. n and K values | `n_value` | ✅ |
| 13. Cowper-Symonds C and P from tests at several rates | `fit_cowper_symonds` | ✅ |
| 14. Strain-rate table, written as `*DEFINE_TABLE` (linear or ln rates, model units) | `rate_table_from_model`, `rate_table_from_curves`, `RateTable.keyword` | ✅ |
| 15. Table checks: crossing curves, rate order, ln-rate form | `RateTable.check` | ✅ |
| 16. Johnson-Cook rate term | `fit_johnson_cook_rate` | ✅ |
| Card writing, unit systems; checking existing cards | | planned |

Units: stress in **MPa**, force in **N**, lengths in **mm**, strain
**dimensionless** (mm/mm, not %). E is in MPa (210 000 for steel).

## Step 1: read the test

```python
from crashmetrics.materials import read_tensile, TensileTest

# Force-elongation from the test machine: give the specimen size.
test = read_tensile("DP-L01.csv", gauge_length=80.0, width=20.0, thickness=1.2)

# Engineering stress-strain already computed; columns by name or index.
test = read_tensile("results.xlsx", sheet="Data", strain="Eng. strain",
                    stress="Eng. stress")

# From arrays.
test = TensileTest.from_force_elongation(force_n, elongation_mm, gauge_length=50.0,
                                         diameter=10.0)
test = TensileTest(strain, stress_mpa, name="DP600-L1")
```

- **Files:** `.csv`, `.txt`, `.dat` with any separator (comma,
  semicolon, tab, spaces; detected) and decimal points or commas
  (detected), or Excel `.xlsx` (values of any sheet). Old `.xls`: save as
  `.xlsx` or CSV.
- **Columns:** by header name (case-insensitive, a unique part is
  enough) or 0-based index. Without names, columns called "stress" and
  "strain", or "force"/"load" and "elongation"/"extension"/
  "displacement", are used.
- **Headers:** every text row above the data counts, so a units row
  under the names works. Units in the header (`Force [kN]`,
  `Strain (%)`, `Stress (GPa)`) are converted; otherwise give
  `strain_unit="%"`, `force_unit="kN"` and so on.
- **Cross-section:** `area` (mm²), `width` and `thickness` (flat
  specimen) or `diameter` (round specimen); stress is force over the
  original area.
- `test.info` records the file, sheet, columns and units used.

## Step 2: clean the curve

```python
from crashmetrics.materials import clean_tensile

clean = clean_tensile(test, smooth=21)
clean.info["cleaning"]     # cut point, smoothing window, toe shift, points removed
```

`clean_tensile` does, in order:

| Step | What it does | Settings |
| --- | --- | --- |
| Cut after fracture | Ends the curve before the first sudden stress drop after the maximum (more than 10 % of Rm from one point to the next), or where the stress falls below 10 % of Rm | `cut_fracture=True`, `fracture_drop=0.1` |
| Smoothing | Savitzky-Golay filter (quadratic) on the stress; off by default | `smooth=21` (odd number of points) |
| Toe correction | Fits the elastic line between 10 and 40 % of Rm, shifts the strain so the line passes through the origin, and replaces the toe points by the origin (as ISO 6892-1) | `toe=True`, `modulus_window=(0.1, 0.4)` or `modulus_stress=(lo, hi)` in MPa |

Use the smallest smoothing window that removes the noise: it rounds a
sharp yield point. For materials with a yield point (Lüders plateau),
set `modulus_stress` below the yield.

## Step 3: tensile properties

```python
from crashmetrics.materials import tensile_properties

p = tensile_properties(clean)
p.modulus, p.yield_strength, p.tensile_strength   # MPa
p.uniform_elongation, p.elongation_after_fracture  # Ag, A (plastic, -)
print(p.summary("DP-L01"))
```

| Property | Definition (ISO 6892-1) |
| --- | --- |
| `modulus` (E) | Least-squares slope between 10 and 40 % of Rm (`modulus_window`), with its R² |
| `yield_strength` (Rp0.2) | First crossing of the curve with the elastic line moved by 0.2 % strain (`offset=0.002`), interpolated |
| `tensile_strength` (Rm) | Maximum engineering stress |
| `uniform_elongation_total` (Agt), `uniform_elongation` (Ag) | Total and plastic strain at Rm (`Ag = Agt − Rm / E`) |
| `fracture_strain_total` (At), `elongation_after_fracture` (A) | Total and plastic strain at the last point (cut the curve at fracture first) |

!!! note "Rm and Ag on noisy data"
    The engineering curve is flat around Rm, so noise moves the maximum
    along it: Rm comes out slightly high and Agt can shift by a percent
    or more. Smooth the curve first (step 2).

## Step 4: Lüders plateau (discontinuous yielding)

Mild and some micro-alloyed steels yield with a drop of stress (upper
yield strength ReH) and then a plateau (around the lower yield strength
ReL) while Lüders bands cross the specimen, before uniform hardening
starts. A `*MAT_024` element cannot reproduce this, so the plateau is
measured and then replaced:

```python
from crashmetrics.materials import luders_plateau, smooth_luders

p = luders_plateau(clean)          # None if the material yields continuously
p.upper_yield, p.lower_yield       # ReH, ReL (MPa)
p.elongation                       # Ae, yield point elongation (-)

card_curve = smooth_luders(clean, mode="remove")   # or mode="flat"
```

| Item | Definition |
| --- | --- |
| ReH | Stress before the first drop of more than `drop` (1 %) below the running maximum |
| ReL | Lowest stress on the plateau; the transient dip straight after ReH is ignored when the plateau dips again later (ISO 6892-1) |
| End of plateau | From here on the stress stays above ReL × (1 + `band`), `band` = 2 % |
| Ae | Strain from ReH to the end of the plateau |

| `smooth_luders` mode | Result | Use |
| --- | --- | --- |
| `"flat"` | Spike and oscillations replaced by a line at ReL; the plateau strain stays | Keeps the measured strain at a given stress |
| `"remove"` | Plateau strain taken out; hardening starts at ReL on the elastic line | Common for crash cards: the plateau is a band-propagation effect, not a material law for one element |

Smooth noisy data only lightly (a short `smooth=` window) before
`luders_plateau`: smoothing rounds the ReH spike. Noise lowers the
measured ReL slightly (it is a minimum).

## Step 5: several specimens

Clean every specimen first (toe correction aligns them at the origin),
then:

```python
from crashmetrics.materials import mean_curve, property_scatter, scatter_summary

mean = mean_curve(cleaned, points=300)     # common strain grid up to the shortest curve
mean.mean, mean.std, mean.minimum, mean.maximum
card_input = mean.as_test("DP600 mean")    # continue the chain with the mean curve

print(scatter_summary(property_scatter(cleaned)))   # E, Rp, Rm, Ag, A: mean, std, CV
```

- The mean is taken at equal strains, linearly interpolated, up to the
  end of the shortest curve (or `strain_max`).
- After necking the strain is local to the neck and differs between
  specimens; for a card, use the mean up to the uniform elongation and
  extrapolate from there.
- `property_scatter` reports the sample standard deviation and the
  coefficient of variation; typical CVs for sheet steel are about 1-3 %
  for Rp and Rm.

## Step 6: machine compliance (no extensometer)

Strain from the cross-head travel includes the deflection of the frame,
load cell and grips: the elastic slope comes out far too low (often
50-150 GPa for steel), and every strain is too large. With the
material's real Young's modulus:

```python
from crashmetrics.materials import correct_compliance

fixed = correct_compliance(test, modulus=210_000.0)   # MPa
fixed.info["compliance"]["measured_modulus"]          # slope before, MPa
fixed.info["compliance_mm_per_n"]                     # machine compliance, mm/N
```

Every strain is reduced by `stress × (1/E_measured − 1/E)`, which
assumes a linear (elastic) machine. Apply it before `clean_tensile`;
strains after necking are local and are not made right by this. Use an
extensometer when you can.

## Steps 7-11: the hardening curve

`*MAT_024` needs **true stress against effective plastic strain**, from
the yield point to large strains (crash elements reach 50-100 % plastic
strain), but a tensile test is valid only up to necking. The chain:

```python
from crashmetrics.materials import (
    compare_fits, extrapolate_curve, fit_hardening, n_value, necking_point,
    plastic_curve, true_curve,
)

neck = necking_point(clean)            # at Rm; Considère ratio ~ 1
curve = plastic_curve(clean)           # (eps_p, true stress) from Rp0.2 to necking
fits = fit_hardening(curve)            # Swift, Voce, Hockett-Sherby, Swift-Voce
print(compare_fits(fits, strains=(0.1, 0.3, 0.5, 1.0)))
card_curve = extrapolate_curve(curve, fits["swift_voce"], strain_max=1.0)
nv = n_value(clean)                    # n10-Ag and K
```

### 7-9. True stress, necking, plastic strain

| Step | Formula | Notes |
| --- | --- | --- |
| True strain and stress | `eps = ln(1 + e)`, `sigma = s (1 + e)` | Constant volume, uniform deformation: valid up to necking (`true_curve` stops there) |
| Necking | Maximum engineering stress, located by a parabola over ±1 % strain | Equivalent to Considère, `d sigma / d eps = sigma`; the Considère ratio of the data is reported as a check |
| Effective plastic strain | `eps_p = eps - sigma / E` | E fitted on the curve, or given |

`plastic_curve(start=...)` chooses where the card curve starts:

| `start` | First point | Use |
| --- | --- | --- |
| `"offset"` (default) | `(0, Rp0.2)`: plastic strain counted from 0.2 % | The usual `*MAT_024` convention: SIGY = Rp0.2 |
| `"zero"` | Where the plastic strain becomes positive (end of the linear part) | Keeps the elastic-plastic transition below Rp0.2 |

### 10. Extrapolation beyond necking

| Law | Equation | Large-strain behaviour |
| --- | --- | --- |
| Swift | `K (eps0 + eps_p)^n` | Keeps hardening (power law): the highest stress at large strain |
| Voce | `sigma0 + Q (1 - exp(-beta eps_p))` | Saturates: the lowest |
| Hockett-Sherby | `sigma_s - (sigma_s - sigma0) exp(-a eps_p^m)` | Saturates more slowly |
| Swift-Voce | `alpha Swift + (1 - alpha) Voce` | In between; often the best compromise for AHSS |

Each law is fitted by least squares (Levenberg-Marquardt, NumPy only) to
the measured part, and reported with:

- **RMS error and R²** on the measured part: all laws usually fit it well.
- **Considère ratio** at necking: `(d sigma / d eps) / sigma` of the
  law. A law that reproduces the test necks at the measured strain
  (ratio 1). Below 1 it hardens too little and a simulation of the
  tensile test necks too early; above 1, too late.
- **Stress at large strain** (`compare_fits`): the laws agree up to
  necking and part beyond it. That spread is what the choice decides;
  without data past necking (DIC, shear or bulge tests, or an inverse
  simulation of the tensile test) it is an engineering judgement.

`extrapolate_curve` keeps the measured points up to necking and adds
`points` law points up to `strain_max`, shifting the law by the small
stress difference at necking so the curve has no step. `fit_range=`
restricts the fit (for example from 2 % plastic strain to necking, when
the yield region does not follow the law).

### 11. n and K values

`n_value` fits `ln(true stress) = ln K + n ln(true strain)` over an
engineering strain range, by default from 10 % to Ag ("n10-Ag"); use
`strain_range=(0.10, 0.20)` for n10-20, and `strain="plastic"` for the
true plastic strain. For certificates, ISO 10275 and ASTM E646 define
the exact procedure.

## Steps 13-16: strain rate

Crash structures deform at 10-1000 /s, where steels are clearly stronger
than in a quasi-static test. `*MAT_024` takes the rate effect either as
**Cowper-Symonds C and P** on the card (the whole curve scaled by one
factor) or as a **rate table**: LCSS pointing to a `*DEFINE_TABLE` with
one hardening curve per strain rate.

```python
from crashmetrics.materials import (
    fit_cowper_symonds, fit_johnson_cook_rate, rate_table_from_curves,
    rate_table_from_model,
)

measured = {0.001: curve_qs, 1.0: curve_1, 100.0: curve_100, 500.0: curve_500}
cs = fit_cowper_symonds(measured)          # cs.c (1/s), cs.p
jc = fit_johnson_cook_rate(measured)       # jc.c with rate0 = lowest rate

table = rate_table_from_model(static_extrapolated, cs,
                              [0.001, 0.01, 0.1, 1, 10, 100, 500, 1000])
print(table.check(log_rates=True, unit_system="mm-ms-kg").summary())
text = table.keyword(2000, unit_system="mm-ms-kg", log_rates=True)
```

### 13 and 16. Rate laws

| Law | Factor on the reference curve | Card |
| --- | --- | --- |
| Cowper-Symonds | `(1 + (rate/C)^(1/P)) / (1 + (rate_ref/C)^(1/P))` | C (1/s; 1/ms in mm-ms-kg) and P on `*MAT_024` |
| Johnson-Cook | `1 + c ln(rate / rate0)`, 1 below rate0 | A table generated from it |

- The curves (from `plastic_curve`) are compared at a few plastic
  strains from the yield point to 90 % of the smallest necking strain,
  against the lowest-rate curve. The reference test is not static
  (0.001 /s), and the fit takes that into account.
- Both laws scale the whole curve by one factor. When the measured
  rate effect changes with strain (often smaller at large strain), a
  table from the measured curves represents the tests better.

### 14. Rate table and `*DEFINE_TABLE`

| Builder | Curves |
| --- | --- |
| `rate_table_from_model(curve, law, rates)` | The reference curve times the law's factor, at any rates you choose |
| `rate_table_from_curves({rate: curve})` | Each test's own (extrapolated) curve |

All curves share one plastic strain grid (`points`, default 50, dense
near yield). `RateTable.keyword(table_id, unit_system=..., log_rates=...)`
writes the `*DEFINE_TABLE` and its `*DEFINE_CURVE` cards directly after
it, as LS-DYNA requires, with:

- rates converted to the model's time unit (1/s → 1/ms for mm-ms-kg)
  and stresses to its stress unit (GPa for mm-ms-kg, MPa for mm-s-t;
  `UNIT_SYSTEMS`);
- `log_rates=True`: the table holds ln(rate). LS-DYNA reads a table as
  logarithmic when its first value is negative, which `check` verifies.
  Logarithmic tables interpolate much better between rates that are
  decades apart.

### 15. Table checks

`RateTable.check()` (also run by `keyword`, which refuses a table with
errors):

| Check | Why |
| --- | --- |
| ❌ A curve below the curve of a lower rate at any strain | Crossing curves mean negative rate sensitivity: noisy, mesh-dependent results. Typical cause: curves extrapolated with different laws |
| ❌ Rates not strictly increasing | LS-DYNA needs ascending table values |
| ❌ Curves not starting at zero plastic strain | `*MAT_024` convention |
| ❌ ln-rate table whose first value is not negative | LS-DYNA would read all values as plain rates |
| ⚠️ Softening along a curve | Usually an extrapolation or data problem |
| ⚠️ Rates more than 100× apart in a linear table | Linear interpolation in rate between them is poor; use `log_rates` |
| ⚠️ No quasi-static curve (lowest rate above 0.01 /s) | Slow loading would use the lowest curve |

## Complete example

A semicolon-separated machine export with decimal commas, force in kN,
a seating toe, noise and fracture, compared with the exact values of
the synthetic steel:

```python
--8<-- "examples/23_tensile_test.py"
```

Output:

```text
--8<-- "examples/expected/23_tensile_test.txt"
```

Three mild-steel specimens with Lüders plateaus, one measured with the
cross-head: compliance correction, ReH / ReL / Ae, the plateau replaced,
the mean curve and the scatter:

```python
--8<-- "examples/24_tensile_specimens.py"
```

Output:

```text
--8<-- "examples/expected/24_tensile_specimens.txt"
```

From a noisy DP steel test to the card curve, with the four laws
compared against the known "true" hardening of the synthetic material:

```python
--8<-- "examples/25_hardening_curve.py"
```

Output:

```text
--8<-- "examples/expected/25_hardening_curve.txt"
```

Tests at four strain rates to Cowper-Symonds, a checked `*DEFINE_TABLE`,
and a table that fails the check because its curves cross:

```python
--8<-- "examples/26_strain_rate_table.py"
```

Output:

```text
--8<-- "examples/expected/26_strain_rate_table.txt"
```

## References

- ISO 6892-1:2019. Metallic materials — Tensile testing — Part 1:
  Method of test at room temperature.
- H. W. Swift (1952). Plastic instability under plane stress. *Journal
  of the Mechanics and Physics of Solids* 1(1), 1-18.
- E. Voce (1948). The relationship between stress and strain for
  homogeneous deformation. *Journal of the Institute of Metals* 74,
  537-562.
- J. E. Hockett, O. D. Sherby (1975). Large strain deformation of
  polycrystalline metals at low homologous temperatures. *Journal of
  the Mechanics and Physics of Solids* 23(2), 87-98.
- A. Considère (1885). Mémoire sur l'emploi du fer et de l'acier dans
  les constructions. *Annales des Ponts et Chaussées* 9, 574-775.
- G. R. Cowper, P. S. Symonds (1957). Strain-hardening and strain-rate
  effects in the impact loading of cantilever beams. Technical Report
  No. 28, Division of Applied Mathematics, Brown University.
- G. R. Johnson, W. H. Cook (1983). A constitutive model and data for
  metals subjected to large strains, high strain rates and high
  temperatures. *Proceedings of the 7th International Symposium on
  Ballistics*, The Hague, 541-547.
- J. H. Hollomon (1945). Tensile deformation. *Transactions of AIME*
  162, 268-290.
- A. Savitzky, M. J. E. Golay (1964). Smoothing and differentiation of
  data by simplified least squares procedures. *Analytical Chemistry*
  36(8), 1627-1639.
