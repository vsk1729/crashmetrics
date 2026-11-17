"""Tests for crashmetrics.deck (keyword deck reader, checks, load case, edits).

Real decks (``tests/data/lsdyna``, MIT) are compared with what LS-DYNA
itself printed for them (``d3hsp``); synthetic decks cover the formats
and keywords those decks do not use.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from crashmetrics import deck as dk
from crashmetrics.deck._fields import format_value, replace_field, split_line, to_float
from crashmetrics.deck.reader import evaluate

DATA = Path(__file__).parent / "data" / "lsdyna"
COLD = DATA / "kagent" / "cold_start" / "ball_drop.k"
CRASH = DATA / "kagent" / "crash" / "crash.k"
IMPACT = DATA / "lsprepost_mcp" / "impact.k"
BROKEN = DATA / "lsprepost_mcp" / "impact_broken.k"
PLADE = DATA / "pladebuk" / "deck" / "main.k"


def f10(*values: object) -> str:
    """A fixed-format card of 10-character fields."""
    return "".join(f"{v:>10}" for v in values)


# --------------------------------------------------------------------------
# Real decks against the solver's own numbers


def test_cold_start_matches_d3hsp():
    deck = dk.read_deck(COLD)
    assert len(deck.files) == 3 and not deck.notes
    assert deck.info.title.startswith("cold start: steel ball drop")
    s = dk.model_summary(deck)
    assert s.unit_system == "mm-s-t"
    assert s.nodes == 988 and s.elements == {"shell": 900, "solid": 8}
    # d3hsp of the same run (R14.1.1): part masses and mass centre
    assert s.part(1).mass == pytest.approx(1.2149954e-04, rel=1e-5)  # single precision
    assert s.part(2).mass == pytest.approx(1.2569384e-05, rel=1e-6)
    assert s.cg[2] == pytest.approx(2.8125846, rel=1e-6)  # model mass centre
    assert s.part(2).rigid and s.part(1).thickness == 2.0
    assert s.mass_kg == pytest.approx(0.134069, rel=1e-5)
    ts = dk.time_steps(deck)
    assert ts.dt == pytest.approx(8.4091e-07, rel=1e-4)  # d3hsp smallest step
    assert ts.skipped == {"rigid (solid)": 8}
    sheet = dk.check_deck(deck)
    assert sheet.passed and not sheet.warnings
    lc = dk.load_case(deck)
    assert lc.end_time == pytest.approx(3e-3)
    assert lc.kmh(lc.speeds[0]) == pytest.approx(14.4)
    assert lc.energy == {"hgen": 2, "rwen": 2, "slnten": 2, "rylen": 2}
    assert lc.outputs["GLSTAT"].binary == 0 and lc.outputs["GLSTAT"].ascii


def test_real_decks_checks_and_versions():
    broken = dk.check_deck(dk.read_deck(BROKEN))
    assert not broken.passed
    (fail,) = broken.failures
    assert fail.name == "Missing sections" and "3: *PART" in fail.items[0]
    assert dk.check_deck(dk.read_deck(IMPACT)).passed
    assert dk.check_deck(dk.read_deck(CRASH)).passed

    plade = dk.read_deck(PLADE)
    info = plade.info
    assert info.version == "LS-PrePost 2024/R2(4.11.14)-25Feb2025"
    assert "CONTROL_IMPLICIT_SOLVER" in info.unknown
    assert any("geometry.k" in n and "not found" in n for n in plade.notes)
    sheet = dk.check_deck(plade)
    assert "Include files" in [c.name for c in sheet.failures]
    lc = dk.load_case(plade)
    assert lc.implicit and lc.unit_system is None
    assert lc.outputs["NODOUT"].binary == 3
    # *PARAMETER_DUPLICATION and titled curves are read
    assert len(dk.curves(plade)) >= 14


def test_crash_round_trip_and_edits(tmp_path):
    deck = dk.read_deck(CRASH)
    out = tmp_path / "same"
    deck.write(out)
    for name in ("crash.k", "mesh_tube.k"):
        assert (out / name).read_bytes() == (CRASH.parent / name).read_bytes()

    dk.set_thickness(deck, 1, 1.8)
    dk.set_end_time(deck, 6e-3)
    assert dk.set_initial_velocity(deck, speed=1.5e4) == 1
    done = dk.prepare_outputs(
        deck, ["quality", "contacts", "nodes"], 1e-5, node_dt=1e-6
    )
    assert "SLEOUT every 1e-05" in done and "NODOUT every 1e-06" in done
    dk.add_history_nodes(deck, [1, 2, 3])
    written = deck.write(tmp_path / "edit", only_modified=True)
    assert [p.name for p in written] == ["crash.k"]
    before = CRASH.read_text().splitlines()[:-1]  # new blocks go before *END
    after = written[0].read_text().splitlines()
    changed = [a for a, b in zip(before, after) if a != b]
    assert len(changed) == 3  # thickness, end time, velocity lines

    again = dk.read_deck(written[0])
    assert dk.model_summary(again).part(1).thickness == 1.8
    assert dk.load_case(again).speeds[0] == pytest.approx(1.5e4)
    req = dk.output_requirements(again, ["quality", "contacts", "nodes"])
    assert req.passed


# --------------------------------------------------------------------------
# Fields


def test_fields():
    assert to_float("1.5+3") == 1500.0 and to_float("2.0D-1") == 0.2
    assert to_float("") == 0.0
    assert format_value(0.1, 10, "f").strip() == "0.1"
    assert format_value(2.1e5, 10, "f").strip() in ("210000.0", "2.1E+5")
    assert len(format_value(1 / 3, 10, "f")) == 10
    assert float(format_value(1 / 3, 10, "f")) == pytest.approx(1 / 3, rel=1e-6)
    with pytest.raises(ValueError):
        format_value(12345678901, 10, "i")
    (a, sa), (b, sb) = split_line("  1,2.5", [10, 10])
    assert (a, b) == ("1", "2.5") and sb.comma
    assert replace_field("1,2.5,3", sb, "7.0") == "1,7.0,3"
    ((_, slot),) = split_line("         1", [10])
    assert replace_field("         1", slot, format_value(42, 10, "i")).endswith("42")


def test_parameter_expressions():
    names = {"a": 2.0, "b": 3.0}.__getitem__
    assert evaluate("a*b + 2^2", names) == 10.0
    assert evaluate("sqrt(a*8) + max(a, b)", names) == 7.0
    with pytest.raises(ValueError):
        evaluate("__import__('os')", names)


# --------------------------------------------------------------------------
# Synthetic decks: formats, includes, parameters, keywords


PLATE = "\n".join(
    [
        "*KEYWORD",
        "*TITLE",
        "synthetic plate",
        "*PARAMETER",
        "R thick   1.5       I mat     7",
        "*PARAMETER_EXPRESSION",
        "R twice   thick*2",
        "*PART",
        "plate",
        f10(1, 1, "&mat"),
        "*SECTION_SHELL",
        f10(1, 2),
        f10("&thick", "&thick", "&thick", "&thick"),
        "*MAT_ELASTIC",
        f10(7, "7.85E-9", "2.1E+5", 0.3),
        "*NODE",
        f"{1:8d}{0.0:16.1f}{0.0:16.1f}{0.0:16.1f}",
        f"{2:8d}{10.0:16.1f}{0.0:16.1f}{0.0:16.1f}",
        f"{3:8d}{10.0:16.1f}{10.0:16.1f}{0.0:16.1f}",
        f"{4:8d}{0.0:16.1f}{10.0:16.1f}{0.0:16.1f}",
        "*ELEMENT_SHELL",
        f"{1:8d}{1:8d}{1:8d}{2:8d}{3:8d}{4:8d}",
        "*SET_NODE_LIST_GENERATE",
        f10(5),
        f10(1, 3),
        "*SET_NODE_ADD",
        f10(6),
        f10(5),
        "*DEFINE_CURVE",
        f10(9, 0, 2.0, 0.5),
        f"{0.0:20}{0.0:20}",
        f"{1.0:20}{1.0:20}",
        "*ELEMENT_MASS",
        f"{1:8d}{3:8d}{0.25:16}",
        "*CONTROL_TERMINATION",
        f10(5.0),
        "*END",
        "",
    ]
)


def test_parameters_sets_curves_masses():
    deck = dk.parse_deck(PLATE)
    assert deck.parameters["thick"].value == 1.5
    assert deck.parameters["twice"].value == 3.0
    sec = next(deck.records("SECTION_SHELL"))
    assert sec["t1"] == 1.5 and sec.params["t1"] == "thick"
    part = dk.part_card(deck, 1)
    assert part["mid"] == 7
    s = dk.model_summary(deck, "mm-s-t")
    assert s.part(1).mass == pytest.approx(100 * 1.5 * 7.85e-9)
    assert s.lumped_mass == pytest.approx(0.25)
    st = dk.sets(deck)
    assert st[("node", 5)].members == [1, 2, 3]
    assert st[("node", 6)].members == [1, 2, 3] and st[("node", 6)].add == [5]
    c = dk.curves(deck)[9]
    np.testing.assert_allclose(c.x, [0.0, 2.0])
    np.testing.assert_allclose(c.y, [0.0, 0.5])
    (m,) = dk.mass_elements(deck)
    assert (m.kind, m.target, m.mass) == ("node", 3, 0.25)

    with pytest.raises(ValueError, match="parameter"):
        sec.set("t1", 2.0)
    dk.set_parameter(deck, "thick", 2.0)
    assert next(deck.records("SECTION_SHELL"))["t1"] == 2.0
    assert deck.parameters["twice"].value == 4.0
    assert deck.text().splitlines()[4] == "R thick          2.0I mat     7"


def test_long_comma_and_percent_formats():
    long_deck = "\n".join(
        [
            "*KEYWORD LONG=Y",
            "*PART",
            "long part",
            f"{1:>20}{2:>20}{3:>20}",
            "*SECTION_SHELL",
            f"{2:>20}{16:>20}",
            f"{1.2:>20}{1.2:>20}{1.2:>20}{1.2:>20}",
            "*MAT_RIGID",
            f"{3:>20}{'7.85E-9':>20}{'2.1E+5':>20}{0.3:>20}",
            "*NODE",
            f"{1:>20}{0.0:>20}{0.0:>20}{0.0:>20}",
            "*END",
        ]
    )
    deck = dk.parse_deck(long_deck)
    assert deck.long_format and deck.info.long_format
    sec = next(deck.records("SECTION_SHELL"))
    assert sec["elform"] == 16 and sec["t1"] == 1.2
    sec.set("t1", 1.25)
    assert deck.text().splitlines()[6] == f"{1.25:>20}" + f"{1.2:>20}" * 3

    comma = (
        "*KEYWORD\n*PART\ncomma part\n1, 2, 3\n"
        "*SECTION_SHELL\n2,16\n1.0,1.0,1.0,1.0\n*END"
    )
    deck = dk.parse_deck(comma)
    sec = next(deck.records("SECTION_SHELL"))
    sec.set("t2", 0.75)
    assert "1.0,0.75,1.0,1.0" in deck.text()

    pct = "*KEYWORD\n*NODE %\n" + f"{123456789:10d}{1.0:16}{2.0:16}{3.0:16}\n*END"
    n = dk.nodes(dk.parse_deck(pct))
    assert n.ids.tolist() == [123456789]
    np.testing.assert_allclose(n.xyz, [[1.0, 2.0, 3.0]])


def test_includes_transform_and_local_parameters(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "part.k").write_text(
        "\n".join(
            [
                "*KEYWORD",
                "*PARAMETER_LOCAL",
                "R t       0.8",
                "*PART",
                "included",
                f10(1, 1, 1),
                "*SECTION_SHELL",
                f10(1),
                f10("&t", "&t", "&t", "&t"),
                "*MAT_ELASTIC",
                f10(1, "7.85E-9", "2.1E+5", 0.3),
                "*NODE",
                f"{1:8d}{0.0:16}{0.0:16}{0.0:16}",
                f"{2:8d}{1.0:16}{0.0:16}{0.0:16}",
                f"{3:8d}{1.0:16}{1.0:16}{0.0:16}",
                "*ELEMENT_SHELL",
                f"{1:8d}{1:8d}{1:8d}{2:8d}{3:8d}{3:8d}",
                "*END",
            ]
        )
    )
    (tmp_path / "main.k").write_text(
        "\n".join(
            [
                "*KEYWORD",
                "*INCLUDE_PATH_RELATIVE",
                "sub",
                "*INCLUDE",
                "part.k",
                "*INCLUDE_TRANSFORM",
                "part.k",
                f10(1000, 1000, 100, 100, 100, 100, 100),
                f10(0),
                f10(0.0, 0.0, 0.0),
                f10(1),
                "*DEFINE_TRANSFORMATION",
                f10(1),
                f10("TRANSL", 0.0, 0.0, 50.0),
                "*INCLUDE",
                "missing.k",
                "*END",
            ]
        )
    )
    deck = dk.read_deck(tmp_path / "main.k")
    assert len(deck.files) == 3
    assert any("missing.k" in n for n in deck.notes)
    n = dk.nodes(deck)
    assert sorted(n.ids.tolist()) == [1, 2, 3, 1001, 1002, 1003]
    np.testing.assert_allclose(n.xyz[n.index([1003])][0], [1.0, 1.0, 50.0])
    s = dk.model_summary(deck, "mm-s-t")
    assert {p.id for p in s.parts} == {1, 101}
    assert s.part(101).thickness == 0.8 and s.part(101).cg[2] == pytest.approx(50)
    sheet = dk.check_deck(deck)
    assert "Include files" in [c.name for c in sheet.failures]
    assert not any("Duplicate" in c.name for c in sheet.checks if c.status != "PASS")


def test_duplicates_and_missing_references():
    text = "\n".join(
        [
            "*KEYWORD",
            "*PART",
            "a",
            f10(1, 1, 1),
            "*PART",
            "b",
            f10(1, 1, 9),
            "*SECTION_SHELL",
            f10(1),
            f10(1.0, 1.0, 1.0, 1.0),
            "*MAT_ELASTIC",
            f10(1, "7.85E-9", "2.1E+5", 0.3),
            "*END",
        ]
    )
    sheet = dk.check_deck(dk.parse_deck(text), unit_system="mm-s-t")
    names = {c.name for c in sheet.failures}
    assert "Duplicate parts" in names and "Missing materials" in names


def test_contact_id_mpp_and_parts():
    text = "\n".join(
        [
            "*KEYWORD",
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID_MPP",
            f10(7) + "  my contact",
            f10(1, 1, 0, 0, 0, 0, 0, 0),
            f10(1, 2, 3, 3),
            f10(0.3, 0.2),
            "",
            "*END",
        ]
    )
    deck = dk.parse_deck(text)
    (c,) = deck.records("CONTACT_*")
    assert c["ssid"] == 1 and c["msid"] == 2 and c["fs"] == 0.3
    lc = dk.load_case(deck)
    assert "part 1 / part 2" in lc.contacts[0]


def test_write_variants(tmp_path):
    from crashmetrics.doe import latin_hypercube

    src = tmp_path / "plate.k"
    src.write_text(PLATE)
    design = latin_hypercube({"thick": (1.0, 2.0), "end": (2.0, 4.0)}, 3, seed=1)
    table = dk.write_variants(
        src,
        design,
        tmp_path / "runs",
        setters={"end": dk.set_end_time},
    )
    rows = table.read_text().splitlines()
    assert rows[0] == "run,thick,end" and len(rows) == 4
    for i, row in enumerate(design.values, 1):
        d = dk.read_deck(tmp_path / "runs" / f"run_{i:03d}" / "plate.k")
        assert d.parameters["thick"].value == pytest.approx(row[0], rel=1e-6)
        assert dk.load_case(d).end_time == pytest.approx(row[1], rel=1e-6)


def test_thickness_shared_sections():
    text = PLATE.replace(
        "*SECTION_SHELL", "*PART\nsecond\n" + f10(2, 1, 7) + "\n*SECTION_SHELL", 1
    ).replace(f10("&thick", "&thick", "&thick", "&thick"), f10(1.0, 1.0, 1.0, 1.0))
    deck = dk.parse_deck(text)
    with pytest.raises(ValueError, match="also used by parts"):
        dk.set_thickness(deck, 1, 2.0)
    new = dk.set_thickness(deck, 1, 2.0, shared="copy")
    assert new == 2
    assert dk.part_card(deck, 1)["secid"] == 2 and dk.part_card(deck, 2)["secid"] == 1
    s = dk.model_summary(deck, "mm-s-t")
    assert s.part(1).thickness == 2.0
    assert not dk.check_deck(deck, unit_system="mm-s-t").failures


def test_cli(capsys, tmp_path):
    code = dk.main([str(CRASH), "--csv", str(tmp_path / "parts.csv")])
    out = capsys.readouterr().out
    assert code == 0 and "20.27 kg" in out and "tube self contact" in out
    assert (tmp_path / "parts.csv").read_text().startswith("part,")
    assert dk.main([str(BROKEN)]) == 1


def test_time_step_with_mass_scaling():
    deck = dk.read_deck(CRASH)
    dk.set_mass_scaling(deck, -6e-7)
    ts = dk.time_steps(deck)
    assert ts.added_mass > 0
    assert ts.added_mass / ts.model_mass < 0.5
    assert not math.isnan(ts.dt)
