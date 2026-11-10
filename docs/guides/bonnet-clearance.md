# Bonnet clearance: why a headform point is red

Modules: `crashmetrics.pedestrian.clearance` (analysis),
`crashmetrics.mesh` (keyword mesh reader) and
`crashmetrics.pedestrian.synthetic` (a bonnet and its headform impacts,
to try it without a solver). NumPy only.

A headform point is red for one of two reasons, and the fixes are
opposite:

1. **The head bottoms out.** It uses up the free space under the bonnet
   and hits a hard part (engine, strut tower, battery, hinge, cowl).
   The cure is space: lower or move the hard part, raise the bonnet, or
   stop the head sooner with a stiffer bonnet.
2. **The bonnet itself is too stiff** where it is hit: a heavy
   reinforcement or the latch (a high first peak), or a hinge area or a
   wing edge (a high plateau). The cure is a softer bonnet there, and
   more space is no help.

This module tells them apart, point by point, from the files every
headform study already has: the **mesh** (for the free space), the grid
**points**, and the **nodout** of the headform in each run.

| Step | Functions |
| --- | --- |
| Read the bonnet and the hard parts from the keyword mesh | `read_mesh`, `Mesh.points`, `Mesh.find_parts` |
| Read the grid points (CSV) | `read_impact_points` |
| Free space under each point, along the headform path and the surface normal | `impact_direction`, `clearance`, `clearance_map` |
| Space a HIC target needs, for a pulse shape | `required_clearance`, `clearance_table` |
| The headform's motion from nodout (CFC 1000, penetration, speed) | `head_impact` |
| HIC, bottoming out and its cause for one impact | `assess_impact` |
| All points: map, table, points lost per cause, head score, CSV | `assess_grid` |
| Two design loops of the same grid | `compare_grids` |

Lengths are in **mm**, times in **ms**, speeds in **m/s** and
accelerations in **g**, whatever the model's units (`unit_system=`,
default mm-ms-kg).

## No data at hand? Use the synthetic bonnet

```python
from crashmetrics.pedestrian.synthetic import bonnet_model, simulate_grid

simulate_grid(bonnet_model("baseline")).write("runs/baseline")
```

This writes what a real headform study gives: `bonnet.k` (the bonnet
outer and the hard parts as shell meshes), `impact_points.csv` (130 grid
points every 100 mm, rows 1 to 5 child headform, 6 to 10 adult) and one
folder with a `nodout` per impact.

Each impact is a lumped model along the headform's path:

- the headform (with a skin contact) pushes a local bonnet mass;
- the bonnet is held by its elastic-plastic bending support (the inner
  panel);
- when the bonnet has used up the free space, measured from the meshes,
  it lands on the hard part, which is stiff and crushes at a high force;
- the latch, the hinges and the wing edges are stiffer and heavier.

| Variant | What changes | What the analysis should find |
| --- | --- | --- |
| `baseline` | Reference bonnet | Red over the intake plenum, the strut towers, the battery, the hinges and the cowl (bottoming); latch and wing edges stiff |
| `lower_engine` | Engine and intake plenum 20 mm lower | The plenum points go from red to brown, orange or yellow; the head score rises |
| `stiff_inner` | Inner panel 40 % stiffer | Fewer points bottom out, but the open bonnet is now too stiff: the stiff points go from 6 to 48 and the score drops |

The model keeps the truth of every impact (`BonnetRun.truth`: when the
bonnet landed on the hard part and the head speed then), which the tests
check the analysis against. It is a teaching model, not a vehicle
simulation; the files say so in their header.

## 1. Geometry: the free space

```python
from crashmetrics.mesh import read_mesh
from crashmetrics.pedestrian.clearance import (
    clearance, clearance_map, impact_direction, read_impact_points)

mesh = read_mesh("runs/baseline/bonnet.k")
points = read_impact_points("runs/baseline/impact_points.csv")
hard = {mesh.part_name(p): mesh.points(p)
        for p in mesh.find_parts("Engine*") + mesh.find_parts("Strut*")}
gaps = clearance({k: p.point for k, p in points.items()}, hard,
                 {k: impact_direction(p.headform) for k, p in points.items()},
                 surface=mesh.points(mesh.find_parts("Bonnet*")))
print(clearance_map(gaps, needed=86))
gaps[(2, 0)]           # distance, part, contact point, normal distance ...
```

