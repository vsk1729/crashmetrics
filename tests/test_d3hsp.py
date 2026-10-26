"""Tests for the d3hsp reader.

The base file is a real LS-DYNA R14.1.1 SMP d3hsp excerpt (see
tests/data/lsdyna/README.md); expected values were taken from the raw
file with grep. The variants (R16 mass summary, MPP, error termination,
messages, incomplete run) edit that text following layouts seen in real
d3hsp files.
"""

from pathlib import Path

import pytest

from crashmetrics.d3hsp import parse_d3hsp, read_d3hsp
from crashmetrics.lsdyna import read_d3hsp as read_d3hsp_from_lsdyna

EXCERPT = Path(__file__).parent / "data/lsdyna/kagent/cold_start/d3hsp_excerpt"
TEXT = EXCERPT.read_text()


@pytest.fixture(scope="module")
def real():
    return read_d3hsp(EXCERPT)


def test_run_information(real):
    assert real.version == "smp s R14"
    assert (real.parallel, real.precision, real.release) == ("smp", "single", "R14")
    assert real.revision == "R14.1.1-4-gaf1eb871e8"
    assert real.platform == "WINDOWS X64 SSE2"
    assert real.hostname == "HOSTNAME"
    assert real.run_date == "10/23/2026 14:41:57"
    assert real.command_line == ("i=ball_drop.k", "ncpu=4", "memory=200m")
    assert real.input_file == "ball_drop.k"
    assert real.ncpu == 4


def test_termination(real):
    assert real.termination == "normal"
    assert real.normal_termination
    assert real.termination_time == "10/23/26 14:41:58"
    assert real.messages == ()


def test_model_size_and_settings(real):
    assert real.model["nodes"] == 988
    assert real.model["solid_elements"] == 8
    assert real.model["shell_elements"] == 900
    assert real.model["materials"] == 2
    assert real.model["contacts"] == 1
    assert real.parameters["termination_time"] == pytest.approx(3.0e-3)
    assert real.parameters["time_step_scale_factor"] == pytest.approx(0.9)
    assert real.parameters["time_step_size_for_mass_scaled_solution_dt2ms"] == 0.0
    # Labels that start with "#" and labels ending in a single dot.
    assert real.parameters["number_of_solid_elements_with_death_times"] == 0
    assert "number_of_shells_with_extra_degrees_of_freedom" in real.parameters


def test_keyword_counts(real):
    assert len(real.keyword_counts) == 640  # grep -c "total # of"
    assert real.keyword_counts["*NODE"] == 988
    assert real.keyword_counts["*ELEMENT_SHELL_option"] == 900
    assert real.keyword_counts["*PART_option card"] == 2
    # Long names that fill their field (one dot or none) are kept whole.
    assert "*CONSTRAINED_SPR2/INTERPOLATION_SPOTWELD" in real.keyword_counts
    assert "*BOUNDARY_ACOUSTIC_COUPLING_DISSIPATIVE" in real.keyword_counts


def test_mass_summary(real):
    assert real.part_masses == {1: pytest.approx(0.12149954e-3),
                                2: pytest.approx(0.12569384e-4)}
    assert real.rigid_parts == (2,)
    assert real.total_mass == pytest.approx(0.13406892e-3)
    assert sum(real.part_masses.values()) == pytest.approx(real.total_mass)


def test_smallest_timesteps(real):
    assert len(real.smallest_timesteps) == 100
    first = real.smallest_timesteps[0]
    assert (first.element_type, first.element_id, first.part_id) == ("shell", 100099, 1)
    assert first.timestep == pytest.approx(8.4091e-7)
    assert real.min_timestep.timestep == pytest.approx(8.4091e-7)


