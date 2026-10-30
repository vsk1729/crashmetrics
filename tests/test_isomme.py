"""Tests for crashmetrics.isomme (ISO-MME read and write).

The fixtures in tests/data/isomme are from pyisomme (MIT licence, see
tests/data/isomme/LICENSE): three channels, 20 samples at 10 kHz from
-0.5 ms, written in ASCII, Windows-1252 and UTF-8 (zip). They cover a
time channel without a time base, an explicit reference time channel,
an implicit time base, one NOVALUE sample, a colon inside a value, an
empty value and tab padding.
"""

from pathlib import Path

import numpy as np
import pytest

from crashmetrics.isomme import (
    FILTER_CLASSES,
    parse_channel_code,
    read_isomme,
    write_isomme,
)

DATA = Path(__file__).parent / "data" / "isomme"
TIMES = -0.0005 + 1e-4 * np.arange(20)
HEAD = "11HEADCG0000ACXP"
CHEST = "11CHST0000H3DSXP"
TIME_CHANNEL = "11TIRS000000TIRP"


@pytest.mark.parametrize("path", [
    DATA / "ascii", DATA / "ascii" / "test.mme", DATA / "windows-1252",
    DATA / "utf-8.zip",
])
def test_fixture_structure(path):
    test = read_isomme(path)
    assert list(test.channels) == [TIME_CHANNEL, HEAD, CHEST]
    time_channel = test.channels[TIME_CHANNEL]
    head, chest = test.channels[HEAD], test.channels[CHEST]
    assert time_channel.time is None                    # no time base given
    np.testing.assert_allclose(time_channel.values, TIMES)
    np.testing.assert_allclose(head.time, TIMES)        # explicit reference channel
    np.testing.assert_allclose(chest.time, TIMES)       # implicit first sample + step
    assert head.values.max() == 42.0 and int(np.argmax(head.values)) == 15
    assert np.isnan(chest.values[12]) and np.isfinite(chest.values).sum() == 19
    assert head.unit == "g" and head.cfc == 1000 and chest.cfc == 600


def test_ascii_header_traps():
    test = read_isomme(DATA / "ascii")
    assert test.test_number == "test"
    assert test.info("Laboratory name") == "MGA Research Corporation"
    assert test.header["Comments"] == [
        "Time zero: first contact with the barrier face",        # colon in value
        "Chest deflection channel: IR-TRACC, 50 % ile Hybrid III",
    ]
    assert test.info("Regulation") == ""                         # empty value
    assert test.info("Movie reference") == ""                    # NOVALUE, tab
    assert test.info("Impact velocity") == "56.3"
    head = test.channels[HEAD]
    assert head.info("Reference channel") == "explicit"
    assert head.info("Transducer type", "unknown") == "unknown"   # NOVALUE


@pytest.mark.parametrize("path, text", [
    (DATA / "windows-1252", "Renault S.A. — Direction de la Sécurité"),
    (DATA / "utf-8.zip", "トヨタ自動車株式会社 (Toyota Motor Corp.)"),
])
def test_encodings(path, text):
    test = read_isomme(path)
    assert test.info("Customer name") == text
    assert test.channels[CHEST].name == "Brustkorb-Eindrückung X (µm)"


def test_find_and_channel_lookup():
    test = read_isomme(DATA / "ascii")
    assert [c.code for c in test.find("11??????????ACX?")] == [HEAD]
    assert test.channel("??CHST*").code == CHEST
    assert test.channel(HEAD).name == "Head CG X acceleration"
    with pytest.raises(KeyError, match="3 channels match"):
        test.channel("11*")
    with pytest.raises(KeyError, match="0 channels match"):
        test.channel("12*")
    text = test.summary()
    assert "3 channels" in text and "-0.50 to 1.40 ms" in text


def test_parse_channel_code():
    c = parse_channel_code("13HEAD0000H3ACXA")
    assert (c.test_object, c.position, c.main_location) == ("1", "3", "HEAD")
    fine = (c.fine_location_1, c.fine_location_2, c.fine_location_3)
    assert fine == ("00", "00", "H3")
    assert (c.dimension, c.direction, c.filter_class, c.cfc) == ("AC", "X", "A", 1000)
    assert parse_channel_code("11CHST0000H3DSX0").cfc is None
    assert FILTER_CLASSES["D"] == 60
    with pytest.raises(ValueError, match="16 characters"):
        parse_channel_code("11HEAD")


def test_write_and_read_back(tmp_path):
    t = np.arange(0.0, 0.0105, 1e-4)
    ax = 40.0 * np.sin(np.pi * t / 0.0105)
    deflection = np.linspace(0.0, 30.0, len(t))
    deflection[5] = np.nan
    folder = write_isomme(
        tmp_path, "VT_LC1",
        {"11HEAD0000H3ACXA": (t, ax), "11CHST0000H3DSXC": (t, deflection)},
        units={"11HEAD0000H3ACXA": "g", "11CHST0000H3DSXC": "mm"},
        names={"11HEAD0000H3ACXA": "Head CoG acceleration X"},
        header={"Test type": "Virtual testing", "Comments": ["one", "two: three"]},
    )
    assert folder == tmp_path / "VT_LC1"
    back = read_isomme(folder)
    assert back.test_number == "VT_LC1"
    assert back.info("Test type") == "Virtual testing"
    assert back.header["Comments"] == ["one", "two: three"]
    head = back.channels["11HEAD0000H3ACXA"]
    np.testing.assert_allclose(head.time, t, atol=1e-12)
    np.testing.assert_allclose(head.values, ax, rtol=1e-6)
    assert head.unit == "g" and head.cfc == 1000
    assert head.name == "Head CoG acceleration X"
    assert head.info("Data source") == "calculated"
    chest = back.channels["11CHST0000H3DSXC"]
    assert np.isnan(chest.values[5]) and chest.cfc == 180 and chest.name == ""


def test_write_errors(tmp_path):
    t = np.arange(0.0, 0.001, 1e-4)
    with pytest.raises(ValueError, match="at least one"):
        write_isomme(tmp_path, "x", {})
    with pytest.raises(ValueError, match="16 characters"):
        write_isomme(tmp_path, "x", {"HEAD": (t, t)})
    uneven = np.array([0.0, 1e-4, 3e-4])
    with pytest.raises(ValueError, match="uniformly"):
        write_isomme(tmp_path, "x", {"11HEAD0000H3ACXA": (uneven, uneven)})
    with pytest.raises(ValueError, match="equal length"):
        write_isomme(tmp_path, "x", {"11HEAD0000H3ACXA": (t, t[:-1])})


def test_read_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_isomme(tmp_path / "missing")
    with pytest.raises(ValueError, match="No .mme"):
        read_isomme(tmp_path)
    test = tmp_path / "bad"
    (test / "Channel").mkdir(parents=True)
    (test / "bad.mme").write_text("Data format :ISO-MME\n")
    (test / "Channel" / "bad.001").write_text(
        "Channel code :11HEAD0000H3ACXA\n1.0\nabc\n")
    with pytest.raises(ValueError, match="Unexpected line"):
        read_isomme(test)
