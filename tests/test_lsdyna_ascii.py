"""Tests for the LS-DYNA ASCII readers (crashmetrics.lsdyna_ascii).

Real files (tests/data/lsdyna, see its README for sources and
licences):

- ``helmet/``: nodout and secforc of a helmeted Hybrid III head drop and
  pendulum test (LS-DYNA R16). The study's own results table gives HIC,
  BrIC and the neck moment computed from these files, which the readers
  reproduce.
- ``pladebuk/``: rcforc (SURFA/SURFB labels, LS-DYNA R14) and spcforc.

The other file types are tested with short files written here in the
layout LS-DYNA (and its l2a binout converter) uses; the values are made
up. The readers were also checked locally against further real files
whose licences do not allow copying them here (see the README).
"""

import math
from pathlib import Path

import numpy as np
import pytest

from crashmetrics.head import bric
from crashmetrics.lsdyna import read_nodout as reexported_read_nodout
from crashmetrics.lsdyna_ascii import (
    KINDS,
    AsciiOutput,
    detect_kind,
    main,
    parse_ascii,
    read_ascii,
    read_nodout,
    read_rcforc,
    read_run,
    read_secforc,
    read_spcforc,
)
from crashmetrics.pedestrian import calculate_hic
from crashmetrics.signals import cfc_filter, resample_uniform

DATA = Path(__file__).parent / "data" / "lsdyna"
HELMET = DATA / "helmet"
PLADE = DATA / "pladebuk"

# Row run_id 0 of the study's bo-runs/master.csv (computed by the study
# from these nodout and secforc files with its own parser and filter).
STUDY = {"hic_drop": 195.2436027206686, "bric_drop": 0.3881936318758607,
         "mom_pend": 58.271}


# --- Real files ------------------------------------------------------------------

def test_nodout_real_file_values():
    n = read_nodout(HELMET / "drop" / "nodout")
    assert n.kind == "nodout"
    assert n.ids == (22626,)
    assert len(n) == 251
    assert n.time[0] == 0.0 and n.time[-1] == pytest.approx(24.999998)
    assert n.title.startswith("LSTC 50th% Full_FE H-III Dummy")
    assert n.version == "ls-dyna smp s R16 R16.0_619_d222963 date 03/18/2025"
    assert n.cycle is not None and n.cycle[1] == 201
    # Second state, translational and rotational lines of the file:
    # 22626  8.34258E-07-4.04483E-06-3.12016E-01 4.76617E-05-4.96463E-04
    #       -3.12074E+00 4.76665E-04-4.96513E-03-7.42748E-03 4.79642E+01
    #       -2.20298E+01 7.02648E+00
    expected = {
        "x_displacement": 8.34258e-07, "y_displacement": -4.04483e-06,
        "z_displacement": -3.12016e-01, "x_velocity": 4.76617e-05,
        "y_velocity": -4.96463e-04, "z_velocity": -3.12074,
        "x_acceleration": 4.76665e-04, "y_acceleration": -4.96513e-03,
        "z_acceleration": -7.42748e-03, "x_coordinate": 47.9642,
        "y_coordinate": -22.0298, "z_coordinate": 7.02648,
        "rx_displacement": 9.61162e-09, "ry_displacement": 3.04031e-08,
        "rz_displacement": 5.27046e-08, "rx_velocity": 1.30707e-06,
        "ry_velocity": 2.72186e-06, "rz_velocity": 5.21215e-06,
        "rx_acceleration": 1.30720e-05, "ry_acceleration": 2.72213e-05,
        "rz_acceleration": 5.21267e-05,
    }
    assert n.channels == list(expected)
    for name, value in expected.items():
        assert n.channel(name)[1] == value, name
    assert n.channel("z_velocity")[0] == -3.12          # 3.12 m/s drop
    assert not np.isnan(n.channel("rz_acceleration")).any()


