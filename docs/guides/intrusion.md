# Intrusion measurement

Module: `crashmetrics.intrusion`.

How far did the pedal, the steering column, the toe pan or the A-pillar
move into the occupant space? The answer depends entirely on **what you
measure against**. The vehicle itself moves, pitches and yaws during a
crash, so a node's displacement in the global (ground) system is mostly
vehicle motion. This module measures intrusions every common way, from
CAE time histories and from static before/after test measurements.

| You have | Use | Measures |
| --- | --- | --- |
| A node and the vehicle's undeformed rear structure | `intrusion(point, reference_nodes)` (3 or more nodes) | Intrusion relative to the vehicle: translation **and** rotation removed |
| A node and one reference node | `intrusion(point, reference_node)` | Displacement relative to that node: translation removed, rotation not |
| A node only | `intrusion(point)` | Displacement in the global system (barriers, impactors, sleds) |
| Two nodes | `node_distance(a, b)` | Change in the distance between them: survival space, gaps |
| Before/after coordinates from a test | Any of the above with two rows | Static (residual) intrusion |
| Many points | `intrusions({name: point}, reference)` | A result per point, ready for a table |

## Step 1: get the coordinates

Each point is an array of shape `(n, 3)`: one row per time step, columns
x, y, z, in any length unit (the results use the same unit).

```python
from crashmetrics.intrusion import node_track

pedal = node_track(x, y, z)                         # coordinate columns
pedal = node_track(ux, uy, uz, initial=(2350.0, 350.0, 250.0))   # displacements
```

LS-DYNA `nodout` holds both coordinates and displacements per node;
either form works. For a physical test, a point is two rows: the
coordinates measured before and after the test.

## Step 2: choose the reference

=== "Vehicle frame (recommended)"

    ```python
    from crashmetrics.intrusion import intrusion

    reference = [seat_cross_member, b_pillar_left, b_pillar_right, sill_rear]
    r = intrusion(pedal, reference, time=t, direction="-x")
    ```

    Three or more reference nodes on structure that stays undeformed
    (rear seat cross member, B-pillar bases, rear sills, tunnel). At
    every time step the best rigid fit of these nodes to their initial
    positions gives the vehicle's translation and rotation, and the
    point's displacement is measured in the vehicle's axes. This is what
    a test measurement relative to reference points on the body does.

=== "One reference node"

    ```python
    r = intrusion(pedal, b_pillar_base, time=t, direction="-x")
    ```

    Removes the reference node's translation only. Any pitch or yaw of
    the vehicle adds an error that grows with the distance from the
    reference node: in the example, 3° of pitch over 1.4 m gives about
    65 mm of false upward intrusion. Use it only for a nearby reference
    or when the vehicle does not rotate.

=== "Global system"

    ```python
    r = intrusion(impactor_node, time=t)
    ```

    Displacement in the global system, including all vehicle motion.
    Right for barrier faces, impactors and sled-mounted parts; wrong for
    intrusions.

!!! tip "Check the reference"
    `r.reference_fit_error` is the largest RMS distance of the
    reference nodes from their rigid fit. Near 0 means they moved
    rigidly; several millimetres means a reference node deforms, so
    choose others. Spread the reference nodes widely: measurement noise
    is amplified by the ratio of the distance to the point and the
    spread of the reference nodes.

## Step 3: directions, dynamic and static values

```python
r = intrusion(pedal, reference, time=t, direction="-x")   # x forward: -x is rearward
r.along_dynamic, r.t_along_ms     # largest rearward intrusion and when (CAE)
r.along_static                     # final (residual) value, after springback
r.x_static, r.y_static, r.z_static, r.resultant_static
r.x_dynamic, r.resultant_dynamic, r.t_dynamic_ms
r.displacement                     # full (n, 3) history, for plots
```

| Value | Meaning |
| --- | --- |
| `*_dynamic` | Peak during the event: the signed component with the largest magnitude, the largest resultant, or the largest value along `direction` |
| `*_static` | Final value: the residual deformation after springback (the last sample, or the mean over the last `static_window_ms`) |
| `along_*` | Displacement projected on `direction`; positive means in that direction |

`direction` is a vector or `"x"`, `"-x"`, `"y"`, `"-y"`, `"z"`,
`"-z"` in the reference's initial (vehicle) axes. Check your model's
axes. With x forward and z up: rearward is `"-x"`, upward `"z"`. With
x rearward (common in CAE models): rearward is `"x"`.

CAE gives both values; a test measured before and after gives only the
static value. CAE results stop at the end time, so springback may not
be complete; `static_window_ms` averages the last part of the record to
smooth oscillation.

## Step 4: distances and survival space

```python
from crashmetrics.intrusion import node_distance

gap = node_distance(steering_wheel_hub, seat_h_point, time=t)
gap.initial, gap.minimum, gap.t_minimum_ms, gap.final
gap.closing_dynamic, gap.closing_static
```

A distance does not depend on any reference frame, so it is the
simplest robust measure for survival space (steering wheel to seat, roof
to head position, door inner panel to seat) and for gaps that must not
close.

## Step 5: many points and the rating

```python
from crashmetrics.intrusion import intrusions
from crashmetrics.bncap import pedal_blocking_modifier, steering_column_modifier

results = intrusions(
    {"brake_pedal": pedal, "steering_column": column, "a_pillar": pillar},
    reference, time=t,
    direction={"brake_pedal": "-x", "steering_column": "-x", "a_pillar": "-x"},
)
col = results["steering_column"]
steering_column_modifier(rearward=col.along_static, upward=col.z_static,
                         lateral=abs(col.y_static))
pedal_blocking_modifier(results["brake_pedal"].along_static)
```

The Bharat NCAP modifiers in `crashmetrics.bncap` take the steering
column, A-pillar and pedal displacements directly. Use the value your
protocol specifies (post-test static or dynamic) and the measurement
points it defines. `flatten(results)` turns all values into columns
such as `brake_pedal.along_static` for a [feature table](ml-features.md).

## Complete example

An offset frontal crash in which the vehicle moves 700 mm, pitches 3°
and yaws 2° while five points deform. It compares the three references,
lists all points, checks survival space, repeats the measurement as a
noisy static test measurement, and applies the Bharat NCAP modifiers:

```python
--8<-- "examples/13_intrusion.py"
```

Output:

```text
--8<-- "examples/expected/13_intrusion.txt"
```