def test_timing_and_memory(real):
    assert real.problem_time == pytest.approx(3.0004e-3)
    assert real.problem_cycles == 3568
    assert real.cpu_seconds == 2.0
    assert real.elapsed_seconds == 1.0
    assert (real.workers, real.worker_type) == (4, "SMP threads")
    assert (real.start_time, real.end_time) == ("10/23/2026 14:41:57",
                                                "10/23/2026 14:41:58")
    phases = [r for r in real.timing if r.level == 0]
    assert phases[0].name == "Keyword Processing"
    # The phases add up to the "T o t a l s" line (2.2890 s clock, 100 %).
    assert sum(r.clock for r in phases) == pytest.approx(2.289)
    assert sum(r.clock_percent for r in phases) == pytest.approx(100.0, abs=0.05)
    assert any(r.name == "Interf. ID         1" and r.level == 1 for r in real.timing)
    assert real.memory["total"] == "755K"
    assert real.memory["memory_required_to_complete_solution"] == "280K"


def test_summary_text(real):
    text = real.summary()
    assert "Termination: NORMAL (10/23/26 14:41:58)" in text
    assert "LS-DYNA smp s R14" in text
    assert "Smallest time step: 8.409e-07 (shell 100099, part 1)" in text
    assert "Warnings: 0, errors: 0" in text


def test_reader_is_available_from_lsdyna_module():
    assert read_d3hsp_from_lsdyna(EXCERPT).problem_cycles == 3568


# --- variants ---------------------------------------------------------------


def test_r16_mass_summary_layout():
    # R16 prints "part id <n>  mass=" without "=" and a lumped-mass entry.
    r16 = TEXT.replace(
        " part id   =        1   mass= 0.12149954E-03\n"
        " part id   =        2   mass= 0.12569384E-04 rigid body\n",
        " lumped mass in deformable\n"
        " part of structure      mass= 0.00000000E+00\n"
        " part id                    1  mass= 0.12149954E-03\n"
        " part id                    2  mass= 0.12569384E-04 rigid body\n",
    )
    assert r16 != TEXT
    d = parse_d3hsp(r16)
    assert d.part_masses == {1: pytest.approx(1.2149954e-4),
                             2: pytest.approx(1.2569384e-5)}
    assert d.rigid_parts == (2,)


def test_mpp_run():
    mpp = (TEXT.replace("Version : smp s R14", "Version : mpp d R14")
               .replace("using  4 SMP threads", "using 16 MPP procs"))
    d = parse_d3hsp(mpp)
    assert (d.parallel, d.precision) == ("mpp", "double")
    assert (d.workers, d.worker_type) == (16, "MPP procs")


def test_error_termination_and_messages():
    messages = (
        "\n *** Warning 41123 (SOL+1123)\n"
        "     SPH in bucket sort of particles time 0.0000E+00\n"
        "     Increasing memory for buckets\n\n"
        " *** Warning 41123 (SOL+1123)\n     second occurrence\n\n"
        " *** Error 10246 (KEY+246)\n     negative volume in solid element 42\n\n"
    )
    bad = TEXT.replace(" 100 smallest timesteps", messages + " 100 smallest timesteps")
    bad = bad.replace("N o r m a l    t e r m i n a t i o n",
                      "E r r o r      t e r m i n a t i o n")
    d = parse_d3hsp(bad)

    assert d.termination == "error"
    assert not d.normal_termination
    assert len(d.warnings) == 2 and len(d.errors) == 1
    first = d.warnings[0]
    assert (first.number, first.code) == (41123, "SOL+1123")
    assert first.text == ("SPH in bucket sort of particles time 0.0000E+00 "
                          "Increasing memory for buckets")
    assert d.errors[0].text == "negative volume in solid element 42"
    assert d.message_counts() == {("warning", 41123): 2, ("error", 10246): 1}
    assert "warning 41123 (SOL+1123) x2" in d.summary()


def test_option_text_is_not_a_termination():
    # d3hsp echoes option descriptions such as "error termination if ...".
    text = TEXT.replace(
        " N o r m a l    t e r m i n a t i o n", " xx", 2
    ) + "          eq.2:  error termination if too small\n"
    assert parse_d3hsp(text).termination == "incomplete"


def test_incomplete_run():
    cut = TEXT.split(" N o r m a l    t e r m i n a t i o n")[0]
    d = parse_d3hsp(cut)
    assert d.termination == "incomplete"
    assert d.termination_time is None
    assert "Termination: INCOMPLETE" in d.summary()


def test_not_a_d3hsp():
    with pytest.raises(ValueError, match="d3hsp"):
        parse_d3hsp("just some text\nwithout anything useful\n")
