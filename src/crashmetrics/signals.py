"""Signal processing for crash time histories.

Functions
---------
cfc_filter
    SAE J211 channel frequency class (CFC) filter.
resultant
    Resultant magnitude of axis components.
to_g
    Convert acceleration from common unit systems to g.
to_seconds
    Convert time to seconds.
resample_uniform
    Linearly interpolate a signal onto a uniform time grid.

Typical head-impact workflow: convert units, filter each axis
component with CFC 1000, compute the resultant, then calculate HIC.
Filter the components, not the resultant.
"""

import math

import numpy as np

__all__ = [
    "STANDARD_GRAVITY",
    "cfc_filter",
    "resample_uniform",
    "resultant",
    "to_g",
    "to_seconds",
]

STANDARD_GRAVITY = 9.80665
"""Standard acceleration of gravity in m/s^2."""

# Factor relating the CFC number to the design frequency of the
# 2-pole Butterworth stage, as given in SAE J211-1 Appendix C.
_J211_FREQUENCY_FACTOR = 2.0775

# Acceleration unit -> factor to m/s^2.
_ACCELERATION_UNITS = {
    "g": STANDARD_GRAVITY,
    "m/s^2": 1.0,
    "mm/s^2": 1.0e-3,
    "mm/ms^2": 1.0e3,
    "m/ms^2": 1.0e6,
    "ft/s^2": 0.3048,
    "in/s^2": 0.0254,
}

_ACCELERATION_ALIASES = {
    "m/s2": "m/s^2",
    "m/s**2": "m/s^2",
    "mm/s2": "mm/s^2",
    "mm/s**2": "mm/s^2",
    "mm/ms2": "mm/ms^2",
    "mm/ms**2": "mm/ms^2",
    "m/ms2": "m/ms^2",
    "ft/s2": "ft/s^2",
    "in/s2": "in/s^2",
    "gs": "g",
}

# Time unit -> factor to seconds.
_TIME_UNITS = {"s": 1.0, "ms": 1.0e-3, "us": 1.0e-6}


def _as_1d_finite(values, name):
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError(f"{name} must be a 1D array.")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values.")
    return array


def _uniform_step(time, rel_tol=1.0e-3):
    """Return the sample interval, or raise if sampling is not uniform."""
    steps = np.diff(time)
    if np.any(steps <= 0):
        raise ValueError("Time values must be strictly increasing.")

    step = (time[-1] - time[0]) / (len(time) - 1)
    if np.max(np.abs(steps - step)) > rel_tol * step:
        raise ValueError(
            "CFC filtering needs uniformly sampled data. Use "
            "resample_uniform() first."
        )
    return step


def cfc_filter(time, signal, cfc, pad_ms=10.0):
    """Apply an SAE J211 channel frequency class (CFC) filter.

    Parameters
    ----------
    time:
        Uniformly sampled 1D time array in seconds.
    signal:
        1D signal, in any unit, sampled at ``time``.
    cfc:
        Channel frequency class, for example 60, 180, 600 or 1000.
        Head acceleration for HIC normally uses CFC 1000.
    pad_ms:
        Length of padding added at each end before filtering, in
        milliseconds, to reduce start-up transients. Set to 0 to
        disable. Limited to the length of the signal.

    Returns
    -------
    numpy.ndarray
        Filtered signal, same length and unit as ``signal``.

    Notes
    -----
    Implements the digital filter of SAE J211-1 Appendix C: a 2-pole
    Butterworth low-pass filter applied forward and then backward,
    giving a phaseless 4-pole response.

    With sample interval ``T``::

        wd = 2 * pi * CFC * 2.0775
        wa = tan(wd * T / 2)
        a0 = wa**2 / (1 + sqrt(2) * wa + wa**2)
        a1 = 2 * a0
        a2 = a0
        b1 = -2 * (wa**2 - 1) / (1 + sqrt(2) * wa + wa**2)
        b2 = (-1 + sqrt(2) * wa - wa**2) / (1 + sqrt(2) * wa + wa**2)

        y[i] = a0*x[i] + a1*x[i-1] + a2*x[i-2] + b1*y[i-1] + b2*y[i-2]

    The padding reflects the signal about each end point (an odd
    reflection), which keeps the end value and slope continuous. The
    padding method is a numerical choice of this package; check that
    it matches the procedure required by your assessment protocol.
    """
    t = _as_1d_finite(time, "time")
    x = _as_1d_finite(signal, "signal")

    if len(t) != len(x) or len(t) < 3:
        raise ValueError(
            "time and signal must have equal lengths and contain at "
            "least three samples."
        )

    if not math.isfinite(cfc) or cfc <= 0:
        raise ValueError("cfc must be positive and finite.")

    if not math.isfinite(pad_ms) or pad_ms < 0:
        raise ValueError("pad_ms must be non-negative and finite.")

    step = _uniform_step(t)
    sample_rate = 1.0 / step

    half_angle = math.pi * cfc * _J211_FREQUENCY_FACTOR * step
    if half_angle >= math.pi / 2:
        raise ValueError(
            f"Sample rate {sample_rate:.6g} Hz is too low for CFC {cfc:g}. "
            f"It must exceed {2 * cfc * _J211_FREQUENCY_FACTOR:.6g} Hz."
        )

    wa = math.tan(half_angle)
    denominator = 1.0 + math.sqrt(2.0) * wa + wa**2
    a0 = wa**2 / denominator
    a1 = 2.0 * a0
    a2 = a0
    b1 = -2.0 * (wa**2 - 1.0) / denominator
    b2 = (-1.0 + math.sqrt(2.0) * wa - wa**2) / denominator

    n_pad = min(len(x) - 1, int(round(pad_ms * 1.0e-3 * sample_rate)))
    if n_pad > 0:
        front = 2.0 * x[0] - x[n_pad:0:-1]
        back = 2.0 * x[-1] - x[-2:-n_pad - 2:-1]
        padded = np.concatenate((front, x, back))
    else:
        padded = x

    forward = _second_order_pass(padded, a0, a1, a2, b1, b2)
    backward = _second_order_pass(forward[::-1], a0, a1, a2, b1, b2)[::-1]

    if n_pad > 0:
        return backward[n_pad:-n_pad]
    return backward


