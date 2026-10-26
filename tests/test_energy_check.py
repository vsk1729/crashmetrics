import numpy as np
import pytest

from crashmetrics.energy_check import (
    EnergyLimits,
    GlobalEnergies,
    PartEnergies,
    check_energies,
)

T = np.linspace(0.0, 0.1, 201)
E0 = 100_000.0  # initial kinetic energy


def impact(hourglass_share=0.03, sliding_share=0.02, **overrides):
    """Balanced impact: kinetic energy turns into internal, hourglass and
    contact energy; total stays at E0."""
    absorbed = E0 * (1 - np.exp(-T / 0.02))
    hourglass = hourglass_share * absorbed
    sliding = sliding_share * absorbed
    internal = absorbed - hourglass - sliding
    kinetic = E0 - absorbed
    data = dict(time=T, kinetic=kinetic, internal=internal,
                hourglass=hourglass, sliding=sliding,
                external_work=np.zeros_like(T))
    data.update(overrides)
    return GlobalEnergies(**data)


def parts(hourglass_shares=(0.03, 0.03, 0.03), peaks=(60e3, 35e3, 5e3),
          negative=(0.0, 0.0, 0.0)):
    shape = np.minimum(T / 0.05, 1.0)[:, None]
    internal = shape * np.array(peaks)
    internal[5] = -np.array(negative) * np.array(peaks)  # dip early on
    hourglass = internal.clip(min=0) * np.array(hourglass_shares)
    return PartEnergies(T, [10, 20, 30], internal, hourglass=hourglass)


def test_balanced_impact_passes():
    report = check_energies(impact(), parts())

    assert report.passed
    assert report.reference_energy == pytest.approx(E0)
    assert report.check("energy_ratio").value == pytest.approx(1.0)
    assert report.check("hourglass").value == pytest.approx(0.03 / 0.95, rel=1e-6)
    assert report.check("negative_contact").value == 0.0
    assert report.check("damping").status == "skipped"
    assert report.check("added_mass").status == "skipped"
    assert "PASSED" in report.summary()


def test_hourglass_over_limit_fails():
    report = check_energies(impact(hourglass_share=0.12))

    hg = report.check("hourglass")
    assert hg.status == "fail"
    assert hg.value == pytest.approx(0.12 / 0.86, rel=1e-6)
    assert not report.passed
    assert report.failures == (hg,)
    assert "FAILED (1 check)" in report.summary()


def test_energy_ratio_detects_energy_growth():
    g = impact()
    report = check_energies(GlobalEnergies(
        time=T, kinetic=g.kinetic, internal=g.internal * 1.2,
        hourglass=g.hourglass, sliding=g.sliding))
    ratio = report.check("energy_ratio")
    assert ratio.status == "fail"
    assert ratio.value > 1.05
    assert ratio.time == pytest.approx(T[-1])


def test_solver_energy_ratio_is_used_when_given():
    solver_ratio = np.full_like(T, 1.0)
    solver_ratio[100] = 0.93
    report = check_energies(impact(energy_ratio=solver_ratio))
    ratio = report.check("energy_ratio")
    assert ratio.value == pytest.approx(0.93)
    assert ratio.status == "fail"
    assert "solver ratio" in ratio.note


def test_negative_contact_energy():
    sliding = -0.08 * E0 * np.sin(np.pi * T / 0.1)
    g = impact()
    report = check_energies(GlobalEnergies(
        time=T, kinetic=g.kinetic, internal=g.internal - sliding + g.sliding,
        sliding=sliding))
    check = report.check("negative_contact")
    assert check.value == pytest.approx(0.08, rel=1e-3)
    assert check.status == "fail"
    assert check.time == pytest.approx(0.05)


def test_added_mass_and_damping():
    report = check_energies(impact(
        added_mass_percent=np.linspace(0, 7.5, len(T)),
        damping=np.linspace(0, 0.02 * E0, len(T))))
    assert report.check("added_mass").value == pytest.approx(7.5)
    assert report.check("added_mass").status == "fail"
    assert report.check("damping").value == pytest.approx(0.02)
    assert report.check("damping").status == "pass"


