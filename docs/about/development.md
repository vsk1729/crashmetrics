# Development and releases

## Set up

```bash
git clone https://github.com/vsk1729/crashmetrics.git
cd crashmetrics
python -m pip install -e ".[dev,docs]"
```

## Checks (the same as CI)

```bash
python -m pytest      # tests, including every example's output
ruff check .          # lint
mypy                  # type check
mkdocs build --strict # documentation
```

## Examples and their expected output

Each numbered script in `examples/` has its expected output in
`examples/expected/`, and `tests/test_examples.py` checks it. The
documentation includes both files directly, so they cannot drift apart.
After an intended change to an example or to a result, regenerate the
expected files and review the difference:

```bash
CRASHMETRICS_UPDATE_EXAMPLES=1 python -m pytest tests/test_examples.py
git diff examples/expected
```

## Documentation

The site is built with MkDocs Material; the API reference is generated
from the NumPy-style docstrings with mkdocstrings.

```bash
mkdocs serve          # live preview at http://127.0.0.1:8000
```

The **Docs** workflow builds the site on every pull request (strict mode,
so broken links and docstring problems fail the build) and publishes it
to GitHub Pages when `main` changes.

## Releasing

Releases are published by `.github/workflows/release.yml` with PyPI
Trusted Publishing, so no API tokens are stored in the repository.

1. Bump `__version__` in `src/crashmetrics/__init__.py` and add the
   CHANGELOG entry; merge to `main`.
2. Optional dry run: run the **Release** workflow manually from the
   Actions tab to publish to TestPyPI.
3. Publish a GitHub release with tag `v<version>` (for example
   `v0.10.0`) on `main`. The workflow checks that the tag matches
   `__version__`, builds and checks the sdist and wheel, and publishes to
   PyPI.

A version can be uploaded to PyPI only once; fix mistakes with a new
version.
