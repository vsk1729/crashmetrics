"""Example 36: LS-DYNA binout files, read and used like the ASCII outputs.

1. A real binout (LS-DYNA R14 plate run, MIT licence, see
   tests/data/lsdyna/README.md): what is in it, its symbol tables
   checked, and its spcforc compared with the ASCII spcforc the same run
   wrote.
2. A synthetic frontal crash written as a binout instead of ASCII files:
   load paths, spot welds and the model quality sheet read straight from
   the run folder, the same calls as for ASCII output.
3. The same run as ASCII and as binout: the differences are the ASCII
   print precision.
"""

from pathlib import Path

import numpy as np

from crashmetrics.binout import read_binout
from crashmetrics.loadpath import energy_ranking, load_run
from crashmetrics.lsdyna_ascii import read_spcforc
from crashmetrics.quality import check_model
from crashmetrics.spotweld import load_welds, weld_summary
from crashmetrics.synthetic import frontal_model, simulate

plate = Path(__file__).resolve().parents[1] / "tests" / "data" / "lsdyna" / "pladebuk"

# --- 1. A real binout ------------------------------------------------------------
bo = read_binout(plate / "binout")
print(bo.summary())
print("symbol tables agree with the records:", bo.verify() == [])
spc = bo.output("spcforc")                      # an AsciiOutput, as read_spcforc
ascii_spc = read_spcforc(plate / "spcforc")
diff = np.max(np.abs(spc.data["y_force"] - ascii_spc.data["y_force"]))
print(f"spcforc y force, binout against ASCII: largest difference {diff:.1e} "
      f"(ASCII prints 5 digits); resultant {spc.totals['y_force'][-1]:.6f} "
      f"against {ascii_spc.totals['y_force'][-1]:g}")
print()

# --- 2. A run with binout output ---------------------------------------------------
simulate(frontal_model("baseline")).write("runs/binout_run", binout=True)
print("files:", ", ".join(sorted(p.name for p in Path("runs/binout_run").iterdir())))
run = load_run("runs/binout_run")               # matsum and secforc from binout
print(energy_ranking(run).table(top=5))
welds = weld_summary(load_welds("runs/binout_run"))
print(welds.table(top=3))
sheet = check_model("runs/binout_run", target_mass=1500.0, target_cg=(1305, 0, 550))
print(sheet.summary())
print()

# --- 3. The same run as ASCII and as binout --------------------------------------
simulate(frontal_model("baseline")).write("runs/ascii_run")
a, b = load_run("runs/ascii_run"), load_run("runs/binout_run")
for name, x, y in (
    ("matsum internal energy", a.energies.internal, b.energies.internal),
    ("secforc x force", a.sections.data["x_force"], b.sections.data["x_force"]),
):
    rel = np.nanmax(np.abs(x - y)) / np.nanmax(np.abs(y))
    print(f"{name}: largest difference {rel:.1e} of the peak (ASCII rounding)")
bo = read_binout("runs/binout_run")
for csv in bo.to_csv("runs/binout_csv", ["secforc", "glstat"]):
    print("written:", csv.as_posix())
