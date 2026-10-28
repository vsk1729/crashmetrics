# crashmetrics examples

Runnable scripts with synthetic (made-up) data. Each one prints its
results; the expected output is in `expected/`, and the test suite
checks that the scripts still produce exactly that output.

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
| `hic_convergence.py` | How HIC changes with the integration resolution (for developers) |

The full step-by-step explanations are in the documentation:
<https://vsk1729.github.io/crashmetrics/>.
