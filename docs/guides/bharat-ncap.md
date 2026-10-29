# Bharat NCAP star rating (AIS-197)

Module: `crashmetrics.bncap` (and `crashmetrics.side` for the ES-2
criteria).

AIS-197 rates cars sold in India in three areas: Adult Occupant
Protection (AOP, 32 points), Child Occupant Protection (COP, 49 points)
and Safety Assist Technologies (qualifiers). This page scores the adult
tests; [child occupant protection and the complete rating](bharat-ncap-cop.md)
covers the child score and the safety assist qualifiers.

| Test | Speed | Dummies | Points |
| --- | --- | --- | --- |
| ODB frontal | 64 km/h | Hybrid III 50th driver and passenger | 16 |
| MDB side | 50 km/h | ES-2 driver | 16 |
| Pole side | 29 km/h | ES-2 driver | pass / fail (3+ stars) |

## How Bharat NCAP scores a region

1. Each criterion scores **0–4 points**, linear between its higher
   performance limit (4 points) and lower performance limit (0).
2. **Neck shear, neck tension and femur compression** are scored from
   their cumulative exceedance curves, between a "higher" and a "lower"
   force–duration curve; the lowest point on the curve gives the score.
3. A region takes its **worst criterion**, then point **modifiers** are
   subtracted (not below 0). Region scores are rounded to 3 decimals.
4. **Frontal:** regions are grouped into head & neck, chest, knee/femur/
   pelvis and leg & foot; each group takes the **worst of driver and
   passenger** (4 × 4 = 16 points).
5. **Side:** head, chest, abdomen and pelvis, 4 points each.

### Limits

| Frontal (Hybrid III 50th) | Higher (4 pts) | Lower (0 pts) |
| --- | --- | --- |
| HIC15 (hard contact only) | 500 | 700 |
| Head 3 ms | 72 g | 88 g |
| Neck shear | 1.9 kN @ 0 ms, 1.2 kN @ 25–35 ms, 1.1 kN @ 45 ms | 3.1 kN @ 0 ms, 1.5 kN @ 25–35 ms, 1.1 kN @ 45 ms |
| Neck tension | 2.7 kN @ 0 ms, 2.3 kN @ 35 ms, 1.1 kN @ 60 ms | 3.3 kN @ 0 ms, 2.9 kN @ 35 ms, 1.1 kN @ 60 ms |
| Neck extension | 42 N m | 57 N m |
| Chest compression | 22 mm | 42 mm |
| Viscous criterion | 0.5 m/s | 1.0 m/s |
| Femur compression | 3.8 kN | 9.07 kN @ 0 ms, 7.56 kN @ ≥ 10 ms |
| Knee slider | 6 mm | 15 mm |
| Tibia Index | 0.4 | 1.3 |
| Tibia compression | 2 kN | 8 kN |
| Pedal rearward (driver) | 100 mm | 200 mm |

| Side (ES-2) | Higher (4 pts) | Lower (0 pts) |
| --- | --- | --- |
| HIC15 | 500 | 700 |
| Head 3 ms | 72 g | 88 g |
| Rib deflection (worst rib) | 22 mm | 42 mm |
| Rib VC | 0.32 m/s | 1.0 m/s |
| Total abdominal force | 1.0 kN | 2.5 kN |
| Pubic symphysis force | 3.0 kN | 6.0 kN |

## Step 1: ES-2 criteria from signals (side test)

```python
from crashmetrics.side import (
    es2_abdominal_force, es2_rib_deflection, es2_rib_vc, pubic_symphysis_force)

rib = es2_rib_deflection(t, upper, middle, lower)     # worst rib, mm
vc = es2_rib_vc(t, upper, middle, lower)              # VC = V x D / 0.140 m
abdomen = es2_abdominal_force(t, front, middle, rear) # peak of the sum, N
pubic = pubic_symphysis_force(t, fy)                  # peak |Fy|, N
```

## Step 2: the frontal occupants

Neck shear, neck tension and femur force are **time histories**
`(t, signal)` because they are scored from exceedance curves; the other
values are peaks. Legs are `(left, right)`.

