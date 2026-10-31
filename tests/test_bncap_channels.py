"""Tests for crashmetrics.bncap_channels (channels -> Bharat NCAP inputs)."""

import numpy as np
import pytest

from crashmetrics.bncap import FrontalOccupant, backplate_modifier, t12_modifier
from crashmetrics.bncap_channels import (
    FRONTAL_CHANNELS,
    HYBRID3_ISOMME,
    SIDE_CHANNELS,
    channels_from_isomme,
    frontal_occupant_from_channels,
    pole_test_from_channels,
    side_occupant_from_channels,
)
from crashmetrics.isomme import read_isomme, write_isomme
from crashmetrics.pedestrian import calculate_hic
from crashmetrics.signals import cfc_filter

T = np.arange(0.0, 0.12, 1e-4)


def tri(peak, start_ms, width_ms):
    """Triangle pulse: exact peak at a sample, easy to check by hand."""
    ms = T * 1000.0
    return peak * np.clip(1.0 - np.abs(ms - start_ms - width_ms / 2) / (width_ms / 2),
                          0.0, 1.0)


def frontal_channels(head=60.0, tibia_locations=("upper",)):
    ch = {
        "head_ax": (T, tri(-head * 0.6, 60, 20)),
        "head_ay": (T, np.zeros_like(T)),
        "head_az": (T, tri(head * 0.8, 60, 20)),
        "neck_fx": (T, tri(-900.0, 55, 30)),
        "neck_fz": (T, tri(2000.0, 55, 30)),
        "neck_my": (T, tri(-30.0, 55, 30)),
        "chest_deflection": (T, tri(32.0, 40, 40)),
    }
    for leg in ("left", "right"):
        ch[f"femur_fz_{leg}"] = (T, tri(-4000.0, 30, 20))
        ch[f"knee_{leg}"] = (T, tri(-5.0, 30, 20))
        for loc in tibia_locations:
            ch[f"tibia_{leg}_{loc}_mx"] = (T, tri(50.0, 30, 20))
            ch[f"tibia_{leg}_{loc}_my"] = (T, tri(100.0, 30, 20))
            ch[f"tibia_{leg}_{loc}_fz"] = (T, tri(-3000.0, 30, 20))
    return ch


def side_channels(**extra):
    ch = {
        "head_ax": (T, np.zeros_like(T)), "head_ay": (T, tri(50.0, 30, 10)),
        "head_az": (T, np.zeros_like(T)),
        "rib_upper": (T, tri(20.0, 20, 30)), "rib_middle": (T, tri(30.0, 20, 30)),
        "rib_lower": (T, tri(25.0, 20, 30)),
        "abdomen_front": (T, tri(400.0, 20, 20)),
        "abdomen_middle": (T, tri(500.0, 20, 20)),
        "abdomen_rear": (T, tri(300.0, 20, 20)),
        "pubic_fy": (T, tri(-2000.0, 20, 20)),
    }
    ch.update({k: (T, v) for k, v in extra.items()})
    return ch


def test_frontal_values_by_hand():
    occ = frontal_occupant_from_channels(frontal_channels(), filtered=True,
                                         pedal_rearward=40.0)
    assert isinstance(occ, FrontalOccupant)
    res = np.hypot(tri(36.0, 60, 20), tri(48.0, 60, 20))      # peak 60 g
    assert occ.hic15 == pytest.approx(calculate_hic(T, res).value)
    assert not occ.hard_contact                                # 60 g <= 80 g
    assert occ.chest_compression == pytest.approx(32.0)
    assert occ.knee_displacement == pytest.approx((5.0, 5.0))
    assert occ.tibia_force == pytest.approx((3000.0, 3000.0))
    # TI = |M_R| / 225 + |Fz| / 35 900 at the common peak.
    ti = np.hypot(50.0, 100.0) / 225.0 + 3000.0 / 35_900.0
    assert occ.tibia_index == pytest.approx((ti, ti), rel=1e-9)
    # Extension at the occipital condyle: M_OCy = My - Fx * 0.01778.
    assert occ.neck_extension == pytest.approx(30.0 - 900.0 * 0.01778, rel=1e-9)
    assert occ.pedal_rearward == 40.0
    np.testing.assert_array_equal(occ.neck_tension[1], tri(2000.0, 55, 30))


def test_head_contact_rule_and_override():
    hard = frontal_occupant_from_channels(frontal_channels(head=81.0), filtered=True)
    soft = frontal_occupant_from_channels(frontal_channels(head=79.0), filtered=True)
    assert hard.hard_contact and not soft.hard_contact
    forced = frontal_occupant_from_channels(frontal_channels(head=79.0),
                                            filtered=True, head_contact=True)
    assert forced.hard_contact


def test_worst_tibia_location_and_passenger():
    ch = frontal_channels(tibia_locations=("upper", "lower"))
    ch["tibia_left_lower_fz"] = (T, tri(-5000.0, 30, 20))
    occ = frontal_occupant_from_channels(ch, filtered=True, driver=False,
                                         pedal_rearward=99.0)
    assert occ.tibia_force == pytest.approx((5000.0, 3000.0))
    assert occ.pedal_rearward is None


