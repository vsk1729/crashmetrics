"""Example 2: Euro NCAP headform grid score (2026 and 2023 protocols).

Every grid point gets a predicted HIC15 (for example from CAE) or a
label: "blue" (scored from its own test), "default_red" (0 points) or
"a_pillar" (2026 reward tests). Verification tests then correct the
predicted points.
"""

from collections import Counter

from crashmetrics.pedestrian import correction_factor, headform_score, hic_colour

# --- 1. Predicted HIC15 per grid point (row, column) -----------------------
grid = {}
for row in range(-2, 9):                 # rows along the wrap-around distance
    for col in range(-6, 7):             # columns across the car
        # Softer bonnet centre, stiffer near the cowl and the wings.
        grid[(row, col)] = 450.0 + 28.0 * col * col + 60.0 * max(row - 5, 0) ** 2
grid[(8, 0)] = "default_red"             # e.g. a wiper spindle area
grid[(7, 3)] = grid[(7, -3)] = "blue"    # tested zones, scored from their tests
grid[(8, 6)] = grid[(8, -6)] = "a_pillar"

colours = Counter(hic_colour(v) for v in grid.values() if isinstance(v, float))
print(f"Grid points  : {len(grid)}  predicted colours {dict(sorted(colours.items()))}")

# --- 2. Verification tests (measured HIC15 at 40 km/h) ----------------------
verification = {(0, 0): 760.0, (3, 4): 1180.0, (6, -5): 1460.0, (8, 2): 1050.0}
cf = correction_factor({p: (grid[p], hic) for p, hic in verification.items()})
# Outside 0.850-1.150 the prediction is reviewed with Euro NCAP; the factor
# is still applied in the score below.
print(f"Correction   : factor {cf.factor:.3f}, accepted without review: {cf.accepted}")
for test in cf.tests:
    print(f"  point {test.point}: predicted {test.predicted_colour:6s} measured "
          f"{test.measured_hic:6.0f} -> {test.assessed_colour}")

# --- 3. Head score -----------------------------------------------------------
blue = {(7, 3): 900.0, (7, -3): 1250.0}              # measured HIC15
a_pillar = {(8, 6): [(20.0, 880.0), (30.0, 1500.0)],  # (km/h, HIC15)
            (8, -6): [(20.0, 1100.0)]}
for protocol in ("euroncap_2026", "euroncap_2023"):
    result = headform_score(
        grid, verification=verification, blue_results=blue,
        a_pillar_results=a_pillar if protocol == "euroncap_2026" else None,
        protocol=protocol,
    )
    print(f"{protocol}: head {result.score:.3f} / {result.max_score:g} points "
          f"({result.percentage:.1f} %), A-pillar points {result.a_pillar_points:g}")

# --- 4. Prediction only (CAE stage, no tests yet) ---------------------------
cae = headform_score({p: v for p, v in grid.items() if v != "a_pillar"} | {
    (8, 6): "default_red", (8, -6): "default_red"}, blue_results=blue)
print(f"CAE estimate : {cae.score:.3f} / {cae.max_score:g} points (no correction)")
