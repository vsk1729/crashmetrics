import csv
import math
from dataclasses import dataclass

import numpy as np
import pytest

from crashmetrics.features import (
    feature_table,
    flatten,
    head_features,
    pulse_features,
    signal_features,
    to_dataframe,
    to_matrix,
    write_csv,
)
from crashmetrics.pedestrian import calculate_hic
from crashmetrics.pulse import olc, pulse_summary

T = np.arange(0.0, 0.05, 1e-5)


def half_sine(amplitude=120.0, start=0.005, width=0.010, t=T):
    phase = (t - start) / width
    return np.where((phase > 0) & (phase < 1), amplitude * np.sin(np.pi * phase), 0.0)


# --- signal_features ---------------------------------------------------------


def test_half_sine_closed_form_features():
    f = signal_features(T, half_sine())
    width_ms = 10.0
    assert f["max"] == pytest.approx(120.0, rel=1e-6)
    assert f["t_max_ms"] == pytest.approx(10.0, abs=0.01)
    # integral of A sin over the pulse = 2 A T / pi
    assert f["integral"] == pytest.approx(2 * 120.0 * 0.010 / math.pi, rel=1e-4)
    assert f["abs_integral"] == pytest.approx(f["integral"])
    # 10 % to 90 % rise: (asin 0.9 - asin 0.1) / pi x width
    rise = (math.asin(0.9) - math.asin(0.1)) / math.pi * width_ms
    assert f["rise_ms"] == pytest.approx(rise, abs=0.01)
    # time above half the peak: 2/3 of the width
    assert f["width50_ms"] == pytest.approx(width_ms * 2 / 3, abs=0.02)
    onset = 5.0 + math.asin(0.05) / math.pi * width_ms
    assert f["onset_ms"] == pytest.approx(onset, abs=0.01)
    assert f["active_ms"] == pytest.approx(width_ms - 2 * (onset - 5.0), abs=0.02)
    # symmetric pulse: energy centroid and half-energy time at the peak
    assert f["centroid_ms"] == pytest.approx(10.0, abs=0.01)
    assert f["energy50_ms"] == pytest.approx(10.0, abs=0.01)
    assert f["excursions50"] == 1.0
    mean = f["integral"] / 0.05
    assert f["mean"] == pytest.approx(mean, rel=1e-3)
    rms = math.sqrt(120.0**2 / 2 * 0.010 / 0.05)
    assert f["rms"] == pytest.approx(rms, rel=1e-3)
    assert f["std"] == pytest.approx(math.sqrt(rms**2 - mean**2), rel=1e-3)


def test_timing_features_do_not_depend_on_sign():
    pos = signal_features(T, half_sine())
    neg = signal_features(T, -half_sine())
    for key in ("peak_abs", "t_peak_abs_ms", "onset_ms", "rise_ms", "width50_ms",
                "centroid_ms", "energy50_ms", "excursions50", "abs_integral"):
        assert neg[key] == pytest.approx(pos[key])
    assert neg["min"] == pytest.approx(-pos["max"])
    assert neg["integral"] == pytest.approx(-pos["integral"])


def test_two_impacts_give_two_excursions():
    x = half_sine(100.0, 0.005) + half_sine(80.0, 0.030)
    assert signal_features(T, x)["excursions50"] == 2.0


def test_dominant_frequency_of_a_sine():
    t = np.arange(0.0, 0.2, 1e-4)
    f = signal_features(t, np.sin(2 * np.pi * 200.0 * t))
    assert f["dominant_hz"] == pytest.approx(200.0, abs=5.0)
    assert f["spectral_centroid_hz"] == pytest.approx(200.0, rel=0.1)


def test_zero_signal_gives_nan_timing():
    f = signal_features(T, np.zeros_like(T))
    assert f["peak_abs"] == 0.0
    assert math.isnan(f["rise_ms"]) and math.isnan(f["centroid_ms"])
    assert f["excursions50"] == 0.0
    assert math.isnan(f["dominant_hz"])


