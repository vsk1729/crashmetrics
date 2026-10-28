from importlib.metadata import version

import crashmetrics


def test_installed_version_matches_package_version():
    """pyproject.toml reads the version from crashmetrics.__version__."""
    assert version("crashmetrics") == crashmetrics.__version__


def test_citation_version_matches_package_version():
    """CITATION.cff must be updated with every release."""
    import re
    from pathlib import Path

    citation = Path(__file__).resolve().parents[1] / "CITATION.cff"
    match = re.search(r'^version: "([^"]+)"', citation.read_text(), re.M)
    assert match is not None
    assert match.group(1) == crashmetrics.__version__
