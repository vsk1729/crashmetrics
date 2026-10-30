# API reference

Generated from the docstrings in the source code. Every public function
lists its parameters, units and return value; every result is a
dataclass, so `dataclasses.asdict(result)` turns it into a plain dict.

| Module | Contents |
| --- | --- |
| [`signals`](signals.md) | CFC filter, resultant, unit conversion, resampling |
| [`acceleration`](acceleration.md) | Peak, 3 ms clip, exceedance curves and force–duration limits |
| [`pedestrian`](pedestrian.md) | HIC, headform and legform grid scoring, Flex-PLI, AIS-100 |
| [`head`](head.md) | DAMAGE, BrIC, loading phase |
| [`neck`](neck.md) | Neck loads, occipital condyle moment, R94 limits, Nij |
| [`thorax`](thorax.md) | Chest deflection, VC, THOR Rmax and abdomen, CTI |
| [`pelvis`](pelvis.md) | Acetabulum force, iliac force drop |
| [`lower_extremity`](lower_extremity.md) | Tibia Index, tibia compression, knee slider, femur force |
| [`side`](side.md) | ES-2 rib deflection and VC, abdominal and pubic forces |
| [`frontal_scoring`](frontal_scoring.md) | Euro NCAP 2026 MPDB and full width scoring |
| [`virtual_testing`](virtual_testing.md) | Euro NCAP frontal sled and virtual testing (VTC): model quality, ISO sensor scores, validation, 10-point score |
| [`bncap`](bncap.md) | Bharat NCAP (AIS-197) scoring and star rating |
| [`pulse`](pulse.md) | OLC and pulse summary |
| [`energy`](energy.md) | Integration, absorbed energy, crush metrics |
| [`energy_check` and `lsdyna`](lsdyna.md) | Energy balance checks, glstat / matsum / d3hsp readers |
| [`isomme`](isomme.md) | ISO-MME (ISO/TS 13499) test data: read and write |
| [`lsdyna_ascii`](lsdyna_ascii.md) | nodout, rcforc, sleout, secforc, rwforc, sbtout, deforc, jntforc, abstat, rbdout, spcforc, swforc readers |
| [`side_scoring`](side_scoring.md) | Euro NCAP 2026 side impact: AE-MDB, pole and far side scoring |
| [`whiplash`](whiplash.md) | BioRID NIC and Nkm, 2026 rear impact score |
| [`bncap_cop` and `bncap_rating`](bncap_cop.md) | Bharat NCAP child occupant protection and complete rating with safety assist |
| [`homologation`](homologation.md) | UN R94 / AIS-098, UN R95 / AIS-099, UN R135 and post-crash electrical safety checks |
| [`intrusion`](intrusion.md) | Intrusion relative to the vehicle, node distances |
| [`correlation`](correlation.md) | ISO/TS 18571, CC rating, error measures |
| [`features`](features.md) | Signal shape features, feature tables, CSV / pandas / NumPy output |
| [`doe`](doe.md) | Latin hypercube, Halton, full factorial, Morris designs; LS-DYNA *PARAMETER cards |
| [`sensitivity`](sensitivity.md) | PRCC, Spearman, SRC and Morris sensitivity ranking |
| [`margins`](margins.md) | Distance to performance limits as continuous ML targets |
| [`uncertainty`](uncertainty.md) | Monte Carlo scatter of inputs, probabilistic scores and star ratings |