```python
from crashmetrics.bncap import FrontalOccupant, a_pillar_modifier, steering_column_modifier

driver = FrontalOccupant(
    hic15=560.0, head_a3ms=62.0,                     # used with hard contact
    neck_shear=(t, fx), neck_tension=(t, fz),        # N
    neck_extension=24.0,                             # N m at the occipital condyle
    chest_compression=28.0, viscous_criterion=0.42,
    femur=((t, femur_l), (t, femur_r)),              # compression negative
    knee_displacement=(4.0, 6.5),
    tibia_index=(0.62, 0.48),                        # worst of upper / lower
    tibia_force=(2600.0, 2300.0),                    # peak compression, N
    pedal_rearward=120.0,                            # driver only
    modifiers={"head": steering_column_modifier(rearward=95.0),
               "chest": a_pillar_modifier(130.0)},   # points to subtract
)
```

Without hard head contact (peak ≤ 80 g), pass `hard_contact=False`: the
head scores 4 points.

### Modifiers (Annexure VII)

Sliding modifiers have helpers; fixed ones are passed as points:

| Modifier | Region | Penalty | Helper |
| --- | --- | --- | --- |
| Steering column displacement | head | 0–1 (90–110 % of 100 / 80 / 100 mm) | `steering_column_modifier` |
| A-pillar rearward displacement | chest | 0–2 (100–200 mm) | `a_pillar_modifier` |
| Pedal upward displacement | lower leg | 0–1 (72–88 mm) | `pedal_upward_modifier` |
| Blocked pedal rearward | foot | 0–1 (50–175 mm) | `pedal_blocking_modifier` |
| Backplate load (side) | chest | 0–2 (1–4 kN) | `backplate_modifier` |
| T12 load (side) | chest | 0–2 (Fy 1.5–2 kN or Mx 150–200 N m) | `t12_modifier` |
| Unstable / hazardous / incorrect airbag | head (or region) | 1 | |
| Steering wheel contact, compartment integrity | chest | 1 | |
| Shoulder belt load > 6 kN | chest | 2 | |
| Knee variable contact / concentrated load | knee (per leg) | 1 | |
| Footwell rupture | foot | 1 | |
| Door opening (per door), fuel leakage | whole test | 1 | `door_openings=`, `fuel_leakage=` |

## Step 3: score the tests

```python
from crashmetrics.bncap import SideOccupant, backplate_modifier, score_frontal, score_side

frontal = score_frontal(driver, passenger, door_openings=0, fuel_leakage=False)
frontal.points, frontal.groups                        # 0-16 and the four groups
frontal.regions["driver"]["neck"].governing           # e.g. 'neck_tension'

side = score_side(SideOccupant(
    hic15=310.0, head_a3ms=48.0, rib_deflection=rib.value, rib_vc=vc.value,
    abdominal_force=abdomen.value, pubic_force=pubic.value,
    modifiers={"chest": backplate_modifier(1600.0)},
))
```

## Step 4: pole test and the star rating

```python
from crashmetrics.bncap import aop_rating, cop_stars, pole_test_passed

pole_ok = pole_test_passed(hic15=420.0, head_peak=61.0, head_contact=False,
                           rib_deflection=31.0, rib_vc=0.55,
                           abdominal_force=1700.0, pubic_force=3900.0)
rating = aop_rating(frontal, side, max_stars_allowed=5)
rating.stars, rating.points, rating.reasons
cop_stars(38.5)                                       # child occupant points -> stars
```

`aop_rating` applies AIS-197's rules in order:

| Rule | Effect |
| --- | --- |
| Frontal + side points ≥ 27 / 22 / 16 / 10 / 4 | 5 / 4 / 3 / 2 / 1 stars |
| A capping limit exceeded (head, neck, chest; side: all four regions) | 0 stars |
| A critical region at 0 points (red) | at most 1 star |
| Front and side differ by more than 35 % (unless both > 8.2 and total > 22) | one star less |
| Safety assist qualifiers (ESC, side head protection + pole test, pedestrian, SBR) | `max_stars_allowed`; computed from the fitment by `bncap_rating.safety_assist_max_stars` ([guide](bharat-ncap-cop.md)) |

`rating.reasons` explains any reduction.

## Complete example

```python
--8<-- "examples/07_bharat_ncap.py"
```

Output:

```text
--8<-- "examples/expected/07_bharat_ncap.txt"
```
