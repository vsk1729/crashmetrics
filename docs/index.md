# crashmetrics

**Open-source Python for automotive crash safety calculations:** injury
criteria, Euro NCAP and Bharat NCAP scoring, pedestrian protection,
AIS-100 compliance and LS-DYNA energy checks, all in one package.

```bash
pip install crashmetrics
```

!!! warning "Alpha software"
    crashmetrics is an engineering calculation aid. Validate its results
    against the official protocol you assess to; it does not certify
    regulatory compliance. See [Protocol notes](protocol-notes.md) for
    every interpretation the package makes.

## What it covers

| Area | What you can calculate | Guide |
| --- | --- | --- |
| Signals | SAE J211 CFC filtering, resultants, unit conversion, resampling, HIC, peak, 3 ms clip | [Signals](guides/signals.md) |
| Pedestrian (Euro NCAP) | Headform grid score with correction factor, blue / default-red / A-pillar points; aPLI and upper legform grids; total VRU score | [Headform](guides/pedestrian-headform.md), [Legforms](guides/pedestrian-legforms.md) |
| Pedestrian (India) | AIS-100 compliance: Flex-PLI and legacy legform limits, upper legform, HIC1000 / HIC1700 zones; Flex-PLI assessment interval and Euro NCAP Flex-PLI score | [Flex-PLI and AIS-100](guides/flexpli-ais100.md) |
| Frontal dummies | DAMAGE, BrIC, neck loads, Nij, R94 limits, chest deflection, VC, CTI, THOR Rmax and abdomen, acetabulum, iliac force drop, femur, Tibia Index, knee slider | [Frontal criteria](guides/frontal-dummy-criteria.md) |
| Euro NCAP 2026 | MPDB (20 points) and full width (10 points) scores with modifiers and the compatibility penalty; side impact AE-MDB (15), pole (10) and far side (10) | [MPDB and full width](guides/euroncap-frontal.md), [Side and far side](guides/euroncap-side.md) |
| Homologation | UN R94 / AIS-098, UN R95 / AIS-099, UN R135 and post-crash electrical safety, pass/fail per requirement | [Homologation](guides/homologation.md) |
| Whiplash | BioRID NIC and Nkm; 2026 rear impact score, 5 points | [Rear impact](guides/whiplash.md) |
| Bharat NCAP | AIS-197 adult occupant scoring (ODB frontal, MDB side), pole test, star rating; child occupant protection; safety assist star qualifiers | [Bharat NCAP](guides/bharat-ncap.md), [Child occupant and rating](guides/bharat-ncap-cop.md) |
| Intrusion | Pedal, steering column, A-pillar and footwell intrusion relative to the vehicle; dynamic and static; survival space | [Intrusion](guides/intrusion.md) |
| Vehicle | OLC, delta-V, rebound, dynamic crush, crash box energy, CFE, SEA | [Pulse and energy](guides/pulse-energy.md) |
| LS-DYNA | ASCII output readers (nodout, rcforc, sleout, secforc, rwforc, sbtout, abstat and more), `crashmetrics-ascii` to CSV; glstat / matsum energy balance checks, d3hsp run summary, `crashmetrics-energy` command | [ASCII output](guides/lsdyna-ascii.md), [LS-DYNA energy](guides/lsdyna-energy.md) |
| Test vs CAE | ISO/TS 18571 rating and grade, corridor and cross-correlation (CC) rating, peak, timing and RMSE errors | [Test-versus-CAE correlation](guides/test-cae-correlation.md) |
| Analytics and ML | Batch runs into tables; signal shape features, criteria and design parameters per run as a training set | [Batch and analytics](guides/batch-analytics.md), [ML features](guides/ml-features.md) |

## A first taste

```python
from crashmetrics.pedestrian import check_flexpli, hic_colour

hic_colour(620)                                   # Euro NCAP headform colour
# 'green'
check_flexpli(tibia_moment=300, mcl=20, acl=6, pcl=5).passed   # AIS-100 Rev.1
# True
```

A full Bharat NCAP rating from dummy results takes about 30 lines; see
the [Bharat NCAP guide](guides/bharat-ncap.md).

## How to use these docs

1. **[Getting started](getting-started/installation.md)**: install, run a
   first calculation, load your own test or CAE data, and learn the units
   and sign conventions.
2. **[Guides](guides/index.md)**: one step-by-step page per load case,
   each built around a runnable example with its real output.
3. **[Protocol notes](protocol-notes.md)**: where a protocol is
   ambiguous or silent, what crashmetrics does and why.
4. **[API reference](reference/index.md)**: every function, parameter and
   result field.

## Where the numbers come from

Every formula and limit comes from publicly available protocols and
standards: Euro NCAP (assessment protocols, CP 005, CP 007), Bharat NCAP
(AIS-197), AIS-100, UN regulations (R94, R127), UN GTR 9, FMVSS 208,
SAE J211 and published research. The test suite reproduces the
protocols' own worked examples wherever they give one, and checks the
other formulas against hand calculations and closed-form solutions.

crashmetrics is an independent project and is not affiliated with or
endorsed by any of these organisations.
