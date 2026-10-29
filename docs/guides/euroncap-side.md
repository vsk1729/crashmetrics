# Euro NCAP side impact: AE-MDB, pole and far side

Module: `crashmetrics.side_scoring`.

The 2026 Euro NCAP side impact assessment is worth **35 points** of
Crash Protection:

| Test | Points | Occupants | Function |
| --- | --- | --- | --- |
| AE-MDB (mobile barrier) | 15 | driver WorldSID 50th (10), rear Q10 (2.5), rear Q6 (2.5) | `score_ae_mdb` |
| Pole (75°) | 10 | driver WorldSID 50th (10) | `score_pole` |
| Far side | 10 | main AE-MDB and pole cases (2 + 2), robustness (2 + 2), occupant-to-occupant (2) | `score_far_side` |

`score_side` adds them up. Together with the
[MPDB and full width](euroncap-frontal.md) scores this covers the
frontal and lateral parts of Euro NCAP adult occupant protection.

Source: [Euro NCAP Crash Protection Side Impact Protocol v1.1 (October
2025)](https://cdn.euroncap.com/cars/assets/euro_ncap_protocol_crash_protection_side_impact_v11_59fafcb51b.pdf).
Every interpretation is listed in the [protocol notes](../protocol-notes.md).

## Step 1: the near side dummies

```python
from crashmetrics.side_scoring import SideOccupant

driver = SideOccupant(
    values={
        "hic15": 412.0, "head_a3ms": 58.0,
        "chest_compression": 27.5,      # worst thorax rib, mm
        "abdomen_compression": 41.5,    # worst abdomen rib, mm
        "pubic_force": 1450.0,          # N
        # modifier inputs (optional):
        "shoulder_force": 1900.0, "chest_vc": 0.31, "abdomen_vc": 0.28,
    },
    hard_contact=False,
)
```

| Region (2.5 points each) | Criteria | HPL | LPL | Capping |
| --- | --- | --- | --- | --- |
| Head | HIC15, resultant 3 ms | 500, 72 g | 700, 80 g | 700, 80 g |
| Chest | rib compression | 28 mm | 50 mm | 50 mm (AE-MDB), 55 mm (pole) |
| Abdomen | rib compression | 47 mm | 65 mm | 65 mm |
| Pelvis | pubic symphysis force | 1.7 kN | 2.8 kN | 2.8 kN |

Child dummies (AE-MDB rear seats, head 1.25, neck 0.625, chest 0.625
points): head HIC15 500–700 and 3 ms 60–80 g, neck tension 2.4 kN (Q6)
and 2.2 kN (Q10), chest 3 ms 67 g.

- **Colour bands** as in the frontal tests: green below the HPL, red at
  or above the LPL, three equal bands between. A region scores its
  lowest criterion's band share (green 100 %, yellow 80 %, orange
  60 %, brown 40 %; pass `band_fractions=BAND_FRACTIONS_TABLE` for the
  table's 100/80/40/20 %).
- **No hard head contact**: the head is assessed on the 3 ms
  acceleration only. Give `hard_contact` from the film, or
  `values["head_peak"]` (contact assumed above 80 g).
- **Automatic WorldSID modifiers**: shoulder force ≥ 3.0 kN or chest VC
  ≥ 1.0 m/s removes the chest points; abdomen VC ≥ 1.0 m/s removes the
  abdomen points; `incorrect_airbag_deployment=True` takes 20 % of every
  region. Other modifiers: `modifiers={"head": [20.0]}`, Q dummy
  modifiers (CRS attachment −50 %) via `dummy_modifiers`.
- **Capping limits** exceeded are reported in `capping_exceeded`.

## Step 2: the AE-MDB and pole tests

```python
from crashmetrics.side_scoring import score_ae_mdb, score_pole

mdb = score_ae_mdb(driver, rear_q10=q10, rear_q6=q6, door_openings=0)
pole = score_pole(pole_driver, curtain_zone_rows_failed=0, rollover_protection=True)
```

Test modifiers are percentages of the 10-point adult load case: door
opening −5 % per door, door detachment and restraint failure −100 %;
pole only: head protection zone not covered −10 % per seat row, no
rollover sensing or curtain inflation for 6 s −20 %. Without a near side
head protection system the pole test is not run and scores zero
(`head_protection_fitted=False`).

## Step 3: far side

The far side occupant (driver, impact on the passenger side) is tested
on a sled with the AE-MDB and pole pulses. The score comes from the
**head excursion zone**: how close the head comes to the struck side.

| Line | Position |
| --- | --- |
| Green | 250 mm inboard of the struck-side seat centreline |
| Yellow | 125 mm inboard of it |
| Orange | the struck-side seat centreline |
| Red | the maximum door panel intrusion from the AE-MDB and pole tests |

```python
from crashmetrics.side_scoring import FarSideCase, far_side_zone

zone = far_side_zone(head_clearance=170.0, red_line_offset=210.0)   # "yellow"
case = FarSideCase(zone, {"chest_compression": 36.0, "upper_neck_tension": 2100.0})
```

`head_clearance` is how far (mm) the peak head excursion stays short of
the struck-side seat centreline (negative beyond it); `red_line_offset`
how far the red line lies outboard of that centreline.

| Zone | With countermeasure | Without |
| --- | --- | --- |
| Green (short of the green line) | 2 | 2 |
| Yellow | 2 | 1 |
| Orange | 1.5 | 0.5 |
| Brown (red zone, red line > 125 mm outboard) | 1 | 0 |
| Red | 0.5 | 0 |
| Capping (beyond the red line) | 0, both load cases | 0 |

A load case is **capped** (0 points) if any far side capping limit is
reached: HIC15 700, head 3 ms 80 g, upper and lower neck tension
3.74 kN, flexion 248 N m, upper neck extension 50 N m, lower 100 N m,
chest 50 mm, abdomen 65 mm. Exceeding a pelvis or lumbar limit (pubic
2.8 kN, lumbar Fy 2.0 kN, Fz 3.5 kN, Mx 120 N m) removes 25 % of the
load case.

```python
from crashmetrics.side_scoring import score_far_side

far = score_far_side(
    main_ae_mdb=case_mdb, main_pole=case_pole,
    robustness_ae_mdb=["green", "yellow", "yellow", "orange"],   # 4 cases
    robustness_pole=["yellow", "orange"],                         # 2 cases
    countermeasure=True, virtual_testing_validated=True,
    occupant_to_occupant_passed=True,
    near_side_driver_points=mdb.occupants["driver"].points + pole.occupants["driver"].points,
)
```

- **Robustness** (2 points per pulse): every robustness case must be at
  most one zone worse than its main case and not red. Nothing if the
  main case is red; without a countermeasure, only if the main case is
  green. Without validated virtual testing only the main cases count.
- **Occupant-to-occupant** (2 points): all or nothing, from the
  dual-occupancy pole test.
- **All far side points are removed** if the driver scores below 17.0
  of 20 in the AE-MDB and pole tests together, on a structural door,
  roof or sill failure, or if a far side restraint fails.

## Step 4: the total

```python
from crashmetrics.side_scoring import score_side

side = score_side(mdb, pole, far)
print(side.summary())
side.points        # out of 35
```

`flatten(side)` gives every region, band and zone as columns, for
example to compare B-pillar or airbag variants in a
[feature table](ml-features.md).

## Complete example

Two design variants: one with all far side rewards, one whose weaker
near side performance (9.5 of 20 driver points) removes all far side
points:

```python
--8<-- "examples/15_euroncap_side.py"
```

Output:

```text
--8<-- "examples/expected/15_euroncap_side.txt"
```

## Protocol documents

- [Crash Protection Side Impact Protocol v1.1, October 2025](https://cdn.euroncap.com/cars/assets/euro_ncap_protocol_crash_protection_side_impact_v11_59fafcb51b.pdf) (scoring, limits, far side): the source of this module
- [Crash Protection Frontal Impact Protocol v1.1, September 2025](https://cdn.euroncap.com/cars/assets/euro_ncap_protocol_crash_protection_frontal_impact_v11_9659fff24e.pdf)
- [CP 005 Data Acquisition and Injury Calculation v1.4.1, April 2026](https://cdn.euroncap.com/cars/assets/CP_005_Data_Acquisition_and_Injury_Calculation_v1_4_1_015875ff46.pdf)
- [Far Side Test and Assessment Protocol v2.4.1 (2023)](https://cdn.euroncap.com/cars/assets/euro_ncap_far_side_test_and_assessment_protocol_v241_b87be7d984.pdf): the earlier far side protocol, used to read the zone table
- [Rescue and Extrication Protocol v1.1, September 2025](https://cdn.euroncap.com/cars/assets/euro_ncap_protocol_post_crash_v11_83a7d345b4.pdf)
