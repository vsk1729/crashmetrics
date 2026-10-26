"""Tests for the LS-DYNA glstat/matsum readers and crashmetrics-energy.

The files are generated in the LS-DYNA ASCII layout (dotted labels in
glstat, key= value pairs in matsum). Validate against your own solver
version's files as well.
"""

import numpy as np
import pytest

from crashmetrics.lsdyna import (
    _to_float,
    check_run,
    main,
    parse_glstat,
    parse_matsum,
    read_glstat,
)

T = np.linspace(0.0, 0.1, 21)
E0 = 1.0e5
ABSORBED = E0 * (1 - np.exp(-T / 0.02))


def glstat_text(hourglass_share=0.03, tiny_fortran=True):
    hourglass = hourglass_share * ABSORBED
    internal = ABSORBED - hourglass
    kinetic = E0 - ABSORBED
    lines = [
        " Global statistics                       ls-dyna R13.1.1  date 10/26/2026",
        "",
    ]
    for i, t in enumerate(T):
        eroded = "1.00000-100" if (tiny_fortran and i == 3) else "0.00000E+00"
        lines += [
            f" dt of cycle {i * 100:6d} is controlled by shell      12345 of part"
            "       42",
            "",
            f" time...........................   {t:.5E}",
            " time step......................   1.00000E-06",
            f" kinetic energy.................   {kinetic[i]:.5E}",
            f" internal energy................   {internal[i]:.5E}",
            " spring and damper energy.......   0.00000E+00",
            f" hourglass energy ..............   {hourglass[i]:.5E}",
            " system damping energy..........   0.00000E+00",
            " sliding interface energy.......   0.00000E+00",
            " external work..................   0.00000E+00",
            " eroded kinetic energy..........   0.00000E+00",
            f" eroded internal energy.........   {eroded}",
            " eroded hourglass energy........   0.00000E+00",
            f" total energy...................   {E0:.5E}",
            " total energy / initial energy..   1.00000E+00",
            " energy ratio w/o eroded energy.   1.00000E+00",
            " global x velocity..............   1.00000E+01",
            " time per zone cycle.(nanosec)        123",
            f" added mass.....................   {0.002 * i:.5E}",
            f" percentage increase............   {0.1 * i:.5E}",
            "",
        ]
    return "\n".join(lines)


def matsum_text(part2_hourglass=0.03):
    shape = np.minimum(T / 0.05, 1.0)
    lines = [" summary of part energies", ""]
    for i, t in enumerate(T):
        lines.append(f" time =   {t:.5E}")
        for pid, peak, share in ((1, 6.0e4, 0.03), (2, 3.5e4, part2_hourglass)):
            ie = shape[i] * peak
            lines += [
                f" mat.#={pid:5d}             inten=   {ie:.4E}     kinen=   "
                f"{(1 - shape[i]) * peak:.4E}     eroded_ie=   0.0000E+00     "
                "eroded_ke=   0.0000E+00",
                " x-mom=   1.0000E+02  y-mom=   0.0000E+00  z-mom=   0.0000E+00",
                " x-rbv=   0.0000E+00  y-rbv=   0.0000E+00  z-rbv=   0.0000E+00",
                f" hgeng=   {share * ie:.4E}     +spen=   0.0000E+00     "
                "-spen=  -1.0000E+00",
            ]
        lines += [" summary   inten=   9.9999E+04     kinen=   1.0000E+00", ""]
    return "\n".join(lines)


@pytest.mark.parametrize(
    "text, value",
    [("1.23456E+05", 1.23456e5), ("1.0D+03", 1.0e3), ("1.00000-100", 1e-100),
     ("-2.5+101", -2.5e101), ("42", 42.0), (".5E-1", 0.05)],
)
def test_fortran_numbers(text, value):
    assert _to_float(text) == pytest.approx(value)


def test_parse_glstat():
    g = parse_glstat(glstat_text())

    np.testing.assert_allclose(g.time, T, rtol=1e-5, atol=1e-12)
    np.testing.assert_allclose(g.kinetic, E0 - ABSORBED, rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(g.hourglass, 0.03 * ABSORBED, rtol=1e-5, atol=1e-6)
    assert g.eroded_internal[3] == pytest.approx(1e-100)
    assert g.energy_ratio is not None and np.all(g.energy_ratio == 1.0)
    assert g.added_mass_percent[-1] == pytest.approx(2.0)
    assert "energy_ratio_w_o_eroded_energy" in g.extra
    assert "global_x_velocity" in g.extra
    assert "dt_of_cycle" not in g.extra


def test_parse_matsum():
    p = parse_matsum(matsum_text())

    assert list(p.part_ids) == [1, 2]
    assert p.internal.shape == (len(T), 2)
    np.testing.assert_allclose(p.internal[-1], [6.0e4, 3.5e4])
    np.testing.assert_allclose(p.hourglass[-1], [0.03 * 6.0e4, 0.03 * 3.5e4])
    # +spen and -spen are kept apart; the summary line is ignored.
    assert p.extra["minus_spen"][0, 0] == -1.0
    assert p.extra["plus_spen"][0, 0] == 0.0
    assert "x_mom" in p.extra


def test_parsers_reject_other_files():
    with pytest.raises(ValueError, match="glstat"):
        parse_glstat("not a glstat file\n")
    with pytest.raises(ValueError, match="matsum"):
        parse_matsum(glstat_text())


def test_check_run_on_directory(tmp_path):
    (tmp_path / "glstat").write_text(glstat_text())
    (tmp_path / "matsum").write_text(matsum_text())

    report = check_run(tmp_path)

    assert report.passed
    assert len(report.parts) == 2
    assert report.check("added_mass").value == pytest.approx(2.0)


def test_check_run_finds_failing_part(tmp_path):
    (tmp_path / "glstat").write_text(glstat_text())
    (tmp_path / "matsum").write_text(matsum_text(part2_hourglass=0.2))

    report = check_run(tmp_path / "glstat")

    assert not report.passed
    assert report.check("part_hourglass").part == 2


def test_read_glstat_from_file(tmp_path):
    path = tmp_path / "glstat"
    path.write_text(glstat_text())
    assert len(read_glstat(path).time) == len(T)


# --- command line ------------------------------------------------------------


def write_run(directory, hourglass_share=0.03):
    directory.mkdir()
    (directory / "glstat").write_text(glstat_text(hourglass_share))
    (directory / "matsum").write_text(matsum_text())
    return directory


def test_cli_pass_fail_and_error(tmp_path, capsys):
    good = write_run(tmp_path / "good")
    bad = write_run(tmp_path / "bad", hourglass_share=0.2)

    assert main([str(good)]) == 0
    assert "Energy check: PASSED" in capsys.readouterr().out

    assert main([str(good), str(bad)]) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out and "hourglass" in out

    assert main([str(tmp_path / "missing")]) == 2
    assert "ERROR" in capsys.readouterr().out


def test_cli_limits(tmp_path, capsys):
    bad = write_run(tmp_path / "bad", hourglass_share=0.2)
    assert main([str(bad), "--hourglass", "off"]) == 0
    assert main([str(bad), "--hourglass", "0.25"]) == 0
    assert main([str(bad), "--added-mass", "1.5"]) == 1
    capsys.readouterr()
