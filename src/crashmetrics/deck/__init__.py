"""LS-DYNA keyword decks: read, check, summarise and edit, before a run.

1. **Read** (`read_deck`): every file of a deck through ``*INCLUDE``,
   ``*INCLUDE_PATH`` and ``*INCLUDE_TRANSFORM``, with ``*PARAMETER``
   values and expressions, in fixed, long and comma formats. Every line is
   kept, so a deck written back is identical except where it was edited.
   Typed values of any described keyword: `Deck.records`. Version
   information: `Deck.info`.
2. **Model tables** (`model_summary`, `time_steps`): every part with its
   elements, section, thickness, material, density, mass and centre of
   gravity; the total mass and centre; estimated element time steps and
   the mass that mass scaling would add.
3. **Checks** (`check_deck`): missing includes and parameters, duplicate
   IDs (also between include files), references to undefined IDs, parts
   without elements, thickness or density, degenerate elements, free
   nodes, parts in no contact, spot welds without a tied contact, unused
   definitions.
4. **Load case** (`load_case`, `output_requirements`): termination, time
   step, energy settings, initial velocities, walls, motions, gravity,
   contacts, outputs; whether the outputs give what crashmetrics'
   analyses read (model quality, load paths, spot welds, node channels).
5. **Edit** (`set_parameter`, `set_thickness`, `set_material`,
   `set_end_time`, `set_output`, `prepare_outputs` ...) and write DOE
   variants (`write_variants`).

The layouts are written from the keyword file format itself; keywords
without a layout are kept, listed (`DeckInfo.unknown`) and written back
unchanged.
"""

from crashmetrics.deck.bulk import curves, elements, mass_elements, nodes, sets
from crashmetrics.deck.checks import DeckCheck, DeckSheet, check_deck
from crashmetrics.deck.edit import (
    add_history_nodes,
    part_card,
    prepare_outputs,
    set_end_time,
    set_initial_velocity,
    set_mass_scaling,
    set_material,
    set_output,
    set_parameter,
    set_section,
    set_thickness,
    write_variants,
)
from crashmetrics.deck.loadcase import (
    ANALYSES,
    LoadCase,
    Output,
    load_case,
    output_requirements,
)
from crashmetrics.deck.model import (
    UNIT_SYSTEMS,
    ModelSummary,
    PartInfo,
    TimeStepEstimate,
    guess_units,
    model_summary,
    time_steps,
)
from crashmetrics.deck.reader import (
    Block,
    Deck,
    DeckFile,
    DeckInfo,
    IncludeTransform,
    Parameter,
    parse_deck,
    read_deck,
)

__all__ = [
    "ANALYSES",
    "UNIT_SYSTEMS",
    "Block",
    "Deck",
    "DeckCheck",
    "DeckFile",
    "DeckInfo",
    "DeckSheet",
    "IncludeTransform",
    "LoadCase",
    "ModelSummary",
    "Output",
    "Parameter",
    "PartInfo",
    "TimeStepEstimate",
    "add_history_nodes",
    "check_deck",
    "curves",
    "elements",
    "guess_units",
    "load_case",
    "main",
    "mass_elements",
    "model_summary",
    "nodes",
    "output_requirements",
    "parse_deck",
    "part_card",
    "prepare_outputs",
    "read_deck",
    "set_end_time",
    "set_initial_velocity",
    "set_mass_scaling",
    "set_material",
    "set_output",
    "set_parameter",
    "set_section",
    "set_thickness",
    "sets",
    "time_steps",
    "write_variants",
]


def main(argv: list[str] | None = None) -> int:
    """``crashmetrics-deck MAIN.k``: model summary, checks, load case and
    output requirements of a deck. Exit code 1 if a check fails."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="crashmetrics-deck",
        description="Check an LS-DYNA keyword deck before running it.",
    )
    parser.add_argument("deck", help="main keyword file")
    parser.add_argument(
        "--units",
        choices=list(UNIT_SYSTEMS),
        default=None,
        help="unit system (guessed from the materials if not given)",
    )
    parser.add_argument(
        "--analyses",
        default=",".join(ANALYSES),
        help=f"outputs to check for, comma separated ({', '.join(ANALYSES)})",
    )
    parser.add_argument(
        "--parts", type=int, default=15, help="parts to list (heaviest first)"
    )
    parser.add_argument(
        "--csv", default=None, help="write the part table to this CSV file"
    )
    args = parser.parse_args(argv)
    deck = read_deck(args.deck)
    print(deck.info.summary())
    print()
    summary = model_summary(deck, args.units)
    print(summary.summary())
    print(summary.table(top=args.parts))
    if args.csv:
        summary.to_csv(args.csv)
    print()
    sheet = check_deck(deck, unit_system=args.units)
    print(sheet.summary())
    print()
    print(load_case(deck, args.units).summary())
    print()
    analyses = [a.strip() for a in args.analyses.split(",") if a.strip()]
    outputs = output_requirements(deck, analyses, unit_system=args.units)
    print(outputs.summary())
    return 0 if sheet.passed else 1
