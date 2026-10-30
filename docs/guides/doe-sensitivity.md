# DOE, sensitivity, margins and probabilistic ratings

Modules: `crashmetrics.doe`, `crashmetrics.sensitivity`,
`crashmetrics.margins`, `crashmetrics.uncertainty` (NumPy only).

Four helpers for design studies and machine learning around crash
results:

| Task | Functions | Question it answers |
| --- | --- | --- |
| Design of experiments | `latin_hypercube`, `halton`, `full_factorial`, `morris_design`, `lsdyna_parameters` | Which runs should I simulate? |
| Margins as targets | `margin`, `margins`, `euroncap_margins`, `margin_features` | How far is each criterion from its limits, as a smooth number a model can learn? |
| Sensitivity | `rank_sensitivity`, `partial_rank_correlation`, `rank_correlation`, `regression_coefficients`, `morris_effects` | Which design variable drives which criterion? |
| Probabilistic rating | `monte_carlo`, `normal`, `relative`, `uniform`, `scale`, `star_probabilities` | How likely is 5 stars, given test scatter? |

## Step 1: sample the design variables

```python
from crashmetrics.doe import latin_hypercube, lsdyna_parameters

design = latin_hypercube({"vent": (25.0, 45.0), "limiter": (3.0, 5.5),
                          "knee_k": (80.0, 200.0)}, n=30, seed=7)
for run in design.rows():                     # {"run": "run001", "vent": ..., ...}
    folder = Path("doe") / run["run"]
    folder.mkdir(parents=True, exist_ok=True)
    values = {k: round(run[k], 3) for k in design.names}
    (folder / "params.k").write_text(lsdyna_parameters(values, title=run["run"]))
```

- **Latin hypercube**: every variable's range is cut into `n` strata,
  each used once; the default for 10 to a few hundred runs. `seed`
  makes it repeatable.
- **Halton**: deterministic and evenly spread (up to about 10
  variables); a run can be added later without breaking the spread.
- **Full factorial**: every combination of given levels; only for few
  variables.
- **Morris design**: trajectories for `morris_effects` screening, `(k + 1)`
  runs per trajectory.
- `lsdyna_parameters` writes `*PARAMETER` cards (names up to 7
  characters, values as reals); include the file in the deck and use
  `&vent` in the cards.

## Step 2: margins instead of points as targets

NCAP points and colour bands jump in steps; regression models learn
those badly. The distance to the limits is continuous:

```python
from crashmetrics.margins import euroncap_margins, margin, margin_features

m = euroncap_margins("hybrid3_50", {"hic15": 600.0, "chest_compression": 31.0},
                     speed=50)
m["chest_compression"].position          # 0.5: halfway from HPL (20) to LPL (42)
m["chest_compression"].margin_lpl        # 0.26: 26 % of the LPL left
margin("thcc", 30.0, 42.0).margin_lpl     # regulation limit (R94 ThCC)
row.update(margin_features(m, prefix="driver."))   # driver.hic15.position, ...
```

| Field | Definition | Use |
| --- | --- | --- |
| `position` | `(v - HPL) / (LPL - HPL)`: 0 at the HPL, 1 at the LPL | Regression target for NCAP criteria |
| `margin_lpl` | `(LPL - v) / LPL` | Safety margin to a regulation limit |
| `margin_hpl` | `(HPL - v) / HPL` | Distance to full points |
| `sliding` | `clip(1 - position, 0, 1)` | Linear sliding-scale fraction (Bharat NCAP style) |

Predict the margins, then apply the scoring functions to the predicted
values.

## Step 3: which variable drives which criterion

```python
from crashmetrics.sensitivity import rank_sensitivity

ranking = rank_sensitivity(rows, ["vent", "limiter", "knee_k"], "chest_compression")
print(ranking.summary())
ranking.ranking            # ["limiter", "vent", "knee_k"]
```

| Measure | Range | Reads as |
| --- | --- | --- |
| **PRCC** (partial rank correlation, used for the ranking) | -1 to 1 | Effect of one variable with the others held out; finds a weak variable behind a strong one |
| Spearman rank correlation | -1 to 1 | Plain monotonic association |
| SRC (standardised regression coefficient) and R² | about -1 to 1 | Linear share of the variance; trust it when R² is near 1 |

All three miss effects that are not monotonic (an optimum inside the
range, such as an airbag vent size). **Morris screening** catches
them: a large `mu_star` means important, a large `sigma` means
non-linear or interacting.

```python
from crashmetrics.doe import morris_design
from crashmetrics.sensitivity import morris_effects

design = morris_design(bounds, trajectories=12, levels=4, seed=3)   # 12 (k + 1) runs
effects = morris_effects(design, hic_of_each_run)    # sorted by mu_star
```

With 30 runs, correlations below about 0.3 are within sampling noise.

## Step 4: probabilistic star rating

```python
from crashmetrics.uncertainty import monte_carlo, relative, scale, star_probabilities

def rating(v):                           # any scoring code: inputs -> outputs
    ...
    return {"points": result.points, "stars": result.stars}

result = monte_carlo(rating, nominal, {"hic15": relative(0.10), "chest": relative(0.06),
                                       "neck_scale": scale(0.08)}, n=2000, seed=1)
result.probability("stars", at_least=5)     # e.g. 0.68
star_probabilities(result)                 # {4: 0.32, 5: 0.68, ...}
result.percentiles("points")               # 5 / 50 / 95 %
```

- `relative(cv)` scatters an input by a coefficient of variation,
  `normal(sd)` by an absolute standard deviation, `uniform(h)` by ±h,
  `scale(cv)` gives a multiplier around 1 (scale a whole time history).
  Samples are clipped at zero unless `nonnegative=False`.
- The scatter should come from your own repeat tests or the dummy
  certification corridors; 5-10 % is typical for dummy channels.
- `result.rows()` gives every sample as a dict, e.g. for
  `rank_sensitivity` (which criteria decide the fifth star?) or a CSV.

## Complete examples

A 30-run Latin hypercube with LS-DYNA parameters, Euro NCAP margins and
the sensitivity of three criteria:

```python
--8<-- "examples/20_doe_margins_sensitivity.py"
```

Output:

```text
--8<-- "examples/expected/20_doe_margins_sensitivity.txt"
```

A Bharat NCAP design just above the 5-star threshold, with the
probability of keeping 5 stars and the criteria that decide it:

```python
--8<-- "examples/21_probabilistic_rating.py"
```

Output:

```text
--8<-- "examples/expected/21_probabilistic_rating.txt"
```

## References

- M. D. McKay, R. J. Beckman, W. J. Conover (1979). A comparison of
  three methods for selecting values of input variables in the analysis
  of output from a computer code. *Technometrics* 21(2), 239-245.
- M. D. Morris (1991). Factorial sampling plans for preliminary
  computational experiments. *Technometrics* 33(2), 161-174.
- F. Campolongo, J. Cariboni, A. Saltelli (2007). An effective screening
  design for sensitivity analysis of large models. *Environmental
  Modelling & Software* 22(10), 1509-1518.
- S. Marino, I. B. Hogue, C. J. Ray, D. E. Kirschner (2008). A
  methodology for performing global uncertainty and sensitivity analysis
  in systems biology. *Journal of Theoretical Biology* 254(1), 178-196
  (PRCC).
