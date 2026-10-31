"""Example 22: Bharat NCAP from dummy channels to a scorecard (AIS-197 2023).

Unfiltered dummy channels of a frontal ODB test (Hybrid III 50th driver
and passenger) and an MDB side test (ES-2) go straight to the occupant
inputs, are scored with named modifiers, and are laid out as a
scorecard: points per body region, the governing criteria, where the
points are lost and how far the next star is.

The channels are synthetic pulses (10 kHz) standing in for test data
or CAE output; with ISO-MME data use
`channels_from_isomme(read_isomme(path), position="1")`.
"""

import datetime as dt

import numpy as np

from crashmetrics.bncap import (
    PROTOCOL,
    edition_for_date,
    frontal_modifiers,
    score_frontal,
    score_side,
)
from crashmetrics.bncap_channels import (
    frontal_occupant_from_channels,
    side_occupant_from_channels,
)
from crashmetrics.bncap_report import scorecard

t = np.arange(0.0, 0.15, 1e-4)                         # s, 10 kHz


def pulse(peak, start_ms, width_ms):
    """Half-sine pulse with a small 1.2 kHz ripple (sensor noise stand-in)."""
    phase = (t * 1000.0 - start_ms) / width_ms
    shape = np.where((phase > 0) & (phase < 1), np.sin(np.pi * phase), 0.0)
    return peak * shape * (1.0 + 0.03 * np.sin(2 * np.pi * 1200.0 * t))


def hybrid3(head_g, neck_tension, chest_mm, femur_n, knee_mm, tibia):
    ch = {
        "head_ax": (t, pulse(-0.8 * head_g, 60, 30)),
        "head_ay": (t, pulse(0.1 * head_g, 60, 30)),
        "head_az": (t, pulse(0.55 * head_g, 60, 30)),
        "neck_fx": (t, pulse(-800.0, 55, 35)),
        "neck_fz": (t, pulse(neck_tension, 55, 40)),
        "neck_my": (t, pulse(-25.0, 60, 30)),
        "chest_deflection": (t, pulse(chest_mm, 40, 50)),
    }
    for leg, k in (("left", 1.0), ("right", 0.9)):
        ch[f"femur_fz_{leg}"] = (t, pulse(-femur_n * k, 35, 25))
        ch[f"knee_{leg}"] = (t, pulse(-knee_mm * k, 35, 25))
        ch[f"tibia_{leg}_upper_mx"] = (t, pulse(tibia[0] * k, 35, 25))
        ch[f"tibia_{leg}_upper_my"] = (t, pulse(tibia[1] * k, 35, 25))
        ch[f"tibia_{leg}_upper_fz"] = (t, pulse(-tibia[2] * k, 35, 25))
    return ch


driver_ch = hybrid3(82.0, 2100.0, 30.0, 3200.0, 3.0, (40.0, 70.0, 2600.0))
passenger_ch = hybrid3(48.0, 1800.0, 24.0, 2800.0, 2.0, (30.0, 50.0, 1900.0))

print(f"Protocol: {PROTOCOL}")
print("Edition for a rating on 15 March 2026:",
      edition_for_date(dt.date(2026, 3, 15)))

# --- Frontal ODB 64 km/h ---------------------------------------------------------
driver = frontal_occupant_from_channels(
    driver_ch, pedal_rearward=62.0,
    modifiers=frontal_modifiers(steering_column=(40.0, 30.0, 10.0),
                                a_pillar=120.0, shoulder_belt_load=5400.0,
                                knee_concentrated_load=(False, True)))
passenger = frontal_occupant_from_channels(passenger_ch, driver=False)
print(f"Driver: HIC15 {driver.hic15:.0f}, 3 ms {driver.head_a3ms:.1f} g, "
      f"hard contact {driver.hard_contact}, chest {driver.chest_compression:.1f} mm, "
      f"VC {driver.viscous_criterion:.2f} m/s, TI {driver.tibia_index[0]:.2f}")
frontal = score_frontal(driver, passenger)

# --- MDB side 50 km/h ------------------------------------------------------------
side_ch = {
    "head_ax": (t, pulse(5.0, 30, 15)), "head_ay": (t, pulse(52.0, 30, 15)),
    "head_az": (t, pulse(8.0, 30, 15)),
    "rib_upper": (t, pulse(24.0, 20, 30)), "rib_middle": (t, pulse(28.0, 20, 30)),
    "rib_lower": (t, pulse(26.0, 20, 30)),
    "abdomen_front": (t, pulse(380.0, 20, 25)),
    "abdomen_middle": (t, pulse(420.0, 20, 25)),
    "abdomen_rear": (t, pulse(350.0, 20, 25)),
    "pubic_fy": (t, pulse(-2400.0, 22, 25)),
    "backplate_fy": (t, pulse(1600.0, 25, 20)),
}
side = score_side(side_occupant_from_channels(side_ch))

card = scorecard(frontal, side)
print()
print(card.markdown())
rows = card.rows()                  # one dict per criterion, for CSV or pandas
first = rows[0]
print(f"{len(rows)} criteria rows; first: {first['test']} {first['occupant']} "
      f"{first['criterion']} = {first['value']:.1f} -> {first['criterion_points']} "
      "points")
