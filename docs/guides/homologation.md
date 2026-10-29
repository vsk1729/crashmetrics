# Homologation compliance (UN R94, R95, R135, electrical safety)

Module: `crashmetrics.homologation`.

Type approval in Europe and India uses the same UN Regulations; India's
AIS standards follow them:

| Test | UN Regulation | India | Dummy | Function |
| --- | --- | --- | --- | --- |
| Frontal offset, 56 km/h, 40 % deformable barrier | R94 (05 series) | AIS-098 | Hybrid III 50th, both front seats | `check_r94_occupant`, `check_r94_vehicle` |
| Side, 50 km/h mobile deformable barrier | R95 | AIS-099 | ES-2 | `check_r95_occupant`, `check_r95_vehicle` |
| Side pole, 32 km/h at 75° | R135 (01 series) | | WorldSID 50th | `check_r135_occupant`, `check_r135_vehicle` |
| Post-crash electrical safety | R94 / R137 5.2.8, R95 5.3.7 | AIS-098 / AIS-099 (EV) | | `check_electrical_safety` |

!!! warning "Use the series that applies to your approval"
    The limits are those of the series named above, taken from the
    official UNECE texts (see [Protocol notes](../protocol-notes.md)).
    AIS revisions can lag or differ from the UN series; check the
    revision in force. The checks are an engineering aid: the approval
    authority's test report is what counts.

## Step 1: compute the criteria

Each check takes the values the regulation limits. Most come straight
from crashmetrics functions:

| Requirement | How |
| --- | --- |
| HPC (R94: intervals up to 36 ms) | `calculate_hic(t, a, window_ms=36.0).value` |
| Head 3 ms (cumulative) | `clip_3ms(t, a)` |
| Neck tension and shear (R94 Figures 1 and 2) | pass `(t, fz)` and `(t, fx)`, or a `neck_force_criterion` result |
| Femur force criterion (R94 Figure 3) | pass `(t, fz)` per femur, or a `femur_force_criterion` result |
| ThCC, V*C | `chest_deflection`, `viscous_criterion` |
| Tibia index, tibia compression, knee slider | `tibia_index`, `tibia_compression`, `knee_slider_displacement` |
| Steering wheel residual displacement | `intrusion(hub, reference, direction=...)` static values |
| R135 lower spine (75 g except for at most 3 ms in total) | pass `(t, a)`; the cumulative 3 ms value is computed |

## Step 2: check the occupants and the vehicle

```python
from crashmetrics.homologation import check_r94_occupant, check_r94_vehicle, combine

driver = check_r94_occupant(
    hpc=627.5, head_a3ms=61.7,
    neck_tension=(t, fz), neck_shear=(t, fx), neck_extension=24.0,
    thcc=34.2, vc=0.38,
    femur_left=(t, fz_left), femur_right=(t, fz_right),
    tibia_compression=2900.0, tibia_index=0.66, knee_slider=3.1,
    position="driver",
)
vehicle = check_r94_vehicle(steering_upward=28.0, steering_rearward=46.0,
                            door_opened=False, doors_unlocked_after=True,
                            doors_open_without_tools=True, fuel_leakage_rate=0.0)
result = combine("UN R94 / AIS-098", driver, passenger, vehicle)
print(result.summary())
```

- **No head contact**: pass `head_contact=False`. R94 (Annex 4, 1.1) and
  R95 then treat the HPC requirement as satisfied.
- **Yes/no requirements** (doors, egress, REESS retention, fire) take
  `True`/`False` as observed.
- Requirements you do not give are **not assessed**: they never count
  as passed.

## Step 3: read the result

```python
result.passed        # every assessed requirement passed
result.complete      # every requirement was assessed
result.failures      # ['passenger: thcc']
result.worst         # requirement with the highest utilisation
result.not_assessed  # ['vehicle: fuel_leakage_rate']
result.requirements["passenger: thcc"]   # value, limit, utilisation, clause
```

Each requirement carries its clause, so a failure points straight to
the paragraph. **Utilisation** (value / limit) shows the margin: a
design at 95 % passes but has little reserve for test scatter. For
force-duration curves (neck, femur) it is the largest ratio of the
exceedance curve to the limit curve.

`flatten(result)` turns the result into columns for a DOE or
[feature table](ml-features.md), for example to track the worst
utilisation across design variants.

## Post-crash electrical safety

For electric and hybrid vehicles every high-voltage bus must meet at
least one of four criteria after the crash (R94 and R137 5.2.8):

| Criterion | Requirement |
| --- | --- |
| Absence of high voltage | ≤ 60 V DC or ≤ 30 V AC within 60 s after the impact |
| Low electrical energy | Total energy and each Y-capacitor energy below 0.2 J |
| Physical protection | IPXXB, and exposed conductive parts below 0.1 Ω to the electrical chassis |
| Isolation resistance | ≥ 100 Ω/V of working voltage (DC), ≥ 500 Ω/V (AC); conductively connected DC and AC: 500 Ω/V, or 100 Ω/V if the AC part is protected |

```python
from crashmetrics.homologation import HVBus, check_electrical_safety

check_electrical_safety(
    buses=[
        HVBus("traction battery DC", "DC", working_voltage=355.0, voltage=352.0,
              isolation_resistance=92_000.0),
        HVBus("drive inverter AC", "AC", working_voltage=355.0, voltage=4.0),
    ],
    electrolyte="non-aqueous", electrolyte_leaked_anywhere=False,
    reess_retained=True, reess_entered_cabin=False, fire_or_explosion=False,
)
```

It also checks electrolyte leakage (aqueous: none into the passenger
compartment, at most 7 % and 5.0 l outside; non-aqueous: no liquid
leakage), REESS retention and no fire or explosion within 60 minutes.
The report says which criterion protected each bus.

Earlier series of some regulations allowed 2.0 J and a 30-minute
electrolyte period: pass
`limits=ElectricalLimits(max_energy=2.0, electrolyte_minutes=30)`.

## Complete example

An electric car through R94 / AIS-098 (the passenger's chest fails at
43.1 mm), electrical safety, R95 / AIS-099, and R135 (pubic force fails
at 3.51 kN):

```python
--8<-- "examples/14_homologation.py"
```

Output:

```text
--8<-- "examples/expected/14_homologation.txt"
```

## Not covered yet

- **UN R137** (full-width frontal, Hybrid III 50th and 5th female): its
  electrical safety requirements are the same as R94's and can be
  checked now; the dummy limits will be added once checked against the
  regulation text.
- Annex procedures (barrier, dummy positioning, test speeds) are the
  test lab's domain; these checks assess the results.