def test_helmet_drop_reproduces_study_hic_and_bric():
    """HIC15 and BrIC from the nodout read here agree with the study.

    The study filtered with its own Butterworth filter; here SAE J211
    CFC 1000 is used, so HIC agrees within 0.5 % (194.60 vs 195.24).
    The model works in mm, ms: acceleration mm/ms^2 = 1000 m/s^2,
    angular velocity rad/ms.
    """
    n = read_nodout(HELMET / "drop" / "nodout")
    t = n.time / 1000.0
    filtered = []
    for axis in "xyz":
        a_g = n.channel(f"{axis}_acceleration") * 1000 / 9.80665
        t_u, a_u = resample_uniform(t, a_g, 10_000.0)
        filtered.append(cfc_filter(t_u, a_u, 1000))
    hic = calculate_hic(t_u, np.sqrt(sum(a**2 for a in filtered)))
    assert hic.value == pytest.approx(194.60, abs=0.01)
    assert hic.value == pytest.approx(STUDY["hic_drop"], rel=0.005)
    # The study's model x axis is the head's pitch axis, hence (56.45, 66.25).
    omega = [n.channel(f"r{axis}_velocity") * 1000 for axis in "xyz"]
    result = bric(t, *omega, critical=(56.45, 66.25, 42.87))
    assert result.value == pytest.approx(STUDY["bric_drop"], rel=0.001)


def test_secforc_real_file_and_study_neck_moment():
    s = read_secforc(HELMET / "pendulum" / "secforc")
    assert s.ids == (1,)
    assert s.name(1) == "Upper_Neck_Force_INJURY"
    assert len(s) == 250
    # Record at t = 1.00490E-01: forces, moments (accelerometer frame
    # "ac ID = 33377"), centroid and area
    assert s.time[1] == pytest.approx(0.10049)
    row = {name: s.channel(name)[1] for name in s.channels}
    assert row == {
        "x_force": 1.3628e-04, "y_force": -4.9878e-03, "z_force": 2.5982e-01,
        "total_force": 2.5987e-01, "x_moment": 4.2550e-01, "y_moment": -1.2521,
        "z_moment": -2.7105e-02, "total_moment": 1.3227, "x_centroid": -3.7387e-01,
        "y_centroid": 1.0590e+01, "z_centroid": -4.6886e+01, "area": 2.5147e+03,
    }
    assert np.max(np.abs(s.channel("total_moment"))) == STUDY["mom_pend"]


def test_rcforc_surfa_surfb_labels_and_legend():
    r = read_rcforc(PLADE / "rcforc")
    assert r.ids == (80085, 8008, 80086, 8009)
    assert r.name(8008) == "Right_on_right_action"
    assert len(r) == 1 and r.time[0] == 0.0
    assert [c for c in r.channels if c.startswith("surfa_")] == [
        "surfa_x_force", "surfa_y_force", "surfa_z_force", "surfa_mass",
        "surfa_x_moment", "surfa_y_moment", "surfa_z_moment",
    ]
    assert np.all(r.data["surfb_x_force"] == 0.0)
    assert r.version.startswith("ls-dyna smp d R14")


def test_spcforc_real_file_and_totals():
    s = read_spcforc(PLADE / "spcforc")
    assert len(s) == 2 and list(s.time) == [0.0, 0.1]
    assert len(s.ids) == 32 and s.ids[0] == 19381
    assert s.channel("x_force", 19381)[1] == 1.9481e+01
    assert s.totals["y_force"][1] == 1.3769e+01
    # The printed resultant equals the sum over the nodes (4 digits).
    assert np.nansum(s.channel("y_force")[1]) == pytest.approx(13.769, rel=1e-3)
    assert "x_moment" not in s.data


def test_reexported_from_lsdyna_module():
    assert reexported_read_nodout is read_nodout


# --- Synthetic files in the LS-DYNA layout ---------------------------------------

HEAD = (
    " Synthetic test model\n"
    "                    ls-dyna smp d R13 R13.1.1 date 10/29/2026\n"
    "\n"
    "{BEGIN LEGEND}\n"
    " Entity #        Title\n"
    "{legend}"
    "{END LEGEND}\n"
)


def head(**names):
    rows = "".join(f"{int(k[1:]):9d}     {v:<60s}\n" for k, v in names.items())
    return HEAD.replace("{legend}", rows)


SLEOUT = head(i1="DOOR_TO_BARRIER", i3="SINGLE_SURFACE") + """



 contact interface energy file, time= 0.0000000E+00
    #             slave       master       cycle=             1    frictional

         1   0.0000E+00   0.0000E+00                               0.0000E+00
         3   0.0000E+00   0.0000E+00                               0.0000E+00

 summary   total slave side= 0.0000000E+00
           total mastr side= 0.0000000E+00
           total energy    = 0.0000000E+00
           friction energy = 0.0000000E+00




 contact interface energy file, time= 0.1000000E+01
    #             slave       master       cycle=           812    frictional

         1   0.2500E+03   0.1500E+03                               0.4000E+02
         3  -0.1000E+01   0.0000E+00                               0.2000E+01

 summary   total slave side= 0.2490000E+03
           total mastr side= 0.1500000E+03
           total energy    = 0.3990000E+03
           friction energy = 0.4200000E+02
"""


