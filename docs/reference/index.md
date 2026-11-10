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
| [`bncap`](bncap.md) | Bharat NCAP (AIS-197, 2023 edition) scoring, named modifiers, star rating, edition and validity dates |
| [`bncap_channels` and `bncap_report`](bncap_channels.md) | Bharat NCAP occupants from dummy channels (and ISO-MME); adult occupant scorecard |
| [`pulse`](pulse.md) | OLC and pulse summary |
| [`energy`](energy.md) | Integration, absorbed energy, crush metrics |
| [`energy_check` and `lsdyna`](lsdyna.md) | Energy balance checks, glstat / matsum / d3hsp readers |
| [`isomme`](isomme.md) | ISO-MME (ISO/TS 13499) test data: read and write |
| [`lsdyna_ascii`](lsdyna_ascii.md) | nodout, rcforc, sleout, secforc, rwforc, sbtout, deforc, jntforc, abstat, rbdout, spcforc, swforc readers |
| [`loadpath`](loadpath.md) | Load paths from matsum and secforc: energy ranking and groups, section forces, load split, crush sequence, run comparison with culprit parts, energy matrix, Markdown report |
| [`spotweld`](spotweld.md) | Spot weld failure from swforc: peak forces and utilisation of every weld, failed and critical welds, failure sequence and bursts, baseline against variant |
| [`quality`](quality.md) | Model quality check sheet of a run: termination, mass and centre of gravity, added mass, time step, energy balance, contact energies; several runs side by side |
| [`synthetic`](synthetic.md) | A toy full-width frontal crash with upper, middle and lower load paths and spot welds that writes LS-DYNA-style matsum, secforc, swforc, glstat, sleout and d3hsp; variants with known causes |
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
| [`materials`](materials.md) | Tensile tests: read (CSV, text, xlsx), clean, properties (E, Rp0.2, Rm, Ag, A); Lüders plateau, machine compliance; mean curve and scatter of several specimens; true stress, necking, plastic strain, Swift / Voce / Hockett-Sherby / Swift-Voce extrapolation, n and K; Cowper-Symonds and Johnson-Cook rate fits, strain-rate `*DEFINE_TABLE` with checks; the `*MAT_024` card in any unit system; GISSMO failure: failure curves from fracture tests with their paths (Hosford-Coulomb, Johnson-Cook, tabulated), instability from the forming limit curve, element size regularisation, damage along a path, `*MAT_ADD_DAMAGE_GISSMO` written, read and checked; read, check, convert and compare existing cards; single-element verification deck; material library |
| [`uncertainty`](uncertainty.md) | Monte Carlo scatter of inputs, probabilistic scores and star ratings |
