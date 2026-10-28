# Frontal dummy criteria (Hybrid III and THOR)

Modules: `crashmetrics.head`, `neck`, `thorax`, `pelvis`,
`lower_extremity`.

The criteria follow the Euro NCAP Data Acquisition and Injury
Calculation protocol (CP 005 v1.4.1) unless another source is named.
BrIC, Nij and CTI are not Euro NCAP criteria; they use the values of
their original sources. Inputs: s, N, N m, rad/s, g; deflections in mm.

| Region | Criterion | Function | Source |
| --- | --- | --- | --- |
| Head | DAMAGE (THOR) | `head.damage`, `head.damage_from_acceleration` | CP 005 3.1.3 |
| Head | BrIC | `head.bric` | Takhounts et al. 2013 |
| Head | End of the loading phase | `head.loading_phase_end` | CP 005 |
| Neck | Occipital condyle moment, shear, tension, compression, extension, flexion | `neck.neck_loads` | CP 005 3.2 |
| Neck | Force–duration limits | `neck.neck_force_criterion` | UN R94 |
| Neck | Nij | `neck.nij` | FMVSS 208 |
| Chest | Hybrid III deflection | `thorax.chest_deflection` | CP 005 3.4.1 |
| Chest | THOR Rmax | `thorax.thor_chest_deflection` | CP 005 3.4.2 |
| Chest | Viscous criterion | `thorax.viscous_criterion` | CP 005 3.4.6 |
| Chest | CTI | `thorax.cti_from_signals` | Eppinger et al. 1999 |
| Abdomen | THOR abdomen deflection | `thorax.thor_abdomen_deflection` | CP 005 3.5.2 |
| Pelvis | Iliac force drop | `pelvis.iliac_force_drop` | CP 005 3.6.1 |
| Pelvis | THOR acetabulum force | `pelvis.acetabulum_force` | CP 005 3.6.2 |
| Legs | Knee slider | `lower_extremity.knee_slider_displacement` | CP 005 3.6.3 |
| Legs | Femur force–duration | `lower_extremity.femur_force_criterion` | UN R94 |
| Legs | Tibia Index, tibia compression | `lower_extremity.tibia_index`, `tibia_compression` | CP 005 / UN R94 |

## Head

### DAMAGE (THOR)

DAMAGE models the brain as a 3-degree-of-freedom mass–spring–damper
system driven by the head angular acceleration:

\[
[m]\{\ddot d\} + [c]\{\dot d\} + [k]\{d\} = [m]\{\ddot\theta\},\qquad
[c] = a_1[k],\qquad \mathrm{DAMAGE} = \beta\,\max_t \lVert d(t)\rVert
\]

with Euro NCAP's stiffnesses (kxx 32142, kyy 23493, kzz 16935, kxz
1636.3 N/m), a₁ = 5.9148 ms and β = 2.9903 1/m.

```python
from crashmetrics.head import damage
from crashmetrics.signals import cfc_filter

w = [cfc_filter(t, w_i, cfc=60) for w_i in (wx, wy, wz)]     # rad/s
result = damage(t, *w, t0=0.0, head_ax_g=head_ax, neck_fx=neck_fx)
result.value, result.end_reason
```

In the Euro NCAP 2026 score, DAMAGE is a head and neck modifier:
`crashmetrics.frontal_scoring.damage_modifier(result.value)` gives −20 %
from 0.42 and −40 % from 0.47.

The window runs from T0 for at most 200 ms and ends earlier when the
external head force \(-4.2\,\mathrm{kg}\cdot a_x + F_{x,\mathrm{neck}}\)
drops below −500 N (pass `head_ax_g` and `neck_fx` to apply it).
Use `damage_from_acceleration` if you already have angular
acceleration.

!!! success "Verification"
    Matches the model developers' reference implementation
    (UVA-CAB/DAMAGE 2.0) to machine precision, and the closed-form step
    response of the 3-DOF system to 1e-7.

### BrIC

\[
\mathrm{BrIC} = \sqrt{\left(\frac{\omega_x}{\omega_{xC}}\right)^2 +
\left(\frac{\omega_y}{\omega_{yC}}\right)^2 + \left(\frac{\omega_z}{\omega_{zC}}\right)^2}
\]

```python
from crashmetrics.head import bric

bric(t, wx, wy, wz).value                  # critical="average" (default), "mps", "csdm"
```

Critical values from Takhounts et al. (2013), Table 3.

### Loading phase

```python
from crashmetrics.head import loading_phase_end

t_end = loading_phase_end(t, head_ax)      # head x acceleration crosses 0 after its minimum
```

Use it as `t_end` for the neck loads.

