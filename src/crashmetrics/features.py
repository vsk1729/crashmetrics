"""Feature extraction for analytics and machine learning.

Turns crash signals and crashmetrics results into flat rows of numbers,
one row per run, ready for a CSV file, a pandas DataFrame or a
scikit-learn model. Only NumPy is needed; pandas is used if installed.

Functions:

- `signal_features`: Shape features of any 1D signal (peaks, timing,
  impulse, pulse width, energy centroid, frequency content).
- `head_features`: HIC15, HIC36, 3 ms clip, peak and the Euro NCAP
  headform colour of a resultant head acceleration, plus its shape.
- `pulse_features`: OLC, delta-V, rebound, dynamic crush and the shape
  of a vehicle crash pulse.
- `flatten`: Any result object (dataclass, dict, nested scores) as a
  flat dict of numbers and labels.
- `feature_table`: Run an extractor over many runs, one row per run;
  a failing run gives an `error` column instead of stopping the batch.
- `write_csv`, `to_dataframe`, `to_matrix`: Hand the table to a CSV
  file, pandas, or NumPy arrays for model training.

Conventions:

- Time is in seconds on input; times in feature names ending in `_ms`
  are milliseconds from the first sample.
- Amplitude features keep the input unit (g, N, mm ...).
- Features that cannot be defined for a signal (for example the rise
  time of an all-zero signal) are `nan`, so every row has the same
  columns.
"""

from __future__ import annotations

import csv
import dataclasses
import importlib
import math
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics.acceleration import _validate, clip_3ms, exceedance_duration, peak
from crashmetrics.pedestrian.headform import hic_colour
from crashmetrics.pedestrian.hic import calculate_hic
from crashmetrics.pulse import olc, pulse_summary

__all__ = [
    "feature_table",
    "flatten",
    "head_features",
    "pulse_features",
    "signal_features",
    "to_dataframe",
    "to_matrix",
    "write_csv",
]

Value = float | int | str | bool | None
"""A cell of a feature row."""

NAN = float("nan")

# np.trapezoid is NumPy 2; np.trapz is its NumPy 1 name.
_trapz: Callable[..., Any] = getattr(np, "trapezoid", None) or getattr(np, "trapz")


# --- Signal shape -------------------------------------------------------------


def _key(prefix: str, name: str) -> str:
    return f"{prefix}{name}"


def _first_crossing(t: NDArray, x: NDArray, level: float, stop: int) -> float:
    """First time (interpolated) at which ``x`` reaches ``level`` in
    ``x[:stop + 1]``; nan if it never does."""
    above = np.nonzero(x[: stop + 1] >= level)[0]
    if above.size == 0:
        return NAN
    i = int(above[0])
    if i == 0:
        return float(t[0])
    x0, x1 = x[i - 1], x[i]
    return float(t[i - 1] + (level - x0) / (x1 - x0) * (t[i] - t[i - 1]))


def _spectrum(t: NDArray, x: NDArray) -> tuple[float, float]:
    """Dominant frequency and spectral centroid in Hz, on a uniform grid."""
    dt = float(np.median(np.diff(t)))
    n = int(round((t[-1] - t[0]) / dt)) + 1
    if n < 8:
        return NAN, NAN
    grid = t[0] + dt * np.arange(n)
    y = np.interp(grid, t, x)
    y = y - y.mean()
    power = np.abs(np.fft.rfft(y * np.hanning(n))) ** 2
    freq = np.fft.rfftfreq(n, dt)
    power[0] = 0.0
    total = power.sum()
    if total <= 0:
        return NAN, NAN
    return float(freq[int(np.argmax(power))]), float((freq * power).sum() / total)


