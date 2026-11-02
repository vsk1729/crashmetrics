"""Example 24: several specimens, Lüders plateau and machine compliance.

Three tensile specimens of a mild steel sheet (synthetic data, 1 MPa
noise), each with a Lüders plateau. Specimen 3 was tested without an
extensometer: its strain comes from the cross-head, so it includes the
machine compliance.

1. Correct the compliance of specimen 3 with E = 210 GPa.
2. Clean all three; find ReH, ReL and the yield point elongation Ae.
3. Replace the plateau for a *MAT_024 card (flat at ReL, or removed).
4. Mean curve of the three and the scatter of their properties.
"""

import numpy as np

from crashmetrics.materials import (
    TensileTest,
    clean_tensile,
    correct_compliance,
    luders_plateau,
    mean_curve,
    property_scatter,
    scatter_summary,
    smooth_luders,
)

E = 210_000.0                                      # MPa
rng = np.random.default_rng(24)


def mild_steel(name, reh, rel, ae_end, k, seed_shift):
    """Elastic to ReH, dip, plateau oscillating 0-6 MPa above ReL to ae_end,
    then hardening up to fracture."""
    e_el = np.linspace(0.0, reh / E, 60)
    e_pl = np.linspace(reh / E + 1e-5, ae_end, 300)
    phase = (e_pl - e_pl[0]) / (ae_end - e_pl[0])
    s_pl = rel + 3.0 + 3.0 * np.cos(2 * np.pi * (7 + seed_shift) * phase)
    s_pl[:12] = np.linspace(rel - 8.0, rel + 6.0, 12)              # transient dip
    e_h = np.linspace(ae_end + 1e-4, 0.32, 500)
    x = e_h - ae_end
    s_h = rel + 6.0 + k * x ** 0.55 * np.exp(-1.7 * x)
    strain = np.concatenate((e_el, e_pl, e_h, [0.3201, 0.3202]))
    stress = np.concatenate((e_el * E, s_pl, s_h, [60.0, 4.0]))   # fracture
    return TensileTest(strain, stress + rng.normal(0.0, 1.0, len(stress)), name)


specimens = [mild_steel("MS-1", 318.0, 289.0, 0.024, 690.0, 0),
             mild_steel("MS-2", 324.0, 292.0, 0.027, 700.0, 1),
             mild_steel("MS-3", 321.0, 290.0, 0.025, 680.0, 2)]

# --- 1. Machine compliance of specimen 3 (cross-head strain) -------------------
crosshead = 1 / 95_000.0 - 1 / E                    # extra strain per MPa
ms3 = specimens[2]
specimens[2] = TensileTest(ms3.strain + ms3.stress * crosshead, ms3.stress,
                           "MS-3", {"area_mm2": 25.0, "gauge_length_mm": 80.0})
fixed = correct_compliance(specimens[2], modulus=E)
c = fixed.info["compliance"]
print(f"MS-3 cross-head strain: measured E {c['measured_modulus'] / 1000:.1f} GPa; "
      f"machine compliance {fixed.info['compliance_mm_per_n'] * 1e6:.2f} µm/N "
      "removed")
specimens[2] = fixed

# --- 2. Clean and find the Lüders plateau ---------------------------------------
clean = [clean_tensile(t) for t in specimens]
print()
print("Specimen   ReH    ReL    Ae")
for t in clean:
    p = luders_plateau(t)
    assert p is not None
    print(f"{t.name:8} {p.upper_yield:6.1f} {p.lower_yield:6.1f} "
          f"{p.elongation * 100:5.2f} %")

# --- 3. Plateau replaced for a material card -------------------------------------
flat = smooth_luders(clean[0], mode="flat")
removed = smooth_luders(clean[0], mode="remove")
print()
print(f"MS-1 for a card: flat at ReL {flat.info['luders']['lower_yield']:.1f} MPa, "
      f"or plateau removed ({removed.info['luders']['strain_removed'] * 100:.2f} % "
      "strain taken out)")

# --- 4. Mean curve and scatter ----------------------------------------------------
cards = [smooth_luders(t, mode="remove") for t in clean]
mean = mean_curve(cards, points=200)
print()
print(f"Mean of {mean.count} specimens up to {mean.strain[-1] * 100:.1f} % strain")
for target in (0.01, 0.05, 0.15, 0.25):
    i = int(np.argmin(np.abs(mean.strain - target)))
    print(f"  strain {mean.strain[i] * 100:5.1f} %: {mean.mean[i]:6.1f} MPa "
          f"± {mean.std[i]:4.1f} (min {mean.minimum[i]:6.1f}, max "
          f"{mean.maximum[i]:6.1f})")
print()
print("Scatter of the tensile properties (curves with the plateau removed):")
print(scatter_summary(property_scatter(cards)))
