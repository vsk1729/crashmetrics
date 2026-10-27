import pytest

from crashmetrics.frontal_scoring import (
    BAND_FRACTIONS,
    BAND_FRACTIONS_TABLE,
    CHEST_COMPRESSION_LIMITS,
    DUMMY_LIMITS,
    FWDB_OCCUPANTS,
    FWDB_SPEED,
    MPDB_OCCUPANTS,
    Limit,
    Occupant,
    colour_band,
    compatibility_penalty,
    compatibility_percentages,
    damage_modifier,
    score_dummy,
    score_fwdb,
    score_mpdb,
)

# --- Colour bands -------------------------------------------------------------


@pytest.mark.parametrize("value, band", [
    (499.9, "green"),
    (500.0, "yellow"),   # "< HPL" is green, so HPL itself is yellow
    (566.6, "yellow"),
    (566.7, "orange"),   # band width (700 - 500) / 3 = 66.67
    (633.3, "orange"),
    (633.4, "brown"),
    (699.9, "brown"),
    (700.0, "red"),
])
def test_colour_band_thirds(value, band):
    assert colour_band(value, Limit(500.0, 700.0, 700.0)) == band


def test_colour_band_lpl_only():
    assert colour_band(87.9, Limit(None, 88.0)) == "green"
    assert colour_band(88.0, Limit(None, 88.0)) == "red"
    with pytest.raises(ValueError, match="HPL"):
        colour_band(1.0, Limit(2.0, 1.0))


def test_band_fractions_match_region_points():
    # Section 3.5: 1.25, 1.0, 0.75, 0.5 and 0 points of 1.25.
    points = {band: 1.25 * f for band, f in BAND_FRACTIONS.items()}
    assert points == pytest.approx(
        {"green": 1.25, "yellow": 1.0, "orange": 0.75, "brown": 0.5, "red": 0.0}
    )


def test_point_allocations():
    mpdb = {pos: sum(points.values()) for pos, (_, points) in MPDB_OCCUPANTS.items()}
    assert mpdb == {"driver": 5.0, "front_passenger": 5.0, "rear_q6": 5.0,
                    "rear_q10": 5.0}
    fwdb = {pos: sum(points.values()) for pos, (_, points) in FWDB_OCCUPANTS.items()}
    assert fwdb == {"driver": 5.0, "front_passenger": 2.5, "rear_passenger": 2.5}
    assert [d for d, _ in MPDB_OCCUPANTS.values()] == ["thor_50", "hybrid3_05",
                                                       "q6", "q10"]
    assert [d for d, _ in FWDB_OCCUPANTS.values()] == ["hybrid3_05", "thor_50",
                                                       "hybrid3_05"]


