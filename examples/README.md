# crashmetrics examples

Runnable scripts with synthetic (made-up) data, except examples 09 and
18, which read real LS-DYNA output from `tests/data/lsdyna` (run them
from a clone of the repository). Each one prints its results; the
expected output is in `expected/`, and the test suite checks that the
scripts still produce exactly that output.

```bash
python -m pip install crashmetrics
python examples/07_bharat_ncap.py
```

| Script | What it shows |
| --- | --- |
| `01_signals_hic.py` | Unit conversion, CFC 1000 filtering, resultant, HIC15, peak, 3 ms clip, resampling |
| `02_headform_grid.py` | Euro NCAP headform grid: predicted colours, verification tests, correction factor, blue / default-red / A-pillar points, 2026 and 2023 scores |
| `03_legform_vru.py` | aPLI point and grid scores, upper legform energy and score, total VRU score |
| `04_flexpli_ais100.py` | Flex-PLI assessment interval and peaks, AIS-100 compliance (Flex-PLI, legacy legform, upper legform, headform zones), Euro NCAP Flex-PLI score |
| `05_frontal_dummy_criteria.py` | DAMAGE, BrIC, neck loads, R94 tension, Nij, chest deflection, VC, CTI, THOR Rmax and abdomen, acetabulum, iliac force drop, femur, knee slider, Tibia Index |
| `06_euroncap_mpdb_fwdb.py` | Euro NCAP 2026 MPDB and full width scores with modifiers and the compatibility penalty |
| `07_bharat_ncap.py` | Bharat NCAP (AIS-197) frontal and side scores, exceedance-curve scoring, modifiers, pole test and star rating |
| `08_pulse_olc_crush.py` | OLC, delta-V, rebound, dynamic crush, crash box energy, mean force, CFE and SEA |
| `09_lsdyna_energy_check.py` | LS-DYNA glstat/matsum energy checks and the d3hsp run summary |
| `10_batch_analytics.py` | A DOE batch run into a CSV results table, correlations and a linear surrogate |
| `11_ml_features.py` | An ML-ready feature table: criteria, signal shape and design parameters per run, failed runs recorded, CSV and matrix output, a surrogate checked on held-out runs |
| `12_test_cae_correlation.py` | Test-versus-CAE correlation: ISO/TS 18571, the CC rating and error measures for three channels and three model versions with different time bases, ranked and put in a feature table |
| `13_intrusion.py` | Intrusion of pedal, steering column, A-pillar and toe pan: global, one-node and vehicle-frame references, dynamic and static values, survival space, a before/after test measurement and the Bharat NCAP modifiers |
| `14_homologation.py` | Homologation of an electric car: UN R94 / AIS-098 (both occupants and vehicle), post-crash electrical safety, UN R95 / AIS-099 and UN R135, with failures traced to clauses |
| `15_euroncap_side.py` | Euro NCAP 2026 side impact: AE-MDB, pole and far side (35 points) for two design variants, head excursion zones, robustness and the 17-point far side rule |
| `16_bharat_ncap_cop_rating.py` | Bharat NCAP child occupant protection (Q1.5 and Q3 dynamic, CRS installation, vehicle based) and the complete rating with the safety assist qualifiers, for two side head protection fitment rates |
| `17_whiplash.py` | Rear impact (whiplash): NIC and Nkm from BioRID signals, medium and high pulse scores with capping, front seat geometry, rear seats, for two seat designs |
| `18_lsdyna_ascii.py` | LS-DYNA ASCII output of a helmeted Hybrid III head (real R16 files): HIC and BrIC from nodout, upper neck load from secforc, a run directory with rcforc and spcforc, features for ML |
| `19_euroncap_virtual_testing.py` | Euro NCAP frontal sled and virtual testing: simulation channels written and read as ISO-MME, model quality, ISO/TS 18571 sensor scores, assessment criteria deviations, load case validation and the driver's sled and virtual score |
| `20_doe_margins_sensitivity.py` | A 30-run Latin hypercube with LS-DYNA *PARAMETER cards, Euro NCAP points and margins to the limits per run, PRCC / Spearman / SRC ranking of three criteria and Morris screening |
| `21_probabilistic_rating.py` | Bharat NCAP adult occupant rating under test scatter: Monte Carlo of the full scoring, probability of 5 stars and the criteria that decide it |
| `hic_convergence.py` | How HIC changes with the integration resolution (for developers) |

The full step-by-step explanations are in the documentation:
<https://vsk1729.github.io/crashmetrics/>.
