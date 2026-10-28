# Vehicle pulse and crush energy

Modules: `crashmetrics.pulse` (`olc`, `pulse_summary`) and
`crashmetrics.energy` (`integrate_acceleration`, `absorbed_energy`,
`crush_metrics`, `kinetic_energy`).

## Occupant Load Criterion (OLC)

The OLC describes how hard the vehicle pulse is on a restrained
occupant. A virtual occupant moves **65 mm** in free flight, then
decelerates uniformly over a further **235 mm** until it reaches the
vehicle velocity; the OLC is that deceleration (Euro NCAP CP 005).

```python
from crashmetrics.pulse import olc
from crashmetrics.signals import cfc_filter

a = cfc_filter(t, accel_x, cfc=180)      # m/s^2, negative while decelerating
result = olc(t, a, v0=50 / 3.6)          # initial velocity, m/s
result.value                             # g (9.81 m/s^2 per g, change with gravity=)
result.t1, result.t2                     # end of free flight and of restraint phase, s
```

The record should start at T0. The tests check `olc` against the
closed-form solution for constant deceleration and an independent
numerical formulation.

## Pulse summary

```python
from crashmetrics.pulse import pulse_summary

s = pulse_summary(t, a, v0=50 / 3.6)
s.delta_v, s.rebound_velocity, s.restitution
s.max_displacement, s.time_of_max_displacement   # dynamic crush, m and s
s.peak_deceleration, s.mean_deceleration         # m/s^2
```

## Velocity and displacement from acceleration

```python
from crashmetrics.energy import integrate_acceleration, kinetic_energy

velocity, displacement = integrate_acceleration(t, a, v0=13.9)
kinetic_energy(1500.0, 13.9)          # J for 1500 kg at 13.9 m/s
```

!!! warning
    Integration amplifies sensor offset and drift. Check the zero level
    of test data before integrating.

## Crash box and rail energy

For a force–displacement curve (for example force in kN and crush in
mm, which gives energy in J):

```python
from crashmetrics.energy import absorbed_energy, crush_metrics

energy_curve = absorbed_energy(crush_mm, force_kN)     # cumulative energy at each sample
box = crush_metrics(crush_mm, force_kN, mass=1.2, max_displacement=150.0)
box.energy, box.mean_force, box.peak_force, box.peak_force_displacement
box.crush_force_efficiency           # mean / peak force
box.specific_energy_absorption       # energy / mass
```

| Metric | Definition |
| --- | --- |
| Absorbed energy | \(E = \int F\,dx\) (trapezoidal) |
| Mean force | \(E / \text{crush distance}\) |
| Crush force efficiency (CFE) | mean force / peak force |
| Specific energy absorption (SEA) | \(E / m\) |

`max_displacement` evaluates the metrics over a fixed stroke, so
different designs compare fairly; always report the stroke with them.
The energy functions do not convert units: use one consistent system.

## Complete example

```python
--8<-- "examples/08_pulse_olc_crush.py"
```

Output:

```text
--8<-- "examples/expected/08_pulse_olc_crush.txt"
```
