# Installation

## Requirements

- Python 3.10 or later
- NumPy 1.24 or later (installed automatically)

crashmetrics has no other required dependencies. It runs on Windows,
Linux and macOS.

## Install from PyPI

```bash
python -m pip install crashmetrics
```

Check the installed version:

```bash
python -c "import crashmetrics; print(crashmetrics.__version__)"
```

Upgrade to the newest release:

```bash
python -m pip install --upgrade crashmetrics
```

## Install in a virtual environment (recommended)

Keeping each project in its own environment avoids version clashes with
other tools.

=== "Windows"

    ```bat
    python -m venv .venv
    .venv\Scripts\activate
    python -m pip install crashmetrics
    ```

=== "Linux / macOS"

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install crashmetrics
    ```

## Behind a company proxy

If `pip` cannot reach PyPI, pass your proxy, or ask IT for the internal
package mirror:

```bash
python -m pip install --proxy http://user:password@proxy.company.com:8080 crashmetrics
python -m pip install --index-url https://your-mirror/simple crashmetrics
```

## Latest development version

To try changes that are merged but not yet released:

```bash
python -m pip install "git+https://github.com/vsk1729/crashmetrics.git"
```

## Optional tools for the guides

The guides use only NumPy. For tables and plots, these are handy:

```bash
python -m pip install pandas matplotlib openpyxl
```

## Run the examples

The repository has fourteen runnable examples with synthetic data:

```bash
git clone https://github.com/vsk1729/crashmetrics.git
cd crashmetrics
python examples/01_signals_hic.py
```

Next: [your first calculation](first-calculation.md).
