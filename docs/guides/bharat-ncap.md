# Bharat NCAP star rating (AIS-197)

Modules: `crashmetrics.bncap` (scoring), `crashmetrics.bncap_channels`
(from dummy channels), `crashmetrics.bncap_report` (scorecard) and
`crashmetrics.side` for the ES-2 criteria.

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

## Which edition: years of validity

Everything on this page is the **2023 edition** of Bharat NCAP: AIS-197
of September 2023, for ratings from **1 October 2023 to 30 September
2027** (four years, AIS-197 Section 1.0). Bharat NCAP 2.0 (AIS-197
Revision 1) replaces it for ratings from October 2027 with a 100-point
rating in five pillars and new tests; it is not implemented yet.

```python
import datetime as dt
from crashmetrics.bncap import PROTOCOL, VALID_FROM, VALID_UNTIL, edition_for_date

edition_for_date(dt.date(2026, 3, 15))   # 2023
edition_for_date(dt.date(2027, 11, 1))   # ValueError: Bharat NCAP 2.0 ... not implemented yet
PROTOCOL                                 # 'Bharat NCAP AIS-197 (2023 edition, ratings 1 Oct 2023 - 30 Sep 2027)'
```

- Every scoring function takes `edition=2023` (the default);
  `edition=2027` raises an error instead of scoring a new car by the
  old rules.
- Every result (`TestResult`, `AopRating`, `CopScore`, `BncapRating`,
  `Scorecard`) has a `protocol` field, so a stored result says which
  rules produced it. `aop_rating` and `bncap_rating` refuse to combine
  results scored under different protocols.

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

Give the modifiers **by name** with `frontal_modifiers` and
`side_modifiers`; they return the points per region for `modifiers=`,
so no penalty lands on the wrong region:

```python
from crashmetrics.bncap import frontal_modifiers, side_modifiers

mods = frontal_modifiers(steering_column=(40.0, 30.0, 10.0),   # rearward, upward, lateral mm
                         a_pillar=120.0, shoulder_belt_load=5400.0,
                         knee_concentrated_load=(False, True))
# {'chest': 0.4, 'knee_right': 1.0}
side_mods = side_modifiers(backplate_fy=1600.0, t12_fy=1700.0, t12_mx=120.0)
```

| Modifier | Argument | Region | Penalty |
| --- | --- | --- | --- |
| Steering column displacement | `steering_column=(r, u, l)` | head | 0–1 (90–110 % of 100 / 80 / 100 mm) |
| Unstable airbag contact | `unstable_airbag_contact=True` | head | 1 |
| Hazardous airbag deployment | `hazardous_airbag_deployment=True` | head | 1 |
| Incorrect airbag deployment | `incorrect_airbag_deployment="head"`, or several: `("knee_left", "knee_right")`, `("head", "chest")` | each region the airbag protects | 1 each |
| A-pillar rearward displacement | `a_pillar=` | chest | 0–2 (100–200 mm) |
| Steering wheel contact | `steering_wheel_contact=True` | chest | 1 |
| Compartment integrity lost | `compartment_integrity_lost=True` | chest | 1 |
| Shoulder belt load | `shoulder_belt_load=` (N) | chest | 2 above 6 kN |
| Knee variable contact / concentrated load | `knee_variable_contact=(l, r)`, `knee_concentrated_load=(l, r)` | knee (per leg) | 1 each |
| Driver knee variable contact by area (no concentrated load on either knee) | `knee_variable_contact_areas=((l_column, l_facia), (r_column, r_facia))` | knee (per leg) | 0.5 per area |
| Pedal upward displacement | `pedal_upward=(l, r)` | lower leg | 0–1 (72–88 mm) |
| Blocked pedal rearward | `blocked_pedal_rearward=` | foot | 0–1 (50–175 mm) |
| Footwell rupture | `footwell_rupture=True` | foot | 1 |
| Backplate load (side) | `side_modifiers(backplate_fy=)` | chest | 0–2 (1–4 kN) |
| T12 load (side) | `side_modifiers(t12_fy=, t12_mx=)` | chest | 0–2 (Fy 1.5–2 kN or Mx 150–200 N m) |
| Incorrect airbag deployment (side) | `side_modifiers(incorrect_airbag_deployment=("head", "chest"))` | each region the airbag protects | 1 each |
| Hazardous airbag seen in the pole test | `score_side(other_test_modifiers=1)` | side test | 1 |
| Door opening (per door), fuel leakage | `score_frontal(door_openings=, fuel_leakage=)` | whole test | 1 |