## Neck

```python
from crashmetrics.neck import neck_force_criterion, neck_loads, nij

loads = neck_loads(t, fx, fz, my, dummy="hybrid3", t_end=t_end)
loads.tension.value, loads.compression.value, loads.shear.value
loads.extension_moment.value, loads.flexion_moment.value
```

- **Hybrid III:** the moment is moved to the occipital condyle,
  \(M_{OC,y} = M_y - F_x \cdot 0.01778\,\mathrm{m}\).
- **THOR** (`dummy="thor"`): the upper neck \(M_y\) is used directly.
- Extension moment = \(|\min(M)|\).

**UN R94 force–duration limits** (cumulative by default):

```python
neck_force_criterion(t, fz, "r94_tension").utilisation     # 3.3 / 2.9 / 1.1 kN at 0 / 35 / 60 ms
neck_force_criterion(t, fx, "r94_shear").passed            # 3.1 / 1.5 / 1.5 / 1.1 kN at 0 / 25 / 35 / 45 ms
```

**Nij** (FMVSS 208, in-position Hybrid III 50th and 5th intercepts):

\[
N_{ij} = \frac{F_z}{F_{zc}} + \frac{M_{OC,y}}{M_{yc}}
\]

```python
n = nij(t, fz, my, fx=fx, dummy="hybrid3_50")
n.value, n.category                         # 'NTE', 'NTF', 'NCE' or 'NCF'
```

## Chest

**Hybrid III deflection and VC:**

\[
\mathrm{VC}(t) = s_f \cdot V(t) \cdot \frac{D(t)}{D_c},\qquad
V(t) = \frac{8\,[D(t{+}1) - D(t{-}1)] - [D(t{+}2) - D(t{-}2)]}{12\,\Delta t}
\]

```python
from crashmetrics.thorax import chest_deflection, viscous_criterion

chest_deflection(t, deflection).value               # mm, compression positive
viscous_criterion(t, deflection, dummy="hybrid3_50").value   # m/s; sf 1.3, Dc 0.229 m
```

**THOR Rmax** from the four IR-TRACCs, each given as (length R in mm,
φy, φz in degrees):

\[
\begin{aligned}
D_x &= \delta\sin\varphi_y + R\cos\varphi_z\cos\varphi_y - D_x(0)\\
D_y &= R\sin\varphi_z - D_y(0)\\
D_z &= \delta\cos\varphi_y - R\cos\varphi_z\sin\varphi_y - D_z(0)
\end{aligned}
\]

with δ = +15.65 mm (upper) and −15.65 mm (lower).

```python
from crashmetrics.thorax import thor_chest_deflection, thor_abdomen_deflection

chest = thor_chest_deflection(t, upper_left, upper_right, lower_left, lower_right)
chest.rmax, chest.location
abdomen = thor_abdomen_deflection(t, left, right)
abdomen.value                    # compression, mm (see Protocol notes for the sign)
```

**CTI** (NHTSA research): \(\mathrm{CTI} = A / A_{int} + D / D_{int}\)
with the 3 ms clip of the spine acceleration:

```python
from crashmetrics.thorax import cti_from_signals

cti_from_signals(t, spine_resultant_g, deflection, dummy="hybrid3_50").value
```

## Pelvis (THOR)

```python
from crashmetrics.pelvis import acetabulum_force, iliac_force_drop

acetabulum_force(t, fx, fy, fz).value       # resultant while Fx is compressive
iliac_force_drop(t, iliac_fx).value         # max of F(t + 1 ms) - F(t)
```

## Legs

```python
from crashmetrics.lower_extremity import (
    femur_force_criterion, knee_slider_displacement, tibia_compression, tibia_index)

femur_force_criterion(t, femur_fz, limit="r94_hybrid3_50").utilisation   # 9.07 kN @ 0 ms -> 7.58 kN @ 10 ms
knee_slider_displacement(t, knee_d).value                                # |min(D)|, mm
tibia_index(t, mx, my, fz, dummy="hybrid3_50").value
tibia_compression(t, fz).value                                           # |min(Fz)|, N
```

\[
\mathrm{TI} = \left|\frac{M_R}{(M_R)_c}\right| + \left|\frac{F_z}{(F_z)_c}\right|,\qquad
M_R = \sqrt{M_x^2 + M_y^2}
\]

while the tibia is in compression (critical values from CP 005: Hybrid
III 50th 225 N m and 35.9 kN).

## Complete example

```python
--8<-- "examples/05_frontal_dummy_criteria.py"
```

Output:

```text
--8<-- "examples/expected/05_frontal_dummy_criteria.txt"
```
