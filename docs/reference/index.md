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
| [`bncap`](bncap.md) | Bharat NCAP (AIS-197) scoring and star rating |
| [`pulse`](pulse.md) | OLC and pulse summary |
| [`energy`](energy.md) | Integration, absorbed energy, crush metrics |
| [`energy_check` and `lsdyna`](lsdyna.md) | Energy balance checks, glstat / matsum / d3hsp readers |
| [`lsdyna_ascii`](lsdyna_ascii.md) | nodout, rcforc, sleout, secforc, rwforc, sbtout, deforc, jntforc, abstat, rbdout, spcforc, swforc readers |
