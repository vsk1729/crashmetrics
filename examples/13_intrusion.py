"""Example 13: intrusion measurement, CAE (dynamic) and test (static).

Synthetic offset frontal crash. The vehicle moves 700 mm forward,
pitches 3 deg and yaws 2 deg while the footwell, pedal, steering column
and A-pillar deform. Vehicle axes: x forward, y left, z up, mm.
"""

import math

import numpy as np

from crashmetrics.bncap import (
    a_pillar_modifier,
    pedal_blocking_modifier,
    pedal_upward_modifier,
    steering_column_modifier,
)
from crashmetrics.features import flatten
from crashmetrics.intrusion import intrusion, intrusions, node_distance

t = np.arange(0.0, 0.1501, 0.0005)                       # s, 0.5 ms output
ramp = np.clip(t / 0.09, 0.0, 1.0)                       # deformation 0..90 ms
settle = np.clip((t - 0.09) / 0.03, 0.0, 1.0)            # springback 90..120 ms


def rotation(fraction):
    pitch, yaw = math.radians(-3.0) * fraction, math.radians(2.0) * fraction
    cp, sp, cy, sy = math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw)
    r_pitch = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    r_yaw = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    return r_yaw @ r_pitch


def move(point0, local=None):
    """Rigid vehicle motion plus an optional local deformation (n, 3)."""
    out = np.empty((t.size, 3))
    for i, f in enumerate(ramp):
        p = point0 + (0.0 if local is None else local[i])
        out[i] = rotation(f) @ p + np.array([700.0, -40.0, -15.0]) * f
    return out


def deformation(rearward, upward, lateral=0.0, springback=0.15):
    """Local deformation (x, y, z): peaks at 90 ms, springs back 15 %."""
    shape = np.sin(np.pi / 2 * ramp) * (1 - springback * settle)
    return np.column_stack([-rearward * shape, lateral * shape, upward * shape])


# Undeformed positions (vehicle axes) and their local deformation
nodes = {
    "brake_pedal": (np.array([2350.0, 350.0, 250.0]), deformation(140, 56, -8)),
    "steering_column": (np.array([1950.0, 370.0, 700.0]), deformation(76, 60, 12)),
    "a_pillar": (np.array([2050.0, 760.0, 650.0]), deformation(120, 10, 6)),
    "toe_pan_left": (np.array([2500.0, 500.0, 150.0]), deformation(190, 70)),
    "toe_pan_right": (np.array([2500.0, 150.0, 150.0]), deformation(130, 50)),
}
tracks = {name: move(p0, d) for name, (p0, d) in nodes.items()}
# Reference: rear seat cross member and both B-pillar bases (undeformed)
reference = np.array([move(np.array(p)) for p in
                      [(1000.0, 0.0, 200.0), (1300.0, 750.0, 300.0),
                       (1300.0, -750.0, 300.0), (900.0, 300.0, 450.0)]])

# --- 1. One point, three references ------------------------------------------
pedal = tracks["brake_pedal"]
print("Brake pedal, rearward (direction -x), dynamic / static, mm:")
for label, ref in [("global (ground)", None), ("one node", reference[0]),
                   ("frame of 4 nodes", reference)]:
    r = intrusion(pedal, ref, time=t, direction="-x")
    print(f"  {label:17}: {r.along_dynamic:7.1f} / {r.along_static:7.1f}"
          f"   upward z static {r.z_static:6.1f}")
true = nodes["brake_pedal"][1]
print(f"  true deformation : {-true[:, 0].min():7.1f} / {-true[-1, 0]:7.1f}"
      f"   upward z static {true[-1, 2]:6.1f}")
print("  (the ground system includes the vehicle's motion; one node misses "
      "its pitch and yaw)")

# --- 2. All points against the vehicle frame ---------------------------------
directions = {"brake_pedal": "-x", "steering_column": "-x", "a_pillar": "-x",
              "toe_pan_left": "-x", "toe_pan_right": "-x"}
results = intrusions(tracks, reference, time=t, direction=directions)
print(f"\n{'point':16} {'rearward dyn':>12} {'static':>7} {'at ms':>6} "
      f"{'up static':>9} {'lat static':>10}")
for name, r in results.items():
    print(f"{name:16} {r.along_dynamic:12.1f} {r.along_static:7.1f} "
          f"{r.t_along_ms:6.1f} {r.z_static:9.1f} {r.y_static:10.1f}")
rigid = results["brake_pedal"].reference_fit_error < 1e-6
print("Reference points stay rigid (fit error below 1e-6 mm):", rigid)

# --- 3. Survival space: steering wheel to seat --------------------------------
seat = move(np.array([1450.0, 370.0, 450.0]))
gap = node_distance(tracks["steering_column"], seat, time=t)
print(f"\nSteering column to seat: {gap.initial:.0f} mm before, closest "
      f"{gap.minimum:.0f} mm at {gap.t_minimum_ms:.1f} ms, {gap.final:.0f} mm after "
      f"(closed {gap.closing_dynamic:.0f} mm dynamic, {gap.closing_static:.0f} static)")

# --- 4. Physical test: before/after measurement (two rows per point) --------
rng = np.random.default_rng(13)
before = np.array([p for p, _ in nodes.values()])
after = np.array([tr[-1] for tr in tracks.values()])
ref_before = reference[:, 0] + rng.normal(0, 0.2, (4, 3))   # 0.2 mm noise
ref_after = reference[:, -1] + rng.normal(0, 0.2, (4, 3))
measured = intrusions(
    {name: np.array([before[i], after[i] + rng.normal(0, 0.2, 3)])
     for i, name in enumerate(nodes)},
    np.stack([ref_before, ref_after], axis=1), direction=directions)
print("\nStatic test measurement (before/after, best-fit reference):")
print("  ", ", ".join(f"{n} {r.along_static:.1f}" for n, r in measured.items()))
print(f"   reference fit error {measured['a_pillar'].reference_fit_error:.2f} mm")

# --- 5. Into the Bharat NCAP modifiers (static values here) ----------------
col, pdl = results["steering_column"], results["brake_pedal"]
penalties = {
    "steering column (head)": steering_column_modifier(
        rearward=col.along_static, upward=col.z_static, lateral=abs(col.y_static)),
    "A-pillar (chest)": a_pillar_modifier(results["a_pillar"].along_static),
    "pedal upward (lower leg)": pedal_upward_modifier(pdl.z_static),
    "pedal blocking (foot)": pedal_blocking_modifier(pdl.along_static),
}
print("\nBharat NCAP modifiers:",
      ", ".join(f"{k} -{v:.2f}" for k, v in penalties.items()))

# --- 6. As feature columns ---------------------------------------------------
row = flatten(results)
print(f"Feature row: {len(row)} columns, e.g. brake_pedal.along_static = "
      f"{row['brake_pedal.along_static']:.1f}")
