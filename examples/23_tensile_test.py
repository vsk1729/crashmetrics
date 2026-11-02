"""Example 23: read, clean and evaluate a tensile test (first step to *MAT_024).

A tensile test of a dual-phase steel sheet as a test machine exports it:
a semicolon-separated CSV with decimal commas, force in kN and
extensometer elongation in mm, with a seating toe at the start, noise,
and the fracture at the end. The data is synthetic (Swift hardening,
E = 210 GPa) so the result can be checked.

1. Read the file (columns found by name, units from the header).
2. Clean the curve: cut after fracture, smooth, toe correction.
3. Tensile properties: E, Rp0.2, Rm, Ag, A.
"""

from pathlib import Path

import numpy as np

from crashmetrics.materials import clean_tensile, read_tensile, tensile_properties

# --- A machine export (synthetic) ------------------------------------------------
E, K, EPS0, N = 210_000.0, 1000.0, 0.004, 0.17      # MPa, MPa, -, -
WIDTH, THICKNESS, GAUGE = 20.0, 1.2, 80.0          # mm

sig_y = K * EPS0 ** N
sig = np.concatenate((np.linspace(0.0, sig_y, 80, endpoint=False),
                      K * (EPS0 + np.linspace(0.0, 0.25, 1500)) ** N))
eps_p = np.concatenate((np.zeros(80), np.linspace(0.0, 0.25, 1500)))
eps_true = sig / E + eps_p
strain = np.expm1(eps_true)
stress = sig * np.exp(-eps_true)
strain = np.concatenate((strain, strain[-1] + [2e-4, 4e-4]))   # fracture
stress = np.concatenate((stress, [150.0, 5.0]))
strain = strain + 0.0025 + 0.0015 * np.clip(1 - stress / 50.0, 0, 1) ** 2  # toe
stress = stress + np.random.default_rng(23).normal(0.0, 3.0, len(stress))  # noise

force_kn = stress * WIDTH * THICKNESS / 1000.0
elongation = strain * GAUGE
lines = ["Specimen;DP-L01", "Time;Force;Elongation", "s;kN;mm"]
lines += [f"{i * 0.02:.2f};{f:.5f};{d:.5f}".replace(".", ",")
          for i, (f, d) in enumerate(zip(force_kn, elongation))]
Path("DP-L01.csv").write_text("\n".join(lines) + "\n", encoding="cp1252")

# --- 1. Read ------------------------------------------------------------------
test = read_tensile("DP-L01.csv", gauge_length=GAUGE, width=WIDTH,
                    thickness=THICKNESS)
print(f"Read {len(test)} points of {test.name}: columns {test.info['columns']}, "
      f"units {test.info['units']}")

# --- 2. Clean -------------------------------------------------------------------
clean = clean_tensile(test, smooth=21)
log = clean.info["cleaning"]
print(f"Cut after fracture at {log['cut_after_strain'] * 100:.2f} % strain "
      f"({log['points_cut']} points), smoothed over {log['smoothing_window']} "
      f"points, toe: strain shifted by {log['toe_strain_shift'] * 100:.3f} % and "
      f"{log['toe_points_removed']} points replaced by the origin")

# --- 3. Properties ------------------------------------------------------------
raw = tensile_properties(test)
props = tensile_properties(clean)
print()
print(props.summary(clean.name))

# --- Check against the exact values of the synthetic steel -----------------------
ep = np.linspace(0.0, 0.25, 500_001)
s_true = K * (EPS0 + ep) ** N
e_true = s_true / E + ep
s_eng, e_eng = s_true * np.exp(-e_true), np.expm1(e_true)
peak = int(np.argmax(s_eng))
rp = s_eng[np.flatnonzero(s_eng - E * (e_eng - 0.002) <= 0)[0]]
print()
print("              exact     raw   cleaned")
print(f"Rp0.2 MPa   {rp:7.1f} {raw.yield_strength:7.1f} {props.yield_strength:9.1f}")
print(f"Rm MPa      {s_eng[peak]:7.1f} {raw.tensile_strength:7.1f} "
      f"{props.tensile_strength:9.1f}")
print(f"Agt %       {e_eng[peak] * 100:7.2f} {raw.uniform_elongation_total * 100:7.2f} "
      f"{props.uniform_elongation_total * 100:9.2f}")
print("Raw: the toe adds strain and the noise moves the maximum on the flat top;")
print("the cleaned curve gives the material's values.")