def _second_order_pass(x, a0, a1, a2, b1, b2):
    """One pass of the J211 recursion, starting from steady state."""
    y = np.empty_like(x)
    # Initialise as if the signal had been constant at x[0]; the
    # filter has unit DC gain, so the output starts at x[0].
    x1 = x2 = y1 = y2 = float(x[0])
    for i, xi in enumerate(x.tolist()):
        yi = a0 * xi + a1 * x1 + a2 * x2 + b1 * y1 + b2 * y2
        y[i] = yi
        x2, x1 = x1, xi
        y2, y1 = y1, yi
    return y


def resultant(*components):
    """Return the resultant magnitude of two or three components.

    Parameters
    ----------
    *components:
        1D arrays of equal length in the same unit, for example the
        x, y and z acceleration of a headform.

    Returns
    -------
    numpy.ndarray
        ``sqrt(x**2 + y**2 + z**2)``, in the unit of the components.
    """
    if len(components) not in (2, 3):
        raise ValueError("resultant() takes two or three components.")

    arrays = [
        _as_1d_finite(c, f"component {i + 1}")
        for i, c in enumerate(components)
    ]
    if len({len(a) for a in arrays}) != 1:
        raise ValueError("All components must have the same length.")

    return np.sqrt(sum(a**2 for a in arrays))


def _normalise_unit(unit):
    key = unit.strip().lower().replace(" ", "").replace("²", "^2")
    return _ACCELERATION_ALIASES.get(key, key)


def to_g(acceleration, unit):
    """Convert acceleration to g (standard gravity, 9.80665 m/s^2).

    Parameters
    ----------
    acceleration:
        Array of acceleration values.
    unit:
        Unit of ``acceleration``: ``"m/s^2"``, ``"mm/s^2"``,
        ``"mm/ms^2"``, ``"m/ms^2"``, ``"ft/s^2"``, ``"in/s^2"`` or
        ``"g"``.

        Common LS-DYNA unit systems: mm-ms-kg gives ``"mm/ms^2"``;
        mm-s-tonne gives ``"mm/s^2"``; m-s-kg gives ``"m/s^2"``.

    Returns
    -------
    numpy.ndarray
        Acceleration in g.
    """
    key = _normalise_unit(unit)
    if key not in _ACCELERATION_UNITS:
        known = ", ".join(sorted(_ACCELERATION_UNITS))
        raise ValueError(
            f"Unknown acceleration unit {unit!r}. Known units: {known}."
        )
    a = np.asarray(acceleration, dtype=float)
    return a * (_ACCELERATION_UNITS[key] / STANDARD_GRAVITY)


def to_seconds(time, unit):
    """Convert time to seconds.

    Parameters
    ----------
    time:
        Array of time values.
    unit:
        ``"s"``, ``"ms"`` or ``"us"``.

    Returns
    -------
    numpy.ndarray
        Time in seconds.
    """
    key = unit.strip().lower()
    if key not in _TIME_UNITS:
        raise ValueError(
            f"Unknown time unit {unit!r}. Known units: s, ms, us."
        )
    return np.asarray(time, dtype=float) * _TIME_UNITS[key]


def resample_uniform(time, signal, sample_rate):
    """Linearly interpolate a signal onto a uniform time grid.

    Parameters
    ----------
    time:
        Strictly increasing 1D time array in seconds.
    signal:
        1D signal sampled at ``time``.
    sample_rate:
        Target sample rate in Hz.

    Returns
    -------
    tuple of numpy.ndarray
        ``(uniform_time, resampled_signal)``. The grid starts at
        ``time[0]`` and does not go beyond ``time[-1]``.

    Notes
    -----
    Linear interpolation does not remove content above the new
    Nyquist frequency. Resample to a rate well above the CFC you will
    apply, not below the original rate.
    """
    t = _as_1d_finite(time, "time")
    x = _as_1d_finite(signal, "signal")

    if len(t) != len(x) or len(t) < 2:
        raise ValueError(
            "time and signal must have equal lengths and contain at "
            "least two samples."
        )
    if np.any(np.diff(t) <= 0):
        raise ValueError("Time values must be strictly increasing.")
    if not math.isfinite(sample_rate) or sample_rate <= 0:
        raise ValueError("sample_rate must be positive and finite.")

    step = 1.0 / sample_rate
    count = int(math.floor((t[-1] - t[0]) / step + 1.0e-9)) + 1
    uniform_time = t[0] + step * np.arange(count)
    return uniform_time, np.interp(uniform_time, t, x)
