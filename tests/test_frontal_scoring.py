import pytest

from crashmetrics.frontal_scoring import (
    BAND_FRACTIONS,
    CHEST_COMPRESSION_LIMITS,
    DUMMY_LIMITS,
    FWDB_OCCUPANTS,
    MPDB_OCCUPANTS,
    Limit,
    Occupant,
    colour_band,
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


def test_limit_tables_spot_checks():
    assert DUMMY_LIMITS["thor_50"]["neck_tension"] == Limit(2700.0, 3300.0, 3300.0)
    assert DUMMY_LIMITS["hybrid3_05"]["neck_shear"] == Limit(1200.0, 2000.0, 2700.0)
    assert DUMMY_LIMITS["thor_50"]["acetabulum_force"] == Limit(3300.0, 4100.0)
    assert DUMMY_LIMITS["hybrid3_05"]["femur_force"] == Limit(2600.0, 6200.0)
    assert DUMMY_LIMITS["q10"]["chest_a3ms"] == Limit(41.0, 55.0, 55.0)
    assert CHEST_COMPRESSION_LIMITS["thor_50"][50] == Limit(35.0, 60.0, 60.0)
    assert CHEST_COMPRESSION_LIMITS["thor_50"][35] == Limit(29.0, 54.0, 54.0)


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
    table = {"green": 1.0, "yellow": 0.8, "orange": 0.4, "brown": 0.2, "red": 0.0}
    result = score_mpdb(_mpdb_occupants(), band_fractions=table)
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

    # THOR Rmax 33 mm: green at 50 km/h (HPL 35), yellow at 35 km/h (HPL 29).
    thor = dict(occupants["front_passenger"].values, chest_compression=33.0)
    occupants["front_passenger"] = Occupant(thor, hard_contact=True)
    assert score_fwdb(occupants).points == pytest.approx(10.0)
    slow = score_fwdb(occupants, speed=35)
    assert slow.occupants["front_passenger"].regions["chest_abdomen"].band == "yellow"
    assert slow.points == pytest.approx(10.0 - 0.2 * 0.625)


# --- Modifiers and inputs -----------------------------------------------------


def test_damage_modifier():
    assert damage_modifier(0.41) == 0.0
    assert damage_modifier(0.42) == 20.0
    assert damage_modifier(0.4699) == 20.0
    assert damage_modifier(0.47) == 40.0


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
