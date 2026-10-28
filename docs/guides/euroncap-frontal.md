# Euro NCAP MPDB and full width (2026)

Module: `crashmetrics.frontal_scoring`.

Protocols: Euro NCAP Crash Protection – Frontal Impact Protocol v1.1
(2026–2028) and CP 007 Assessment Modifiers v1.1.

| Test | Speed | Occupants and points | Total |
| --- | --- | --- | --- |
| MPDB (offset) | 50 km/h | THOR 50th driver 5, Hybrid III 5th passenger 5, Q6 rear 5, Q10 rear 5 | 20 |
| Full width | 35 km/h | Hybrid III 5th driver 5, THOR 50th passenger 2.5, Hybrid III 5th rear 2.5 | 10 |

## How a region is scored

1. Each criterion gets a **colour band** from its higher (HPL) and lower
   (LPL) performance limits. The band width is \((\mathrm{LPL} -
   \mathrm{HPL})/3\):

    | Band | Range | Share of region points |
    | --- | --- | --- |
    | green | value < HPL | 100 % |
    | yellow | HPL ≤ value < HPL + width | 80 % |
    | orange | HPL + width ≤ value < HPL + 2 width | 60 % |
    | brown | HPL + 2 width ≤ value < LPL | 40 % |
    | red | value ≥ LPL | 0 % |

2. A body region takes the band of its **worst criterion**.
3. **Occupant modifiers** (% of the region points) are subtracted; a
   region never goes below 0.
4. The test score is the sum of the regions, minus **full-scale
   modifiers** (% of 10 points) and, for the MPDB, the **compatibility
   penalty**.

```python
from crashmetrics.frontal_scoring import Limit, colour_band, DUMMY_LIMITS

colour_band(600.0, Limit(hpl=500.0, lpl=700.0))     # 'orange'
DUMMY_LIMITS["thor_50"]["neck_tension"]             # Limit(hpl=2700.0, lpl=3300.0, capping=3300.0, ...)
```

## Step 1: describe each occupant

An `Occupant` holds the peak values (worst of left and right), the head
contact and the modifiers:

```python
from crashmetrics.frontal_scoring import Occupant, damage_modifier

thor_driver = Occupant(
    values={
        "head_peak": 62.0,                    # g; > 80 g means hard contact
        "neck_shear": 1500.0, "neck_tension": 2800.0, "neck_extension": 30.0,
        "chest_compression": 50.0,            # THOR: Rmax, mm
        "abdomen_compression": 70.0, "acetabulum_force": 3000.0,
        "femur_force": 4000.0, "knee_displacement": 5.0,
        "tibia_index": 0.3, "tibia_force": 1500.0,
    },
    modifiers={"head_neck": [damage_modifier(0.44)]},   # % of the region's points
)
```

Criterion names:

| Region (adult) | Criteria |
| --- | --- |
| `head_neck` | `hic15`, `head_a3ms`, `neck_shear`, `neck_tension`, `neck_extension` |
| `chest_abdomen` | `chest_compression`, `viscous_criterion`, `abdomen_compression` |
| `knee_femur_pelvis` | `acetabulum_force`, `femur_force`, `knee_displacement` |
| `lower_leg` | `tibia_index`, `tibia_force` |

| Region (Q6, Q10) | Criteria |
| --- | --- |
| `head` | `hic15`, `head_a3ms` |
| `neck` | `neck_tension`, `neck_extension` (only with head contact) |
| `chest` | `chest_compression`, `chest_a3ms` (Q10) |

Only the criteria that have limits for that dummy are used; a missing
required value raises an error, so typos are caught.

**Head contact:** without hard contact (head peak ≤ 80 g, or
`hard_contact=False`), HIC15 and the head 3 ms are not applied to
adults (full head points), and Q dummies are scored on the head 3 ms
only.

## Step 2: modifiers

```python
from crashmetrics.frontal_scoring import FULL_SCALE_MODIFIERS, OCCUPANT_MODIFIERS

OCCUPANT_MODIFIERS["shoulder_belt_load"]     # ('chest_abdomen', 40.0)
OCCUPANT_MODIFIERS["submarining"]            # ('knee_femur_pelvis', 100.0)
FULL_SCALE_MODIFIERS["a_pillar_100mm"]       # 2.5 (% of 10 points)
FULL_SCALE_MODIFIERS["door_opening"]         # 5.0 per door
```

Q dummy score modifiers (belt slippage, ejection, ...) apply to the whole
dummy: `Occupant(..., dummy_modifiers=[50.0])`.

## Step 3: compatibility penalty (MPDB)

From CP 007 Appendix A: the barrier deformation standard deviation
(SD, 50–150 mm) and the trolley OLC (25–40 g) each map to a 0–1 scale
\(s\) and \(o\):

\[
\text{penalty} = 1.25\,(s + o + 2so) + 1.25\ \text{(bottoming out)},\quad \le 5\ \text{points}
\]

```python
from crashmetrics.frontal_scoring import compatibility_penalty

compatibility_penalty(sd=119.0, olc=34.9, bottoming_out=False)   # 2.826
```

This reproduces CP 007's three worked examples (2.826, 5.0 and 2.242).

## Step 4: score the test

```python
from crashmetrics.frontal_scoring import score_fwdb, score_mpdb

mpdb = score_mpdb(
    {"driver": thor_driver, "front_passenger": h3_passenger,
     "rear_q6": q6, "rear_q10": q10},
    full_scale_modifiers=[2.5],
    compatibility_penalty=compatibility_penalty(119.0, 34.9, False),
)
mpdb.points
mpdb.occupants["driver"].regions["head_neck"]       # band, governing criterion, points

fw = score_fwdb({"driver": ..., "front_passenger": ..., "rear_passenger": ...})
```

The full width test uses the 35 km/h chest compression limits (THOR
29–54 mm instead of 35–60 mm at 50 km/h).

**Capping:** values at or above a capping limit are listed in
`DummyScore.capping_exceeded` (the Hybrid III 5th neck capping applies
to the driver only). The protocol does not say what exceeding a capping
limit does, so crashmetrics reports it without applying a penalty.

## Complete example

```python
--8<-- "examples/06_euroncap_mpdb_fwdb.py"
```

Output:

```text
--8<-- "examples/expected/06_euroncap_mpdb_fwdb.txt"
```

## Points per band: a note

The protocol's Section 3.5 text gives 1.25 / 1.0 / 0.75 / 0.5 / 0
points per band (100/80/60/40/0 %), while its Section 3.4 tables print
100/80/40/20/0 %. crashmetrics uses the text by default; pass
`band_fractions=BAND_FRACTIONS_TABLE` to use the table values. See
[Protocol notes](../protocol-notes.md).
