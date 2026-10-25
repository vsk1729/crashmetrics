from importlib.metadata import version

import crashmetrics


def test_installed_version_matches_package_version():
    """pyproject.toml reads the version from crashmetrics.__version__."""
    assert version("crashmetrics") == crashmetrics.__version__
