"""Example 25: from a tensile test to the extrapolated *MAT_024 hardening curve.

A dual-phase steel tensile test (synthetic, with noise): the true
hardening of this "material" is a Swift-Voce mix, so it is known at
every strain and the extrapolation can be judged.

1. Clean the test; true stress-strain; necking (Considère).
2. Effective plastic strain from Rp0.2 to necking: the measured part.
3. Fit Swift, Voce, Hockett-Sherby and Swift-Voce; compare them beyond
   necking, where the test gives no data.
4. Extrapolate with the chosen law to 100 % plastic strain.
5. n and K values.
"""

import numpy as np

from crashmetrics.materials import (
    TensileTest,
    clean_tensile,
    compare_fits,
    extrapolate_curve,
    fit_hardening,
    n_value,
    necking_point,
    plastic_curve,
)

E = 210_000.0


def truth(p):
    """True stress (MPa) of the synthetic DP steel at plastic strain p."""
    swift = 1050.0 * (0.004 + p) ** 0.19
    voce = 420.0 + 330.0 * (1.0 - np.exp(-14.0 * p))
    return 0.6 * swift + 0.4 * voce


p = np.linspace(0.0, 0.2, 1500)
sig = np.concatenate((np.linspace(0.0, truth(0.0), 70, endpoint=False), truth(p)))
eps = sig / E + np.concatenate((np.zeros(70), p))
strain, stress = np.expm1(eps), sig * np.exp(-eps)
strain = np.concatenate((strain, strain[-1] + [2e-4, 4e-4]))          # fracture
stress = np.concatenate((stress, [200.0, 5.0]))
stress = stress + np.random.default_rng(25).normal(0.0, 1.5, len(stress))
test = clean_tensile(TensileTest(strain, stress, "DP-T1"), smooth=15)

# --- 1. Necking ---------------------------------------------------------------
neck = necking_point(test)
print(f"Necking: engineering strain {neck.engineering_strain * 100:.2f} %, "
      f"Rm {neck.engineering_stress:.1f} MPa; true strain "
      f"{neck.true_strain:.4f}, true stress {neck.true_stress:.1f} MPa "
      f"(Considère ratio {neck.considere_ratio:.2f})")

# --- 2. Measured plastic curve ----------------------------------------------------
curve = plastic_curve(test)                  # starts at Rp0.2, plastic strain 0
print(f"Plastic curve: {len(curve.plastic_strain)} points, yield (SIGY) "
      f"{curve.yield_stress:.1f} MPa, measured up to plastic strain "
      f"{curve.necking_strain:.4f}, E {curve.modulus / 1000:.1f} GPa")

# --- 3. Hardening laws -----------------------------------------------------------
fits = fit_hardening(curve)
print()
print("Fits to the measured part, and their stress (MPa) at plastic strain:")
print(compare_fits(fits, strains=(0.1, 0.3, 0.5, 1.0)))
exact = [truth(e + 0.002) for e in (0.1, 0.3, 0.5, 1.0)]
print(f"{'truth':15} {'':8} {'':8} {'':9} " + " ".join(f"{v:8.1f}" for v in exact))
for name, f in fits.items():
    print(f"  {name:13} " + ", ".join(f"{k} {v:.4g}" for k, v in f.params.items()))

# --- 4. Extrapolated card curve ----------------------------------------------------
chosen = fits["swift_voce"]
full = extrapolate_curve(curve, chosen, strain_max=1.0, points=30)
print()
print(f"Card curve ({chosen.law}): {len(full.plastic_strain)} points from "
      f"{full.plastic_strain[0]:.1f} to {full.plastic_strain[-1]:.1f} plastic strain")
for e in (0.0, 0.05, 0.15, 0.5, 1.0):
    i = int(np.argmin(np.abs(full.plastic_strain - e)))
    print(f"  eps_p {full.plastic_strain[i]:6.3f}: {full.stress[i]:7.1f} MPa "
          f"(truth {truth(full.plastic_strain[i] + 0.002):7.1f})")

# --- 5. n and K -------------------------------------------------------------------
nv = n_value(test)
print()
print(f"n10-Ag = {nv.n:.3f}, K = {nv.k:.0f} MPa (R² {nv.r2:.4f}, "
      f"{nv.points} points)")
