import numpy as np
import pytest

from crashmetrics.features import flatten
from crashmetrics.homologation import (
    R94_LIMITS,
    R95_LIMITS,
    R135_LIMITS,
    ElectricalLimits,
    HVBus,
    check_electrical_safety,
    check_r94_occupant,
    check_r94_vehicle,
    check_r95_occupant,
    check_r95_vehicle,
    check_r135_occupant,
    check_r135_vehicle,
    combine,
)
from crashmetrics.neck import neck_force_criterion

T = np.arange(0.0, 0.15, 1e-4)


def plateau(level, duration_ms, start=0.02):
    """Constant level for duration_ms (with 0.1 ms ramps)."""
    return np.interp(T, [0, start, start + 1e-4, start + duration_ms / 1000,
                         start + duration_ms / 1000 + 1e-4, 1],
                     [0, 0, level, level, 0, 0])


# --- the limits are the regulation values -----------------------------------


def test_limit_values():
    assert R94_LIMITS == {
        "hpc": 1000.0, "head_a3ms": 80.0, "neck_extension": 57.0, "thcc": 42.0,
        "vc": 1.0, "tibia_compression": 8000.0, "tibia_index": 1.3,
        "knee_slider": 15.0, "steering_upward": 80.0, "steering_rearward": 100.0,
        "fuel_leakage_rate": 30.0,
    }
    assert R95_LIMITS == {"hpc": 1000.0, "rdc": 42.0, "vc": 1.0, "pspf": 6000.0,
                          "apf": 2500.0, "fuel_leakage_rate": 30.0}
    assert R135_LIMITS["thorax_rib_deflection"] == 55.0
    assert R135_LIMITS["abdominal_rib_deflection"] == 65.0
    assert R135_LIMITS["pubic_force"] == 3360.0
    assert R135_LIMITS["lower_spine_3ms"] == 75.0
    assert R135_LIMITS["shoulder_force"] == 3000.0


# --- UN R94 --------------------------------------------------------------------


GOOD_R94 = dict(hpc=620, head_a3ms=58, neck_extension=22, thcc=36.5, vc=0.42,
                tibia_compression=3100, tibia_index=0.71, knee_slider=4.2)


def test_r94_occupant_passes_and_is_complete_with_all_values():
    r = check_r94_occupant(
        **GOOD_R94,
        neck_tension=(T, plateau(1900, 20)), neck_shear=(T, plateau(-700, 20)),
        femur_left=(T, plateau(-4200, 20)), femur_right=(T, plateau(-6100, 8)),
        position="driver")
    assert r.passed and r.complete and r.failures == []
    assert r.regulation == "UN R94 (driver)"
    assert r.requirements["thcc"].utilisation == pytest.approx(36.5 / 42)
    assert r.worst == "thcc"


@pytest.mark.parametrize("name, at_limit", [
    ("hpc", 1000), ("head_a3ms", 80), ("neck_extension", 57), ("thcc", 42),
    ("vc", 1.0), ("tibia_compression", 8000), ("tibia_index", 1.3),
    ("knee_slider", 15),
])
def test_r94_numeric_limits_are_inclusive(name, at_limit):
    assert check_r94_occupant(**{name: at_limit}).requirements[name].passed
    above = check_r94_occupant(**{name: at_limit * 1.001})
    assert above.requirements[name].passed is False
    assert above.failures == [name] and not above.passed


def test_r94_neck_and_femur_curves():
    # tension 3.0 kN held 30 ms: the limit at 30 ms is 3.3 - 0.4 * 30/35 kN
    over = check_r94_occupant(neck_tension=(T, plateau(3000, 30)))
    assert over.requirements["neck_tension"].passed is False
    assert check_r94_occupant(neck_tension=(T, plateau(2800, 30))).passed
    # femur 8.0 kN held 12 ms exceeds 7.58 kN; held 4 ms it does not
    assert not check_r94_occupant(femur_left=(T, plateau(-8000, 12))).passed
    assert check_r94_occupant(femur_left=(T, plateau(-8000, 4))).passed
    # a precomputed result is accepted as well
    pre = neck_force_criterion(T, plateau(1500, 10), "r94_shear")
    assert check_r94_occupant(neck_shear=pre).requirements["neck_shear"].passed


def test_r94_no_head_contact_satisfies_hpc():
    r = check_r94_occupant(hpc=5000, head_contact=False)
    assert r.requirements["hpc"].passed is True
    assert "no head contact" in r.requirements["hpc"].note
    assert "no head contact: satisfied" in r.summary()


def test_not_assessed_is_not_a_pass():
    r = check_r94_occupant(thcc=30)
    assert r.passed and not r.complete
    assert "hpc" in r.not_assessed and "thcc" not in r.not_assessed
    assert "not assessed" in r.summary()


def test_r94_vehicle():
    ok = check_r94_vehicle(steering_upward=34, steering_rearward=-61,
                           door_opened=False, doors_unlocked_after=True,
                           doors_open_without_tools=True, fuel_leakage_rate=0)
    assert ok.passed and ok.complete
    bad = check_r94_vehicle(steering_rearward=101, door_opened=True)
    assert bad.failures == ["steering_rearward", "door_opened"]