def test_sleout_contacts_totals_and_cycle():
    s = parse_ascii(SLEOUT)
    assert s.kind == "sleout"
    assert s.ids == (1, 3)
    assert s.name(1) == "DOOR_TO_BARRIER"
    assert list(s.time) == [0.0, 1.0]
    assert list(s.cycle) == [1, 812]
    assert s.channel("surfa_energy", 1)[1] == 250.0
    assert s.channel("surfb_energy", 1)[1] == 150.0
    assert s.channel("friction_energy", 3)[1] == 2.0
    assert s.channel("surfa_energy", 3)[1] == -1.0
    assert s.totals == {
        "surfa_energy": pytest.approx([0.0, 249.0]),
        "surfb_energy": pytest.approx([0.0, 150.0]),
        "total_energy": pytest.approx([0.0, 399.0]),
        "friction_energy": pytest.approx([0.0, 42.0]),
    }
    surfa_surfb = SLEOUT.replace("slave       master", "surfa       surfb")
    surfa_surfb = surfa_surfb.replace("total slave side", "total surfa side")
    surfa_surfb = surfa_surfb.replace("total mastr side", "total surfb side")
    s2 = parse_ascii(surfa_surfb, "sleout")
    assert s2.totals["surfb_energy"][1] == 150.0
    np.testing.assert_array_equal(s2.data["surfa_energy"], s.data["surfa_energy"])


def test_sleout_transducer_column_is_ignored():
    text = SLEOUT.replace("frictional\n", "frictional  transducer\n").replace(
        "0.4000E+02\n", "0.4000E+02       1\n")
    s = parse_ascii(text, "sleout")
    assert s.channel("friction_energy", 1)[1] == 40.0


RCFORC_OLD = head(i5="BUMPER_TO_WALL") + """
 interface number,         7,is single surface-resultants are undefined
  slave           5 time 0.00000E+00  x  0.00000E+00  y  0.00000E+00  z  0.00000E+00 mass  0.00000E+00  mx  0.00000E+00  my  0.00000E+00  mz  0.00000E+00
  master          5 time 0.00000E+00  x  0.00000E+00  y  0.00000E+00  z  0.00000E+00 mass  0.00000E+00  mx  0.00000E+00  my  0.00000E+00  mz  0.00000E+00
 interface number,         7,is single surface-resultants are undefined
  slave           5 time 1.00000E+00  x -1.25000E+02  y  3.00000E+00  z  4.00000E+00 mass  2.50000E-01  mx  0.00000E+00  my  0.00000E+00  mz  0.00000E+00
  master          5 time 1.00000E+00  x  1.25000E+02  y -3.00000E+00  z -4.00000E+00 mass  1.00000E+00  mx  0.00000E+00  my  0.00000E+00  mz  0.00000E+00
"""  # noqa: E501


def test_rcforc_slave_master_map_to_surfa_surfb():
    r = parse_ascii(RCFORC_OLD)
    assert r.kind == "rcforc"
    assert r.ids == (5,)                     # single-surface contact 7 has no data
    assert r.channel("surfa_x_force")[1] == -125.0
    assert r.channel("surfb_x_force")[1] == 125.0
    assert r.channel("surfb_mass")[1] == 1.0
    np.testing.assert_allclose(
        r.magnitude(("surfb_x_force", "surfb_y_force", "surfb_z_force"), 5),
        [0.0, math.sqrt(125**2 + 9 + 16)])


