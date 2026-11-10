# Protocol notes and interpretations

Crash protocols are written for test labs, not for code. Some rules are
ambiguous, some documents contradict themselves, and some leave a detail
unstated. This page lists **every such place**, what crashmetrics does,
and how to change it. If your organisation reads a rule differently, the
"Change it" column shows how to match your reading.

!!! info "How to read this page"
    **Source** is the protocol section. **crashmetrics** is the default
    behaviour. Items marked ⚠️ are genuine contradictions inside the
    source document; the others are unstated details or numerical
    choices.

## Signals and generic criteria

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| CFC filter end effects | SAE J211-1 does not prescribe padding | Each end padded by odd reflection over 10 ms | `cfc_filter(..., pad_ms=...)` |
| HIC integration | Definition only | Linear interpolation between samples, integrated exactly; end points on a 0.1 ms grid plus the samples (a lower bound, usually within 0.05 %), or the exact maximum over continuous end points; warning if the record is shorter than the window | `calculate_hic(..., resolution_ms=..., method="exact")`; see [HIC accuracy](guides/hic-accuracy.md) |
| 3 ms clip | Euro NCAP: cumulative | Cumulative by default | `clip_3ms(..., mode="continuous")` |
| UN R94 neck and femur durations | R94 does not say cumulative or continuous | Cumulative | `mode="continuous"` |
| R94 femur limit | R94: 9.07 kN at 0 ms, 7.58 kN at ≥ 10 ms; Euro NCAP / AIS-197 print 7.56 kN | `"r94_hybrid3_50"` uses 7.58 kN; Bharat NCAP scoring uses 7.56 kN | Pass your own `limit` points |

## Pedestrian: headform (Euro NCAP)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| A-pillar rewards (2026) | VRU Impacts v1.1 gives the rewards, not how they add to the grid | Added to the grid points; the maximum stays the number of grid points | Score A-pillar points yourself and pass them as labels |
| Correction factor outside 0.85–1.15 | Prediction is reviewed with Euro NCAP | Factor still applied; `correction.accepted` is `False` | Check `accepted` |
| Verification tolerance | Tabulated ranges | Uses the protocols' table exactly (e.g. green < 722.22) | |

