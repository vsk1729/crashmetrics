"""Write a shields.io endpoint badge for the test coverage.

    python -m pytest --cov=crashmetrics --cov-report=json:coverage.json
    python tools/coverage_badge.py coverage.json docs/coverage.json

The badge JSON is published with the documentation site, and the README
badge reads it through https://img.shields.io/endpoint.
"""

import json
import sys
from pathlib import Path


def badge(percent: float) -> dict[str, object]:
    color = ("brightgreen" if percent >= 90 else "green" if percent >= 80
             else "yellow" if percent >= 70 else "orange" if percent >= 60 else "red")
    return {"schemaVersion": 1, "label": "coverage",
            "message": f"{percent:.0f}%", "color": color}


def main(argv: list[str]) -> int:
    source, target = Path(argv[0]), Path(argv[1])
    percent = float(json.loads(source.read_text())["totals"]["percent_covered"])
    totals = json.loads(source.read_text())["totals"]
    target.write_text(json.dumps(badge(percent)) + "\n")
    print(f"### Test coverage: {percent:.1f} % ({totals['covered_lines']} of "
          f"{totals['num_statements']} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