def test_same_columns_for_every_signal():
    a = signal_features(T, half_sine())
    b = signal_features(T, np.zeros_like(T))
    assert list(a) == list(b)


def test_prefix_and_spectrum_switch():
    f = signal_features(T, half_sine(), prefix="chest_", spectrum=False)
    assert all(k.startswith("chest_") for k in f)
    assert "chest_dominant_hz" not in f


def test_time_offset_is_removed():
    shifted = signal_features(T + 1.0, half_sine())
    assert shifted["t_max_ms"] == pytest.approx(10.0, abs=0.01)
    assert shifted["centroid_ms"] == pytest.approx(10.0, abs=0.01)


def test_invalid_input_raises():
    with pytest.raises(ValueError):
        signal_features([0.0, 0.0, 1.0], [1.0, 2.0, 3.0])


def test_all_values_are_python_floats():
    f = signal_features(T, half_sine())
    assert all(type(v) is float for v in f.values())


# --- head_features and pulse_features ---------------------------------------


def test_head_features_match_the_criteria():
    a = half_sine()
    f = head_features(T, a)
    assert f["head_hic15"] == pytest.approx(calculate_hic(T, a).value)
    assert f["head_hic36"] == pytest.approx(calculate_hic(T, a, window_ms=36.0).value)
    assert f["head_peak_g"] == pytest.approx(120.0, rel=1e-6)
    assert f["head_colour"] == "yellow"
    assert f["head_hic15_t1_ms"] < f["head_t_peak_ms"] < f["head_hic15_t2_ms"]
    assert "head_rise_ms" in f and "head_peak_abs" not in f
    assert all(type(v) in (float, str) for v in f.values())


def test_head_features_short_record_has_no_hic36_and_no_warning(recwarn):
    t = np.arange(0.0, 0.03, 1e-5)
    f = head_features(t, half_sine(t=t), shape=False)
    assert math.isnan(f["head_hic36"])
    assert not recwarn.list
    assert set(f) == {"head_hic15", "head_hic15_t1_ms", "head_hic15_t2_ms",
                      "head_hic36", "head_a3ms", "head_peak_g", "head_t_peak_ms",
                      "head_colour"}


def test_pulse_features_match_pulse_summary():
    t = np.arange(0.0, 0.15, 1e-4)
    v0 = 50 / 3.6
    a = np.where(t < 0.1, -1.15 * v0 * np.pi / 0.2 * np.sin(np.pi * t / 0.1), 0.0)
    f = pulse_features(t, a, v0)
    s = pulse_summary(t, a, v0=v0)
    assert f["pulse_olc_g"] == pytest.approx(olc(t, a, v0=v0).value)
    assert f["pulse_delta_v"] == pytest.approx(s.delta_v)
    assert f["pulse_restitution"] == pytest.approx(0.15, abs=0.01)
    assert f["pulse_max_crush_mm"] == pytest.approx(s.max_displacement * 1000)
    assert f["pulse_peak_decel_g"] == pytest.approx(s.peak_deceleration / 9.81)
    assert f["pulse_min"] == pytest.approx(a.min() / 9.81)
    assert f["pulse_integral"] == pytest.approx(-s.delta_v / 9.81, rel=1e-3)


# --- flatten ----------------------------------------------------------------


@dataclass
class Inner:
    points: float
    band: str


@dataclass
class Outer:
    total: np.float64
    passed: np.bool_
    count: np.int64
    regions: dict
    limits: tuple
    curve: np.ndarray
    note: None = None