## Pedestrian: bonnet clearance and bottoming out

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| Headforms | Euro NCAP / UN GTR 9: child 3.5 kg at 50°, adult 4.5 kg at 65°, both 165 mm at 40 km/h | `HEADFORMS`; direction rearward and down at that angle, x rearward and z up | `Headform(...)`, `impact_direction(rearward=, up=)` |
| ⚠️ Free space | Not defined by any protocol | A rigid 165 mm sphere touching the bonnet at the point (centre on the surface normal), swept along the impact direction until it touches a node of a hard part | `radius=`, `max_distance=`, `surface=` |
| ⚠️ No bonnet surface given | — | The headform is taken to hit head-on (the point is the sphere's leading point), which underestimates the space under a sloping bonnet | Give `surface=` |
| ⚠️ Hard parts | The user's choice | Only the parts given; their nodes, not their faces | Refine coarse meshes |
| Space needed | Not defined | The stopping distance of a pulse shape scaled to stop the head with exactly that HIC15; the square wave is the physical lower limit | `shape=`, `speed=`, `window_ms=` |
| Filtering | Euro NCAP: CFC 1000 for the headform | CFC 1000 on the three axes, then the resultant; uneven output resampled first | `cfc=` |
| First contact | Not defined | The unfiltered resultant reaches 2 g; penetration is measured from then | `contact_g=` |
| ⚠️ Bottoming out (geometry) | Not defined | Penetration reaches the free space minus the crushed bonnet stack (5 mm) plus the headform skin compression (3 mm) | `stack=`, `skin=` |
| ⚠️ Bottoming out (pulse) | Not defined | A later peak at least 1.25 × the first contact peak after a dip; onset where it starts to rise. The geometric time wins when both exist | `rise=`, `first_fraction=` |
| Extra space | Estimate | v² / (2 a) with the residual speed and the plateau before bottoming out | |
| ⚠️ Diagnosis | Not defined | Against a target colour (yellow): bottoming if ≥ 25 % of the HIC window comes after it; first peak if the first contact phase alone gives ≥ 70 % of the HIC; else stiff | `target=` |
| ⚠️ Synthetic bonnet | Not LS-DYNA output | A lumped teaching model per point in the keyword and nodout layouts; the header says so | |

## Pedestrian: legforms (Euro NCAP)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| Untested upper legform points below 160 J | No test required; the score is not stated | 1.0 (full points) | `not_required_score=` |
| Negative upper legform angle α | Not covered | Treated as 0° | |
| Sharing results between points | Energies must be similar | Shared only if energies differ by ≤ 10 % of the tested point's energy | `energy_tolerance=` |
| Grid filling | Symmetry, then worst adjacent | Applied separately for femur and knee/tibia | `asymmetric_points=`, `symmetric=False` |

## Pedestrian: Flex-PLI and AIS-100

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| Assessment interval end | AIS-100 Rev.1 §3.2 / GTR 9: "last zero crossing ... within their particular common zero crossing phases" | Latest of each segment's first zero crossing after its first maximum above 15 N m | Compute your own and pass `interval=` |
| Assessment interval start | First contact | First sample unless `t_contact` is given | `assessment_interval(..., t_contact=)` |
| ACL / PCL exactly 10 mm (Euro NCAP) | Text: "smaller than the threshold"; worked example: 10.00 mm fails | 10 mm scores the knee 0 | |
| Euro NCAP Flex-PLI grid filling | Worst adjacent result | Filled on the total point score (tibia + knee) | |
| HIC1000 zone shares | Projected areas from the manufacturer's drawing | You supply the projected areas | |

## Frontal dummy criteria (CP 005, R94, FMVSS 208)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| THOR abdomen sign | CP 005 §3.5.2 writes `max(Dx)` with `Dx = R cos φz cos φy − Dx(0)`; R shortens in compression | `value` = compression `max(−Dx)`; `max_dx` = literal `max(Dx)` | Use `max_dx` if your R grows in compression |
| Acetabulum compression sign | CP 005 §3.6.2 does not state it | Negative Fx is compression | `compression_negative=False` |
| Iliac force drop sign | CP 005 §3.6.1 formula assumes force negative under load | As written; drop is positive | `loaded_negative=False` |
| DAMAGE angular acceleration | CP 005 gives CFC 60 angular velocity, not the derivative method | Second-order central differences | Differentiate yourself and use `damage_from_acceleration` |
| DAMAGE model details | CP 005 / TB 035 give the parameters | Spring-network stiffness, z axis reversed, Newmark average acceleration, as in the developers' reference code | |
| Nij intercepts | FMVSS 208 has several dummies and positions | In-position Hybrid III 50th and 5th only | `intercepts=NijIntercepts(...)` |
| BrIC critical values | Takhounts 2013: MPS-based, CSDM-based and average | Average | `critical="mps"` / `"csdm"` / your tuple |
| CTI acceleration | NHTSA defines A for the 3 ms clip | 3 ms clip of the spine resultant | `acceleration_measure="peak"` |

## Euro NCAP 2026 frontal scoring (MPDB, full width)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| ⚠️ Points per colour band | §3.5 text: 1.25 / 1.0 / 0.75 / 0.5 / 0 (100/80/60/40/0 %); §3.4 tables: 100/80/40/20/0 % | Text values | `band_fractions=BAND_FRACTIONS_TABLE` |
| Band boundaries | §3.4: green "< HPL", red "≥ LPL", band width (LPL − HPL)/3 (§3.4.1) | HPL itself is yellow; thirds between HPL and LPL | |
| Capping limits | Tabulated, consequence not stated | Reported in `capping_exceeded`, not applied | Apply your own rule to the result |
| Single-value limits | Q6/Q10 neck extension (36 / 49 N m), Q10 chest (56 mm), Hybrid III 5th tibia (1.3, 8 kN), THOR abdomen (88 mm) | Treated as LPL only: green below, red at or above | Edit `DUMMY_LIMITS` |
| Hybrid III 5th neck capping | Marked "driver only" | Applied to the driver only | |
| Full width speed | §3.2: 35 km/h | 35 km/h chest limits | `score_fwdb(..., speed=50)` |
| No hard head contact | Adults: HIC15 and 3 ms not applied; Q dummies: 3 ms only | As stated | `hard_contact=` |
| ⚠️ Compatibility with bottoming out | CP 007 text: "a further 25 % of the penalty", A.2: −7 %, A.3: −6.25 % | Figure 2: +1.25 points (6.25 % of 20), total ≤ 5 points; reproduces all three worked examples | Pass your own `compatibility_penalty` |
| Compatibility combination | CP 007 Figure 2 (no formula in the text) | `1.25 (s + o + 2so)` points, read from the figure and checked against the worked examples | |
| Modifier totals | CP 007: no limit to the number of modifiers; scores not below 0 | Summed per region; regions and tests floored at 0 | |

## Euro NCAP sled and virtual testing (VTC)

Virtual Testing Protocol v1.0.2 and Frontal Impact Protocol v1.2.

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| ⚠️ Points per load case | §3.3 table: sled "0.625 / 2", virtual "0.625 / 3" per region; the text does not explain the divisors | 0.625 / 2 per region in each of the two sled load cases, 0.625 / 3 in each of the three virtual Hybrid III load cases (totals 2.5 + 2.5 per occupant) | |
| ⚠️ Which load cases are sled tested | Two validation load cases, chosen in the procedure | Given by the user (any two of load cases 1-5; the other three are virtual) | `sled=`, `virtual=` |
| ⚠️ No HBM data | "the maximum available score for virtual testing is halved" | Virtual points halved, for driver and passenger | Adjust the result |
| Validation not met | "only the sled load cases can be scored" | Virtual points 0 (`validated=False`) | |
| ⚠️ Validation scope | Acceptance per sensor and criterion; the protocol does not say whether one failed load case fails all | One `validated` flag per occupant; decide from your `validate_load_case` results | |
| Sensor score | §5.3.1: weights from the test, for sensors with more than one axis | Same; single-axis sensors use their one score | |
| ⚠️ Filtering before rating | Simulation submitted unfiltered; filter classes for the rating not stated | Not applied: filter test and simulation the same way (CP 005 classes) before `sensor_score` | |
| Rating interval | Data from T0 to Tend; Tend = maximum head x excursion + 40 % | `frontal_end_time`; pass `t_start`, `t_end` | |
| AC limit | §5.3.2: the lower performance limits of the Frontal Impact Protocol §3.5 | LPLs of `frontal_scoring` for the load case's dummy and speed | |
| dAC below 50 % | dAC defined only where rAC_test ≥ 50 % | Not assessed; listed in the notes | |
| Strict limits | "below 10 %", "below 5 %", "exceed 0.5", "below 30 %", "> 0.95" | Strict comparisons: a value at the limit fails | |
| Virtual criteria | Knee displacement and tibia criteria not applicable; lower leg points by default unless a physical test exceeds a tibia LPL | As stated | `tibia_lpl_exceeded=` |
| ⚠️ Modifiers | §4.3.3: "% of the maximum available score for that load case"; same as full scale "where feasible" | Applied per body region as in the full-scale tests (`Occupant.modifiers`) | |
| Human body model | Required for full virtual points; HBM limits not given | Not scored | |

## Euro NCAP 2026 side impact (AE-MDB, pole, far side)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| ⚠️ Points per colour band | Side Impact Protocol §3.3 text: 1.25 / 1.0 / 0.75 / 0.5 / 0; the band percentages printed alongside: 100 / 80 / 40 / 20 / 0 % | Text values, as for the frontal tests | `band_fractions=BAND_FRACTIONS_TABLE` |
| WorldSID chest limits | §3.4 table: HPL 28 mm, LPL 50 mm, capping 50 mm (AE-MDB) and 55 mm (pole); the table layout leaves open whether the pole LPL is also 55 mm | LPL 50 mm in both tests; capping 50 / 55 mm | Edit `SIDE_DUMMY_LIMITS` |
| Q6 / Q10 neck and chest | Printed as single values (neck 2.4 / 2.2 kN, chest 3 ms 67 g) | Used as LPLs: green below, red at or above | |
| Capping (near side) | Capping limits tabulated; consequence not stated in §3.4 | Reported in `capping_exceeded`, not applied (as for the frontal tests) | Apply your rule to the result |
| Test modifiers | % of the 10-point maximum per adult load case | Deducted from the test total, so the Q dummies' points remain after −100 % | |
| Shoulder and VC modifiers | ≥ 3.0 kN, ≥ 1.0 m/s: −100 % of the region | Applied from `shoulder_force`, `chest_vc`, `abdomen_vc` in the values | |
| ⚠️ Far side zone points | 2026 table garbled in the text extract: with countermeasure 0 / 0.5 / 1 / 1.5 / 2 / 2, without 0 / 0 / 0.5 / 1 / 2 | Mapped to capping / red / brown / orange / yellow / green in the row order of the Far Side Protocol v2.4.1 table (whose dummy scores scale to the same values) | Edit `FAR_SIDE_ZONE_POINTS` |
| Far side zone geometry | Lines defined; which side of a line a zone lies is shown in a figure | Clearance to the struck-side seat centreline: ≥ 250 green, ≥ 125 yellow, ≥ 0 orange, then red/brown to the red line, beyond it capping; a head on a line is in the better zone | Pass the zone yourself |
| Far side robustness | AE-MDB: at most one zone worse than the main case and not red; "pole robustness scores 2 points" | The same rule for both pulses | |
| Far side capping | Any capping limit exceeded caps the load case; a head in the capping zone caps both | As stated; neck moments compared as magnitudes | |
| 17-point rule | Driver total in AE-MDB and pole below 17.0 of 20 removes far side rewards | All far side points removed | `near_side_driver_points=` |
| Not implemented | OEM colour prediction and verification, head protection coverage geometry, DAMAGE monitoring | Give the outcome (`curtain_zone_rows_failed`, modifiers) | |

## Rear impact (whiplash, 2026)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| Points per criterion | Rear Impact Protocol v1.2 lists HPL / LPL and 0.5 points each for NIC, +Fx, Fz; the calculation is deferred to CP 005 | Linear sliding scale between the limits, as stated in the earlier Euro NCAP / ANCAP whiplash scoring text | |
| Capping | v1.2 tabulates capping limits; the earlier scoring text: "no score is given for that pulse" | Any capping limit reached: that pulse scores 0; T1 and T-HRC only when both are reached | |
| ⚠️ Pulse names | Appendix B: medium and high severity; the scoring summary table says "low severity" | `"medium"` and `"high"` | |
| Nkm | Not used in the medium pulse; capping 0.78 in the high pulse | Accepted and ignored for the medium pulse | |
| ⚠️ Front geometry total | Test position "0 / +1.0", lowest and rearmost 0.5/n per seat, static total 1 point; how they combine is not stated | Test position plus the lowest/rearmost credit, capped at 1 | Use `test_position` and `lowest_rearmost` separately |
| Test position height | HPL 825 mm, LPL 790 mm | Linear between | |
| Backset | Single limits: 45 mm (test position), 70 mm (lowest and rearmost) | Pass/fail: below 45 mm scores 1, otherwise 0; at most 70 mm for the credit | |
| Rear seat scaling | Sum of the two outboard seats (or one doubled) scaled to 1 point; up to 1 point per seat | Mean of the seat scores | |
| NIC formula | CP 005: `0.2 a_rel + v_rel²`, `a_rel = T1 − head` (x), maximum to T-HRC(end) | As written; trapezoidal integration | |
| Nkm | CP 005 intercepts 88.1 / −47.5 N m, ±845 N; "particular forces and moments must be set to 0 ... AND condition" | Each combination counted only where both signs match | |

## Bharat NCAP (AIS-197)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| Edition and validity | AIS-197 (September 2023), Section 1.0: valid for four years; Bharat NCAP 2.0 (AIS-197 Rev 1) from October 2027 | 2023 edition for ratings 1 Oct 2023 – 30 Sep 2027; `edition=2027` raises an error | `edition_for_date`, `PROTOCOL` |
| Frontal hard head contact from channels | No hard contact if the peak resultant head acceleration is at most 80 g and there is no other evidence | `frontal_occupant_from_channels` assumes contact above 80 g | `head_contact=` |
| Tibia location | Upper and lower tibia measured | The worse Tibia Index and the worse compression of the given locations, per leg | Pass only one location |
| Incorrect airbag deployment | Annexure VII 2.1.4 and 3.1: −1 on each of the most relevant body parts, also in the other test if the airbag protects there | 1 point per region given; you choose the regions (and the test) | `incorrect_airbag_deployment=` |
| Driver knee variable contact split | 2.1.7.2: without concentrated loading on either driver knee, −0.5 for the column area and −0.5 for the rest of the facia, per knee | `knee_variable_contact_areas=`; refused for the passenger (2.2) or with concentrated loading | |
| ⚠️ Backplate and T12 load direction | 3.2 / 3.3: only loads that unload the chest count; T12 sign Fy < 0 and Mx > 0 for RHD (SAE J211) | Peak magnitudes are used | Pass only the unloading direction's peak |
| Asymmetry of reinforcements | 2.1.6.3: test agencies apply the structural and footwell modifiers (and T12 / backplate in side tests) | Not a separate modifier; apply those modifiers | |
| Shoulder belt load modifier | 2 points for a shoulder belt load above 6 kN | Applied strictly above 6000 N | |
| Backplate and T12 modifiers | Both listed for the side chest | Added together (each 0–2) | `modifiers=` |
| ISO-MME codes | AIS-197 lists channels, not ISO codes | Hybrid III codes of Euro NCAP CP 005 (`HYBRID3_ISOMME`); no ES-2 default | `channels_from_isomme(patterns=)` |
| ⚠️ Neck exceedance | Annex IV §3.1.2.2 says "continuous", §3.2.2 note says "cumulative exceedance plots" | Cumulative (as in Global NCAP) | `score_frontal` always uses cumulative; check a curve yourself with `curve_points(..., mode="continuous")` |
| ⚠️ T12 modifier lower bound | Annex VII §3.3 text: 1.5 kN; its limits table: 1.0 kN | 1.5 kN (text) | Compute the penalty yourself |
| 35 % front / side rule | "difference of scores above 35 %" | 35 % of the 16-point test maximum | |
| Capping | "exceeding a capping limit" | Strictly above the lower (capping) limit; a value exactly at it scores 0 and triggers the 1-star cap | |
| Region floor | Not stated | Region scores do not go below 0 | |
| Side head assessment | No hard-contact rule stated for the side test | HIC15 and 3 ms limits always applied | |
| Steering column modifier | Listed under the head (Annex VII §2.1.5) | Applied to the driver's head | Put it under another region in `modifiers` |
| Safety assist qualifiers | Annexure VI: ESC, side head protection fitment by year, pedestrian (AIS-100), SBR (AIS-145) | `safety_assist_max_stars`; applied to the adult stars only (Table 2B has no qualifier column) | `aop_rating(..., max_stars_allowed=)` |
| Pole test | Side head protection functionality shown by a pole test for 3, 4 and 5 stars | A passed pole test (`pole_test_passed`) is required at those levels | |
| ⚠️ 4-star side head fitment Oct 2027 – Sep 2030 | Annexure VI 3.2 table ends Sept 2027; 100 % "as from October 2030" | The last tabulated share (50 %) until Oct 2030 | Check `side_head_fitment_required` against the current amendment |
| 3-star side head protection after Oct 2027 | 4.2: "From October 2023 to October 2027 ... optional in at least one variant" | The same rule after Oct 2027 | |
| 3-star ESC | 4.1: optional to Sept 2025, then as 5 stars | From 1 Oct 2025 the 5-star ESC requirements | |
| Publication years | Tables run October to September | A date on or after 1 October starts the next period | |
| COP head contact with the CRS | Direct evidence, or peak head acceleration ≥ 80 g (Q1.5) / ≥ 96 g (Q3) | Either one; the 3 ms scale applies only with contact | |
| COP head excursion | 4 points ≤ 549 mm, 0 ≥ 550 mm; not estimable: ≤ 549 mm | Linear between 549 and 550 mm (the general sliding scale rule) | |
| Q1.5 in a forward facing CRS | "reduced by 6 points, 4 for head and 2 for neck" | Frontal head and neck set to 0 (they total 6) | |
| ⚠️ Gabarit points | 5.2 awards 2 points but also mentions "the 1 point" for the handbook/airbag requirements f–h; Annexure VIII lists 2 | 1 point for a–e on all seats, 1 more for f–h | |
| Three simultaneous use | Annexure VIII lists 2 points: 5.3.1 (installation list) 1 and 5.3.1.3 (i-Size) 1 | As two separate points | |
| ⚠️ Two-seater stars | 6.1.2.2: the 22-point score "is scaled to be equivalent" to 49; Annexure VIII 4.3 gives 22-point thresholds 20 / 17 / 13 / 9 / 5 | Annexure VIII thresholds (they differ from scaling 41/49 × 22 = 18.4) | |
| CRS installation formula | 3.7.2 image: CRSi = (Ti − Fi) / Ti | As written; reproduces Table 1 (9.143) | |

## Materials (tensile tests)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| Modulus range | ISO 6892-1 leaves the fit range to the laboratory | Linear least squares between 10 and 40 % of Rm on the loading branch | `modulus_window=`, `modulus_stress=` |
| Toe correction | ISO 6892-1: extend the linear part to zero stress | Strain shifted so the fitted line passes the origin; points below the fit range replaced by the origin | `toe=False` |
| Rp0.2 | Stress at 0.2 % non-proportional extension | First crossing with the fitted line moved by 0.2 % strain (keeping its intercept), linear interpolation | `offset=` |
| Ag, A | Plastic extension at maximum force, after fracture | Total strain minus stress / E at the maximum and at the last point | |
| ⚠️ Fracture point | Not defined for digital data | First drop larger than 10 % of Rm between two samples after Rm, or stress below 10 % of Rm | `fracture_drop=`, `cut_fracture=False` |
| Smoothing | Not specified | Savitzky-Golay, quadratic, window given in points; off by default | `smooth=` |
| ReH | ISO 6892-1: stress at the first decrease in force | Running maximum before the first drop of more than 1 % below it (ignoring loading below 10 % of Rm) | `drop=` |
| ReL | Lowest stress during plastic yielding, initial transient ignored | Initial transient = the dip straight after ReH up to the median plateau stress; ignored only when the plateau dips below that median later | |
| ⚠️ End of the Lüders plateau | Start of uniform work hardening (no numerical rule) | Last point from which the stress stays above ReL × 1.02 up to Rm | `band=` |
| Plateau for a card | Not covered | `smooth_luders`: flat at ReL, or the plateau strain removed | `mode=` |
| Mean of several specimens | Not covered | Linear interpolation at equal engineering strain, up to the shortest curve; sample standard deviation | `strain_max=`, `points=` |
| True stress-strain | Constant volume, uniform deformation | `ln(1 + e)`, `s (1 + e)` up to the maximum engineering stress; later points dropped | `true_curve(after_necking=True)` |
| Necking | Considère: `d sigma / d eps = sigma`, i.e. maximum force | Maximum of a parabola fitted over ±1 % engineering strain around the largest stress | `necking_point(window=)` |
| Start of the card curve | `*MAT_024`: first point at zero plastic strain, the yield stress | Rp0.2 point with plastic strain counted from 0.2 % (default), or the end of the linear part | `plastic_curve(start=)` |
| ⚠️ Extrapolation beyond necking | No test data | Law fitted to the measured part (yield to necking); measured points kept, law added beyond with a shift to close the step | `fit_range=`, law choice |
| ⚠️ n-value | ISO 10275 / ASTM E646 define strain measure and range | Log-log least squares of true stress against total true strain, 10 % to Ag by default | `strain=`, `strain_range=` |
| Rate-law fit points | Not defined | Stress ratio to the lowest-rate curve at the yield point and five strains up to 90 % of the smallest necking strain | `strains=`, `reference_rate=` |
| Cowper-Symonds with a slow reference | `*MAT_024` scales the static curve by `1 + (rate/C)^(1/P)` | The reference test's own factor is included in the fit, so C and P refer to a static curve | |
| Johnson-Cook below rate0 | Formula gives a factor below 1 | Factor 1 below the reference rate (usual cut-off) | |
| ⚠️ ln-rate tables | LS-DYNA reads a `*DEFINE_TABLE` as ln(rate) when its first value is negative | `keyword(log_rates=True)` writes ln of the rate in the model's time unit; `check` refuses a first value ≥ 0 | |
| Table curves | Curves follow `*DEFINE_TABLE` directly | Written in ascending rate order with consecutive IDs after the table | `first_curve_id=` |
| SIGY with LCSS | The curve defines the yield stress | SIGY written as the curve's first stress anyway, so both agree | |
| Curve points | LS-DYNA re-discretises curves internally | 50 points by default, geometric spacing (dense near yield), necking point kept, 8 significant digits | `points=` |
| ⚠️ Simple failure strain | Not a protocol; FAIL is a single plastic strain | `uniform + (fracture − uniform) × min(1, neck / element)`; ignores triaxiality | Use GISSMO for predictions |
| Unit system of a card | Not stored in the deck | Guessed from density (500-25 000 kg/m³) and E (500 MPa-1000 GPa) together; none or two plausible: unknown | `unit_system=` |
| ⚠️ Curve re-discretisation | LS-DYNA re-samples curves at LCINT equal intervals (`*CONTROL_SOLUTION`, default 100) | Warning when that changes the curve by more than 1 % | `lcint=` |
| `*DEFINE_CURVE` scaling | Abscissa `SFA a + OFFA`, ordinate `SFO o + OFFO`; SFA, SFO 0 mean 1 | As stated | |
| Table membership | The curves of a `*DEFINE_TABLE` follow it directly | The next N `*DEFINE_CURVE` after the table, N = number of values | |
| Stress lookup | LS-DYNA extrapolates beyond the last point | `Mat024.stress`: last segment extended linearly; tables interpolated in ln(rate), end curves beyond | |
| Single-element stress | Element output | True stress from the reaction force with constant volume, `F (L + u) / (A L)` | |
| ⚠️ Machine compliance | Use an extensometer (strain from cross-head not accepted for E) | Linear machine: strain − stress × (1/E_measured − 1/E) | `correct_compliance(modulus=)` |

## Materials: GISSMO failure

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| Damage | GISSMO: `dD = n D^(1−1/n) dεp / εf(η)`, failure at D = 1 | Integrated exactly along piecewise-linear paths: `D^(1/n) = ∫ dεp / εf` | |
| Instability | F accumulates like D against ECRIT; D_crit is D when F reaches 1 | Same exponent DMGEXP for F | |
| Fading | `σ* = σ (1 − ((D − D_crit) / (1 − D_crit))^FADEXP)` | As stated; DCRIT starts it when ECRIT is 0 | |
| Failure curve fit | Not standardised | Least squares of `ln ∫ dεp / εf` along each test's path, so D = 1 at the measured fracture | `weight=`, `model` |
| ⚠️ Hosford-Coulomb | Marcadet and Mohr: a function of triaxiality and Lode parameter | Plane stress: Lode parameter from the triaxiality (von Mises); exponent n fixed at 0.1 | `hc_exponent=` |
| Stress states | Plane stress, von Mises, proportional loading | `triaxiality_from_strain_ratio`, `plane_stress_strains`, `lode_parameter` | |
| ⚠️ ECRIT below uniaxial tension | An FLC covers uniaxial to equibiaxial tension only | FLC extended with constant values to −1/3 and 2/3 | `extend_to=` |
| ⚠️ Regularisation estimate | Not defined; usually a mesh study of the tensile test | `ε(h) = εn + (εf − εn) min(1, L / h)`, factor relative to the reference size | Your own `RegularizationCurve` |
| LCREGD | Scales the failure strain with element size (DYNAmore / Ansys GISSMO update 2020) | Failure strain only, the same factor at every triaxiality; ECRIT not scaled | |
| ⚠️ SHRF, BIAXF | LS-DYNA: reduction factors of the regularisation in shear (η 0) and biaxial tension (η 2/3); Altair's documentation of the LS-DYNA format calls them triaxiality bounds | Written as given; not modelled in `failure_strain`, `damage` or `check` | |
| LCREGD table | Newer versions: factors per triaxiality and element size | Not written; reported as an unsupported table when read | |
| ⚠️ LCSRS | Positive ID: the rate factor also scales ECRIT, negative: failure strain only; rates read as ln when the first value is negative | `scale_instability_with_rate=`; ln(rate) in the model time unit by default | `log_rates=False` |
| ⚠️ FADEXP blank | Default not stated consistently across documentation | Always written; a blank read as 1 and flagged | |
| DMGEXP blank | Default 1 | Read as 1 and flagged | |
| Failure curve range | LS-DYNA holds the end values beyond a curve | Written from −2/3 to 2/3 with 41 points | `triaxiality_range=`, `points=` |
| Card layout | Cards 1-3 (MID ... LCREGD, INSTF; LCSRS, SHRF, BIAXF, LCDLIM, ...) | First three fields of card 3 written and read; later fields blank (defaults) | |
| Curve IDs | Free | MID + 2000, then steps of 100 | `first_curve_id=` |

## Homologation (UN R94, R95, R135, electrical safety)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| R94 series | 04 series (2021) and 05 series (2025) texts give the same occupant and vehicle limits | Those limits | |
| R94 HPC | Annex 4: maximum over t1..t2, intervals over 36 ms ignored; satisfied without head contact | `calculate_hic(window_ms=36)`; `head_contact=False` passes | |
| R94 neck and femur curves | Figures 1 to 3; R94 does not say cumulative or continuous | Cumulative exceedance (as elsewhere in crashmetrics) | Pass your own `neck_force_criterion` / `femur_force_criterion` result |
| Limit boundaries | "shall not exceed" | A value equal to the limit passes | |
| R95 series | Dummy limits unchanged across the series checked; older texts have 2.0 J and a 30-minute electrolyte period | Dummy limits as in 5.2.1; electrical defaults from R94 05 series | `ElectricalLimits(...)` |
| R95 VC | Transitional period in which VC is recorded only | Always checked | Ignore `vc` if it does not apply |
| R135 lower spine | 75 g except intervals with cumulative duration up to 3 ms | Cumulative 3 ms value of the resultant ≤ 75 g | |
| Electrical: DC+AC buses | 500 Ω/V, or 100 Ω/V if the AC part meets physical protection or ≤ 30 V AC | `ac_part_protected=True` selects 100 Ω/V | |
| Electrical: physical protection | IPXXB and < 0.1 Ω to chassis (and < 0.2 Ω between parts closer than 2.5 m) | IPXXB and the largest chassis resistance < 0.1 Ω | Give the largest measured resistance |
| Not assessed | | A requirement without a value is reported as not assessed and does not count as passed | Check `complete` |
| R137 | Full-width frontal | Dummy limits not included until checked against the regulation text; electrical safety is the same as R94 5.2.8 | |

## Test-versus-CAE correlation (ISO/TS 18571, CC rating)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| ISO/TS 18571 edition | 2014 and 2024 editions; 2024 specifies the time-warping window (10 % of the length) and a nine-point moving average for the slope | 2024 edition; verified against TU Graz's `objective-rating-metrics` (2024) on 40 signal pairs | `ISO18571Parameters(dtw_window=...)` |
| Sampling | ISO/TS 18571 assumes 10 kHz and equal time bases | Both signals linearly resampled to `dt` = 0.1 ms over the common interval | `dt=` |
| Interval of evaluation | User's choice | The common interval of both signals | `t_start=`, `t_end=` |
| Equal correlation at two shifts | ISO: use the smallest shift | Smallest shift; at equal size, the comparison-late shift is found first | |
| Time-warping ties | Not stated | On equal accumulated cost: vertical, then horizontal, then diagonal step (as in TU Graz's implementation) | |
| Grade boundaries | Excellent above 0.94, good above 0.80, fair above 0.58 | A rating exactly at a boundary gets the lower grade (0.94 is good) | Use `rating` directly |
| CC rating defaults | Gehre et al. (2009); settings differ between tools and versions and are often customised | Commonly cited values (D_MIN 0.01, D_MAX 0.12, INT_MIN 0.8, equal phase/size/shape weights, 0.5/0.5 corridor/cross-correlation); not checked against PDB's CORA manual | `CCParameters(...)` |
| CC cross-correlation | Normalised cross-correlation over the shifted overlap | Uncentred `sum(T C) / sqrt(sum T^2 sum C^2)`; size from the signal energies over the same overlap | |
| CC interval and corridors | Some tools offer an automatic interval and standard-deviation corridors | Not implemented: give the interval; corridors from the reference curve | |
| Combining channels | ISO/TS 18571 rates one signal pair | Not combined; the guide suggests the mean and the worst channel | |

## Intrusion measurement

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| Vehicle reference | Protocols measure relative to undeformed body points | Least-squares rigid fit (Kabsch) of three or more reference nodes at every sample; intrusion in the reference's initial axes | Choose the reference nodes; check `reference_fit_error` |
| One reference node | | Translation removed, rotation not (documented error source) | Use three or more nodes |
| Dynamic value | Protocols differ (peak during the event or post-test) | Component with the largest magnitude (signed), largest resultant, largest value along `direction` | Use `displacement` for other definitions |
| Static value | Post-test residual | Last sample, or the mean over the last `static_window_ms` | `static_window_ms=` |
| Directions | Vehicle axes differ between models | Given by the user in the reference's initial axes | `direction=` |
| Measurement points | Defined by each protocol (pedal pad centre, steering wheel hub, A-pillar height) | Your nodes | |

## LS-DYNA energy checks

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| Hourglass limit | LS-DYNA rule of thumb: 10 % of internal energy | 10 % globally and per part | `EnergyLimits(hourglass=..., part_hourglass=...)` |
| Other limits | No standard | Common rules of thumb (ratio 0.95–1.05, contact and damping 5 %, added mass 5 %) | `EnergyLimits(...)` or command-line flags |

## LS-DYNA ASCII readers

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| Contact sides | `slave` / `master` before R13, `SURFA` / `SURFB` after | Both read as `surfa_*` / `surfb_*` (slave = SURFA) | |
| Restarts | A restarted run appends to the file from the restart time | States from the restart time on are replaced by the restarted ones | |
| `sleout` totals | LS-DYNA's printed summary | Kept as printed in `totals`; force transducer contacts are not in them | Sum `data` yourself |
| `spcforc` | A node can appear in several constraint sets | Its forces are added up per state | |
| `swforc` | Trailing columns depend on the weld type | Length, resultant moment and torsion read for spotweld beams, solids and assemblies only; `failure` is 1.0 when printed as `failure` | |
| ⚠️ `rwforc`, `sbtout`, `jntforc`, `rbdout` | No public real file with data was found | Written to the layout of LS-DYNA's l2a converter | Please report a file that is not read correctly |

## Load paths and energy (matsum, secforc)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| Absorbed energy | matsum internal energy per part | Internal energy plus the internal energy of eroded elements, at the end of the run | `include_eroded=False`, `time=` |
| Hourglass | matsum `hgeng` (not part of the internal energy) | Reported as a share of the part's absorbed energy, not added | |
| Section force component | Not defined | Per section the axis with the largest impulse | `component=` |
| ⚠️ Section sign | The section normal decides the sign | Sections whose impulse is negative are reversed, so the main load is positive | `orientation="as_written"` |
| Filtering | SAE J211 classes; none is prescribed for section forces | No filter by default; with `cfc=`, unevenly spaced output resampled at its median step first | `cfc=60` or `180` |
| Impulse, mean force | Not defined | Impulse of the positive force; mean = impulse / time from the first to the last point above 10 % of the peak | `onset=`, `window=` |
| Load split | Design choice, no protocol | Share of the summed impulse of each path's sections; history where the total exceeds 5 % of its peak | `target=`, `tolerance=` |
| ⚠️ Sections in series | They carry the same load | Not detected; give each path one cut. A section in two paths is reported | |
| Crush onset | Not defined | 10 % of the stage's final energy | `onset=` |
| Crush order | Design intent | Violation if a stage starts before the one in front; warning if the one in front has absorbed less than half its energy | `overlap=` |
| Stage not crushed | — | Below 2 % of the chain's energy: left out of the order check | `min_energy=` |
| Culprit parts | Not defined | The fewest parts (largest change first) explaining 80 % of the summed absolute energy change | `explain=` |
| Curve similarity | ISO/TS 18571 rates CAE against test | Used for run against run (baseline as reference) | `rate=False` |
| ⚠️ Synthetic runs | Not LS-DYNA output | A lumped teaching model in the LS-DYNA ASCII layout; the header says so | |

## Spot welds (swforc)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| Failure time | swforc prints `failure` in the failure column from the state a connection has failed | First state with `failure` (or the printed `failure time`, if earlier); so at most one output interval late | Shorter swforc interval |
| Failure criterion | `*CONSTRAINED_SPOTWELD`: `(fn/Sn)^n + (fs/Ss)^m ≥ 1` | `WeldLimits`, n = m = 2 by default | `n=`, `m=` |
| ⚠️ Axial compression | The criterion is written with the normal force | Only tension counts | `compression=True` |
| ⚠️ Limits | Not in swforc | Given by the user; none: no utilisation | `limits=` |
| ⚠️ Other failure models | `*MAT_SPOTWELD` can fail on stress, resultants with moments or damage | Failures are found from the file; the force criterion is only a comparison; moments and torsion are not used | |
| Utilisation | Not defined | 1 / the factor by which both forces can grow until the criterion is met | |
| File's failure measure | Some weld materials print a value between 0 and 1 | Used as utilisation when no limits are given | |
| Forces before failure | — | The last output state before the failure state | |
| Burst (unzipping) | Not defined | 3 or more welds of a group, each within 1 ms of the one before | `burst_size=`, `burst_window=` |
| Earlier / later failure | Not defined | Failure time moved by more than 0.5 ms | `time_tolerance=` |
| Groups | swforc has no titles | Name → IDs from the user, or from the numbering | `groups_by_id(divisor=)` |
| ⚠️ Synthetic welds | Not LS-DYNA output | A teaching model: shear share of the path force, peel with folding, partial load redistribution, strength loss of the part | |

## Model quality check sheet

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| ⚠️ Limits | No standard; team rules differ | Common rules of thumb as defaults | `QualityLimits`, `EnergyLimits` |
| Verdict | — | Passed when no check fails; advisory checks only warn; skipped checks do not fail | |
| End time | d3hsp `Problem time` against the termination time | ≥ 99.5 %; the last glstat time if d3hsp has no problem time | `end_time=` |
| Total mass, centre of gravity | d3hsp mass summary (the lines after the total mass) | Against the targets given; reported only without targets | `mass_tolerance=`, `cg_tolerance=` |
| Added mass | glstat `added mass` and `percentage increase` | The printed percentage; without it, added mass over the d3hsp total mass | `added_mass=` |
| Added mass growth | Not defined | Peak minus the first value, % points (advisory) | `added_mass_growth=` |
| Added mass per part | matsum added mass, d3hsp part masses | Peak added mass over the part's mass | `part_added_mass=` |
| Time step drop | glstat `time step` | Lowest against the first value (advisory) | `timestep_drop=` |
| ⚠️ Mass-scaled time step | `dt2ms`, negative: only where needed | `|dt2ms|` times the time step scale factor for negative values | |
| Element mass factor | Not defined | `(time step / smallest element time step)²` (advisory) | `element_mass_factor=` |
| Energy checks | See LS-DYNA energy checks | The same checks; the added mass one is replaced by the two above | `energy=` |
| Contact energy | sleout slave and master side energies | Their sum per contact; its lowest value against the peak internal energy of glstat | `contact_negative=` |
| ⚠️ Synthetic quality data | Not LS-DYNA output | `ModelQuality` sets what is written; it does not change the crash | |

## Found something else?

If a protocol you use reads differently, or a newer version changes a
value, please open an issue on
[GitHub](https://github.com/vsk1729/crashmetrics/issues) with the
document, version and section.
