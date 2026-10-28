# crashmetrics

[![PyPI](https://img.shields.io/pypi/v/crashmetrics)](https://pypi.org/project/crashmetrics/)
[![Python](https://img.shields.io/pypi/pyversions/crashmetrics)](https://pypi.org/project/crashmetrics/)
[![Tests](https://github.com/vsk1729/crashmetrics/actions/workflows/tests.yml/badge.svg)](https://github.com/vsk1729/crashmetrics/actions/workflows/tests.yml)
[![Docs](https://github.com/vsk1729/crashmetrics/actions/workflows/docs.yml/badge.svg)](https://vsk1729.github.io/crashmetrics/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/vsk1729/crashmetrics/blob/main/LICENSE)

Open-source Python for automotive crash safety calculations: injury
criteria, Euro NCAP and Bharat NCAP scoring, pedestrian protection,
AIS-100 compliance and LS-DYNA energy checks.

**Documentation: <https://vsk1729.github.io/crashmetrics/>**, with
step-by-step guides, runnable examples, the full API reference and the
[protocol notes](https://vsk1729.github.io/crashmetrics/protocol-notes/)
(every interpretation the package makes).

**Development status:** alpha. Validate results against the official
protocol; the package does not certify regulatory compliance.

## Install

```bash
python -m pip install crashmetrics
```

Python 3.10 or later; the only dependency is NumPy 1.24 or later.

## What it covers

| Area | Highlights | Guide |
| --- | --- | --- |
| Signals | SAE J211 CFC filter, resultants, unit conversion, HIC, peak, 3 ms clip, exceedance curves | [Signals](https://vsk1729.github.io/crashmetrics/guides/signals/) |
| Pedestrian (Euro NCAP) | Headform grid with correction factor, blue / default-red / A-pillar points; aPLI, upper legform, total VRU score | [Headform](https://vsk1729.github.io/crashmetrics/guides/pedestrian-headform/), [Legforms](https://vsk1729.github.io/crashmetrics/guides/pedestrian-legforms/) |
| Pedestrian (India) | AIS-100 compliance: Flex-PLI and legacy legform, upper legform, HIC1000 / HIC1700 zones; Flex-PLI assessment interval and Euro NCAP Flex-PLI score | [Flex-PLI and AIS-100](https://vsk1729.github.io/crashmetrics/guides/flexpli-ais100/) |
| Frontal dummies | DAMAGE, BrIC, neck loads, Nij, R94 limits, chest deflection, VC, CTI, THOR Rmax and abdomen, acetabulum, iliac force drop, femur, Tibia Index, knee slider | [Frontal criteria](https://vsk1729.github.io/crashmetrics/guides/frontal-dummy-criteria/) |
| Euro NCAP 2026 | MPDB (20 points) and full width (10 points) with modifiers and the compatibility penalty | [MPDB and full width](https://vsk1729.github.io/crashmetrics/guides/euroncap-frontal/) |
| Bharat NCAP | AIS-197 ODB frontal and MDB side scores, ES-2 criteria, pole test, star rating | [Bharat NCAP](https://vsk1729.github.io/crashmetrics/guides/bharat-ncap/) |
| Vehicle | OLC, delta-V, rebound, crush, absorbed energy, CFE, SEA | [Pulse and energy](https://vsk1729.github.io/crashmetrics/guides/pulse-energy/) |
| LS-DYNA | glstat / matsum energy checks, d3hsp run summary, `crashmetrics-energy` command | [LS-DYNA energy](https://vsk1729.github.io/crashmetrics/guides/lsdyna-energy/) |
| Analytics and ML | Batch runs into tables; signal shape features, criteria and design parameters per run as a training set; CSV, pandas and NumPy output | [Batch and analytics](https://vsk1729.github.io/crashmetrics/guides/batch-analytics/), [ML features](https://vsk1729.github.io/crashmetrics/guides/ml-features/) |

## Quick examples

```python
from crashmetrics.pedestrian import calculate_hic, check_flexpli, hic_colour
from crashmetrics.signals import cfc_filter, resultant, to_g, to_seconds

# HIC15 from LS-DYNA headform output (mm-ms-kg): filter each axis, then the resultant
t = to_seconds(time_ms, "ms")
a = resultant(*(cfc_filter(t, to_g(c, "mm/ms^2"), cfc=1000) for c in (ax, ay, az)))
hic = calculate_hic(t, a, window_ms=15.0)
print(hic.value, hic_colour(hic.value))          # Euro NCAP headform colour

# AIS-100 Rev.1 Flex-PLI check (peaks in N m and mm)
check = check_flexpli(tibia_moment=300, mcl=20, acl=6, pcl=5)
print(check.passed, check.worst, check.utilisation)
```

Bharat NCAP star rating, Euro NCAP MPDB score, legform grids and more
are in the [guides](https://vsk1729.github.io/crashmetrics/guides/).

## Runnable examples

The [`examples/`](https://github.com/vsk1729/crashmetrics/tree/main/examples)
folder has eleven scripts with synthetic data, one per topic, from
`01_signals_hic.py` to `11_ml_features.py`. The test suite checks that
each one still prints exactly its documented output.

```bash
python examples/07_bharat_ncap.py
```

## Where the numbers come from

Formulas and limits come from publicly available protocols and
standards: Euro NCAP (assessment protocols, CP 005, CP 007), Bharat NCAP
(AIS-197), AIS-100, UN R94 and R127, UN GTR 9, FMVSS 208, SAE J211 and
published research. The tests reproduce the protocols' own worked
examples where they give one, and check other formulas against hand
calculations and closed-form solutions.

## Contributing

Issues and pull requests are welcome. See
[Development and releases](https://vsk1729.github.io/crashmetrics/about/development/)
for the setup and the checks CI runs, and the
[changelog](https://github.com/vsk1729/crashmetrics/blob/main/CHANGELOG.md)
for what changed.

## Disclaimer and trademarks

crashmetrics is an engineering calculation aid and an independent
open-source project. It is not affiliated with, endorsed by or sponsored
by Ansys, Euro NCAP, Bharat NCAP, ARAI, UNECE or any other organisation
whose software, file formats, protocols or regulations it refers to.
LS-DYNA, Ansys and Euro NCAP are trademarks or registered trademarks of
their respective owners, used here only to describe compatibility. The
LS-DYNA readers were written from the text layout of output files; no
LS-DYNA code or documentation is included.

## License

MIT. See the [LICENSE](https://github.com/vsk1729/crashmetrics/blob/main/LICENSE) file.
