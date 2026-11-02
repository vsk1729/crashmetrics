"""Example 28: check, convert, compare, verify and store *MAT_024 cards.

A supplier sends a deck in mm-s-t with three DP600 cards; one has a unit
mix-up, one a rate table whose curves cross. The steps:

1. Read the cards and check them.
2. Convert the good card to mm-ms-kg.
3. Compare it with our own card.
4. Write a single-element tension test to verify a card in LS-DYNA, and
   compare its result with the card (the LS-DYNA output is replaced here
   by the exact response of the card, as no solver runs in this example).
5. Summary table, and the cards stored in a material library with their
   provenance.
"""

import datetime as dt
from pathlib import Path

import numpy as np

from crashmetrics.materials import (
    HardeningCurve,
    Mat024,
    MaterialLibrary,
    card_summary,
    check_keyword,
    compare_cards,
    compare_tension,
    convert_keyword,
    read_keyword,
    single_element_deck,
    summary_markdown,
)

SUPPLIER = """*KEYWORD
$ Supplier deck, units mm-s-t
*MAT_PIECEWISE_LINEAR_PLASTICITY_TITLE
DP600 supplier
$#     mid        ro         e        pr      sigy      etan      fail      tdel
       101   7.85e-9  210000.0       0.3     380.0       0.0       0.0       0.0
      40.0       5.0       201         0       0.0
       0.0       0.0       0.0       0.0       0.0       0.0       0.0       0.0
       0.0       0.0       0.0       0.0       0.0       0.0       0.0       0.0
*DEFINE_CURVE
201,0,1.0,1.0
0.000,380.0
0.005,440.0
0.020,520.0
0.050,590.0
0.100,650.0
0.200,710.0
0.400,770.0
0.700,820.0
1.000,855.0
*MAT_PIECEWISE_LINEAR_PLASTICITY_TITLE
DP600 copied from an mm-ms-kg deck
       102   7.85e-6  210000.0       0.3     380.0
       0.0       0.0       201         0       0.0
*MAT_PIECEWISE_LINEAR_PLASTICITY_TITLE
DP600 rate table
       103   7.85e-9  210000.0       0.3     380.0
       0.0       0.0       300         0       1.0
*DEFINE_TABLE
300
-6.9
0.0
4.6
*DEFINE_CURVE
301
0.0,380.0
0.2,710.0
1.0,855.0
*DEFINE_CURVE
302
0.0,440.0
0.2,780.0
1.0,920.0
*DEFINE_CURVE
303
0.0,520.0
0.2,850.0
1.0,900.0
*END
"""
Path("supplier.k").write_text(SUPPLIER)

# --- 1. Read and check -------------------------------------------------------------
deck = read_keyword("supplier.k")
print(f"Read {len(deck.materials)} *MAT_024 cards, {len(deck.curves)} curves, "
      f"{len(deck.tables)} table")
for result in check_keyword(deck):
    print(result.summary())

# --- 2. Convert the good card to mm-ms-kg -----------------------------------------
text = convert_keyword(deck, "mm-ms-kg", mids=[101])
print()
print("MID 101 in mm-ms-kg:")
print("\n".join(text.splitlines()[:6]))

# --- 3. Compare with our own card --------------------------------------------------
p = np.concatenate(([0.0], np.geomspace(1e-3, 1.0, 40)))
ours = Mat024(mid=600, density=7850.0, modulus=210_000.0,
              curve=HardeningCurve(p, 0.6 * 980.0 * (0.004 + p) ** 0.17 + 0.4 * (
                  370.0 + 290.0 * (1 - np.exp(-16.0 * p))), 210_000.0, 0.13),
              c=40.4, p=5.0, title="DP600 ours",
              provenance={"tests": "DP600-L1..L3", "hardening": "Swift-Voce"})
supplier = deck.material(101)
print()
print(compare_cards(supplier, ours, strains=(0.0, 0.05, 0.2, 0.5, 1.0),
                    rates=(None, 100.0), names=("supplier", "ours")).summary())

# --- 4. Single-element verification --------------------------------------------------
deck_text = single_element_deck(ours, "mm-ms-kg", strain=0.6, rate=1.0)
Path("single_element.k").write_text(deck_text)
print()
print(f"single_element.k: {len(deck_text.splitlines())} lines; run it, then "
      "verify_single_element(run_dir, ours, 'mm-ms-kg')")
ep = np.linspace(0.0, 0.55, 120)              # stand-in for the LS-DYNA result
sig = ours.stress(ep)
u = np.expm1(ep + sig / ours.modulus)
print(compare_tension(u, sig / (1.0 + u), ours).summary())
print(compare_tension(u, 1.03 * sig / (1.0 + u), ours).summary(),
      "(a 3 % stiffer response)")

# --- 5. Summary and library ----------------------------------------------------------
print()
print(summary_markdown(card_summary([supplier, ours], strains=(0.05, 0.5))))
lib = MaterialLibrary("materials")
lib.save(ours, "dp600_ours", overwrite=True, date=dt.date(2026, 11, 2),
         note="validated in 1-element")
lib.save(supplier, "dp600_supplier", overwrite=True, date=dt.date(2026, 11, 2),
         note="as received")
print()
print(f"Library: {lib.names()}; dp600_ours saved {lib.info('dp600_ours')['saved']}, "
      f"provenance {lib.info('dp600_ours')['provenance']}")
lib.export("dp600_ours", "dp600_ours_mm-s-t.k", "mm-s-t", date=dt.date(2026, 11, 2))
print("Exported dp600_ours in mm-s-t:",
      read_keyword("dp600_ours_mm-s-t.k").materials[600].e, "MPa")