def test_filtering_matches_manual_cfc():
    ch = frontal_channels()
    occ = frontal_occupant_from_channels(ch)
    manual = cfc_filter(T, ch["chest_deflection"][1], 180)
    assert occ.chest_compression == pytest.approx(float(np.max(manual)))
    assert FRONTAL_CHANNELS["chest_deflection"] == ("mm", 180)
    assert FRONTAL_CHANNELS["neck_my"] == ("N m", 600)


def test_frontal_errors():
    ch = frontal_channels()
    del ch["tibia_right_upper_mx"]
    with pytest.raises(ValueError, match="Mx, My and Fz"):
        frontal_occupant_from_channels(ch, filtered=True)
    ch = frontal_channels(tibia_locations=())
    with pytest.raises(ValueError, match="tibia loads"):
        frontal_occupant_from_channels(ch, filtered=True)
    ch = frontal_channels()
    ch["neck_fz"] = (T[:-1], ch["neck_fz"][1][:-1])
    with pytest.raises(ValueError, match="same time base"):
        frontal_occupant_from_channels(ch, filtered=True)
    ch = frontal_channels()
    del ch["chest_deflection"]
    with pytest.raises(ValueError, match="'chest_deflection' is missing"):
        frontal_occupant_from_channels(ch, filtered=True)
    with pytest.raises(ValueError, match="Bharat NCAP 2.0"):
        frontal_occupant_from_channels(frontal_channels(), edition=2027)


def test_side_values_and_automatic_modifiers():
    occ = side_occupant_from_channels(side_channels(), filtered=True)
    assert occ.rib_deflection == pytest.approx(30.0)
    assert occ.abdominal_force == pytest.approx(1200.0)
    assert occ.pubic_force == pytest.approx(2000.0)
    assert occ.modifiers == {}
    ch = side_channels(backplate_fy=tri(-2500.0, 20, 20), t12_fy=tri(1800.0, 20, 20),
                       t12_mx=tri(120.0, 20, 20))
    occ = side_occupant_from_channels(ch, filtered=True, modifiers={"chest": 0.5,
                                                                    "head": 1.0})
    expected = 0.5 + backplate_modifier(2500.0) + t12_modifier(1800.0, 120.0)
    assert occ.modifiers["chest"] == pytest.approx(expected)
    assert occ.modifiers["head"] == 1.0
    assert set(SIDE_CHANNELS) >= {"backplate_fy", "t12_fy", "t12_mx"}


def test_pole_test_from_channels():
    assert pole_test_from_channels(side_channels(), head_contact=False, filtered=True)
    assert not pole_test_from_channels(side_channels(), head_contact=True,
                                       filtered=True)
    hard = side_channels(head_ay=tri(85.0, 30, 10))            # peak > 80 g
    assert not pole_test_from_channels(hard, head_contact=False, filtered=True)


def test_channels_from_isomme(tmp_path):
    named = frontal_channels()
    codes = {}
    units = {}
    for name, body in HYBRID3_ISOMME.items():
        if name not in named:
            continue                                         # no lower tibia
        code = "11" + body.replace("????", "0000") + "P"     # unfiltered
        codes[code] = named[name]
        units[code] = FRONTAL_CHANNELS[name][0].replace(" ", "")
    # Different units in the file: head in m/s^2, femur in kN.
    head_x = "11HEAD0000H3ACXP"
    codes[head_x] = (T, named["head_ax"][1] * 9.80665)
    units[head_x] = "m/s**2"
    femur = "11FEMRLE00H3FOZP"
    codes[femur] = (T, named["femur_fz_left"][1] / 1000.0)
    units[femur] = "kN"
    write_isomme(tmp_path, "T1", codes, units=units)
    test = read_isomme(tmp_path / "T1")

    raw = channels_from_isomme(test, position="1", filter=False)
    assert set(raw) == {n for n in named if n in HYBRID3_ISOMME}
    # The files store about 7 significant digits.
    np.testing.assert_allclose(raw["head_ax"][1], named["head_ax"][1], atol=1e-5)
    np.testing.assert_allclose(raw["femur_fz_left"][1], named["femur_fz_left"][1],
                               atol=1e-3)
    filtered = channels_from_isomme(test)
    occ = frontal_occupant_from_channels(filtered, filtered=True)
    direct = frontal_occupant_from_channels(named)
    assert occ.hic15 == pytest.approx(direct.hic15, rel=1e-5)
    assert occ.tibia_index == pytest.approx(direct.tibia_index, rel=1e-5)
    with pytest.raises(ValueError, match="No ISO-MME channel"):
        channels_from_isomme(test, position="3")


def test_isomme_wrong_filter_and_unit(tmp_path):
    write_isomme(tmp_path, "T2", {"11HEAD0000H3ACXB": (T, T)}, units={
        "11HEAD0000H3ACXB": "g"})
    test = read_isomme(tmp_path / "T2")
    with pytest.raises(ValueError, match="CFC 600"):
        channels_from_isomme(test, patterns={"head_ax": "HEAD0000H3ACX"})
    write_isomme(tmp_path, "T3", {"11NECKUP00H3FOZA": (T, T)}, units={
        "11NECKUP00H3FOZA": "lbf"})
    test = read_isomme(tmp_path / "T3")
    with pytest.raises(ValueError, match="unit 'lbf'"):
        channels_from_isomme(test, patterns={"neck_fz": "NECKUP00H3FOZ"})