def test_limit_tables_match_protocol_section_3_5():
    # Frontal Impact Protocol v1.1, Section 3.5 (pages 25-26), kN -> N.
    L = Limit
    expected = {
        "hybrid3_05": {
            "hic15": L(500, 700, 700), "head_a3ms": L(72, 80, 80),
            "neck_shear": L(1200, 2000, 2700, True),
            "neck_tension": L(1700, 2600, 2900, True),
            "neck_extension": L(36, 49, 57, True),
            "viscous_criterion": L(0.5, 1.0, 1.0),
            "femur_force": L(2600, 6200), "knee_displacement": L(6, 15),
            "tibia_index": L(None, 1.3), "tibia_force": L(None, 8000),
        },
        "hybrid3_50": {
            "hic15": L(500, 700, 700), "head_a3ms": L(72, 80, 80),
            "neck_shear": L(1900, 3100, 3100), "neck_tension": L(2700, 3300, 3300),
            "neck_extension": L(42, 57, 57), "viscous_criterion": L(0.5, 1.0, 1.0),
            "femur_force": L(3800, 9100), "knee_displacement": L(6, 15),
            "tibia_index": L(0.4, 1.3), "tibia_force": L(2000, 8000),
        },
        "thor_50": {
            "hic15": L(500, 700, 700), "head_a3ms": L(72, 80, 80),
            "neck_shear": L(1900, 3100, 3100), "neck_tension": L(2700, 3300, 3300),
            "neck_extension": L(42, 57, 57), "abdomen_compression": L(None, 88),
            "acetabulum_force": L(3300, 4100), "femur_force": L(3800, 9100),
            "knee_displacement": L(6, 15), "tibia_index": L(0.4, 1.3),
            "tibia_force": L(2000, 8000),
        },
        "hybrid3_95": {
            "hic15": L(500, 700), "head_a3ms": L(72, 80),
            "neck_shear": L(2300, 3800), "neck_tension": L(3300, 4000),
            "neck_extension": L(56, 76), "viscous_criterion": L(0.5, 1.0),
            "femur_force": L(4800, 11500), "knee_displacement": L(6, 17),
            "tibia_index": L(0.4, 1.3), "tibia_force": L(4000, 10000),
        },
        "q6": {
            "hic15": L(500, 700, 700), "head_a3ms": L(60, 80, 80),
            "neck_tension": L(1700, 2620), "neck_extension": L(None, 36),
            "chest_compression": L(30, 42, 56),
        },
        "q10": {
            "hic15": L(500, 700, 700), "head_a3ms": L(60, 80, 80),
            "neck_tension": L(1700, 2620), "neck_extension": L(None, 49),
            "chest_compression": L(None, 56, 56), "chest_a3ms": L(41, 55, 55),
        },
    }
    assert DUMMY_LIMITS == expected
    assert CHEST_COMPRESSION_LIMITS == {
        "hybrid3_05": {35: L(18, 34, 34), 50: L(18, 34, 34), 56: L(22, 42, 42)},
        "hybrid3_50": {35: L(20, 42, 42), 50: L(20, 42, 42)},
        "thor_50": {35: L(29, 54, 54), 50: L(35, 60, 60)},
        "hybrid3_95": {50: L(28, 55), 56: L(28, 55)},
    }


# --- Hand-calculated MPDB example ----------------------------------------------


def _mpdb_occupants():
    driver = Occupant(  # THOR 50th, no hard head contact
        values={"head_peak": 60.0, "neck_shear": 1500.0, "neck_tension": 2800.0,
                "neck_extension": 30.0, "chest_compression": 50.0,
                "abdomen_compression": 70.0, "acetabulum_force": 3000.0,
                "femur_force": 4000.0, "knee_displacement": 5.0,
                "tibia_index": 0.3, "tibia_force": 1500.0},
        modifiers={"head_neck": [damage_modifier(0.44)]},
    )
    passenger = Occupant(  # Hybrid III 5th, hard contact
        values={"head_peak": 95.0, "hic15": 600.0, "head_a3ms": 70.0,
                "neck_shear": 1000.0, "neck_tension": 1500.0,
                "neck_extension": 30.0, "chest_compression": 20.0,
                "viscous_criterion": 0.4, "femur_force": 2000.0,
                "knee_displacement": 3.0, "tibia_index": 1.0,
                "tibia_force": 9000.0},
    )
    q6 = Occupant(values={"hic15": 1200.0, "head_a3ms": 65.0, "neck_tension": 1000.0,
                          "chest_compression": 35.0}, hard_contact=False)
    q10 = Occupant(values={"hic15": 450.0, "head_a3ms": 50.0, "neck_tension": 2700.0,
                           "neck_extension": 20.0, "chest_compression": 40.0,
                           "chest_a3ms": 50.0}, hard_contact=True)
    return {"driver": driver, "front_passenger": passenger, "rear_q6": q6,
            "rear_q10": q10}