ABSTAT = head(i1="DRIVER_AIRBAG", i2="PASSENGER_AIRBAG") + """


      time   airbag/cv #  volume        pressure    internal energy      dm/dt in      density dm/dt out  total mass gas temp. surface area   reaction dm/dt outp dm/dt outv
 0.00000E+00       1     1.0000E+03     1.0000E-04     1.5000E-01     0.0000E+00     1.1800E-09  0.000E+00  1.180E-06  2.930E+02  5.600E+03  0.000E+00  0.000E+00  0.000E+00
    Material I.D.=           1  Unblocked  Area=  0.2125E+04    Blocked  Area=  0.0000E+00    Leakage      =  0.0000E+00
 0.00000E+00       2     2.0000E+03     1.0000E-04     3.0000E-01     0.0000E+00     1.1800E-09  0.000E+00  2.360E-06  2.930E+02  9.100E+03  0.000E+00  0.000E+00  0.000E+00


      time   airbag/cv #  volume        pressure    internal energy      dm/dt in      density dm/dt out  total mass gas temp. surface area   reaction dm/dt outp dm/dt outv
 3.00000E+01       1     6.0000E+04     1.5000E-04     2.7000E+04     1.2000E+00     1.0000E-06  4.000E-01  6.000E-02  8.000E+02  9.000E+04  1.350E+00  0.000E+00  4.000E-01
    Material I.D.=           1  Unblocked  Area=  0.2125E+04    Blocked  Area=  0.0000E+00    Leakage      =  0.0000E+00
 3.00000E+01       2     9.5000E+04     1.2000E-04     4.0000E+04     2.4000E+00     8.0000E-07  0.000E+00  1.100E-01  7.500E+02  1.400E+05  2.100E+00  0.000E+00  0.000E+00
"""  # noqa: E501


def test_abstat_airbags():
    a = parse_ascii(ABSTAT)
    assert a.kind == "abstat"
    assert a.ids == (1, 2)
    assert a.name(2) == "PASSENGER_AIRBAG"
    assert list(a.time) == [0.0, 30.0]
    assert a.channels == [
        "volume", "pressure", "internal_energy", "dm_dt_in", "density", "dm_dt_out",
        "total_mass", "gas_temp", "surface_area", "reaction", "dm_dt_outp",
        "dm_dt_outv",
    ]
    assert a.channel("pressure", 1)[1] == 1.5e-4
    assert a.channel("volume", 2)[1] == 9.5e4
    assert a.channel("gas_temp", 1)[1] == 800.0
    assert a.channel("dm_dt_outv", 1)[1] == 0.4


SWFORC = head() + """
 constraint #      axial        shear         time  failure                                       length  rslt moment      torsion
          1  0.00000E+00  0.00000E+00  0.00000E+00  0.00+00    spotweld beam  ID    5000001  1.20000E+00  0.00000E+00  0.00000E+00
          2  0.00000E+00  0.00000E+00  0.00000E+00  0.00+00    spotweld beam  ID    5000002  1.20000E+00  0.00000E+00  0.00000E+00

 constraint #      axial        shear         time  failure                                       length  rslt moment      torsion
          1  1.50000E+00 -2.50000E-01  1.00000E+01  4.50-01    spotweld beam  ID    5000001  1.25000E+00  3.00000E-02  1.00000E-03
          2  0.00000E+00  0.00000E+00  1.00000E+01  failure    spotweld beam  ID    5000002               failure time=  8.5000E+00
"""  # noqa: E501


def test_swforc_spotwelds_and_failure():
    w = parse_ascii(SWFORC)
    assert w.kind == "swforc"
    assert w.ids == (5000001, 5000002)          # element IDs, not the counter
    assert list(w.time) == [0.0, 10.0]
    assert w.channel("axial", 5000001)[1] == 1.5
    assert w.channel("shear", 5000001)[1] == -0.25
    assert w.channel("failure", 5000001)[1] == pytest.approx(0.45)   # "4.50-01"
    assert w.channel("length", 5000001)[1] == 1.25
    assert w.channel("resultant_moment", 5000001)[1] == 0.03
    assert w.channel("torsion", 5000001)[1] == 0.001
    assert w.channel("failure", 5000002)[1] == 1.0
    assert w.channel("failure_time", 5000002)[1] == 8.5
    assert np.isnan(w.channel("length", 5000002)[1])


