"""Example 18: LS-DYNA ASCII output (nodout, secforc, rcforc, spcforc).

Real LS-DYNA R16 output of a helmeted Hybrid III head (MIT-licensed
helmet fit study, see tests/data/lsdyna/README.md): the head centre of
gravity node in a 3.12 m/s drop test (nodout) and the upper neck section
force in a pendulum test (secforc). The model units are mm, ms, kg, kN.
Point the paths at your own run directory instead.

The same files can be summarised or written to CSV on the command line:

    crashmetrics-ascii run01 --csv results
"""

from pathlib import Path

import numpy as np

from crashmetrics.features import signal_features
from crashmetrics.head import bric
from crashmetrics.lsdyna import read_nodout, read_run, read_secforc
from crashmetrics.pedestrian import calculate_hic
from crashmetrics.signals import cfc_filter, resample_uniform

data = Path(__file__).resolve().parents[1] / "tests" / "data" / "lsdyna"

# --- 1. nodout: head CG acceleration and angular velocity ---------------------
nodout = read_nodout(data / "helmet" / "drop" / "nodout")
print(nodout.summary())
node = nodout.ids[0]
t = nodout.time / 1000.0                                 # ms -> s

head_g = []
for axis in "xyz":                                       # mm/ms^2 -> g, CFC 1000
    a_g = nodout.channel(f"{axis}_acceleration", node) * 1000.0 / 9.80665
    t_u, a_u = resample_uniform(t, a_g, 10_000.0)        # output is not exactly uniform
    head_g.append(cfc_filter(t_u, a_u, 1000))
resultant = np.sqrt(sum(a**2 for a in head_g))
hic = calculate_hic(t_u, resultant)
print(f"\nHead CG: peak {resultant.max():.1f} g, HIC15 {hic.value:.1f} "
      f"({hic.start_time_ms:.1f} to {hic.end_time_ms:.1f} ms)")

omega = [nodout.channel(f"r{axis}_velocity", node) * 1000.0 for axis in "xyz"]
# The model's x axis is the head's pitch axis, so the x and y critical
# velocities swap places: (56.45, 66.25, 42.87) rad/s.
print(f"BrIC {bric(t, *omega, critical=(56.45, 66.25, 42.87)).value:.3f}")
print("The study reported HIC 195.2 and BrIC 0.388 from these files.")

# --- 2. secforc: upper neck section forces and moments ------------------------
secforc = read_secforc(data / "helmet" / "pendulum" / "secforc")
section = secforc.ids[0]
force_n = 1000.0 * secforc.channel("total_force", section)        # kN -> N
moment_nm = secforc.channel("total_moment", section)              # kN mm = N m
tension_n = 1000.0 * secforc.channel("z_force", section)
print(f"\n{secforc.name(section)}: peak force {force_n.max():.0f} N, "
      f"peak tension {tension_n.max():.0f} N, peak moment {moment_nm.max():.2f} N m "
      f"(section area {secforc.channel('area', section)[-1]:.0f} mm^2)")

# --- 3. A whole run directory: every ASCII file it contains -------------------
run = read_run(data / "pladebuk")
print(f"\nFiles found: {', '.join(run)}")
contacts = run["rcforc"]
print("rcforc contacts: " + ", ".join(
    f"{cid} ({' '.join(contacts.name(cid).split())})" for cid in contacts.ids))
spc = run["spcforc"]
reaction = np.nansum(spc.channel("y_force"), axis=1)
print(f"spcforc: {len(spc.ids)} constrained nodes; y reaction at t = "
      f"{spc.time[-1]:g}: sum of nodes {reaction[-1]:.3f}, "
      f"printed resultant {spc.totals['y_force'][-1]:.3f}")

# --- 4. Into a feature table (see example 11) ------------------------------------
features = signal_features(t_u, resultant, prefix="head_res.", spectrum=False)
print(f"\n{len(features)} features of the head resultant, e.g. " + ", ".join(
    f"{k} {features[k]:.3g}" for k in ("head_res.t_peak_abs_ms", "head_res.rise_ms",
                                       "head_res.width50_ms")))
