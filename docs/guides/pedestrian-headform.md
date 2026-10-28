# Pedestrian headform (Euro NCAP)

Module: `crashmetrics.pedestrian` (`headform_score`, `correction_factor`,
`hic_colour`, `verification_colour`).

Protocols: `"euroncap_2026"` (Crash Protection – VRU Impacts v1.1,
head maximum 10 points) and `"euroncap_2023"` (Assessment Protocol – VRU
v11.4, head maximum 18 points).

## How Euro NCAP scores the head

1. The manufacturer predicts a colour (from HIC15) for every grid point
   of the bonnet, windscreen and A-pillar area.
2. Euro NCAP tests a few **verification points**. Comparing the tested
   and predicted points gives a **correction factor** that scales all
   predicted points.
3. Some points are scored directly: **blue** points from their own
   tests, **default red** points as 0 and (2026) **A-pillar** points from
   reward tests.
4. Head score = corrected grid points / number of grid points × head
   maximum.

## Step 1: colours from HIC15

```python
from crashmetrics.pedestrian import hic_colour

hic_colour(620)    # 'green'
```

| HIC15 | Colour | Points |
| --- | --- | --- |
| < 650 | green | 1.00 |
| 650 – < 1000 | yellow | 0.75 |
| 1000 – < 1350 | orange | 0.50 |
| 1350 – < 1700 | brown | 0.25 |
| ≥ 1700 | red | 0.00 |

## Step 2: build the grid

A dict with one entry per grid point. The key is any label you like,
usually `(row, column)`. The value is either a predicted HIC15, a
predicted colour, or a special label:

```python
grid = {
    (0, 0): 541.0,          # predicted HIC15 (e.g. from CAE)
    (0, 1): "yellow",       # or a predicted colour
    (8, 0): "default_red",  # 0 points, e.g. wiper spindle
    (7, 3): "blue",         # scored from its own test
    (8, 6): "a_pillar",     # 2026: reward tests; 2023: default red
    # ... every grid point
}
```

## Step 3: verification tests and correction factor

For each verification point, give the measured HIC15:

```python
from crashmetrics.pedestrian import correction_factor

verification = {(0, 0): 760.0, (3, 4): 1180.0}
cf = correction_factor({p: (grid[p], hic) for p, hic in verification.items()})
cf.factor, cf.accepted
for test in cf.tests:
    print(test.point, test.predicted_colour, test.measured_hic, test.assessed_colour)
```

- A tested point keeps its **predicted colour** if the measured HIC15 is
  within the 10 % tolerance range of that colour; otherwise it takes the
  colour of the measured value, without tolerance (`verification_colour`):

    | Predicted colour | Measured HIC15 that confirms it |
    | --- | --- |
    | green | < 722.22 |
    | yellow | 590.91 – < 1111.11 |
    | orange | 909.09 – < 1500.00 |
    | brown | 1227.27 – < 1888.89 |
    | red | ≥ 1545.45 |

- Factor = tested points ÷ predicted points of the verification tests,
  rounded to 3 decimals.
- `accepted` is `True` inside 0.850–1.150. Outside it the prediction is
  reviewed with Euro NCAP; crashmetrics still applies the factor.

## Step 4: the head score

```python
from crashmetrics.pedestrian import headform_score

result = headform_score(
    grid,
    verification=verification,                    # optional
    blue_results={(7, 3): 900.0},                 # HIC15 per blue point
    a_pillar_results={(8, 6): [(20.0, 880.0), (30.0, 1500.0)]},  # (km/h, HIC15)
    protocol="euroncap_2026",
)
result.score, result.max_score, result.percentage
result.colour_counts, result.correction.factor
```

**A-pillar rewards (2026):** each tested A-pillar point earns the reward
of the highest speed it passes: 20 km/h with HIC15 < 1000 → 1 point,
30 km/h with HIC15 < 1700 → 2, 40 km/h with HIC15 < 1700 → 3.

**Score:**
\[
\text{score} = \min\left(\frac{\text{corrected predicted} + \text{blue} + \text{A-pillar points}}{\text{grid points}},\ 1\right) \times \text{head maximum}
\]

!!! tip "CAE stage"
    Without `verification`, no correction is applied: the result is the
    score predicted from your CAE HIC15 values alone. That is the quickest
    way to track the pedestrian head score during development.

## Verified against the protocols

The tests reproduce the worked examples of both protocols: 10.554 of 18
points (2023) and a correction factor of 1.120 (2026).

## Complete example

```python
--8<-- "examples/02_headform_grid.py"
```

Output:

```text
--8<-- "examples/expected/02_headform_grid.txt"
```