DEFORC = head(i101="BELT_LOAD_CELL", i102="ROT_SPRING") + """
 time.........................   0.00000E+00
 spring/damper number.........       101
 x-force......................   0.00000E+00
 y-force......................   0.00000E+00
 z-force......................   0.00000E+00
 resultant force..............   0.00000E+00
 change in length.............   0.00000E+00
 spring/damper number.........       102
 x-moment.....................   0.00000E+00
 y-moment.....................   0.00000E+00
 z-moment.....................   0.00000E+00
 resultant moment.............   0.00000E+00
 relative rotation............   0.00000E+00

 time.........................   5.00000E+01
 spring/damper number.........       101
 x-force......................  -3.00000E+00
 y-force......................   0.00000E+00
 z-force......................   4.00000E+00
 resultant force..............   5.00000E+00
 change in length.............   1.20000E+01
 spring/damper number.........       102
 x-moment.....................   0.00000E+00
 y-moment.....................   2.00000E+01
 z-moment.....................   0.00000E+00
 resultant moment.............   2.00000E+01
 relative rotation............   1.50000E-01
"""


def test_deforc_springs_and_dampers():
    d = parse_ascii(DEFORC)
    assert d.kind == "deforc"
    assert d.ids == (101, 102)
    assert list(d.time) == [0.0, 50.0]
    assert d.channel("resultant_force", 101)[1] == 5.0
    assert d.channel("change_in_length", 101)[1] == 12.0
    assert d.channel("relative_rotation", 102)[1] == 0.15
    assert set(d.entity(102)) == {
        "x_moment", "y_moment", "z_moment", "resultant_moment", "relative_rotation"}


JNTFORC = head(i11="NECK_PIVOT") + """

 time.........................   0.00000E+00
 joint ID.....................        11
 x-force......................   0.00000E+00
 y-force......................   0.00000E+00
 z-force......................   0.00000E+00
 x-moment.....................   0.00000E+00
 y-moment.....................   0.00000E+00
 z-moment.....................   0.00000E+00
 resultant force..............   0.00000E+00
 resultant moment.............   0.00000E+00
 joint stiffness id number....        21
 phi (degrees)................   0.00000E+00
 joint energy.................   0.00000E+00


 time.........................   2.00000E+01
 joint ID.....................        11
 x-force  (local) ............   1.00000E+00
 y-force  (local) ............   2.00000E+00
 z-force  (local) ............   2.00000E+00
 x-moment (local) ............   0.00000E+00
 y-moment (local) ............   7.50000E+00
 z-moment (local) ............   0.00000E+00
 resultant force..............   3.00000E+00
 resultant moment.............   7.50000E+00
 joint stiffness id number....        21
 phi (degrees)................   1.20000E+01
 joint energy.................   4.00000E-01
"""


def test_jntforc_joints_and_stiffness():
    j = parse_ascii(JNTFORC)
    assert j.kind == "jntforc"
    assert j.ids == (11, 21)
    assert j.name(11) == "NECK_PIVOT"
    assert j.channel("resultant_moment", 11)[1] == 7.5
    assert j.channel("y_moment_local", 11)[1] == 7.5     # "y-moment (local)"
    assert np.isnan(j.channel("y_moment_local", 11)[0])   # global at t = 0
    assert j.channel("phi_degrees", 21)[1] == 12.0
    assert j.channel("joint_energy", 21)[1] == 0.4


SBTOUT = head() + """



 S E A T B E L T    O U T P U T



 time...........................     0.00000E+00

 seat belt number...............       1
 force..........................     0.00000E+00
 current length.................     4.50000E+02

 slip ring number...............       1
 total slip from side 1 to .....     0.00000E+00

 retractor number...............       1
 pull-out to date...............   0.00000E+00
 force in attached element......   0.00000E+00


 time...........................     6.00000E+01

 seat belt number...............       1
 force..........................     6.50000E+00
 current length.................     4.62000E+02

 slip ring number...............       1
 total slip from side 1 to .....    -1.80000E+01

 retractor number...............       1
 pull-out to date...............   2.50000E+01
 force in attached element......   6.40000E+00
"""


def test_sbtout_belts_slip_rings_retractors():
    s = parse_ascii(SBTOUT)
    assert s.kind == "sbtout"
    assert s.ids == (1,)
    assert list(s.time) == [0.0, 60.0]
    assert s.channel("belt_force")[1] == 6.5
    assert s.channel("belt_length")[1] == 462.0
    assert s.channel("ring_slip")[1] == -18.0
    assert s.channel("retractor_pull_out")[1] == 25.0
    assert s.channel("retractor_force")[1] == 6.4