def test_mpdb_hand_calculation():
    result = score_mpdb(_mpdb_occupants(), full_scale_modifiers=[2.5],
                        compatibility_penalty=1.5)
    occ = result.occupants

    # Driver: head & neck yellow (tension 2.8 kN) 1.0 - DAMAGE 20 % of 1.25;
    # chest orange (Rmax 50 mm of 35-60); femur yellow; lower leg green.
    d = occ["driver"].regions
    assert d["head_neck"].band == "yellow"
    assert d["head_neck"].governing == "neck_tension"
    assert d["head_neck"].points == pytest.approx(0.75)
    assert d["chest_abdomen"].band == "orange"
    assert d["knee_femur_pelvis"].band == "yellow"
    assert occ["driver"].points == pytest.approx(3.75)
    assert not occ["driver"].hard_contact

    # Passenger: HIC15 600 orange; chest yellow; knee green; tibia 9 kN red.
    p = occ["front_passenger"].regions
    assert p["head_neck"].governing == "hic15" and p["head_neck"].band == "orange"
    assert p["lower_leg"].band == "red" and p["lower_leg"].governing == "tibia_force"
    assert occ["front_passenger"].points == pytest.approx(3.0)

    # Q6 without hard contact: head on 3 ms only (65 g yellow) -> 2.0 of 2.5;
    # neck 1.25; chest 35 mm orange 0.75.
    q6 = occ["rear_q6"].regions
    assert [c.name for c in q6["head"].criteria] == ["head_a3ms"]
    assert occ["rear_q6"].points == pytest.approx(4.0)
    # Q10: head green 2.5; neck tension red 0; chest 3 ms 50 g orange 0.75.
    assert occ["rear_q10"].points == pytest.approx(3.25)

    assert result.occupant_points == pytest.approx(14.0)
    assert result.max_points == 20.0
    assert result.full_scale_deduction == pytest.approx(0.25)  # 2.5 % of 10
    assert result.points == pytest.approx(14.0 - 0.25 - 1.5)


def test_adult_head_without_hard_contact_ignores_hic():
    values = dict(_mpdb_occupants()["front_passenger"].values)
    values["hic15"] = 2000.0
    values["head_peak"] = 79.0
    score = score_dummy("hybrid3_05", Occupant(values),
                        MPDB_OCCUPANTS["front_passenger"][1])
    assert score.regions["head_neck"].band == "green"
    assert score.capping_exceeded == ()


def test_capping_is_reported():
    values = dict(_mpdb_occupants()["front_passenger"].values)
    values["hic15"] = 720.0
    score = score_dummy("hybrid3_05", Occupant(values),
                        MPDB_OCCUPANTS["front_passenger"][1])
    assert score.capping_exceeded == ("hic15",)
    assert score.regions["head_neck"].band == "red"


def test_modifiers_do_not_go_below_zero():
    occupants = _mpdb_occupants()
    occupants["driver"] = Occupant(occupants["driver"].values,
                                   modifiers={"knee_femur_pelvis": [100.0, 20.0]})
    result = score_mpdb(occupants, full_scale_modifiers=[100.0, 100.0, 100.0])
    assert result.occupants["driver"].regions["knee_femur_pelvis"].points == 0.0
    result = score_mpdb(occupants, compatibility_penalty=50.0)
    assert result.points == 0.0


def test_band_fraction_override():
    result = score_mpdb(_mpdb_occupants(), band_fractions=BAND_FRACTIONS_TABLE)
    # Driver chest orange: 0.4 * 1.25 instead of 0.75
    assert result.occupants["driver"].regions["chest_abdomen"].points == \
        pytest.approx(0.5)


# --- Full width ---------------------------------------------------------------


def _green_adult(dummy):
    limits = DUMMY_LIMITS[dummy]
    values = {k: (lim.hpl if lim.hpl is not None else lim.lpl) * 0.5
              for k, lim in limits.items()}
    values["chest_compression"] = 10.0
    return Occupant(values, hard_contact=True)


def test_fwdb_full_marks_and_speed():
    occupants = {"driver": _green_adult("hybrid3_05"),
                 "front_passenger": _green_adult("thor_50"),
                 "rear_passenger": _green_adult("hybrid3_05")}
    result = score_fwdb(occupants)
    assert result.points == pytest.approx(10.0) and result.max_points == 10.0
    assert "lower_leg" not in result.occupants["rear_passenger"].regions

    # The full width test runs at 35 km/h: THOR Rmax 33 mm is yellow
    # (29-54 mm); it would be green with the 50 km/h limits (35-60 mm).
    assert FWDB_SPEED == 35
    thor = dict(occupants["front_passenger"].values, chest_compression=33.0)
    occupants["front_passenger"] = Occupant(thor, hard_contact=True)
    result = score_fwdb(occupants)
    assert result.occupants["front_passenger"].regions["chest_abdomen"].band == \
        "yellow"
    assert result.points == pytest.approx(10.0 - 0.2 * 0.625)
    assert score_fwdb(occupants, speed=50).points == pytest.approx(10.0)


