import pytest

from crashmetrics.pedestrian.ais100 import (
    AIS100_FLEXPLI_LIMITS,
    AIS100_LEGACY_LEGFORM_LIMITS,
    AIS100_UPPER_LEGFORM_LIMITS,
    bumper_legform,
    check_flexpli,
    check_headform_tests,
    check_headform_zones,
    check_legacy_legform,
    check_relaxation_width,
    check_upper_legform_bumper,
)


def test_limits_from_ais_100():
    assert AIS100_FLEXPLI_LIMITS == {"mcl": 22.0, "acl": 13.0, "pcl": 13.0,
                                     "tibia_moment": 340.0,
                                     "tibia_moment_relaxed": 380.0}
    assert AIS100_LEGACY_LEGFORM_LIMITS == {
        "knee_bending_angle": 19.0, "knee_shear_displacement": 6.0,
        "tibia_acceleration": 170.0, "tibia_acceleration_relaxed": 250.0}
    assert AIS100_UPPER_LEGFORM_LIMITS == {"sum_of_forces": 7500.0,
                                           "bending_moment": 510.0}


def test_bumper_legform_choice():
    assert bumper_legform(424.9) == "lower_legform"
    assert bumper_legform(425.0) == "either"
    assert bumper_legform(499.9) == "either"
    assert bumper_legform(500.0) == "upper_legform"


def test_flexpli_check():
    ok = check_flexpli(330.0, 21.0, 12.0, -8.0)
    assert ok.passed and ok.worst == "tibia_moment"
    assert ok.utilisation["acl"] == pytest.approx(12.0 / 13.0)
    fail = check_flexpli(360.0, 21.0, 12.0, 8.0)
    assert not fail.passed
    assert check_flexpli(360.0, 21.0, 12.0, 8.0, relaxed_zone=True).passed
    assert not check_flexpli(300.0, 22.5, 1.0, 1.0).passed


def test_legacy_legform_check():
    assert check_legacy_legform(18.0, 5.5, 160.0).passed
    assert not check_legacy_legform(18.0, 5.5, 200.0).passed
    assert check_legacy_legform(18.0, 5.5, 200.0, relaxed_zone=True).passed
    assert not check_legacy_legform(19.5, 5.5, 100.0).passed


def test_upper_legform_and_relaxation_width():
    assert check_upper_legform_bumper(7400.0, 500.0).passed
    assert not check_upper_legform_bumper(7600.0, 500.0).passed
    assert check_relaxation_width([132.0, 132.0]).passed
    assert not check_relaxation_width([150.0, 120.0]).passed


def test_headform_zones():
    # Child 0.6 m2 with 0.35 HIC1000 (58 %); adult 0.4 with 0.32: total 67 %.
    ok = check_headform_zones(0.6, 0.4, 0.35, 0.32)
    assert ok.passed
    assert ok.values["total_share"] == pytest.approx(0.67)
    # Child share below one half fails even with a large total share.
    assert not check_headform_zones(0.6, 0.6, 0.29, 0.6).passed
    # Total share below two thirds fails.
    assert not check_headform_zones(0.6, 0.4, 0.4, 0.2).passed
    only_child = check_headform_zones(0.9, 0.0, 0.6, 0.0)
    assert only_child.passed and only_child.notes == ("child headform test area only",)
    assert not check_headform_zones(0.9, 0.0, 0.59, 0.0).passed
    with pytest.raises(ValueError):
        check_headform_zones(0.6, 0.4, 0.7, 0.1)


def test_headform_tests():
    result = check_headform_tests([("hic1000", 850.0), ("hic1000", 990.0),
                                   ("hic1700", 1500.0)])
    assert result.passed and result.values == {"hic1000": 990.0, "hic1700": 1500.0}
    assert not check_headform_tests([("hic1000", 1010.0)]).passed
    assert not check_headform_tests([("hic1700", 1750.0)]).passed
    with pytest.raises(ValueError, match="zone"):
        check_headform_tests([("hic2000", 100.0)])