### Reading the mesh

- `read_mesh` reads `*NODE`, `*ELEMENT_SHELL`, `*ELEMENT_SOLID`,
  `*ELEMENT_BEAM` and the titles of `*PART` cards, in fixed, long (`+`)
  and comma formats.
- `*INCLUDE` files are not followed: read each and combine them with
  `Mesh.merge`.
- `mesh.points(part_ids)` gives the node coordinates of parts and
  `mesh.find_parts("Strut*")` finds parts by title.

### What counts as a hard part

Give only parts the head **cannot push away**: the engine, the strut
towers, the battery, the hinges, the cowl or wiper motor, the
radiator support top. The bonnet inner panel is not one; it is what
deforms.

### How the free space is measured

The headform is a sphere (165 mm, `radius=82.5`).

- **Where it starts.** At first contact it touches the bonnet at the
  impact point, with its centre on the surface normal (`surface=`).
- **How far it can go.** It moves along the impact direction, and the
  free space is how far it travels until the sphere touches the first
  node of a hard part.
- **The result** (`Clearance`):
  - the travel;
  - the part and the node touched;
  - that node's distance from the centre line;
  - the same measured along the surface normal (`normal_distance`).

| Headform | Mass | Diameter | Angle to the ground | Speed |
| --- | --- | --- | --- | --- |
| `child` | 3.5 kg | 165 mm | 50° | 40 km/h |
| `adult` | 4.5 kg | 165 mm | 65° | 40 km/h |

`impact_direction(headform)` is rearward and down at that angle. With
`rearward=` and `up=` it can follow other model axes; the default is x
rearward and z up.

!!! warning "Give the bonnet surface"
    On an inclined bonnet the point the headform touches is not the
    sphere's lowest point along its path. Without `surface=`, the
    headform is assumed to hit head-on, which underestimates the space
    under a sloping bonnet.

!!! tip "Mesh density"
    The sphere is checked against the **nodes** of the hard parts. With
    10 mm elements the error is below 0.2 mm, but on a coarse mesh
    (50 mm elements on a flat engine cover) refine the cover or add
    nodes on its faces.

## 2. How much space is needed

```python
from crashmetrics.pedestrian.clearance import clearance_table, required_clearance

required_clearance(1000, shape="half_sine")        # 81 mm at 40 km/h
print(clearance_table())
```

`required_clearance` scales a pulse shape in time and level until it
stops the head (40 km/h by default) with exactly that HIC15, and gives
its stopping distance.

- The **square** wave stops the head in the least space for a HIC: that
  is the physical lower limit. For HIC 1000 at 40 km/h it is 68 mm.
- Real bonnet pulses, with a first peak and a falling end, need more;
  the half-sine is a fair estimate.

| HIC15 limit | Square | Half-sine | Triangle |
| --- | --- | --- | --- |
| 650 (green) | 88 | 108 | 114 |
| 1000 (yellow) | 68 | 81 | 85 |
| 1350 (orange) | 56 | 66 | 70 |
| 1700 (brown) | 48 | 57 | 60 |

Add the crushed thickness of the bonnet outer and inner panels (about
5 mm) before comparing with the free space.

## 3. One impact: what happened

```python
from crashmetrics.pedestrian.clearance import assess_impact, head_impact

impact = head_impact("runs/baseline/r02_c+0", headform="child")
result = assess_impact(impact, gaps[(2, 0)])
print(result.colour, result.diagnosis, result.reason)
```

`head_impact` reads the headform's centre of gravity node from nodout:

- the resultant acceleration, CFC 1000 filtered;
- the penetration and the speed along the impact direction.

Penetration is measured from first contact, when the unfiltered
acceleration reaches 2 g, because the phaseless filter moves the onset
earlier.

`assess_impact` then gives:

| Result | What it is |
| --- | --- |
| `hic`, `hic_window`, `colour` | HIC15, its window and the Euro NCAP colour |
| `first_peak`, `plateau` | The first contact peak; the mean deceleration after it (until bottoming out, or the deepest penetration) |
| `penetration`, `margin` | Deepest travel; space left then (negative: used up) |
| `bottoming`, `bottoming_time`, `bottoming_source` | Whether and when the head bottomed out, and how it was found |
| `residual_speed`, `residual_energy`, `residual_share` | Head speed and energy left at that moment |
| `hic_share_after` | Share of the HIC window's velocity change after bottoming out |
| `extra_space` | Space that would have stopped the residual speed on the plateau: v² / (2 a) |
| `diagnosis`, `reason` | The cause, in one line |

