"""Example 19: Euro NCAP frontal sled and virtual testing (VTC), 2026.

A vehicle manufacturer validates its driver restraint model against two
sled tests and scores the sled and virtual load cases (5 of the 10
points). Synthetic signals: the "simulation" is the "test" with small
differences in timing and level.

1. Simulation channels are exchanged as ISO-MME (written and read back).
2. Model quality, ISO/TS 18571 sensor scores and assessment criteria
   deviations decide whether the simulation is validated.
3. The driver is scored from two sled and three virtual load cases.
"""

import tempfile

import numpy as np

from crashmetrics.frontal_scoring import Occupant
from crashmetrics.isomme import read_isomme, write_isomme
from crashmetrics.virtual_testing import (
    FRONTAL_LOAD_CASES,
    FRONTAL_SENSORS,
    check_model_quality,
    frontal_end_time,
    kpi_checks,
    score_sled_virtual,
    sensor_score,
    validate_load_case,
)

t = np.arange(0.0, 0.15, 1e-4)                            # s, 10 kHz


def pulse(peak, start, width):
    phase = (t - start) / width
    return np.where((phase > 0) & (phase < 1), peak * np.sin(np.pi * phase) ** 2, 0.0)


def sled_channels(shift=0.0, scale=1.0):
    """Driver channels of load case 1 (H-III 50th, 50 km/h): code -> signal."""
    s = scale
    return {
        "11HEAD0000H3ACXA": pulse(-48 * s, 0.035 + shift, 0.060),   # g
        "11HEAD0000H3ACYA": pulse(4 * s, 0.040 + shift, 0.050),
        "11HEAD0000H3ACZA": pulse(15 * s, 0.040 + shift, 0.055),
        "11CHST0000H3ACXC": pulse(-38 * s, 0.030 + shift, 0.065),
        "11CHST0000H3ACYC": pulse(3 * s, 0.035 + shift, 0.050),
        "11CHST0000H3ACZC": pulse(9 * s, 0.035 + shift, 0.060),
        "11CHST0000H3DSXC": pulse(-31 * s, 0.035 + shift, 0.070),   # mm
        "11PELV0000H3ACXA": pulse(-42 * s, 0.025 + shift, 0.060),
        "11PELV0000H3ACYA": pulse(2 * s, 0.030 + shift, 0.050),
        "11PELV0000H3ACZA": pulse(11 * s, 0.030 + shift, 0.055),
        "10SLED000000ACXD": pulse(-30.0, 0.010, 0.080),             # same pulse
        "11SEBE0000B3FO0B": pulse(5.6 * s, 0.025 + shift, 0.070),   # kN
    }


SENSOR_CODES = {
    "head": {"x": "11HEAD0000H3ACXA", "y": "11HEAD0000H3ACYA",
             "z": "11HEAD0000H3ACZA"},
    "chest_acceleration": {"x": "11CHST0000H3ACXC", "y": "11CHST0000H3ACYC",
                           "z": "11CHST0000H3ACZC"},
    "chest_deflection": {"x": "11CHST0000H3DSXC"},
    "pelvis": {"x": "11PELV0000H3ACXA", "y": "11PELV0000H3ACYA",
               "z": "11PELV0000H3ACZA"},
    "sled": {"x": "10SLED000000ACXD"},
    "shoulder_belt": {"force": "11SEBE0000B3FO0B"},
}
assert {k: tuple(v) for k, v in SENSOR_CODES.items()} == FRONTAL_SENSORS

# --- 1. Simulation results as ISO-MME ------------------------------------------
test = sled_channels()
with tempfile.TemporaryDirectory() as folder:
    write_isomme(folder, "VTC_LC1_SIM", {c: (t, v) for c, v in
                                         sled_channels(0.002, 1.06).items()},
                 header={"Test type": "Euro NCAP VTC load case 1, simulation"})
    simulation = read_isomme(f"{folder}/VTC_LC1_SIM")
print(f"ISO-MME {simulation.test_number}: {simulation.info('Test type')}, "
      f"{len(simulation.channels)} channels, e.g. "
      f"{simulation.channel('11HEAD??????ACX?').code}")

# --- 2. Validation of load case 1 (driver) ------------------------------------
head_x_excursion = pulse(420.0, 0.0, 0.17)        # mm relative to the sled, max 85 ms
t_end = frontal_end_time(t, head_x_excursion)
quality = check_model_quality(hourglass_ratio=0.046, added_mass_ratio=0.011,
                              hpoint_dz_mm=1.8,
                              dummy_hourglass_ratios={"driver": 0.071})
sim_time = simulation.channel("11HEAD0000H3ACXA").time
sensors = {
    name: sensor_score(name, t, {a: test[c] for a, c in axes.items()},
                       {a: simulation.channels[c].values for a, c in axes.items()},
                       simulation_time=sim_time, t_end=t_end)
    for name, axes in SENSOR_CODES.items()
}
kpis = kpi_checks("hybrid3_50",
                  test={"hic15": 410.0, "head_a3ms": 47.0, "neck_tension": 1900.0,
                        "chest_compression": 31.0, "femur_force": 3100.0},
                  simulation={"hic15": 455.0, "head_a3ms": 50.0,
                              "neck_tension": 2050.0, "chest_compression": 33.5,
                              "femur_force": 2600.0},
                  speed=FRONTAL_LOAD_CASES[1].speed)
validation = validate_load_case("load case 1, driver", sensors, kpis, quality)
print(f"\nRating interval 0 to {t_end * 1000:.1f} ms (head excursion + 40 %)")
print(validation.summary())

# --- 3. Driver score: sled load cases 1 and 3, virtual 2, 4 and 5 -------------
base = dict(hic15=410.0, head_a3ms=47.0, neck_shear=900.0, neck_tension=1900.0,
            neck_extension=20.0, chest_compression=31.0, viscous_criterion=0.4,
            femur_force=3100.0)
lower_leg = dict(knee_displacement=2.5, tibia_index=0.35, tibia_force=1800.0)
sled = {1: Occupant(base | lower_leg, hard_contact=True),
        3: Occupant(base | lower_leg | {"chest_compression": 24.0}, hard_contact=True)}
virtual = {2: Occupant(base | {"femur_force": 6900.0, "chest_compression": 38.0},
                       hard_contact=True),                          # 95th, 56 km/h
           4: Occupant(base | {"chest_compression": 26.0, "neck_tension": 2100.0},
                       hard_contact=True),                          # 5th, 35 km/h
           5: Occupant(base | {"chest_compression": 33.0, "neck_tension": 2300.0},
                       hard_contact=True)}                          # 5th, 56 km/h
score = score_sled_virtual("driver", sled, virtual, validated=validation.passed)
print()
print(score.summary())
fallback = score_sled_virtual("driver", sled, virtual, hbm_provided=False)
print(f"\nWithout human body model data: {fallback.points:.3f} / 5 "
      f"(virtual {fallback.virtual_points:.3f})")