# --- Modifiers and inputs -----------------------------------------------------


def test_damage_modifier():
    assert damage_modifier(0.41) == 0.0
    assert damage_modifier(0.42) == 20.0
    assert damage_modifier(0.4699) == 20.0
    assert damage_modifier(0.47) == 40.0


@pytest.mark.parametrize("sd, olc, bottoming, expected", [
    (119.0, 34.9, False, 2.826),  # CP 007 Appendix A, example 1
    (140.0, 37.7, True, 5.0),     # example 2 (5.338 capped at 5)
    (100.0, 27.2, True, 2.242),   # example 3
])
def test_compatibility_penalty_cp007_examples(sd, olc, bottoming, expected):
    assert compatibility_penalty(sd, olc, bottoming) == pytest.approx(expected,
                                                                      abs=1e-3)


def test_compatibility_penalty_limits():
    # CP 007 A.3: none below the HPLs; 6.25 % of 20 points for bottoming
    # out alone; 25 % (5 points) at or beyond both LPLs.
    assert compatibility_penalty(40.0, 20.0, False) == 0.0
    assert compatibility_penalty(40.0, 20.0, True) == pytest.approx(1.25)
    assert compatibility_penalty(160.0, 45.0, False) == pytest.approx(5.0)
    assert compatibility_penalty(160.0, 45.0, True) == pytest.approx(5.0)
    # Figure 2: SD alone or OLC alone at 100 % gives 1.25 points.
    assert compatibility_penalty(150.0, 25.0, False) == pytest.approx(1.25)
    assert compatibility_penalty(50.0, 40.0, False) == pytest.approx(1.25)


def test_driver_only_capping():
    values = dict(_mpdb_occupants()["front_passenger"].values)
    values["neck_tension"] = 3000.0  # above the 2.9 kN HIII 5th capping
    points = MPDB_OCCUPANTS["front_passenger"][1]
    assert score_dummy("hybrid3_05", Occupant(values), points).capping_exceeded \
        == ()
    driver = score_dummy("hybrid3_05", Occupant(values), points, driver=True)
    assert driver.capping_exceeded == ("neck_tension",)


def test_q_dummy_score_modifier():
    q6 = _mpdb_occupants()["rear_q6"]
    partial = Occupant(q6.values, hard_contact=False, dummy_modifiers=[50.0])
    score = score_dummy("q6", partial, MPDB_OCCUPANTS["rear_q6"][1])
    assert score.points == pytest.approx(4.0 - 0.5 * 5.0)


def test_compatibility_percentages():
    assert compatibility_percentages(100.0, 32.5) == pytest.approx((50.0, 50.0))
    assert compatibility_percentages(70.0, 28.0) == pytest.approx((20.0, 20.0))
    assert compatibility_percentages(30.0, 50.0) == (0.0, 100.0)


def test_input_errors():
    occupants = _mpdb_occupants()
    points = MPDB_OCCUPANTS["driver"][1]
    with pytest.raises(ValueError, match="Unknown criteria"):
        score_dummy("thor_50", Occupant({"hic": 1.0}, hard_contact=True), points)
    values = dict(occupants["driver"].values)
    del values["femur_force"]
    with pytest.raises(ValueError, match="femur_force"):
        score_dummy("thor_50", Occupant(values), points)
    with pytest.raises(ValueError, match="hard_contact"):
        score_dummy("thor_50", Occupant({"neck_shear": 1.0}), points)
    with pytest.raises(ValueError, match="Unknown dummy"):
        score_dummy("hybrid2", occupants["driver"], points)
    with pytest.raises(ValueError, match="56 km/h"):
        score_dummy("thor_50", occupants["driver"], points, speed=56)
    with pytest.raises(ValueError, match="not scored"):
        score_dummy("q6", Occupant(occupants["rear_q6"].values, False,
                                   {"lower_leg": [20.0]}),
                    MPDB_OCCUPANTS["rear_q6"][1])
    del occupants["rear_q10"]
    with pytest.raises(ValueError, match="missing"):
        score_mpdb(occupants)
