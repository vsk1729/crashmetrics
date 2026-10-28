# Units, signs and filters

Most wrong crash results come from units, signs or filtering, not from
the formulas. This page lists what crashmetrics expects.

## Units

crashmetrics uses SI units, with a few exceptions that follow the
protocols:

| Quantity | Unit | Notes |
| --- | --- | --- |
| Time | **s** | Always seconds. HIC windows and exceedance durations are given in ms (`window_ms`, `duration_ms`). |
| Acceleration (head, chest, headform) | **g** | Convert with `to_g`. |
| Vehicle acceleration (OLC, pulse) | **m/s²** | Negative while decelerating. |
| Force | **N** | Protocol limits in kN are stored in N (e.g. 3300 N). |
| Moment | **N m** | |
| Deflection, displacement, elongation | **mm** | Chest, ribs, knee slider, ligaments, intrusions. |
| Angular velocity | **rad/s** | DAMAGE and BrIC. |
| Viscous criterion | **m/s** | |
| Energy | J or your solver's unit | Energy checks are ratios, so any consistent unit works. |

Converting LS-DYNA output:

```python
from crashmetrics.signals import to_g, to_seconds

t = to_seconds(time_ms, "ms")          # "s", "ms", "us"
a = to_g(acc, "mm/ms^2")               # "m/s^2", "mm/s^2", "mm/ms^2", "g", ...
force_N = force_kN * 1000.0            # mm-ms-kg gives kN
moment_Nm = moment_kNmm                # kN mm equals N m
```

## Sign conventions

crashmetrics follows SAE J211, as Euro NCAP and Bharat NCAP do. Where a
protocol does not state the sign, the default is documented and can be
switched:

| Channel | Default | Switch |
| --- | --- | --- |
| Femur and tibia axial force | compression **negative** | `compression_negative=False` |
| Neck Fz | tension **positive** | |
| Neck My / occipital condyle moment | flexion **positive**, extension negative | |
| Hybrid III chest deflection | compression **positive** | `compression_negative=True` |
| THOR abdomen IR-TRACC length | shortens in compression | `value` vs `max_dx`, see [Protocol notes](../protocol-notes.md) |
| Acetabulum Fx | compression **negative** | `compression_negative=False` |
| Iliac force | **negative** under belt load | `loaded_negative=False` |
| Knee slider | displacement **negative** in compression (`abs(min(D))`) | |
| Vehicle acceleration (pulse) | negative while decelerating | |

!!! tip
    If a peak comes out as 0 or tiny, the sign is usually the cause:
    check the channel's polarity against the table above.

## Filter classes (CFC)

Filter every channel with the CFC its protocol gives, using
`cfc_filter(t, signal, cfc=...)`. The values used in the Euro NCAP and
Bharat NCAP protocols:

| Channel | CFC |
| --- | --- |
| Head linear acceleration (dummy, headform) | 1000 |
| Head angular velocity for DAMAGE | 60 |
| Upper neck forces | 1000 (600 for Nij) |
| Upper neck moments | 600 |
| Chest and rib deflections, IR-TRACC length and angles | 180 |
| Spine and chest accelerations | 180 |
| Pelvis, acetabulum, iliac, femur and tibia loads | 600 |
| Knee slider displacement | 180 |
| ES-2 rib deflections / abdominal and pubic forces | 180 / 600 |
| Flex-PLI moments and elongations | 180 |
| Vehicle acceleration for OLC | 180 |

Check the CFC table of the protocol version you assess to.

The filter is the SAE J211-1 Appendix C digital filter: a 2-pole
Butterworth run forward and backward (phaseless, 4-pole). It needs
uniform sampling and pads each end by odd reflection (`pad_ms`, 10 ms
by default) to limit start-up transients.

## Time zero and windows

- Time zero should be first contact (T0). Many criteria accept
  `t_start` / `t_end` to limit the evaluation window, for example the
  loading phase for neck loads (`loading_phase_end`).
- Head impacts after rebound are not assessed in the protocols; cut the
  record or pass `t_end` when needed.

## Numbers and rounding

Scores are rounded the way each protocol does it (for example 3
decimals for Euro NCAP legform points and Bharat NCAP region scores).
Intermediate values are not rounded. Pass `round_to=None` where offered
to keep exact values.