def signal_features(
    time: ArrayLike,
    signal: ArrayLike,
    prefix: str = "",
    spectrum: bool = True,
) -> dict[str, float]:
    """Return shape features of a 1D signal.

    Parameters
    ----------
    time:
        1D time array in s, strictly increasing.
    signal:
        Signal of the same length, in any unit.
    prefix:
        Text put in front of every feature name, e.g. ``"head_"``.
    spectrum:
        Include the frequency features (needs a resampling and an FFT).

    Returns
    -------
    dict
        Features, in the signal's unit unless named otherwise:

        - `max`, `min`, `peak_abs`: largest, smallest and largest
          absolute value.
        - `t_max_ms`, `t_min_ms`, `t_peak_abs_ms`: their times.
        - `mean`, `rms`, `std`.
        - `integral`, `abs_integral`: area under the signal and under its
          magnitude (unit x s; for an acceleration in m/s^2 the
          integral is the velocity change).
        - `onset_ms`, `end_ms`, `active_ms`: first and last time the
          magnitude is at least 5 % of `peak_abs`, and the time between.
        - `rise_ms`: time from 10 % to 90 % of `peak_abs` before the
          peak.
        - `width50_ms`: total time at or above 50 % of `peak_abs`.
        - `excursions50`: number of separate excursions above 50 % of
          `peak_abs` (1 for a single pulse, more for multiple impacts).
        - `centroid_ms`: time centroid of the signal energy (x^2).
        - `energy50_ms`: time at which half of the signal energy has
          accumulated.
        - `dominant_hz`, `spectral_centroid_hz`: frequency of the
          largest spectral peak and the power-weighted mean frequency
          (if `spectrum` is True).

    Notes
    -----
    Timing and width features use the magnitude ``|signal|``, so they do
    not depend on the sign convention of the channel. Times are measured
    from the first sample.
    """
    t, x = _validate(time, signal)
    t0 = float(t[0])
    mag = np.abs(x)
    i_abs = int(np.argmax(mag))
    peak_abs = float(mag[i_abs])

    out: dict[str, float] = {
        "max": float(x.max()),
        "min": float(x.min()),
        "peak_abs": peak_abs,
        "t_max_ms": (float(t[int(np.argmax(x))]) - t0) * 1000.0,
        "t_min_ms": (float(t[int(np.argmin(x))]) - t0) * 1000.0,
        "t_peak_abs_ms": (float(t[i_abs]) - t0) * 1000.0,
        "mean": float(_trapz(x, t) / (t[-1] - t0)),
    }
    sq = float(_trapz(x * x, t))
    out["rms"] = float(math.sqrt(sq / (t[-1] - t0)))
    out["std"] = float(math.sqrt(max(out["rms"] ** 2 - out["mean"] ** 2, 0.0)))
    out["integral"] = float(_trapz(x, t))
    out["abs_integral"] = float(_trapz(mag, t))

    if peak_abs > 0:
        active = np.nonzero(mag >= 0.05 * peak_abs)[0]
        onset, end = float(t[active[0]]) - t0, float(t[active[-1]]) - t0
        t10 = _first_crossing(t, mag, 0.1 * peak_abs, i_abs)
        t90 = _first_crossing(t, mag, 0.9 * peak_abs, i_abs)
        above = mag >= 0.5 * peak_abs
        rises = int(above[0]) + int(np.count_nonzero(above[1:] & ~above[:-1]))
        energy = np.concatenate([[0.0], np.cumsum(np.diff(t) * 0.5 * (
            x[1:] ** 2 + x[:-1] ** 2))])
        out.update({
            "onset_ms": onset * 1000.0,
            "end_ms": end * 1000.0,
            "active_ms": (end - onset) * 1000.0,
            "rise_ms": (t90 - t10) * 1000.0,
            "width50_ms": exceedance_duration(t, mag, 0.5 * peak_abs),
            "excursions50": float(rises),
            "centroid_ms": (float(_trapz(t * x * x, t) / sq) - t0) * 1000.0,
            "energy50_ms": (float(np.interp(0.5 * energy[-1], energy, t)) - t0)
            * 1000.0,
        })
    else:
        for name in ("onset_ms", "end_ms", "active_ms", "rise_ms", "width50_ms"):
            out[name] = NAN
        out["excursions50"] = 0.0
        out["centroid_ms"] = out["energy50_ms"] = NAN

    if spectrum:
        dominant, centroid = _spectrum(t, x)
        out["dominant_hz"] = dominant
        out["spectral_centroid_hz"] = centroid

    return {_key(prefix, k): v for k, v in out.items()}


# --- Load-case extractors ----------------------------------------------------


