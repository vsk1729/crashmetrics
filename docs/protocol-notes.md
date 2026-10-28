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
| HIC integration | Definition only | Trapezoidal rule on a 0.1 ms refined grid; warning if the record is shorter than the window | `calculate_hic(..., resolution_ms=...)` |
| 3 ms clip | Euro NCAP: cumulative | Cumulative by default | `clip_3ms(..., mode="continuous")` |
| UN R94 neck and femur durations | R94 does not say cumulative or continuous | Cumulative | `mode="continuous"` |
| R94 femur limit | R94: 9.07 kN at 0 ms, 7.58 kN at ≥ 10 ms; Euro NCAP / AIS-197 print 7.56 kN | `"r94_hybrid3_50"` uses 7.58 kN; Bharat NCAP scoring uses 7.56 kN | Pass your own `limit` points |

## Pedestrian: headform (Euro NCAP)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| A-pillar rewards (2026) | VRU Impacts v1.1 gives the rewards, not how they add to the grid | Added to the grid points; the maximum stays the number of grid points | Score A-pillar points yourself and pass them as labels |
| Correction factor outside 0.85–1.15 | Prediction is reviewed with Euro NCAP | Factor still applied; `correction.accepted` is `False` | Check `accepted` |
| Verification tolerance | Tabulated ranges | Uses the protocols' table exactly (e.g. green < 722.22) | |

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

## Bharat NCAP (AIS-197)

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| ⚠️ Neck exceedance | Annex IV §3.1.2.2 says "continuous", §3.2.2 note says "cumulative exceedance plots" | Cumulative (as in Global NCAP) | `score_frontal` always uses cumulative; check a curve yourself with `curve_points(..., mode="continuous")` |
| ⚠️ T12 modifier lower bound | Annex VII §3.3 text: 1.5 kN; its limits table: 1.0 kN | 1.5 kN (text) | Compute the penalty yourself |
| 35 % front / side rule | "difference of scores above 35 %" | 35 % of the 16-point test maximum | |
| Capping | "exceeding a capping limit" | Strictly above the lower (capping) limit; a value exactly at it scores 0 and triggers the 1-star cap | |
| Region floor | Not stated | Region scores do not go below 0 | |
| Side head assessment | No hard-contact rule stated for the side test | HIC15 and 3 ms limits always applied | |
| Steering column modifier | Listed under the head (Annex VII §2.1.5) | Applied to the driver's head | Put it under another region in `modifiers` |
| Safety assist qualifiers | ESC, side head protection fitment by year, pedestrian (AIS-100), SBR (AIS-145) | Not evaluated; pass the result as `max_stars_allowed` | `aop_rating(..., max_stars_allowed=)` |
| Pole test | Required (with side head protection) for 3+ stars | `pole_test_passed` checks it; its effect on stars is set through `max_stars_allowed` | |

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

## LS-DYNA energy checks

| Topic | Source | crashmetrics | Change it |
| --- | --- | --- | --- |
| Hourglass limit | LS-DYNA rule of thumb: 10 % of internal energy | 10 % globally and per part | `EnergyLimits(hourglass=..., part_hourglass=...)` |
| Other limits | No standard | Common rules of thumb (ratio 0.95–1.05, contact and damping 5 %, added mass 5 %) | `EnergyLimits(...)` or command-line flags |

## Found something else?

If a protocol you use reads differently, or a newer version changes a
value, please open an issue on
[GitHub](https://github.com/vsk1729/crashmetrics/issues) with the
document, version and section.