def test_combine_prefixes_parts():
    both = combine("UN R94", check_r94_occupant(thcc=30, position="driver"),
                   check_r94_occupant(thcc=44, position="passenger"),
                   check_r94_vehicle(door_opened=False))
    assert both.failures == ["passenger: thcc"]
    assert "driver: thcc" in both.requirements
    assert "vehicle: door_opened" in both.requirements
    assert not both.passed


# --- UN R95 and R135 ------------------------------------------------------------


def test_r95():
    r = check_r95_occupant(hpc=410, rdc=38.0, vc=0.6, pspf=3200, apf=1400)
    assert r.passed and r.complete
    assert not check_r95_occupant(apf=2600).passed
    assert not check_r95_occupant(rdc=42.5).passed
    assert check_r95_occupant(head_contact=False).requirements["hpc"].passed
    v = check_r95_vehicle(door_opened=False, non_struck_doors_unlocked=True,
                          egress_possible=True, dangerous_detachment=False,
                          fuel_leakage_rate=12)
    assert v.passed and v.complete


def test_r135_with_lower_spine_series():
    spine = plateau(80, 2.5) + plateau(60, 30, start=0.05)   # 80 g for 2.5 ms
    r = check_r135_occupant(hic36=540, shoulder_force=2100, thorax_rib_deflection=41,
                            abdominal_rib_deflection=52, lower_spine=(T, spine),
                            pubic_force=2400)
    assert r.passed and r.complete
    assert r.requirements["lower_spine_3ms"].value == pytest.approx(60, abs=0.5)
    long = plateau(80, 4.0)
    assert not check_r135_occupant(lower_spine=(T, long)).passed
    assert not check_r135_occupant(pubic_force=3400).passed
    v = check_r135_vehicle(struck_door_separated=False, other_doors_held=True,
                           fuel_leakage_first_5_min=150)
    assert v.failures == ["fuel_leakage_first_5_min"]


# --- Electrical safety --------------------------------------------------------


@pytest.mark.parametrize("bus, passed, how", [
    (HVBus("dc", "DC", voltage=59.0), True, "voltage"),
    (HVBus("dc", "DC", voltage=61.0), False, "none"),
    (HVBus("ac", "AC", voltage=31.0), False, "none"),
    (HVBus("dc", "DC", energy=0.19), True, "energy"),
    (HVBus("dc", "DC", energy=0.2), False, "none"),            # less than 0.2 J
    (HVBus("dc", "DC", ipxxb=True, chassis_resistance=0.05), True, "IPXXB"),
    (HVBus("dc", "DC", ipxxb=True, chassis_resistance=0.15), False, "none"),
    (HVBus("dc", "DC", working_voltage=400, isolation_resistance=40_000), True,
     "isolation"),                                            # 100 ohm/V
    (HVBus("ac", "AC", working_voltage=400, isolation_resistance=150_000), False,
     "none"),                                                 # needs 500 ohm/V
    (HVBus("mix", "DC+AC", working_voltage=400, isolation_resistance=60_000,
           ac_part_protected=True), True, "isolation"),
    (HVBus("mix", "DC+AC", working_voltage=400, isolation_resistance=60_000), False,
     "none"),
    (HVBus("dc", "DC", voltage=380, working_voltage=400, isolation_resistance=60_000),
     True, "isolation"),                                      # one criterion suffices
])
def test_shock_protection_criteria(bus, passed, how):
    req = check_electrical_safety([bus]).requirements[f"shock_protection[{bus.name}]"]
    assert req.passed is passed
    assert (how in req.note) if passed else req.note.startswith("none of")


def test_electrical_electrolyte_retention_fire():
    ok = check_electrical_safety(
        [HVBus("dc", voltage=20)], electrolyte="aqueous", electrolyte_in_cabin=False,
        electrolyte_outside_percent=5.0, electrolyte_outside_litres=1.2,
        reess_retained=True, reess_entered_cabin=False, fire_or_explosion=False)
    assert ok.passed and ok.complete
    assert not check_electrical_safety(electrolyte="aqueous",
                                       electrolyte_outside_percent=7.5).passed
    assert not check_electrical_safety(electrolyte="non-aqueous",
                                       electrolyte_leaked_anywhere=True).passed
    assert not check_electrical_safety(fire_or_explosion=True).passed
    assert not check_electrical_safety(reess_entered_cabin=True).passed
    with pytest.raises(ValueError, match="electrolyte"):
        check_electrical_safety(electrolyte="gel")
    with pytest.raises(ValueError, match="working voltage"):
        check_electrical_safety([HVBus("dc", isolation_resistance=1e5)])


def test_electrical_older_series_limits():
    older = ElectricalLimits(max_energy=2.0, electrolyte_minutes=30)
    bus = HVBus("dc", energy=1.5)
    assert check_electrical_safety([bus], limits=older).passed
    assert not check_electrical_safety([bus]).passed
    assert "30 min" in check_electrical_safety(limits=older).notes[0]


def test_results_flatten_and_validate():
    flat = flatten(check_r94_occupant(thcc=30))
    assert flat["requirements.thcc.utilisation"] == pytest.approx(30 / 42)
    with pytest.raises(ValueError, match="finite"):
        check_r94_occupant(thcc=float("nan"))
    with pytest.raises(ValueError, match="time history"):
        check_r94_occupant(neck_tension=[1, 2, 3])