RWFORC = head(i1="FULL_WIDTH_WALL") + """

    time       wall#   normal-force    x-force        y-force        z-force
 0.00000E+00       1   0.000000E+00   0.000000E+00   0.000000E+00   0.000000E+00
 1.00000E+00       1  -4.500000E+02  -4.500000E+02   1.000000E+00   0.000000E+00
 2.00000E+00       1  -6.000000E+02  -6.000000E+02   2.000000E+00   1.000000E+00
"""


def test_rwforc_wall_forces():
    w = parse_ascii(RWFORC)
    assert w.kind == "rwforc"
    assert w.ids == (1,)
    assert w.name(1) == "FULL_WIDTH_WALL"
    assert list(w.time) == [0.0, 1.0, 2.0]
    np.testing.assert_array_equal(w.channel("normal_force"), [0.0, -450.0, -600.0])
    assert w.channel("z_force")[2] == 1.0


RBDOUT = head(i7="BARRIER") + """1

  r i g i d   b o d y   m o t i o n   a t  cycle=       0    time=   0.000000E+00

 rigid body       7
   global             x           y           z          x-rot       y-rot       z-rot
   coordinates:    1.0000E+03  0.0000E+00  5.0000E+02
 displacements:    0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00
    velocities:   -1.5556E+01  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00
 accelerations:    0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00

principal or user defined local coordinate direction vectors
                     a           b           c
     row 1     1.0000E+00     0.0000E+00     0.0000E+00
     row 2     0.0000E+00     1.0000E+00     0.0000E+00
     row 3     0.0000E+00     0.0000E+00     1.0000E+00

 output in principal or user defined local coordinate directions
                      a           b           c          a-rot       b-rot       c-rot
 displacements:    0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00
    velocities:   -1.5556E+01  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00
 accelerations:    0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00
1

  r i g i d   b o d y   m o t i o n   a t  cycle=    1200    time=   1.000000E+01

 rigid body       7
   global             x           y           z          x-rot       y-rot       z-rot
   coordinates:    9.0000E+02  0.0000E+00  5.0100E+02
 displacements:   -1.0000E+02  0.0000E+00  1.0000E+00  0.0000E+00  2.0000E-03  0.0000E+00
    velocities:   -4.0000E+00  0.0000E+00  1.0000E-01  0.0000E+00  1.0000E-04  0.0000E+00
 accelerations:    1.1000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00

principal or user defined local coordinate direction vectors
                     a           b           c
     row 1     9.9999E-01     0.0000E+00    -2.0000E-03
     row 2     0.0000E+00     1.0000E+00     0.0000E+00
     row 3     2.0000E-03     0.0000E+00     9.9999E-01

 output in principal or user defined local coordinate directions
                      a           b           c          a-rot       b-rot       c-rot
 displacements:   -9.9998E+01  0.0000E+00  1.2000E+00  0.0000E+00  2.0000E-03  0.0000E+00
    velocities:   -3.9998E+00  0.0000E+00  1.0800E-01  0.0000E+00  1.0000E-04  0.0000E+00
 accelerations:    1.0999E+00  0.0000E+00  2.2000E-03  0.0000E+00  0.0000E+00  0.0000E+00
"""  # noqa: E501


def test_rbdout_global_local_and_direction_cosines():
    r = parse_ascii(RBDOUT)
    assert r.kind == "rbdout"
    assert r.ids == (7,)
    assert list(r.time) == [0.0, 10.0]
    assert list(r.cycle) == [0, 1200]
    assert r.channel("global_x")[1] == 900.0
    assert r.channel("global_dx")[1] == -100.0
    assert r.channel("global_vx")[0] == -15.556
    assert r.channel("global_rdy")[1] == 0.002
    assert r.channel("global_ax")[1] == 1.1
    assert r.channel("local_dx")[1] == -99.998
    assert r.channel("local_az")[1] == 0.0022
    assert r.channel("dircos_13")[1] == -0.002
    assert r.channel("dircos_31")[1] == 0.002