def test_flatten_nested_results():
    obj = Outer(np.float64(7.5), np.bool_(True), np.int64(3),
                {"head": Inner(4.0, "green"), "chest": Inner(1.2, "orange")},
                (500.0, 700.0), np.arange(5))
    flat = flatten(obj, prefix="mpdb.")
    assert flat == {
        "mpdb.total": 7.5,
        "mpdb.passed": True,
        "mpdb.count": 3,
        "mpdb.regions.head.points": 4.0,
        "mpdb.regions.head.band": "green",
        "mpdb.regions.chest.points": 1.2,
        "mpdb.regions.chest.band": "orange",
        "mpdb.limits.0": 500.0,
        "mpdb.limits.1": 700.0,
        "mpdb.note": None,
    }
    assert type(flat["mpdb.total"]) is float and type(flat["mpdb.count"]) is int


def test_flatten_plain_value_and_separator():
    assert flatten(3.0) == {"value": 3.0}
    assert flatten({"a": {"b": 1}}, sep="_") == {"a_b": 1}
    assert flatten({"long": list(range(100))}) == {}


def test_flatten_real_score():
    from crashmetrics.pedestrian import calculate_hic

    flat = flatten(calculate_hic(T, half_sine()))
    assert set(flat) == {"value", "start_time", "end_time"}


# --- feature_table and output ------------------------------------------------


def runs():
    return {"r1": 100.0, "r2": 120.0, "bad": -1.0}


def extract(amplitude):
    if amplitude < 0:
        raise ValueError("negative amplitude")
    shape = signal_features(T, half_sine(amplitude), spectrum=False)
    return [{"amp": amplitude}, shape]


def test_feature_table_rows_params_and_errors():
    params = {"r1": {"thickness": 1.0}, "r2": {"thickness": 1.2}}
    rows = feature_table(runs(), extract, params=params)
    assert [r["run"] for r in rows] == ["r1", "r2", "bad"]
    assert rows[0]["thickness"] == 1.0 and rows[0]["amp"] == 100.0
    assert rows[1]["max"] == pytest.approx(120.0, rel=1e-6)
    assert rows[2] == {"run": "bad", "error": "ValueError: negative amplitude"}


def test_feature_table_accepts_pairs_and_can_raise():
    rows = feature_table([("a", 50.0)], extract, id_column="case")
    assert rows[0]["case"] == "a"
    with pytest.raises(ValueError, match="negative"):
        feature_table(runs(), extract, on_error="raise")
    with pytest.raises(ValueError, match="on_error"):
        feature_table(runs(), extract, on_error="ignore")


def test_write_csv_union_of_columns(tmp_path):
    rows = feature_table(runs(), extract)
    path = tmp_path / "features.csv"
    columns = write_csv(rows, path)
    assert columns[0] == "run" and columns[-1] == "error"
    with open(path, newline="") as file:
        read = list(csv.DictReader(file))
    assert len(read) == 3
    assert read[2]["error"] == "ValueError: negative amplitude" and read[2]["max"] == ""
    assert float(read[0]["max"]) == pytest.approx(100.0, rel=1e-6)


def test_to_matrix_selects_numeric_columns():
    rows = feature_table(runs(), extract)
    names, x = to_matrix(rows)
    assert "run" not in names and "error" not in names
    assert x.shape == (3, len(names))
    assert x[0, names.index("amp")] == 100.0
    assert np.isnan(x[2]).all()


def test_to_matrix_explicit_columns_and_bools():
    rows = [{"a": 1, "ok": True}, {"a": 2.5, "ok": False}, {"ok": None}]
    names, x = to_matrix(rows, ["a", "ok"])
    np.testing.assert_array_equal(x, [[1, 1], [2.5, 0], [np.nan, np.nan]])
    with pytest.raises(ValueError, match="non-numeric"):
        to_matrix([{"a": "x"}], ["a"])


def test_to_dataframe():
    pd = pytest.importorskip("pandas")
    df = to_dataframe(feature_table(runs(), extract))
    assert isinstance(df, pd.DataFrame)
    assert list(df["run"]) == ["r1", "r2", "bad"]
    assert df.columns[-1] == "error"
