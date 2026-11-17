# Validation

What every part of crashmetrics is checked against, in one place. Use
it to judge how far to trust a result before you validate it on your own
data, which you should always do (see the
[disclaimer](about/disclaimer.md)).

Everything listed here is a test in the repository's test suite and
runs on every change, on Python 3.10 to 3.13 with NumPy 1.24 and the
latest NumPy. The few checks that were done once during development, or
only on files that cannot be redistributed, are marked as such.

## Kinds of evidence

| Evidence | What it means | Strength |
| --- | --- | --- |
| **Real data** | Real test or solver data, with a result that someone else computed or that physics fixes | Strongest: the whole chain is checked, from file to number |
| **Independent implementation** | The same input run through another group's code gives the same number | Strong for the algorithm |
| **Protocol example** | A worked example printed in the protocol or standard is reproduced | Strong for scoring rules |
| **Closed form or hand calculation** | An exact formula, a calculation worked by hand, or a brute-force search | Shows the formula is coded correctly |
| **Synthetic truth** | Data generated from a model whose answer is known | Shows the analysis finds what was put in |

Limit values and tables are checked against the source document in
every scoring module; that is not repeated in each row below.

## Signals and generic criteria

| Function | Checked against | Evidence | Tests |
| --- | --- | --- | --- |
| CFC filter | Frequency response inside the SAE J211 corridor for every class and several sample rates; equal to the J211 recursion written out; zero phase | Closed form | `test_signals.py` |
| CFC filter, CFC 60 | NHTSA test 2320 (see [Pulse](#vehicle-pulse-energy-and-intrusion)) | Real data | `test_nhtsa.py` |
| HIC | Constant acceleration and triangle pulse optima to 1e-10; brute-force search over all window pairs; a second optimiser | Closed form | `test_hic.py`, `test_hic_exact.py`, `test_hic_reference.py` |
| HIC15, CFC 1000 | LS-DYNA head drop (helmeted Hybrid III): 194.60 against the study's own 195.24 (0.3 %) | Real data | `test_lsdyna_ascii.py`, `test_clearance.py` |
| 3 ms clip, exceedance curves | Constant, triangle and plateau pulses; brute-force reference on random signals, cumulative and continuous | Closed form | `test_acceleration.py` |

## Dummy injury criteria

| Criterion | Checked against | Evidence | Tests |
| --- | --- | --- | --- |
| DAMAGE | The model developers' reference implementation (UVA-CAB/DAMAGE 2.0) for the same input; modal solution of a coupled step | Independent implementation | `test_head.py` |
| BrIC | Hand calculation; critical values of the source paper (Takhounts 2013) | Hand calculation | `test_head.py` |
| BrIC | LS-DYNA head drop: the study's own value reproduced | Real data | `test_lsdyna_ascii.py` |
| Nij, neck loads, occipital condyle moment | FMVSS 208 intercepts; hand calculations for all four load cases and both dummy sizes | Hand calculation | `test_neck.py` |
| Peak neck moment | LS-DYNA pendulum test (secforc): the study's own value reproduced | Real data | `test_lsdyna_ascii.py` |
| Chest deflection, VC, THOR Rmax, abdomen, CTI | VC of a sinusoid; the five-point velocity exact for a cubic; THOR rib geometry; hand calculations | Closed form | `test_thorax.py` |
| Acetabulum force, iliac force drop | Hand calculations | Hand calculation | `test_pelvis.py` |
| Tibia Index, femur force-duration, knee slider | Hand calculations; brute-force search for the femur curve | Closed form | `test_lower_extremity.py` |
| Side dummy criteria (rib deflection, VC, abdominal and pubic force) | Sinusoid and hand calculations | Closed form | `test_side.py` |
| NIC, Nkm (whiplash) | Closed form and hand calculations | Closed form | `test_whiplash.py` |

!!! warning "Not yet checked on physical crash test data"
    No dummy criterion has yet been compared with the value a test lab
    reported for a physical vehicle crash test. See
    [What is not validated yet](#what-is-not-validated-yet).

## Scoring: Euro NCAP, Bharat NCAP, regulations

| Area | Checked against | Evidence | Tests |
| --- | --- | --- | --- |
| Pedestrian headform grid | Worked examples of both protocols: 10.554 of 18 points (VRU v11.4, 2023) and correction factor 1.120 (VRU Impacts v1.1, 2026) | Protocol example | `test_headform.py` |
| Pedestrian legforms, VRU total | Worked examples of both protocols (upper legform, femur, knee and tibia) | Protocol example | `test_legform.py` |
| Flex-PLI score and assessment interval | Hand calculations | Hand calculation | `test_flexpli.py` |
| AIS-100 checks | Limit values; hand cases | Hand calculation | `test_ais100.py` |
| Euro NCAP MPDB and full width | Hand-worked MPDB example; compatibility penalty examples of CP 007 | Protocol example, hand calculation | `test_frontal_scoring.py` |
| Euro NCAP sled and virtual testing | Thresholds of the Virtual Testing Protocol v1.0.2; a score example worked by hand | Hand calculation | `test_virtual_testing.py` |
| Euro NCAP side, pole, far side | Hand cases for bands, capping and modifiers | Hand calculation | `test_side_scoring.py` |
| Euro NCAP whiplash | Sliding scales, capping and seat scores by hand | Hand calculation | `test_whiplash.py` |
| Bharat NCAP adult occupant, rating | Frontal and side scores worked by hand; exceedance curves; balance, capping and qualifier rules | Hand calculation | `test_bncap.py`, `test_bncap_channels.py`, `test_bncap_report.py` |
| Bharat NCAP child occupant, complete rating | Clause by clause against AIS-197 Annexures V, VI and VIII, including the standard's own CRS installation example | Protocol example | `test_bncap_cop.py` |
| UN R94, R95, R135, EV safety | Limit values; hand cases at and around each limit | Hand calculation | `test_homologation.py` |

## Vehicle pulse, energy and intrusion

| Function | Checked against | Evidence | Tests |
| --- | --- | --- | --- |
| Pulse summary | **NHTSA test 2320** (1996 Dodge Neon, 56.5 km/h rigid barrier): peak 35.2 g, crush 740 mm at 78 ms, restitution 0.162, against 35.2 g, 740 mm, 78 ms and 0.163 that an independent project computed from the same channel | Real data, independent implementation | `test_nhtsa.py` |
| Pulse summary | **NHTSA test 4429** (1999 Lincoln Navigator into 1996 Dodge Neon, head-on): the velocity changes of the two cars are in the inverse ratio of their masses within 10 % (1.96 against 2.08), and both end at the common velocity of a plastic impact within 1 m/s | Real data | `test_nhtsa.py` |
| OLC | Constant deceleration; an independent numerical formulation; independent of sampling | Closed form | `test_pulse.py` |
| Integration, absorbed energy, crush metrics | Exact integrals; work done equals kinetic energy lost | Closed form | `test_energy.py` |
| Intrusion | Local deformation recovered exactly under rigid-body motion; with measurement noise | Synthetic truth | `test_intrusion.py` |

## LS-DYNA readers and run analysis

| Area | Checked against | Evidence | Tests |
| --- | --- | --- | --- |
| nodout, secforc | LS-DYNA R16 head drop and pendulum runs; HIC, BrIC and the neck moment of the study reproduced | Real data | `test_lsdyna_ascii.py` |
| rcforc, spcforc | LS-DYNA R14 plate buckling run | Real data | `test_lsdyna_ascii.py` |
| glstat, matsum | LS-DYNA R14.1.1 drop test | Real data | `test_lsdyna.py`, `test_quality.py` |
| d3hsp | LS-DYNA R14.1.1 file; expected values read from the raw file | Real data | `test_d3hsp.py` |
| Other ASCII files (sleout, rwforc, sbtout, deforc, jntforc, abstat, rbdout, swforc) | Short files written in the solver's layout | Synthetic truth | `test_lsdyna_ascii.py` |
| Energy checks | Balanced and faulty energy histories | Synthetic truth | `test_energy_check.py` |
| Load paths | Synthetic frontal runs with a known cause; two real secforc runs compared | Synthetic truth, real data | `test_loadpath.py` |
| Spot welds | Synthetic runs with known failure times | Synthetic truth | `test_spotweld.py` |
| Model quality sheet | Synthetic runs with known faults; the real drop test files | Synthetic truth, real data | `test_quality.py` |
| Keyword mesh | Fixed, long and comma formats; round trip | Synthetic truth | `test_mesh.py` |
| Keyword decks: masses, centre of gravity, time step | LS-DYNA R14.1.1 ball drop deck: part masses, the model's centre of gravity and the smallest time step equal what the solver printed in its d3hsp (to its single-precision output) | Real data | `test_deck.py` |
| Keyword decks: reading, checks, write-back | Four real decks (R14 drop and tube crush, a deck with one deliberate fault, an LS-PrePost 2024/R2 thermal deck with missing includes); unchanged write-back byte for byte; synthetic decks for every format, parameters, includes and edits | Real data, synthetic truth | `test_deck.py` |
| Bonnet clearance | 130 synthetic impacts with known bottoming; analytic geometry; the square-wave limit; the real head drop nodout | Synthetic truth, closed form, real data | `test_clearance.py` |
| ISO-MME | Hand-built containers of another project (pyisomme) in three encodings | Synthetic truth | `test_isomme.py` |

Several readers were also run on real files whose licences do not allow
copying them into the repository (a full-width frontal crash with 394
spot welds, a hat section crush, a bolted joint and others). Those
checks are described in the guides and are not part of the test suite.

## Test versus CAE, materials, statistics

| Area | Checked against | Evidence | Tests |
| --- | --- | --- | --- |
| ISO/TS 18571 rating | objective-rating-metrics 1.3 (Vehicle Safety Institute, TU Graz): corridor, phase, magnitude, slope and overall rating equal to 1e-10 for three signal pairs, and its published examples | Independent implementation | `test_correlation.py` |
| CC rating, error measures | Scaled and shifted signals with known results | Closed form | `test_correlation.py` |
| Tensile evaluation, hardening, strain rate | Synthetic steels with a known law: every property and every fit must return the law | Synthetic truth | `test_materials_tensile.py`, `test_materials_hardening.py`, `test_materials_rate.py` |
| `*MAT_024` cards, unit conversion, card checks | Round trip; hand-written cards in all formats | Synthetic truth | `test_materials_card.py`, `test_materials_keyword.py` |
| GISSMO | Analytic stress states; fits return the generating criterion; damage of a constant state | Closed form, synthetic truth | `test_materials_gissmo.py` |
| DOE sampling | Values worked by hand; identical to SciPy's Halton during development | Hand calculation | `test_doe.py` |
| Sensitivity ranking | Exact cases; equal to SciPy and SALib during development | Closed form | `test_sensitivity.py` |
| Margins, probabilistic ratings | Hand cases | Hand calculation | `test_margins_uncertainty.py` |
| Features and batch tables | Signals with known features | Closed form | `test_features.py` |

## The examples

All 35 example scripts run in the test suite, and their printed output
must match the files shown in the guides character for character
(`test_examples.py`). So every number in the documentation is the
number the current code prints.

## What is not validated yet

Be aware of these gaps when you use the results:

- **Dummy criteria on physical crash tests.** HIC, Nij, chest
  deflection, femur loads and the others have not been compared with
  values a test lab reported for a real vehicle crash test. The real
  head and neck checks above are from simulations.
- **Published ratings.** No score has been compared with a published
  Euro NCAP or Bharat NCAP datasheet of a real car.
- **Solver runs of the generated cards.** The `*MAT_024` and GISSMO
  cards and the single-element deck are checked as text and against
  exact responses, not by running LS-DYNA. Decks edited by
  `crashmetrics.deck` are checked by reading them back, not by a run.
- **ASCII files without a real sample in the repository** (the row
  "Other ASCII files" above).
- **Synthetic models.** The frontal crash and bonnet models are
  teaching models. They test the analysis, and they are not vehicle
  simulations.
- **Protocol versions.** Each module states the protocol version it
  implements; later versions are not covered until they are added.

## Real data in the repository

| Data | Source | Licence | Used for |
| --- | --- | --- | --- |
| NHTSA tests 2320 and 4429, vehicle accelerations | NHTSA Vehicle Crash Test Database, through an MIT-licensed repository | NHTSA public information; MIT | Pulse, CFC filter |
| Head drop and pendulum runs (LS-DYNA R16) | A helmet fit study | MIT | nodout, secforc, HIC, BrIC, neck moment |
| Drop test (LS-DYNA R14.1.1) | An LS-DYNA modelling project | MIT | glstat, matsum, d3hsp; its keyword deck |
| Tube crush deck (LS-DYNA R14 template) | The same LS-DYNA modelling project | MIT | Keyword deck reader, edits |
| Block on plate decks | An LS-PrePost automation project | MIT | Keyword deck checks |
| Plate buckling (LS-DYNA R14) | A plate buckling study | MIT | rcforc, spcforc; its main keyword deck (LS-PrePost 2024/R2) |
| ISO-MME containers | pyisomme | MIT | ISO-MME reader |

Each folder under `tests/data/` has a README with the exact source,
commit and licence file.

## Run it yourself

```bash
git clone https://github.com/vsk1729/crashmetrics
cd crashmetrics
python -m pip install -e ".[dev]"
python -m pytest
```

If a result differs from your own validated tool or from a protocol,
please open an issue on
[GitHub](https://github.com/vsk1729/crashmetrics/issues) with the input
and the expected value.
