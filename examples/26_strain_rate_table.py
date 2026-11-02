"""Example 26: strain-rate tests to Cowper-Symonds and a *DEFINE_TABLE.

Tensile tests of one steel at 0.001, 1, 100 and 500 /s (synthetic, 2 MPa
noise; dynamic tests are noisier in practice). The "true" rate effect is
Cowper-Symonds with C = 40.4 /s and P = 5.

1. Each test: clean -> plastic curve -> Swift-Voce fit -> extrapolate.
2. Fit Cowper-Symonds (card fields C, P) and the Johnson-Cook rate term.
3. Rate table from the static curve and the fitted law: check, write.
4. Rate table from separately extrapolated curves, where 100 /s was
   extrapolated with Swift (keeps hardening) and 500 /s with Voce
   (saturates): the check finds where the curves cross.
"""

import numpy as np

from crashmetrics.materials import (
    TensileTest,
    clean_tensile,
    extrapolate_curve,
    fit_cowper_symonds,
    fit_hardening,
    fit_johnson_cook_rate,
    plastic_curve,
    rate_table_from_curves,
    rate_table_from_model,
)

E, C, P = 210_000.0, 40.4, 5.0
rng = np.random.default_rng(26)


def tensile(rate):
    """Engineering curve of the steel at a strain rate (true law: Swift-Voce
    static hardening times the Cowper-Symonds factor)."""
    def law(p):
        static = 0.6 * 1000.0 * (0.005 + p) ** 0.18 + 0.4 * (
            380.0 + 300.0 * (1 - np.exp(-15.0 * p)))
        return static * (1 + (rate / C) ** (1 / P))

    p = np.linspace(0.0, 0.2, 1200)
    sig = np.concatenate((np.linspace(0.0, law(0.0), 60, endpoint=False), law(p)))
    eps = sig / E + np.concatenate((np.zeros(60), p))
    strain, stress = np.expm1(eps), sig * np.exp(-eps)
    stress = stress + rng.normal(0.0, 2.0, len(stress))
    return TensileTest(strain, stress, f"{rate:g}/s")


# --- 1. Each test to an extrapolated curve ------------------------------------------
measured, extrapolated = {}, {}
print("rate /s   SIGY MPa  necking eps_p  Swift-Voce RMS MPa")
for rate in (0.001, 1.0, 100.0, 500.0):
    curve = plastic_curve(clean_tensile(tensile(rate), smooth=15))
    fit = fit_hardening(curve, ["swift_voce"])["swift_voce"]
    measured[rate] = curve
    extrapolated[rate] = extrapolate_curve(curve, fit, strain_max=1.0, points=30)
    print(f"{rate:8g} {curve.yield_stress:10.1f} {curve.necking_strain:14.4f} "
          f"{fit.rms:19.2f}")

# --- 2. Rate laws --------------------------------------------------------------------
cs = fit_cowper_symonds(measured)
jc = fit_johnson_cook_rate(measured)
print()
print(f"Cowper-Symonds: C = {cs.c:.1f} /s ({cs.c / 1000:.4f} /ms), P = {cs.p:.2f} "
      f"(truth 40.4, 5); RMS of the stress ratio {cs.rms:.4f}")
print(f"Johnson-Cook:   c = {jc.c:.4f} with rate0 = {jc.reference_rate:g} /s; "
      f"RMS {jc.rms:.4f}")
print("Dynamic / quasi-static stress:")
for rate in (1.0, 10.0, 100.0, 1000.0):
    print(f"  {rate:6g} /s: Cowper-Symonds {float(cs.ratio(rate)[()]):.3f}, "
          f"Johnson-Cook {float(jc.ratio(rate)[()]):.3f}")

# --- 3. Table from the static curve and the law -------------------------------------
rates = [0.001, 0.01, 0.1, 1.0, 10.0, 100.0, 500.0, 1000.0]
table = rate_table_from_model(extrapolated[0.001], cs, rates, points=40)
check = table.check(log_rates=True, unit_system="mm-ms-kg")
print()
print(f"Table from Cowper-Symonds: {len(table.rates)} rates x "
      f"{len(table.plastic_strain)} points")
print(check.summary())
text = table.keyword(2000, unit_system="mm-ms-kg", log_rates=True,
                     title="steel rate table")
print("\n".join(text.splitlines()[:13]))
print(f"... {len(text.splitlines())} lines")

# --- 4. Table from curves extrapolated with different laws ---------------------------
mixed = dict(extrapolated)
for rate, law in ((100.0, "swift"), (500.0, "voce")):
    fit = fit_hardening(measured[rate], [law])[law]
    mixed[rate] = extrapolate_curve(measured[rate], fit, strain_max=1.0, points=30)
direct = rate_table_from_curves(mixed, points=40)
print()
print("Table from curves extrapolated separately (100 /s Swift, 500 /s Voce):")
print(direct.check(log_rates=True, unit_system="mm-ms-kg").summary())
