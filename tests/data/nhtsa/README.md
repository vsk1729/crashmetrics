# NHTSA crash test signals

Vehicle acceleration channels of two physical crash tests from the
NHTSA Vehicle Crash Test Database
(<https://www.nhtsa.gov/research-data/research-testing-databases>),
used to test `crashmetrics.pulse` and `crashmetrics.signals` on real
test data.

## Source and terms

- Unchanged copies of `data/nhtsa/` in
  [osullivryan/crushrs](https://github.com/osullivryan/crushrs), commit
  `6eb7e78328511457254aaf523ac9a56ba899fb74`, MIT licence (see
  `LICENSE`, Copyright (c) 2026 Ryan O'Sullivan). That repository gives
  the NHTSA download location of each file as
  `https://nrd-static.nhtsa.dot.gov/tsv/vehdb/...` and the test
  details below.
- NHTSA's terms of use (<https://www.nhtsa.gov/about-nhtsa/terms-use>)
  state: "Information presented on this web site is considered public
  information and may be distributed or copied."

## Files

Format: `time [s] <TAB> acceleration [g]`, 12.5 kHz, time 0 at first
contact, as measured (unfiltered).

| File | Test | Vehicle and test | Channel |
| --- | --- | --- | --- |
| `v02320tsv.078` | 2320 | 1996 Dodge Neon, NCAP full frontal rigid barrier, 56.5 km/h, 1354 kg | Seat, left rear, X |
| `v04429tsv.179`, `.182` | 4429 | 1999 Lincoln Navigator (2873 kg), head-on into a 1996 Dodge Neon, 48.5 km/h each, 0 % offset | Sill, left and right rear, X |
| `v04429tsv.089`, `.092` | 4429 | 1996 Dodge Neon (1378 kg) of the same test | Sill, left and right rear, X |

The test speeds and masses are as given in the source repository; they
were not checked against the NHTSA database here.

## What the tests check (`tests/test_nhtsa.py`)

- Test 2320: with CFC 60, the peak deceleration, the maximum dynamic
  crush, its time and the restitution agree with the values the source
  repository reports for this measured pulse (35.2 g, 740 mm at 78 ms,
  0.163), computed there with its own code. crashmetrics gives 35.2 g,
  740 mm, 78 ms and 0.162.
- Test 4429: the velocity changes of the two vehicles satisfy momentum
  conservation (their ratio is the inverse of the mass ratio) within
  10 %, and both vehicles end with the common velocity of a plastic
  impact within 1 m/s.

NHTSA is not affiliated with this project and does not endorse it.
