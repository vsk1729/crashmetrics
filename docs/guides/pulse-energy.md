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

## Tested on real crash tests

`pulse_summary` and the CFC filter are checked on vehicle acceleration
channels of two tests of the NHTSA Vehicle Crash Test Database (public
information; the files are in `tests/data/nhtsa/`):

| Test | Check | Result |
| --- | --- | --- |
| 2320: 1996 Dodge Neon, rigid barrier, 56.5 km/h | Peak, crush, its time and restitution (CFC 60) against the values an independent project computed from the same channel | 35.2 g, 740 mm at 78 ms, 0.162, against 35.2 g, 740 mm, 78 ms and 0.163 |
| 4429: 1999 Lincoln Navigator head-on into a 1996 Dodge Neon, 48.5 km/h each | Momentum conservation: the velocity changes are in the inverse ratio of the masses | 1.96 against 2.08 (6 %) |
| 4429 | Both cars end at the common velocity of a plastic impact (4.7 m/s) | 4.0 and 5.0 m/s |

For test 2320 the OLC is 29 g. Removing the 0.06 g pre-impact offset of
the channel changes the crush by 2 mm.

```python
import numpy as np
from crashmetrics.pulse import pulse_summary
from crashmetrics.signals import cfc_filter

t, a_g = np.loadtxt("tests/data/nhtsa/v02320tsv.078").T      # s, g
keep = t >= 0                                                # from first contact
a = cfc_filter(t, a_g, 60)[keep] * 9.80665                   # m/s^2
s = pulse_summary(t[keep], a, v0=56.5 / 3.6)
s.max_displacement, s.time_of_max_displacement, s.restitution   # 0.740 m, 0.078 s, 0.162
```

## Complete example

```python
--8<-- "examples/08_pulse_olc_crush.py"
```

Output:

```text
--8<-- "examples/expected/08_pulse_olc_crush.txt"
```