def head_features(
    time: ArrayLike,
    acceleration: ArrayLike,
    prefix: str = "head_",
    shape: bool = True,
) -> dict[str, Value]:
    """Return head injury criteria and shape features.

    Parameters
    ----------
    time:
        1D time array in s.
    acceleration:
        Resultant head (or headform) acceleration in g, already filtered
        (CFC 1000).
    prefix:
        Text put in front of every feature name.
    shape:
        Also include `signal_features` of the acceleration.

    Returns
    -------
    dict
        `hic15`, `hic15_t1_ms`, `hic15_t2_ms`, `hic36` (nan if the record
        is shorter than 36 ms), `a3ms`, `peak_g`,
        `t_peak_ms` and `colour` (the Euro NCAP headform colour of
        HIC15, a label for classification), followed by the shape
        features.
    """
    t, a = _validate(time, acceleration)
    hic15 = calculate_hic(t, a, window_ms=15.0)
    # HIC36 only if the record covers the window (no warning per run).
    hic36 = (
        calculate_hic(t, a, window_ms=36.0).value
        if t[-1] - t[0] >= 0.036
        else NAN
    )
    p = peak(t, a)
    out: dict[str, Value] = {
        "hic15": hic15.value,
        "hic15_t1_ms": float(hic15.start_time - t[0]) * 1000.0,
        "hic15_t2_ms": float(hic15.end_time - t[0]) * 1000.0,
        "hic36": hic36,
        "a3ms": clip_3ms(t, a),
        "peak_g": p.value,
        "t_peak_ms": float(p.time - t[0]) * 1000.0,
        "colour": hic_colour(hic15.value),
    }
    if shape:
        out.update(signal_features(t, a))
        for key in ("max", "peak_abs", "t_max_ms", "t_peak_abs_ms"):
            out.pop(key)  # the same as peak_g and t_peak_ms
    return {_key(prefix, k): v for k, v in out.items()}


def pulse_features(
    time: ArrayLike,
    acceleration: ArrayLike,
    v0: float,
    prefix: str = "pulse_",
    shape: bool = True,
) -> dict[str, Value]:
    """Return crash pulse metrics and shape features.

    Parameters
    ----------
    time:
        1D time array in s, starting at T0.
    acceleration:
        Vehicle longitudinal acceleration in m/s^2 (negative when
        decelerating), filtered (CFC 60 or 180).
    v0:
        Impact velocity in m/s.
    prefix:
        Text put in front of every feature name.
    shape:
        Also include `signal_features` of the acceleration in g.

    Returns
    -------
    dict
        `olc_g`, `delta_v`, `rebound_velocity`, `restitution`,
        `max_crush_mm`, `t_max_crush_ms`, `t_zero_velocity_ms`,
        `peak_decel_g` and `mean_decel_g`, followed by the shape features
        of the acceleration in g.
    """
    t, a = _validate(time, acceleration)
    s = pulse_summary(t, a, v0=v0)
    g = 9.81
    out: dict[str, Value] = {
        "olc_g": olc(t, a, v0=v0).value,
        "delta_v": s.delta_v,
        "rebound_velocity": s.rebound_velocity,
        "restitution": s.restitution,
        "max_crush_mm": s.max_displacement * 1000.0,
        "t_max_crush_ms": float(s.time_of_max_displacement - t[0]) * 1000.0,
        "t_zero_velocity_ms": NAN
        if s.time_to_zero_velocity is None
        else float(s.time_to_zero_velocity - t[0]) * 1000.0,
        "peak_decel_g": s.peak_deceleration / g,
        "mean_decel_g": NAN
        if s.mean_deceleration is None
        else s.mean_deceleration / g,
    }
    if shape:
        out.update(signal_features(t, a / g))
    return {_key(prefix, k): v for k, v in out.items()}


# --- Result objects to flat rows ---------------------------------------------


def _scalar(value: Any) -> tuple[bool, Value]:
    if value is None or isinstance(value, (bool, str)):
        return True, value
    if isinstance(value, np.bool_):
        return True, bool(value)
    if isinstance(value, (int, np.integer)):
        return True, int(value)
    if isinstance(value, (float, np.floating)):
        return True, float(value)
    return False, None


def flatten(
    obj: Any,
    prefix: str = "",
    sep: str = ".",
    max_items: int = 50,
) -> dict[str, Value]:
    """Return any result as a flat dict of numbers and labels.

    Dataclasses and mappings are walked recursively and their keys joined
    with ``sep``: ``score_mpdb(...)`` gives keys such as
    ``"occupants.driver.regions.head_neck.points"``. Short lists and
    tuples of values get index keys (``"limits.0"``). NumPy arrays (time
    histories) and longer sequences are left out, so every value is a
    single number, string, bool or None.

    Parameters
    ----------
    obj:
        A result object, dict, or plain value.
    prefix:
        Text put in front of every key, e.g. ``"mpdb."``.
    sep:
        Separator between nested names.
    max_items:
        Longest list or tuple that is expanded.
    """
    out: dict[str, Value] = {}

    def walk(value: Any, key: str) -> None:
        ok, scalar = _scalar(value)
        if ok:
            out[key or "value"] = scalar
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            for f in dataclasses.fields(value):
                walk(getattr(value, f.name), f"{key}{sep}{f.name}" if key else f.name)
        elif isinstance(value, Mapping):
            for k, v in value.items():
                walk(v, f"{key}{sep}{k}" if key else str(k))
        elif isinstance(value, (list, tuple)) and len(value) <= max_items:
            for i, v in enumerate(value):
                walk(v, f"{key}{sep}{i}" if key else str(i))
        # NumPy arrays, long sequences and other objects are skipped.

    walk(obj, "")
    return {f"{prefix}{k}": v for k, v in out.items()}


