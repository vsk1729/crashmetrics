# Euro NCAP sled and virtual testing (VTC)

Modules: `crashmetrics.virtual_testing`, `crashmetrics.isomme`.

From 2026, Euro NCAP's frontal assessment includes **sled and virtual
testing**: 10 points (driver 5, front passenger 5) for how well the
restraint system protects different occupant sizes at different crash
severities. The vehicle manufacturer simulates a matrix of load cases;
Euro NCAP sled-tests two of them to validate the simulation model, and
the simulations of the others are scored if the model is validated.

Sources: [Crash Protection Virtual Testing Protocol v1.0.2 (December
2025)](https://cdn.euroncap.com/cars/assets/euro_ncap_supporting_protocol_crash_protection_virtual_testing_v102_ca63155dc4.pdf)
(model quality, ISO score, acceptance) and [Frontal Impact Protocol
v1.2](https://cdn.euroncap.com/cars/assets/Euro_NCAP_Protocol_Crash_Protection_Frontal_Impact_v1_2_7f33c197c2.pdf)
(load cases, limits, points). Interpretations are in the
[protocol notes](../protocol-notes.md#euro-ncap-sled-and-virtual-testing-vtc).

## The load case matrix

`FRONTAL_LOAD_CASES` (Frontal Impact Protocol 3.3.1, numbered here from
left to right):

| Load case | Speed | Pulse | Driver | Front passenger |
| --- | --- | --- | --- | --- |
| 1 | 50 km/h | UN R137 (from the vehicle manufacturer) | Hybrid III 50th | Hybrid III 95th |
| 2 | 56 km/h | Rigid wall (vehicle manufacturer) | Hybrid III 95th | Hybrid III 5th |
| 3 | 35 km/h | Euro NCAP FWDB | Hybrid III 50th | Hybrid III 5th |
| 4 | 35 km/h | Euro NCAP FWDB | Hybrid III 5th | Hybrid III 50th |
| 5 | 56 km/h | Rigid wall (vehicle manufacturer) | Hybrid III 5th | Hybrid III 95th |
| 6 | 50 km/h | UN R137 | Human body model 50th | - |

## Step 1: exchange the data as ISO-MME

Simulation results are submitted as ISO-MME channels (unfiltered, at
least 10 kHz, from T0 to Tend). `write_isomme` writes them;
`read_isomme` reads test or simulation data (a folder, its `.mme` file
or a zip):

```python
from crashmetrics.isomme import read_isomme, write_isomme

write_isomme("submission", "VTC_LC1_SIM",
             {"11HEAD0000H3ACXA": (t, head_ax), "11CHST0000H3DSXC": (t, chest_dx)},
             units={"11HEAD0000H3ACXA": "g", "11CHST0000H3DSXC": "mm"},
             header={"Test type": "Euro NCAP VTC load case 1"})

test = read_isomme("sled_tests/LC1.zip")
print(test.summary())
head_x = test.channel("11HEAD??????ACX?")          # ? and * wildcards
head_x.time, head_x.values, head_x.unit, head_x.cfc
```

Channel codes are split by `parse_channel_code` (test object, position,
location, dummy type, dimension, direction, filter class). `NOVALUE`
samples become NaN; text in UTF-8, Windows-1252 and ISO-8859-1 is read.

## Step 2: model quality

```python
from crashmetrics.lsdyna import read_glstat, read_matsum
from crashmetrics.virtual_testing import check_model_quality, model_quality_inputs

inputs = model_quality_inputs(read_glstat("lc1/glstat"), read_matsum("lc1/matsum"),
                              dummy_parts={"driver": driver_part_ids})
quality = check_model_quality(hpoint_dz_mm=1.8, **inputs)
```

| Criterion (Section 5.2) | Limit |
| --- | --- |
| Hourglass energy / maximum internal energy, whole set-up and each dummy | below 10 % |
| Added mass / model mass | below 5 % (2.5 % for separate driver and passenger models) |
| H-point z displacement in the first 5 ms | below 10 mm |
| Sled x acceleration ISO score (separate models only) | above 0.95 |

## Step 3: sensor scores and assessment criteria

```python
from crashmetrics.virtual_testing import frontal_end_time, kpi_checks, sensor_score

t_end = frontal_end_time(t, head_x_excursion)      # max head x excursion + 40 %
head = sensor_score("head", t, {"x": ax_test, "y": ay_test, "z": az_test},
                    {"x": ax_sim, "y": ay_sim, "z": az_sim},
                    simulation_time=t_sim, t_end=t_end)
kpis = kpi_checks("hybrid3_50", test_values, simulation_values, speed=50)
```

- **Sensor score** (5.3.1): ISO/TS 18571 rating per axis, combined with
  weights from the physical test, `w_i = max|c_i| / sum_j max|c_j|`, so
  the dominant axis counts most. Filter test and simulation the same
  way first; simulation output is submitted unfiltered.
- **Assessment criteria** (5.3.2): `rAC = AC / LPL` for test and
  simulation; where `rAC_test >= 50 %`, the deviation
  `dAC = |rAC_test - rAC_sim|` is checked. Knee displacement and the
  tibia criteria are not used in virtual testing.

## Step 4: validate the load case

```python
from crashmetrics.virtual_testing import validate_load_case

result = validate_load_case("load case 1, driver", sensors, kpis, quality)
print(result.summary())
result.passed, result.failures, result.not_assessed
```

Acceptance (5.4): the sensor scores of head, chest and pelvis
acceleration, chest deflection, sled acceleration and shoulder belt
force above **0.5**, every assessed `dAC` below **30 %**, and the
model quality criteria met. Other sensors are listed as monitored; axes
at 0.5 or less are flagged for a plausibility check (sign, units,
channel mapping). If validation fails, Euro NCAP may allow a rerun with
adjusted dummy position, seat cushion deflection, belt routing or
pulse.

## Step 5: score an occupant

```python
from crashmetrics.frontal_scoring import Occupant
from crashmetrics.virtual_testing import score_sled_virtual

score = score_sled_virtual(
    "driver",
    sled={1: Occupant(lc1_test), 3: Occupant(lc3_test)},
    virtual={2: Occupant(lc2_sim), 4: Occupant(lc4_sim), 5: Occupant(lc5_sim)},
    validated=result.passed,
    hbm_provided=True,
)
print(score.summary())
```

- Each body region (head and neck, chest and abdomen, knee femur
  pelvis, lower leg) is scored with the colour bands and limits of the
  [frontal guide](euroncap-frontal.md) for the load case's dummy and
  speed: **0.625 / 2** points per region in each of the two sled load
  cases (2.5 points) and **0.625 / 3** in each of the three virtual
  load cases (2.5 points).
- Virtual lower leg points are awarded by default, unless any dummy in
  any physical test exceeded the tibia index or tibia force LPL
  (`tibia_lpl_exceeded=True`).
- No human body model data: the virtual score is **halved**.
- Virtual data not provided or not validated: **only the sled load
  cases** are scored.
- Each `Occupant` holds the criteria values of
  `crashmetrics.frontal_scoring` (`hic15`, `neck_tension`,
  `chest_compression` ... and `head_peak` or `hard_contact`).
- Occupant modifiers (head bottoming out, steering wheel contact,
  shoulder belt load of 6 kN or more, submarining ...) are given per
  region in `Occupant.modifiers`, as in the full-scale tests.

## Complete example

Validation of load case 1 for the driver with simulation channels
written and read back as ISO-MME, then the driver score:

```python
--8<-- "examples/19_euroncap_virtual_testing.py"
```

Output:

```text
--8<-- "examples/expected/19_euroncap_virtual_testing.txt"
```

## Protocol documents

- [Euro NCAP Crash Protection Virtual Testing Protocol v1.0.2, December 2025](https://cdn.euroncap.com/cars/assets/euro_ncap_supporting_protocol_crash_protection_virtual_testing_v102_ca63155dc4.pdf)
- [Euro NCAP Crash Protection Frontal Impact Protocol v1.2](https://cdn.euroncap.com/cars/assets/Euro_NCAP_Protocol_Crash_Protection_Frontal_Impact_v1_2_7f33c197c2.pdf)
- [Euro NCAP Virtual Testing in Frontal Impacts (ESV 26-283)](https://cdn.euroncap.com/cars/assets/ESV_26_283_EURO_NCAP_VIRTUAL_TESTING_IN_FRONTAL_IMPACTS_60a1873dec.pdf): background, pilot results
- [Euro NCAP Human Body Model Simulations in Frontal Impacts (CP 551) v1.1](https://cdn.euroncap.com/cars/assets/cp_551_human_body_model_simulations_in_frontal_impacts_v11_ea0d932797.pdf)