### How bottoming out is found

- **Geometry.** The penetration reaches `clearance - stack + skin`:
  - `stack` (5 mm) is the crushed bonnet outer and inner panels;
  - `skin` (3 mm) is how much more the head centre travels than the
    bonnet, because the headform skin compresses.
- **Pulse.** After the first contact peak and a dip, a later peak at
  least 1.25 times the first one (`rise=`). The onset is where the
  acceleration starts to rise towards that peak.

With both, the geometric time is used. With no geometry (`clearance`
not given), the pulse alone decides.

### The diagnosis

Each diagnosis is checked against a `target` colour, yellow by default.

| Diagnosis | When | What it means |
| --- | --- | --- |
| `ok` | Within the target colour | |
| `bottoming` | Worse than the target, bottomed out, and 25 % or more of the HIC window comes after it | The hard part sets the HIC: find space |
| `light_bottoming` | Bottomed out but within the target, or late with little speed left | The space is just used up; watch it in later loops |
| `first_peak` | Worse than the target, and the HIC of the first contact phase alone is 70 % or more of the total | Too much bonnet mass or contact stiffness at the point (latch, reinforcement) |
| `stiff` | Worse than the target, and the plateau sets the HIC without reaching a hard part | The bonnet is too stiff in bending there (hinge area, wing edge, double inner) |

## 4. The grid

```python
from crashmetrics.pedestrian.clearance import assess_grid, compare_grids

impacts = {k: head_impact(p.run, headform=p.headform) for k, p in points.items()}
grid = assess_grid(impacts, gaps)
print(grid.map())          # colours, * bottoming, ^ stiff bonnet
print(grid.summary())      # colours, head score, grid points lost per cause
print(grid.table(top=10))  # worst points with their cause
grid.to_csv("headform_grid.csv")
print(compare_grids(grid, other_grid, names=("baseline", "loop 2")).summary())
```

- `grid.lost_points()` gives the grid points lost to each cause, which
  says where the next design loop should go.
- `grid.score()` is the Euro NCAP head score of the predicted HIC15
  values (`headform_score`, see
  [Pedestrian headform](pedestrian-headform.md)). Pass verification,
  blue or A-pillar results as keyword arguments.
- `compare_grids` lists:
  - the points whose colour changed, most improved first;
  - the score and grid points before and after;
  - the points that stopped or started bottoming out.

## Example

```python
--8<-- "examples/34_bonnet_clearance.py"
```

Output:

```text
--8<-- "examples/expected/34_bonnet_clearance.txt"
```

Reading the output:

- **Plenum points.** Over the intake plenum the head has 38 to 47 mm of
  space, where 86 mm is needed. It bottoms out at 6 ms with a third of
  its energy left, and the whole HIC window comes after that. The
  engine 20 mm lower turns them brown, orange or yellow.
- **Latch.** The latch points (row 1, `^`) have 100 mm of space but a
  heavy reinforcement: their first peak alone gives brown.
- **Stiffer inner panel.** Stiffening the inner panel instead stops a
  few points bottoming out, but it makes most of the open bonnet too
  stiff, and the score drops by 1.6 points.

## Tested with

- **Synthetic grids, whose truth is known.** Every bottoming out in
  the 130 impacts is found, and no impact is wrongly flagged. The time
  is within 0.8 ms and the residual speed within 1 m/s of the model's
  own.
- **Analytic geometry.** A sphere against a plane at 50° (height /
  sin 50°) and against a single point off its path (s − √(R² − r²)).
- **The square-wave limit.** It matches the closed form (68.4 mm at HIC
  1000), including when the 15 ms window limits it.
- **Real LS-DYNA output (MIT licence, in the repository).** The nodout
  of a helmeted Hybrid III head drop gives HIC 194.6 at CFC 1000,
  within 0.5 % of the study's own 195.24. The mesh reader was also
  checked locally on public keyword decks, including `*PART_CONTACT`
  cards.