NODOUT = head(i1001="HEAD_CG") + """


 n o d a l   p r i n t   o u t   f o r   t i m e  s t e p       1                              ( at time 0.0000000E+00 )

 nodal point  x-disp     y-disp      z-disp      x-vel       y-vel       z-vel      x-accl      y-accl      z-accl      x-coor      y-coor      z-coor
     1001  0.00000E+00 0.00000E+00 0.00000E+00-1.00000E+01 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00 1.00000E+02 2.00000E+02 3.00000E+02
     1002  0.00000E+00 0.00000E+00 0.00000E+00-1.00000E+01 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00 1.10000E+02 2.00000E+02 3.00000E+02



 n o d a l   p r i n t   o u t   f o r   t i m e  s t e p     100                              ( at time 1.0000000E+00 )

 nodal point  x-disp     y-disp      z-disp      x-vel       y-vel       z-vel      x-accl      y-accl      z-accl      x-coor      y-coor      z-coor
     1001 -9.90000E+00-1.00000-100 0.00000E+00-9.80000E+00 0.00000E+00 0.00000E+00-4.00000E+00*********** 0.00000E+00 9.01000E+01 2.00000E+02 3.00000E+02
     1002 -9.90000E+00 0.00000E+00 0.00000E+00-9.80000E+00 0.00000E+00 0.00000E+00-4.00000E+00 0.00000E+00 0.00000E+00 1.00100E+02 2.00000E+02 3.00000E+02
"""  # noqa: E501


def test_nodout_touching_numbers_fortran_exponent_and_overflow():
    n = parse_ascii(NODOUT)
    assert n.ids == (1001, 1002)
    assert n.name(1001) == "HEAD_CG" and n.name(1002) == ""
    assert n.channel("x_velocity", 1001)[0] == -10.0      # touches the field before
    assert n.channel("y_displacement", 1001)[1] == -1.0e-100
    assert math.isnan(n.channel("y_acceleration", 1001)[1])   # ***********
    assert n.channel("x_coordinate", 1002)[1] == 100.1
    assert n.channel("x_acceleration").shape == (2, 2)
    assert "rx_velocity" not in n.data                     # no rotational output


def test_ids_filter_reads_only_selected_entities():
    n = parse_ascii(NODOUT, ids=[1002])
    assert n.ids == (1002,)
    assert n.channel("x_coordinate")[1] == 100.1


def test_restart_replaces_states_after_the_restart_time():
    second_run = NODOUT.split("{END LEGEND}\n", 1)[1]
    restarted = second_run.replace("1.0000000E+00 )", "5.0000000E-01 )").replace(
        "-9.90000E+00", "-4.95000E+00")
    n = parse_ascii(NODOUT + restarted)
    np.testing.assert_array_equal(n.time, [0.0, 0.5])
    assert n.channel("x_displacement", 1002)[1] == -4.95


def test_restart_in_per_line_files():
    later = RWFORC.split("z-force\n", 1)[1]
    later = later.replace(" 2.00000E+00       1  -6.0", " 1.50000E+00       1  -6.0")
    w = parse_ascii(RWFORC + later)
    np.testing.assert_array_equal(w.time, [0.0, 1.0, 1.5])


def test_states_without_entities_and_empty_files():
    empty = parse_ascii(head(), "rcforc")
    assert len(empty) == 0 and empty.ids == () and empty.data == {}
    assert "no states" in empty.summary()


# --- Detection, run directories, CSV and command line -----------------------------

@pytest.mark.parametrize("text, kind", [
    (SLEOUT, "sleout"), (RCFORC_OLD, "rcforc"), (ABSTAT, "abstat"),
    (SWFORC, "swforc"),
    (DEFORC, "deforc"), (JNTFORC, "jntforc"), (SBTOUT, "sbtout"), (RWFORC, "rwforc"),
    (RBDOUT, "rbdout"), (NODOUT, "nodout"),
])
def test_detect_kind_from_text(text, kind):
    assert detect_kind(text=text) == kind


def test_detect_kind_from_name_and_errors():
    assert detect_kind("run3/NODOUT") == "nodout"
    assert detect_kind("job12.rcforc") == "rcforc"
    assert detect_kind("sleout_old.txt") == "sleout"
    assert sorted(KINDS) == sorted(set(KINDS)) and len(KINDS) == 12
    with pytest.raises(ValueError, match="Cannot tell"):
        detect_kind("notes.txt", "nothing to see")
    with pytest.raises(ValueError, match="Unsupported file type"):
        parse_ascii(SLEOUT, "glstat")


def test_read_ascii_detects_from_content(tmp_path):
    path = tmp_path / "contact_energy.txt"
    path.write_text(SLEOUT)
    assert read_ascii(path).kind == "sleout"


def test_lookup_errors_name_the_choices():
    s = parse_ascii(SLEOUT)
    with pytest.raises(KeyError, match="IDs in the file: 1, 3"):
        s.channel("surfa_energy", 2)
    with pytest.raises(KeyError, match="channels: surfa_energy"):
        s.channel("x_force")
    assert 3 in s and 2 not in s