def test_quasi_static_case_uses_external_work():
    work = 5_000.0 * T / T[-1]  # prescribed motion, no initial energy
    report = check_energies(GlobalEnergies(
        time=T, kinetic=np.zeros_like(T), internal=work.copy(),
        external_work=work))
    assert report.reference_energy == pytest.approx(5_000.0)
    assert report.check("energy_ratio").value == pytest.approx(1.0)
    assert report.passed


def test_eroded_energy_is_reported_only_by_default():
    eroded = np.linspace(0, 0.08 * E0, len(T))
    report = check_energies(impact(eroded_internal=eroded))
    assert report.check("eroded_energy").status == "info"
    assert report.passed
    strict = check_energies(impact(eroded_internal=eroded),
                            limits=EnergyLimits(eroded_energy=0.05))
    assert strict.check("eroded_energy").status == "fail"


def test_limits_can_be_switched_off():
    report = check_energies(impact(hourglass_share=0.2),
                            limits=EnergyLimits(hourglass=None))
    assert report.check("hourglass").status == "info"
    assert report.passed


def test_missing_hourglass_is_skipped_with_hint():
    g = impact()
    report = check_energies(GlobalEnergies(time=T, kinetic=g.kinetic,
                                           internal=g.internal + g.hourglass
                                           + g.sliding))
    hg = report.check("hourglass")
    assert hg.status == "skipped"
    assert "HGEN=2" in hg.note


# --- part checks -----------------------------------------------------------


def test_part_hourglass_failure_and_small_parts_skipped():
    # Part 20 over the limit; part 30 is small (5 % share) but checked;
    # with a 10 % minimum share it would be skipped.
    report = check_energies(impact(), parts(hourglass_shares=(0.03, 0.15, 0.5)))
    check = report.check("part_hourglass")
    assert check.status == "fail"
    assert check.part == 30
    assert {p.part_id for p in report.failed_parts} == {20, 30}

    relaxed = check_energies(
        impact(), parts(hourglass_shares=(0.03, 0.15, 0.5)),
        limits=EnergyLimits(part_min_internal_share=0.1))
    assert relaxed.check("part_hourglass").part == 20
    assert [p.checked for p in relaxed.parts] == [True, True, False]


def test_part_negative_internal_energy():
    report = check_energies(impact(), parts(negative=(0.0, 0.0, 0.2)))
    check = report.check("part_negative_internal")
    assert check.part == 30
    assert check.status == "fail"
    assert check.value == pytest.approx(0.2)


def test_part_shares_use_model_internal_energy():
    report = check_energies(impact(), parts())
    shares = {p.part_id: p.share for p in report.parts}
    peak_model = float(np.max(impact().internal))
    assert shares[10] == pytest.approx(60e3 / peak_model)


# --- from_mapping and validation ------------------------------------------


def test_from_mapping_accepts_glstat_and_binout_names():
    g = impact()
    data = {
        "time": T,
        "Kinetic Energy": g.kinetic,
        "internal_energy": g.internal,
        "hourglass energy": g.hourglass,
        "sliding_interface_energy": g.sliding,
        "total energy / initial energy": np.ones_like(T),
        "percent_increase": np.zeros_like(T),
        "global x velocity": np.zeros_like(T),
    }
    mapped = GlobalEnergies.from_mapping(data)
    assert mapped.hourglass is not None
    assert mapped.energy_ratio is not None
    assert mapped.added_mass_percent is not None
    assert "global_x_velocity" in mapped.extra


def test_part_from_mapping():
    p = PartEnergies.from_mapping(
        T, [1, 2], {"inten": np.ones((len(T), 2)), "hgeng": np.zeros((len(T), 2)),
                    "x-mom": np.zeros((len(T), 2))})
    assert p.hourglass is not None
    assert "x_mom" in p.extra


def test_validation():
    with pytest.raises(ValueError, match="Missing required"):
        GlobalEnergies.from_mapping({"time": T, "kinetic energy": T})
    with pytest.raises(ValueError, match="samples"):
        GlobalEnergies(time=T, kinetic=T[:-1], internal=T)
    with pytest.raises(ValueError, match="bracket"):
        check_energies(impact(), limits=EnergyLimits(energy_ratio=(1.01, 1.1)))
    with pytest.raises(ValueError, match="reference energy"):
        check_energies(GlobalEnergies(time=T, kinetic=0 * T, internal=0 * T))
    with pytest.raises(ValueError, match="shape"):
        PartEnergies(T, [1, 2], np.ones((len(T), 3)))
