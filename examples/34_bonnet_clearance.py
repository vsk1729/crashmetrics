"""Example 34: bonnet clearance, bottoming out, and why a point is red.

A headform study of a bonnet (synthetic, crashmetrics.pedestrian.synthetic):
the bonnet and its hard parts as a keyword mesh, the grid points in a CSV,
and a nodout of the headform per impact. Point the same calls at your own
model, points and runs.

1. Geometry: the free space under each point, and the space a HIC target
   needs.
2. The impacts: HIC, colour, bottoming out and its cause for every point.
3. One red point explained.
4. Design loops: the engine 20 mm lower, a stiffer bonnet inner panel.
"""

from crashmetrics.mesh import read_mesh
from crashmetrics.pedestrian.clearance import (
    assess_grid,
    clearance,
    clearance_map,
    clearance_table,
    compare_grids,
    head_impact,
    impact_direction,
    read_impact_points,
    required_clearance,
)
from crashmetrics.pedestrian.synthetic import bonnet_model, simulate_grid


def analyse(folder):
    """Clearances and assessed impacts of one design loop."""
    mesh = read_mesh(f"{folder}/bonnet.k")
    points = read_impact_points(f"{folder}/impact_points.csv")
    hard = {mesh.part_name(p): mesh.points(p) for p in mesh.part_ids
            if mesh.part_name(p) != "Bonnet outer"}
    gaps = clearance({k: p.point for k, p in points.items()}, hard,
                     {k: impact_direction(p.headform) for k, p in points.items()},
                     surface=mesh.points(mesh.find_parts("Bonnet*")))
    impacts = {k: head_impact(p.run, headform=p.headform) for k, p in points.items()}
    return gaps, assess_grid(impacts, gaps)


for variant in ("baseline", "lower_engine", "stiff_inner"):
    simulate_grid(bonnet_model(variant)).write(f"runs/{variant}")

# --- 1. Geometry -----------------------------------------------------------------
print(clearance_table())
needed = required_clearance(1000, shape="half_sine") + 5     # + bonnet stack
print(f"\nHIC 1000 with a half-sine pulse needs {needed:.0f} mm of free space.\n")
gaps, base = analyse("runs/baseline")
print(clearance_map(gaps, needed=round(needed)))

# --- 2. The impacts --------------------------------------------------------------
print()
print(base.map())
print()
print(base.summary())
print()
print(base.table(top=6))
base.to_csv("headform_grid.csv")                             # every point

# --- 3. One red point ------------------------------------------------------------
p = base.points[(2, 0)]
print(f"\nPoint (2, 0): HIC {p.hic:.0f} ({p.colour}), {p.diagnosis}")
print(f"  free space {p.clearance:.0f} mm to the {p.part}, the head travels "
      f"{p.penetration:.0f} mm")
print(f"  first peak {p.first_peak:.0f} g at {p.first_peak_time:.1f} ms, plateau "
      f"{p.plateau:.0f} g")
print(f"  bottoms out at {p.bottoming_time:.1f} ms ({p.bottoming_source}) with "
      f"{p.residual_speed:.1f} m/s, {p.residual_energy:.0f} J "
      f"({100 * p.residual_share:.0f} % of the impact energy) left")
print(f"  HIC window {p.hic_window[0]:.1f} to {p.hic_window[1]:.1f} ms: "
      f"{100 * p.hic_share_after:.0f} % of it after bottoming out")
print(f"  about {p.extra_space:.0f} mm more space would stop the head on the plateau")

# --- 4. Design loops -------------------------------------------------------------
for variant in ("lower_engine", "stiff_inner"):
    _, grid = analyse(f"runs/{variant}")
    print()
    print(compare_grids(base, grid, names=("baseline", variant)).summary(top=4))
    before, after = base.diagnoses(), grid.diagnoses()
    print("  points per cause: " + ", ".join(
        f"{k} {before[k]} -> {after[k]}" for k in ("bottoming", "first_peak",
                                                   "stiff")))