def test_entity_and_summary():
    a = parse_ascii(ABSTAT)
    assert set(a.entity(1)) == set(a.channels)
    text = a.summary()
    assert "abstat: Synthetic test model" in text
    assert "2 states, time 0 to 30" in text
    assert "1 (DRIVER_AIRBAG)" in text


def test_read_run_finds_files_and_skips_empty(tmp_path):
    (tmp_path / "sleout").write_text(SLEOUT)
    (tmp_path / "RWFORC").write_text(RWFORC)
    (tmp_path / "rcforc").write_text(head())               # requested, no contacts
    (tmp_path / "glstat").write_text("not read here")
    (tmp_path / "d3plot").write_bytes(b"\x00\x01")
    run = read_run(tmp_path)
    assert list(run) == ["sleout", "rwforc"]
    assert all(isinstance(v, AsciiOutput) for v in run.values())
    assert list(read_run(tmp_path, kinds=["rwforc"])) == ["rwforc"]
    with pytest.raises(FileNotFoundError):
        read_run(tmp_path / "missing")


def test_read_run_errors(tmp_path):
    (tmp_path / "nodout").write_bytes(b"\xff\xfe binary")
    assert read_run(tmp_path) == {}            # nothing parseable: no states
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "nodout").mkdir()                                 # a directory, not a file
    assert read_run(bad) == {}


def test_to_csv(tmp_path):
    a = parse_ascii(ABSTAT)
    path = a.to_csv(tmp_path / "abstat.csv", channels=["pressure"])
    lines = path.read_text().splitlines()
    assert lines[0] == "time,pressure[1],pressure[2]"
    assert lines[2] == "30.0,0.00015,0.00012"
    s = parse_ascii(SLEOUT)
    header = s.to_csv(tmp_path / "sleout.csv").read_text().splitlines()[0]
    assert header.startswith("time,surfa_energy[1],surfa_energy[3]")
    assert header.endswith("total.total_energy,total.friction_energy")


def test_command_line(tmp_path, capsys):
    run = tmp_path / "run01"
    run.mkdir()
    (run / "abstat").write_text(ABSTAT)
    (run / "sbtout").write_text(SBTOUT)
    out = tmp_path / "csv"
    assert main([str(run), "--csv", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "(abstat)" in printed and "(sbtout)" in printed
    written = sorted(p.name for p in out.iterdir())
    assert written == ["run01_abstat.csv", "run01_sbtout.csv"]
    assert main([str(run / "abstat")]) == 0
    assert main([str(tmp_path / "missing")]) == 2
    (tmp_path / "plain.txt").write_text("hello")
    assert main([str(tmp_path / "plain.txt")]) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main([str(empty)]) == 0
    assert "no supported ASCII files" in capsys.readouterr().out


def test_one_reader_per_kind(tmp_path):
    import crashmetrics.lsdyna_ascii as la

    texts = {"sleout": SLEOUT, "rcforc": RCFORC_OLD, "abstat": ABSTAT,
             "swforc": SWFORC, "deforc": DEFORC, "jntforc": JNTFORC,
             "sbtout": SBTOUT, "rwforc": RWFORC, "rbdout": RBDOUT, "nodout": NODOUT}
    for kind, text in texts.items():
        path = tmp_path / f"file_{kind}.txt"
        path.write_text(text)
        output = getattr(la, f"read_{kind}")(path)
        assert output.kind == kind and len(output) >= 2, kind
    secforc = read_secforc(HELMET / "pendulum" / "secforc", ids=[2])
    assert secforc.ids == () and len(secforc) == 250


def test_read_run_skip_errors(tmp_path, monkeypatch):
    import crashmetrics.lsdyna_ascii as la

    (tmp_path / "sleout").write_text(SLEOUT)
    (tmp_path / "abstat").write_text(ABSTAT)

    def broken(path, kind=None, ids=None):
        if kind == "abstat":
            raise ValueError("damaged file")
        return parse_ascii(Path(path).read_text(), kind)

    monkeypatch.setattr(la, "read_ascii", broken)
    with pytest.raises(ValueError, match="abstat: damaged file"):
        read_run(tmp_path)
    assert list(read_run(tmp_path, skip_errors=True)) == ["sleout"]
