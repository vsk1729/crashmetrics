# Pedestrian legforms and the VRU score (Euro NCAP)

Module: `crashmetrics.pedestrian` (`apli_point_score`, `apli_score`,
`upper_legform_alpha`, `upper_legform_energy`, `upper_legform_score`,
`vru_score`, `leg_colour`).

| Region | Impactor | 2026 maximum | 2023 maximum |
| --- | --- | --- | --- |
| Pelvis | Upper legform (WAD 775 line, `U` points) | 2.5 | 4.5 |
| Femur | aPLI (bumper, `L` points) | 2.5 | 4.5 |
| Knee / tibia | aPLI | 5 | 9 |
| Head | Headform ([guide](pedestrian-headform.md)) | 10 | 18 |
| **Total VRU** | | **20** | **36** |

## Limits

| Criterion | Higher limit (score 1) | Lower limit (score 0) |
| --- | --- | --- |
| Upper legform sum of forces | 5.0 kN | 6.0 kN |
| aPLI femur bending moment | 390 N m | 440 N m |
| aPLI tibia bending moment | 275 N m | 320 N m |
| aPLI MCL elongation | 27 mm | 32 mm |

Each test point scores 0–1, linear between the limits, rounded to 3
decimals as in the protocols' worked examples (`round_to=None` keeps the
exact value).

## Step 1: score one aPLI test

```python
from crashmetrics.pedestrian import apli_point_score

one = apli_point_score(
    femur_moment=[410.0, 395.0, 372.0],        # peaks of the femur gauges, N m
    tibia_moment=[290.0, 301.0, 260.0, 240.0], # peaks of the tibia gauges, N m
    mcl_elongation=28.5,                       # mm
)
one.femur, one.knee_tibia      # knee/tibia = lower of tibia and MCL scores
```

You can pass single peaks, several gauge peaks, or full time histories;
the worst (largest magnitude) value is used.

## Step 2: score the aPLI grid

Give every grid point and the results of the tested points. Untested
points are filled automatically:

```python
from crashmetrics.pedestrian import apli_score

grid_l = ["L+5", "L+4", "L+3", "L+2", "L+1", "L0", "L-1", "L-2", "L-3", "L-4", "L-5"]
apli = apli_score(grid_l, {
    "L0": (370.0, 250.0, 22.0),          # (femur N m, tibia N m, MCL mm)
    "L+2": (400.0, 257.0, 20.0),
    "L+4": (438.0, 300.0, 29.0),
}, protocol="euroncap_2026")
apli.femur.points, apli.knee_tibia.points
apli.knee_tibia.scores["L+3"], apli.knee_tibia.sources["L+3"]
```

How untested points are filled, in order:

1. **Symmetry**: the result of the mirror point (`L-2` takes `L+2`),
   unless the point is listed in `asymmetric_points`.
2. **Worst adjacent**: the lower score of the neighbouring points that
   have a tested or mirrored result.

`sources` tells you where each score came from, e.g.
`"symmetry of 'L+2'"` or `"worst adjacent 'L+4'"`. Femur and knee/tibia
are filled separately.

Region points = sum of grid-point scores / number of grid points ×
region maximum.

## Step 3: does the upper legform need a test?

The impact energy depends on the bonnet leading edge angle α:

\[
E_n = \tfrac{1}{2}\,(7.4\ \mathrm{kg})\,\bigl(11.11\ \mathrm{m/s}\cdot\cos(1.2\,\alpha)\bigr)^2,
\qquad v_t = \sqrt{2E_n / 10.5\ \mathrm{kg}}
\]

No test is required below 160 J.

```python
from crashmetrics.pedestrian import upper_legform_alpha, upper_legform_energy

# Side-view points, x rearward and z up (mm): the internal bumper
# reference line and WAD 930 at the grid point's lateral position.
alpha = upper_legform_alpha(ibrl=(0.0, 650.0), wad930=(120.0, 820.0))
e = upper_legform_energy(alpha)
e.energy, e.test_velocity, e.test_required
```

## Step 4: score the upper legform grid

```python
from crashmetrics.pedestrian import upper_legform_score

grid_u = ["U+4", "U+3", "U+2", "U+1", "U0", "U-1", "U-2", "U-3", "U-4"]
pelvis = upper_legform_score(grid_u, {"U0": 5260.0, "U+2": 6800.0, "U+4": 4890.0})
pelvis.points
```

Pass `energies={point: J}` for every grid point to apply the energy
rules: untested points below 160 J score `not_required_score` (1.0 by
default) and a result is only shared between points whose energies
differ by at most 10 %.

## Step 5: total VRU score

```python
from crashmetrics.pedestrian import vru_score

total = vru_score(head=head_result, pelvis=pelvis, femur=apli.femur,
                  knee_tibia=apli.knee_tibia, protocol="euroncap_2026")
total.total, total.max_total, total.percentage
```

Each argument can be a result object or a number of points.

## Colours

`leg_colour(score)`: green 1.000, yellow ≥ 0.750, orange ≥ 0.500,
brown ≥ 0.001, red 0.000.

## Verified against the protocols

The tests reproduce the protocols' worked examples: 2023 upper legform
1.370 / 4.5, femur 1.898 / 4.5, knee/tibia 3.908 / 9; 2026 upper
legform 0.761 / 2.5.

## Complete example

```python
--8<-- "examples/03_legform_vru.py"
```

Output:

```text
--8<-- "examples/expected/03_legform_vru.txt"
```
