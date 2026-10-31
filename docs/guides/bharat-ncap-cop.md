# Bharat NCAP child occupant protection and the complete rating

Modules: `crashmetrics.bncap_cop` (child occupant protection) and
`crashmetrics.bncap_rating` (safety assist qualifiers, complete rating).

This completes Bharat NCAP end to end. The [adult occupant
guide](bharat-ncap.md) scores the frontal and side tests (32 points);
this page adds the **child occupant protection (COP, 49 points)** and
the **safety assist technology qualifiers** that cap the adult stars.

Source: AIS-197 Annexure V (child occupant protection), Annexure VI
(safety assist technologies), Annexure VIII (scoring), Table 2A/2B.

Edition: the 2023 edition of AIS-197, for ratings from 1 October 2023
to 30 September 2027. `score_cop` and `bncap_rating` take
`edition=2023`, their results carry a `protocol` field, and the rating
summary prints it; see [Which edition](bharat-ncap.md#which-edition-years-of-validity).
Every number on this page and in the code was checked against the
standard; interpretations are in the [protocol notes](../protocol-notes.md).

## The child occupant score

| Area | Points | Function |
| --- | --- | --- |
| Dynamic: ODB frontal, Q1.5 and Q3 (head 4, neck 2, chest 2 each) | 16 | `score_child_frontal` |
| Dynamic: MDB side, Q1.5 and Q3 (head 4 each) | 8 | `score_child_side` |
| CRS installation: installation list 10, manufacturer recommended 2 | 12 | `score_crs_installation` |
| Vehicle based assessments | 13 | `score_vehicle_based` |
| **Total** | **49** | `score_cop` |

Stars (Table 2B, Annexure VIII 4.3): 41 / 35 / 27 / 18 / 9 points for
5 / 4 / 3 / 2 / 1 stars. Vehicles without rear seats (two-seaters) have
no dynamic assessment and score out of 22 (installation 12, vehicle
based 10) with 20 / 17 / 13 / 9 / 5.

## Step 1: dynamic assessment

```python
from crashmetrics.bncap_cop import score_child_frontal, score_child_side, score_cop_dynamic

q15 = score_child_frontal("q1.5", "rearward", head_a3ms=58.0, head_peak=66.0,
                          neck_tension=1550.0, chest_a3ms=46.0)
q3 = score_child_frontal("q3", "forward", head_a3ms=91.0, head_peak=98.0,
                         neck_tension=2050.0, chest_a3ms=53.0, head_excursion=505.0)
side = [score_child_side("q1.5", head_a3ms=55.0, head_peak=61.0),
        score_child_side("q3", head_a3ms=78.0, head_peak=97.0)]
dynamic = score_cop_dynamic([q15, q3], side)
```

**Frontal** (Annexure V 4.2.2), sliding scales between the limits:

| Criterion | Q1.5 | Q3 | Points |
| --- | --- | --- | --- |
| Head 3 ms (only with head contact with the CRS) | 72 → 88 g | 87 → 100 g | 4 |
| Head excursion (forward facing, from the Cr point) | 549 → 550 mm | 549 → 550 mm | 4 |
| Head exposure (rearward facing) | contained, no load on the head top | | 4 or 0 |
| Upper neck Fz tension | 1.70 → 2.62 kN | 1.70 → 2.62 kN | 2 |
| Chest resultant 3 ms | 41 → 55 g | 50 → 66 g | 2 |

The head scores the worst of contact, excursion (forward facing) or
exposure (rearward facing). Head contact with the CRS is direct
evidence or a peak head acceleration of at least 80 g (Q1.5) or 96 g
(Q3); without contact the head contact score is 4. An excursion that
cannot be estimated is deemed 549 mm or less.

**Side** (4.2.3): 4 points without head contact with the CRS; with
contact 72 → 88 g (head 3 ms) for both dummies; zero if the head is not
contained in the CRS shell.

**Penalties**:

| Event | Effect | Clause |
| --- | --- | --- |
| Dummy ejected, or CRS released from a vehicle interface | 0 dynamic points for that dummy (frontal and side): `ejected=["q3"]` | 4.1 |
| Q1.5 in a forward facing CRS | −6 points (head 4, neck 2) | 4.1.1 |
| Head contact with the vehicle | no head points in that test: `vehicle_head_contact=True` | 4.2.1 |
| No (appropriate) CRS recommendation | no dynamic points: `recommendation_valid=False` | 2.1.4 |

## Step 2: CRS installation

```python
from crashmetrics.bncap_cop import CrsInstallation, score_crs_installation

installation = score_crs_installation(
    installation_list=[CrsInstallation("Group 0+ belted", eligible_positions=2, failed=0),
                       CrsInstallation("Group I FWF belted", 3, 1), ...],
    recommended=[CrsInstallation("OEM seat for Q1.5", 2, 0),
                 CrsInstallation("OEM seat for Q3", 2, 1)],
)
```

Per CRS, **CRSi = (Ti − Fi) / Ti** (eligible positions minus failed
installations, over eligible positions; a CRS with no eligible position
scores zero). The installation list average gives up to 10 points, the
two recommended seats up to 2 (no recommendation: maximum 10). If the
group coverage requirements of 3.2.9 are not met, the score is halved
(`coverage_requirements_met=False`). This reproduces AIS-197's own
worked example (Table 1 of 3.7: 7.143 + 2.000 = 9.143); the test suite
checks it.

## Step 3: vehicle based assessments

```python
from crashmetrics.bncap_cop import VehicleBasedAssessment, score_vehicle_based

vehicle_based = score_vehicle_based(VehicleBasedAssessment(
    gabarit_all_seats=True, gabarit_handbook_and_airbag=True,
    isofix_un=True, isofix_marked=True, two_largest_isofix=True, airbag="manual"))
```

| Item | Points | Clause |
| --- | --- | --- |
| Gabarit on all passenger seats (a–e), plus handbook and airbag requirements (f–h) | 1 + 1 | 5.2 |
| Three seating positions for installation-list CRS at once; for i-Size CRS at once | 1 + 1 | 5.3 |
| ISOFIX usability: A (UN ISOFIX) precondition, B (marking) 1, C (i-Size ready) 1 | 2 | 5.4 |
| Two positions for the largest rearward facing ISOFIX CRS | 1 | 5.5 |
| Passenger airbag: label not OK 0, label only 1, manual disabling 3, automatic 4 | 4 | 5.6 |
| Integrated CRS as standard; plus a group I–III integrated CRS | 1 + 1 | 5.7 |
| No compliant 3-point belt on any passenger seat | all 0 | 5.1 |

Two-seaters (`two_seater=True`): Gabarit 1, no simultaneous use, and 0
points if the passenger airbag cannot be deactivated (6.1.4).

## Step 4: the child score and stars

```python
from crashmetrics.bncap_cop import score_cop

cop = score_cop(installation, vehicle_based, dynamic)
cop.points, cop.stars
print(cop.summary())
```

## Step 5: safety assist qualifiers and the complete rating

Safety assist technologies are not scored: they decide the highest
**adult** star rating the car can get (Annexure VI). The child stars
are not affected.

| Requirement | 1–2 stars | 3 stars | 4 stars | 5 stars |
| --- | --- | --- | --- | --- |
| Pedestrian protection (AIS-100) and seat belt reminders (AIS-145), standard | ✓ | ✓ | ✓ | ✓ |
| ESC fitted, demonstrated (UN GTR 8 / UN R140 / AIS-133), 100 % within 2 years | | from Oct 2025 | ✓ | ✓ |
| Side head protection with a passed pole test | | optional in a variant | fitted, share below | fitted, share below |

Minimum share of production with side head protection as standard
(`side_head_fitment_required`):

| Publication (Oct–Sep) | 2023/24 | 2024/25 | 2025/26 | 2026/27 | from Oct 2027 | from Oct 2030 |
| --- | --- | --- | --- | --- | --- | --- |
| 5 stars | 30 % | 50 % | 70 % | 90 % | 100 % | 100 % |
| 4 stars | optional in a variant | optional in a variant | 30 % | 50 % | (50 %) | 100 % |

```python
import datetime as dt
from crashmetrics.bncap_rating import SafetyAssist, bncap_rating

sat = SafetyAssist(
    publication=dt.date(2026, 11, 15),
    pedestrian_ais100=True, seat_belt_reminder_ais145=True,
    esc_fitted=True, esc_demonstrated=True, esc_full_fitment_commitment=True,
    side_head_protection_fitted=True, pole_test_passed=True,
    side_head_standard_fitment=0.60,
)
rating = bncap_rating(frontal, side, cop, sat)
print(rating.summary())       # adult capped at 4 stars: 90 % needed for 5
```

The summary lists what is missing for the next star level.

## Complete example

A compact SUV published in November 2026, rated twice: with side head
protection standard in 95 % of production (5 adult stars) and in 60 %
(capped at 4):

```python
--8<-- "examples/16_bharat_ncap_cop_rating.py"
```

Output:

```text
--8<-- "examples/expected/16_bharat_ncap_cop_rating.txt"
```
