"""Example 27: tensile test to a *MAT_024 include file.

The whole chain for a DP600 sheet (synthetic test data, 1.5 MPa noise):

1. Clean the test, plastic curve from Rp0.2, Swift-Voce extrapolation.
2. Simple failure strain for 2.5 mm shells of 1.2 mm sheet, from the
   reduction of area (screening only; GISSMO is better).
3. Card with Cowper-Symonds C and P, written in mm-ms-kg with a
   provenance header.
4. The same material with a strain-rate table instead, in mm-s-t.
"""

import datetime as dt
from pathlib import Path

import numpy as np

from crashmetrics.materials import (
    CowperSymonds,
    Mat024,
    TensileTest,
    clean_tensile,
    extrapolate_curve,
    failure_strain,
    fit_hardening,
    fracture_strain,
    plastic_curve,
    rate_table_from_model,
    tensile_properties,
)

E = 210_000.0


def truth(p):
    return 0.6 * 980.0 * (0.004 + p) ** 0.17 + 0.4 * (370.0 + 290.0 * (
        1 - np.exp(-16.0 * p)))


p = np.linspace(0.0, 0.2, 1400)
sig = np.concatenate((np.linspace(0.0, truth(0.0), 60, endpoint=False), truth(p)))
eps = sig / E + np.concatenate((np.zeros(60), p))
stress = sig * np.exp(-eps) + np.random.default_rng(27).normal(0.0, 1.5, 1460)
test = clean_tensile(TensileTest(np.expm1(eps), stress, "DP600-L1"), smooth=15)

# --- 1. Hardening curve ------------------------------------------------------------
props = tensile_properties(test)
curve = plastic_curve(test)
fit = fit_hardening(curve, ["swift_voce"])["swift_voce"]
full = extrapolate_curve(curve, fit, strain_max=1.0, points=40)
print(f"Rp0.2 {props.yield_strength:.0f} MPa, Rm {props.tensile_strength:.0f} MPa, "
      f"necking at plastic strain {curve.necking_strain:.3f}; Swift-Voce RMS "
      f"{fit.rms:.2f} MPa")

# --- 2. Failure strain -------------------------------------------------------------
eps_frac = fracture_strain(0.55)                     # reduction of area 55 %
fail = failure_strain(uniform=curve.necking_strain, fracture=eps_frac,
                      element_size=2.5, neck_length=1.2)
print(f"Fracture strain {eps_frac:.3f} in the neck; FAIL for 2.5 mm elements "
      f"{fail:.3f}")

# --- 3. Card with Cowper-Symonds ---------------------------------------------------
mat = Mat024(mid=600, density=7850.0, modulus=E, curve=full, c=40.4, p=5.0,
             fail=fail, title="DP600 1.2 mm",
             provenance={"tests": "DP600-L1, 0.001 /s, rolling direction",
                         "hardening": "measured to necking, Swift-Voce beyond",
                         "rate": "Cowper-Symonds C 40.4 /s, P 5",
                         "failure": "FAIL from Z = 55 %, 2.5 mm shells"})
path = mat.write(Path("dp600_mat024.k"), "mm-ms-kg", points=30,
                 date=dt.date(2026, 11, 2))
lines = path.read_text().splitlines()
print()
# (line 2 of the header names the crashmetrics version, left out here)
print("\n".join([lines[0], *lines[2:22]]))
print("...")
print("\n".join(lines[-3:]))

# --- 4. The same material with a rate table (mm-s-t) -------------------------------
table = rate_table_from_model(full, CowperSymonds(40.4, 5.0, 0.0, 0.0, 0),
                              [0.001, 1.0, 10.0, 100.0, 1000.0], points=30)
tabled = Mat024(mid=601, density=7850.0, modulus=E, table=table, vp=1,
                title="DP600 1.2 mm table")
text = tabled.keyword("mm-s-t")
print()
print("\n".join(text.splitlines()[:21]))
print(f"... {len(text.splitlines())} lines: the card, the table and 5 curves")