Steering, pedal and footwell modifiers and the knee area split are
driver-only: `frontal_modifiers(driver=False, ...)` refuses them. The
split into a column area (75 mm either side of the steering column
centreline) and the rest of the facia applies only when the concentrated
loading modifier is applied to neither driver knee (Annexure VII
2.1.7.2). The sliding
helpers (`steering_column_modifier`, `a_pillar_modifier`, ...) remain
available for single values.

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

## Shortcut: straight from dummy channels

`crashmetrics.bncap_channels` does steps 1 and 2 in one call from the
dummy time histories, from a test or a simulation. It filters each
channel with its CFC (unless `filtered=True`), calculates every
criterion and returns the occupant:

```python
from crashmetrics.bncap_channels import (
    channels_from_isomme, frontal_occupant_from_channels,
    pole_test_from_channels, side_occupant_from_channels,
)
from crashmetrics.isomme import read_isomme

test = read_isomme("tests/ODB_001")
driver = frontal_occupant_from_channels(
    channels_from_isomme(test, position="1"), filtered=True,
    pedal_rearward=62.0, modifiers=mods)
passenger = frontal_occupant_from_channels(
    channels_from_isomme(test, position="3"), filtered=True, driver=False)

side_occupant = side_occupant_from_channels(es2_channels)       # {name: (t, values)}
pole_ok = pole_test_from_channels(es2_pole_channels, head_contact=False)
```

| Function | Dummy | Calculates |
| --- | --- | --- |
| `frontal_occupant_from_channels` | Hybrid III 50th | HIC15 and 3 ms of the resultant head acceleration, hard contact (peak > 80 g unless `head_contact=` is given), neck shear and tension histories, extension moment at the occipital condyle, chest compression and VC, femur histories, knee slider, worst Tibia Index and tibia compression of the upper and lower locations |
| `side_occupant_from_channels` | ES-2 | HIC15, 3 ms, worst rib deflection and VC, total abdominal force, pubic force; backplate and T12 modifiers if those channels are given |
| `pole_test_from_channels` | ES-2 | The pole test pass / fail |
| `channels_from_isomme` | any | The named channels of one seating position from an ISO-MME test, in N, N m, mm and g, filtered with the protocol CFC |

The channel names, units and CFCs are in `FRONTAL_CHANNELS` and
`SIDE_CHANNELS`; the Hybrid III ISO-MME codes (`HYBRID3_ISOMME`) follow
Euro NCAP CP 005. For the ES-2, pass your laboratory's codes as
`patterns=` with `table=SIDE_CHANNELS`. From LS-DYNA, read the dummy
outputs (for example with `crashmetrics.lsdyna_ascii`), convert them to
these units, resample them to a uniform step and pass them by name.

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

## Step 5: the scorecard

`crashmetrics.bncap_report.scorecard` lays the result out like a rating
sheet, for design reviews:

```python
from crashmetrics.bncap_report import scorecard

card = scorecard(frontal, side)          # or scorecard(frontal, side, rating=full.aop)
print(card.markdown())                   # tables per test, losses, next star
card.points_to_next_star                 # e.g. 3.715 more points for 5 stars
card.losses[0]                           # largest loss: test, group, occupant, region, cause
write_csv(card.rows(), "scorecard.csv")  # one row per criterion (crashmetrics.features)
```

- Every body region with its points, colour, governing criterion (in
  bold) and the modifiers it lost.
- Every criterion with its value, unit, higher and lower performance
  limit and points (force–duration criteria show the exceedance level
  where the score is lowest).
- **Where the points are lost**: per scored group, the occupant and
  region that set it and whether a criterion or the modifiers cost
  most, largest first.
- **Next star**: the points the next star threshold needs (left out of
  the text when a rule such as capping limits the rating).

## Complete example

```python
--8<-- "examples/07_bharat_ncap.py"
```

Output:

```text
--8<-- "examples/expected/07_bharat_ncap.txt"
```

From unfiltered dummy channels to the scorecard, with named modifiers:

```python
--8<-- "examples/22_bncap_channels_scorecard.py"
```

Output:

```text
--8<-- "examples/expected/22_bncap_channels_scorecard.txt"
```