# --- Many runs ---------------------------------------------------------------


def feature_table(
    runs: Mapping[str, Any] | Iterable[tuple[str, Any]],
    extract: Callable[[Any], Any],
    id_column: str = "run",
    params: Mapping[str, Mapping[str, Any]] | None = None,
    on_error: str = "record",
) -> list[dict[str, Value]]:
    """Run ``extract`` on every run and return one flat row per run.

    Parameters
    ----------
    runs:
        Run names and inputs: a dict ``{name: input}`` or pairs
        ``(name, input)``. The input is anything ``extract`` accepts, such
        as a folder path or a tuple of arrays.
    extract:
        Function returning the features of one run: a dict, a result
        object or a list of them (all are flattened with `flatten`).
    id_column:
        Name of the column holding the run name.
    params:
        Design parameters per run name (thickness, variant ...), added to
        the row so the table is directly a training set.
    on_error:
        ``"record"`` (default): a run that raises an exception gets a row
        with only its name, its parameters and an ``error`` column, and
        the batch continues. ``"raise"``: stop at the first error.

    Returns
    -------
    list of dict
        One row per run, in input order.
    """
    if on_error not in ("record", "raise"):
        raise ValueError('on_error must be "record" or "raise".')
    items = runs.items() if isinstance(runs, Mapping) else runs
    rows: list[dict[str, Value]] = []
    for name, data in items:
        row: dict[str, Value] = {id_column: name}
        if params is not None:
            row.update(flatten(params.get(name, {})))
        try:
            result = extract(data)
        except Exception as error:
            if on_error == "raise":
                raise
            row["error"] = f"{type(error).__name__}: {error}"
        else:
            parts = result if isinstance(result, list) else [result]
            for part in parts:
                row.update(flatten(part))
        rows.append(row)
    return rows


def _columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    columns: dict[str, None] = {}
    for row in rows:
        columns.update(dict.fromkeys(row))
    return list(columns)


def write_csv(
    rows: Sequence[Mapping[str, Any]],
    path: str | os.PathLike[str],
    columns: Sequence[str] | None = None,
) -> list[str]:
    """Write rows to a CSV file and return the column names.

    The columns are the union of all rows' keys in first-seen order
    (unless given), so runs with missing features or an ``error``
    column still line up; missing cells are left empty.
    """
    names = list(columns) if columns is not None else _columns(rows)
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return names


def to_dataframe(rows: Sequence[Mapping[str, Any]]) -> Any:
    """Return the rows as a pandas DataFrame (pandas must be installed)."""
    try:
        pd = importlib.import_module("pandas")
    except ImportError as error:  # pragma: no cover - depends on the environment
        raise ImportError(
            "to_dataframe needs pandas: python -m pip install pandas"
        ) from error
    return pd.DataFrame(list(rows), columns=_columns(rows))


def to_matrix(
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str] | None = None,
) -> tuple[list[str], NDArray[np.float64]]:
    """Return numeric columns as a 2D float array for model training.

    Parameters
    ----------
    rows:
        Feature rows, e.g. from `feature_table`.
    columns:
        Columns to use, in order. By default every column whose values
        are all numbers (bools count as 0/1) or missing.

    Returns
    -------
    names, matrix
        Column names and an array of shape (rows, columns). Missing
        values are ``nan``; drop or impute them before training.
    """

    def number(value: Any) -> float | None:
        ok, scalar = _scalar(value)
        if not ok or isinstance(scalar, str):
            return None
        return NAN if scalar is None else float(scalar)

    if columns is None:
        columns = [
            c for c in _columns(rows)
            if all(number(r[c]) is not None for r in rows if c in r)
        ]
    matrix = np.full((len(rows), len(columns)), NAN)
    for i, row in enumerate(rows):
        for j, column in enumerate(columns):
            if column in row:
                value = number(row[column])
                if value is None:
                    raise ValueError(
                        f"Column {column!r} has a non-numeric value "
                        f"{row[column]!r} in row {i}."
                    )
                matrix[i, j] = value
    return list(columns), matrix
