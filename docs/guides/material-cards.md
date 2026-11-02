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
| True stress-strain, necking, extrapolation (Swift, Voce, ...) | | planned |
| Strain-rate fits and `*DEFINE_TABLE` | | planned |
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

## References

- ISO 6892-1:2019. Metallic materials — Tensile testing — Part 1:
  Method of test at room temperature.
- A. Savitzky, M. J. E. Golay (1964). Smoothing and differentiation of
  data by simplified least squares procedures. *Analytical Chemistry*
  36(8), 1627-1639.
