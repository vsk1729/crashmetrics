"""Run every example and compare its output with examples/expected/.

The documentation shows these outputs, so this keeps the docs correct.
After an intended change, regenerate the files with

    CRASHMETRICS_UPDATE_EXAMPLES=1 python -m pytest tests/test_examples.py
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
NUMBERED = sorted(EXAMPLES.glob("[0-9][0-9]_*.py"))
UPDATE = os.environ.get("CRASHMETRICS_UPDATE_EXAMPLES") == "1"


def _run(script: Path, cwd: Path) -> str:
    result = subprocess.run(
        [sys.executable, str(script)], cwd=cwd, capture_output=True, text=True,
        check=False, timeout=300,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_examples_are_found():
    assert len(NUMBERED) >= 10


@pytest.mark.parametrize("script", NUMBERED, ids=lambda p: p.stem)
def test_example_output(script, tmp_path):
    output = _run(script, tmp_path)
    expected = EXAMPLES / "expected" / f"{script.stem}.txt"
    if UPDATE:
        expected.write_text(output)
    assert output == expected.read_text()


def test_hic_convergence_runs(tmp_path):
    # Prints run times, so only check that it runs.
    assert "HIC numerical convergence study" in _run(
        EXAMPLES / "hic_convergence.py", tmp_path)
