"""Example 29: GISSMO failure model for a DP800 sheet.

From fracture tests to ``*MAT_ADD_DAMAGE_GISSMO`` (synthetic tests made
from a known Hosford-Coulomb curve, with 2-3 % scatter added):

1. Five fracture tests from shear to equibiaxial tension. Triaxiality
   changes while they load (the dogbone after necking, the notch as it
   thins), so each test carries its path from a simulation of the test.
2. Hosford-Coulomb and Johnson-Cook failure curves, fitted so that the
   damage reaches 1 at every measured fracture.
3. Instability (ECRIT) from the forming limit curve.
4. Element size regularisation (first estimate, before a mesh study).
5. Damage and stress fading of a 2.5 mm shell in uniaxial tension.
6. ``*MAT_024`` with the GISSMO card in one include (mm-ms-kg), read back
   and checked.
"""

import datetime as dt
import math
from pathlib import Path

import numpy as np

from crashmetrics.materials import (
    TRIAXIALITY,
    FractureTest,
    GissmoCard,
    HardeningCurve,
    Mat024,
    check_gissmo,
    fit_failure_curve,
    instability_from_flc,
    integrate_damage,
    read_keyword,
    regularization_estimate,
)
from crashmetrics.materials.gissmo import _hosford_coulomb


def truth(eta):
    """The synthetic material's failure curve (unknown in practice)."""
    return _hosford_coulomb(np.asarray(eta, dtype=float), 1.45, 0.60, 0.03, 0.1)


def ramp(start, end, over):
    """Triaxiality going from start to end over the first `over` strain."""
    return lambda e: start + (end - start) * np.minimum(np.asarray(e) / over, 1.0)


def dogbone(e):
    """Uniaxial until necking at 0.12, then rising as the neck forms."""
    return 1 / 3 + (0.45 - 1 / 3) * np.clip((np.asarray(e) - 0.12) / 0.38, 0.0, 1.0)


# --- 1. Fracture tests -------------------------------------------------------------
specimens = {"shear": ramp(0.03, 0.08, 0.5),
             "dogbone": dogbone,
             "notch R5": ramp(0.40, 0.50, 0.3),
             "plane strain R2": ramp(0.53, 0.57, 0.2),
             "Nakajima biaxial": ramp(0.64, 0.665, 0.3)}
scatter = [1.02, 0.97, 1.03, 0.98, 1.01]
tests = []
e = np.linspace(0.0, 2.0, 4001)
for (name, path), s in zip(specimens.items(), scatter):
    ef = round(integrate_damage(e, path(e), truth).fracture_strain * s, 3)
    pe = np.linspace(0.0, ef, 41)
    tests.append(FractureTest(name, ef, path_strain=pe, path_triaxiality=path(pe)))
print(f"{'test':18} {'eta start':>9} {'eta end':>8} {'average':>8} {'fracture':>9}")
for t in tests:
    print(f"{t.name:18} {t.path_triaxiality[0]:9.3f} {t.path_triaxiality[-1]:8.3f} "
          f"{t.eta:8.3f} {t.fracture_strain:9.3f}")

# --- 2. Failure curves -------------------------------------------------------------
hc = fit_failure_curve(tests)                        # Hosford-Coulomb
jc = fit_failure_curve(tests, "johnson_cook")
print()
print(hc.summary())
print()
print(jc.summary())
states = {"compression": TRIAXIALITY["uniaxial_compression"], "shear": 0.0,
          "uniaxial": 1 / 3, "plane strain": 1 / math.sqrt(3), "equibiaxial": 2 / 3}
print()
print(f"{'failure strain':15} {'eta':>7} {'HC':>7} {'JC':>7} {'truth':>7}")
for name, eta in states.items():
    print(f"{name:15} {eta:7.3f} {float(hc(eta)):7.3f} {float(jc(eta)):7.3f} "
          f"{float(truth(eta)):7.3f}")
print("(compression is extrapolated: no test below shear)")

# --- 3. Instability from the forming limit curve -----------------------------------
major = [0.36, 0.22, 0.14, 0.17, 0.21]
minor = [-0.20, -0.10, 0.0, 0.08, 0.15]
eta_c, eps_c = instability_from_flc(major, minor)
print()
print("ECRIT from the FLC (triaxiality, critical strain):")
print("  " + "  ".join(f"({x:.3f}, {y:.3f})" for x, y in zip(eta_c, eps_c)))

# --- 4. Regularisation -------------------------------------------------------------
# The specimens were simulated with 0.5 mm elements (the reference size);
# the neck is about as long as the sheet is thick.
reg = regularization_estimate([1.0, 2.5, 5.0, 10.0], reference_size=0.5,
                              necking_strain=0.12, fracture_strain=float(hc(1 / 3)),
                              neck_length=1.0)
print()
print("LCREGD estimate: " + ", ".join(f"{h:g} mm {f:.3f}" for h, f in
                                      zip(reg.element_size, reg.factor)))

# --- 5. The card and a 2.5 mm shell in uniaxial tension ----------------------------
card = GissmoCard(mid=800, failure=hc, instability=(eta_c, eps_c), dmgexp=2.0,
                  fadexp=3.0, regularization=reg)
# The check flags where large elements fail before they fade: one LCREGD
# curve regularises every stress state, also shear, where no neck forms.
errors, warnings = card.check()
print()
print(f"Card check: {len(errors)} errors, {len(warnings)} warnings")
for w in warnings:
    print(f"  warning: {w}")
strain = np.linspace(0.0, 0.5, 501)
h = card.damage(strain, np.full_like(strain, 1 / 3), element_size=2.5)
print(f"2.5 mm shell, uniaxial: failure strain {h.fracture_strain:.3f} "
      f"(x {reg(2.5):.3f}), coupling at {h.coupling_strain:.3f}, "
      f"D_crit {h.critical_damage:.3f}")
print(f"{'strain':>8} {'D':>7} {'F':>7} {'stress':>7}")
for s in (0.1, 0.2, 0.27, 0.285, 0.295, 0.3, 0.305, 0.31):
    i = int(np.argmin(np.abs(strain - s)))
    print(f"{s:8.3f} {h.damage[i]:7.3f} {h.instability[i]:7.3f} "
          f"{h.fading[i] * 100:6.1f}%")

# --- 6. *MAT_024 with GISSMO, read back and checked --------------------------------
p = np.concatenate(([0.0], np.geomspace(1e-3, 1.0, 39)))
hardening = HardeningCurve(p, 1250.0 * (0.003 + p) ** 0.14, 210_000.0, 0.12, "DP800")
mat = Mat024(mid=800, density=7850.0, modulus=210_000.0, curve=hardening,
             c=40.4, p=5.0, title="DP800 1.0 mm")
path = mat.write(Path("dp800_gissmo.k"), "mm-ms-kg", damage=card,
                 date=dt.date(2026, 11, 2))
lines = path.read_text().splitlines()
start = lines.index("*MAT_ADD_DAMAGE_GISSMO")
print()
print("\n".join(lines[start:start + 14]))
print("...")
deck = read_keyword(path)
print(check_gissmo(deck)[0].summary())
back = deck.damage(800)
x = np.linspace(-1 / 3, 2 / 3, 7)
diff = np.max(np.abs(back.failure_strain(x, 2.5) / card.failure_strain(x, 2.5) - 1))
print(f"Read back: {len(deck.curves)} curves, failure strain within {diff:.1e}")
