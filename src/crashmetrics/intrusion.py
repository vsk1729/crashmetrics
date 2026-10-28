"""Intrusion and deformation measurement from node or point coordinates.

Works on coordinate histories from CAE (for example LS-DYNA ``nodout``)
and on static before/after measurements from a physical test.

Functions:

- `intrusion`: Displacement of a point, absolute or relative to a
  reference node or to a reference frame of three or more points that
  move with the vehicle (translation and rotation removed), with dynamic
  (peak) and static (final) values, overall and along a direction.
- `intrusions`: The same for many points with one reference.
- `node_distance`: Distance between two points over time: closing,
  opening and the remaining (survival) space.
- `node_track`: Build an (n, 3) coordinate array from x, y and z
  columns, or from an initial position and displacements.

Conventions:

- A point's coordinates are an array of shape (n, 3): one row per time
  step (or two rows, before and after, for a static measurement), in
  any length unit (results use the same unit).
- Intrusions are expressed in the axes of the reference at the first
  sample, normally the vehicle axes of the undeformed model.
- ``direction`` is a vector or one of ``"x"``, ``"-x"``, ``"y"``,
  ``"-y"``, ``"z"``, ``"-z"``. For example, with x pointing forward,
  rearward intrusion is ``direction="-x"``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Union

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "DistanceResult",
    "IntrusionResult",
    "intrusion",
    "intrusions",
    "node_distance",
    "node_track",
]

Array = NDArray[np.float64]
Direction = Union[str, ArrayLike]

_AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


# --- Inputs ------------------------------------------------------------------


def node_track(
    x: ArrayLike,
    y: ArrayLike,
    z: ArrayLike,
    initial: ArrayLike | None = None,
) -> Array:
    """Return a point's coordinates as an (n, 3) array.

    Parameters
    ----------
    x, y, z:
        Coordinate histories, or displacement histories if ``initial``
        is given.
    initial:
        Initial coordinates (x0, y0, z0); the displacements are added to
        them. LS-DYNA ``nodout`` gives both coordinates and
        displacements, so either form works.
    """
    xyz = np.column_stack([np.asarray(c, dtype=float) for c in (x, y, z)])
    if initial is not None:
        start = np.asarray(initial, dtype=float)
        if start.shape != (3,):
            raise ValueError("initial must be three coordinates.")
        xyz = xyz + start
    return xyz


def _track(points: ArrayLike, name: str) -> Array:
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 3 or p.shape[0] < 2:
        raise ValueError(f"{name} must have shape (n, 3) with n >= 2, "
                         f"not {p.shape}.")
    if not np.all(np.isfinite(p)):
        raise ValueError(f"{name} must contain only finite values.")
    return p


def _time(time: ArrayLike | None, n: int) -> Array | None:
    if time is None:
        return None
    t = np.asarray(time, dtype=float)
    if t.shape != (n,):
        raise ValueError(f"time must have {n} values, one per row.")
    if not np.all(np.isfinite(t)) or np.any(np.diff(t) <= 0):
        raise ValueError("time must be finite and strictly increasing.")
    return t


def _unit(direction: Direction) -> Array:
    if isinstance(direction, str):
        key = direction.strip().lower()
        sign = -1.0 if key.startswith("-") else 1.0
        axis = key.lstrip("+-")
        if axis not in _AXES:
            raise ValueError(
                f"direction must be a vector or one of x, -x, y, -y, z, -z, "
                f"not {direction!r}."
            )
        return sign * np.array(_AXES[axis])
    v = np.asarray(direction, dtype=float)
    norm = float(np.linalg.norm(v)) if v.shape == (3,) else 0.0
    if not (math.isfinite(norm) and norm > 0):
        raise ValueError("direction must be a non-zero 3D vector.")
    return v / norm


def _final(values: Array, time: Array | None, window_ms: float | None) -> Array:
    """Last value, or the mean over the last ``window_ms``."""
    if window_ms is None:
        return np.asarray(values[-1])
    if time is None:
        raise ValueError("static_window_ms needs the time array.")
    if not window_ms > 0:
        raise ValueError("static_window_ms must be positive.")
    tail = time >= time[-1] - window_ms / 1000.0
    return np.asarray(values[tail].mean(axis=0))


# --- Rigid reference frame ---------------------------------------------------


def _rigid_fit(ref: Array) -> tuple[Array, Array, Array, Array]:
    """Best-fit rigid motion of reference points from the first sample.

    ``ref`` has shape (k, n, 3). Returns, per time step, the rotation R
    (n, 3, 3), the centroids c0 (3,) and c (n, 3) such that a point
    moving rigidly with the reference goes from x0 to R (x0 - c0) + c,
    and the RMS distance of the reference points from that fit (n,).
    The rotation is the least-squares (Kabsch) solution, so measurement
    noise and small deformations of the reference are averaged out.
    """
    a0 = ref[:, 0, :]                                   # (k, 3)
    c0 = a0.mean(axis=0)
    c = ref.mean(axis=0)                                # (n, 3)
    a = a0 - c0
    b = ref - c[None, :, :]                             # (k, n, 3)
    h = np.einsum("ki,knj->nij", a, b)                  # (n, 3, 3)
    u, _, vt = np.linalg.svd(h)
    v = np.transpose(vt, (0, 2, 1))
    ut = np.transpose(u, (0, 2, 1))
    d = np.sign(np.linalg.det(v @ ut))
    d[d == 0] = 1.0
    fix = np.zeros((len(d), 3, 3))
    fix[:, 0, 0] = 1.0
    fix[:, 1, 1] = 1.0
    fix[:, 2, 2] = d
    rot = v @ fix @ ut                                   # (n, 3, 3)
    fitted = np.einsum("nij,kj->kni", rot, a) + c[None, :, :]
    rms = np.sqrt(((fitted - ref) ** 2).sum(axis=2).mean(axis=0))
    return rot, c0, c, rms


# --- Intrusion -------------------------------------------------------------


@dataclass(frozen=True)
class IntrusionResult:
    """Displacement of a point relative to a reference."""

    reference: str
    """``"global"``, ``"node"`` or ``"frame"``."""
    x_dynamic: float
    """Largest x displacement in magnitude during the event (signed)."""
    y_dynamic: float
    """Largest y displacement in magnitude (signed)."""
    z_dynamic: float
    """Largest z displacement in magnitude (signed)."""
    resultant_dynamic: float
    """Largest resultant displacement."""
    t_dynamic_ms: float
    """Time of the largest resultant displacement, ms from the first
    sample (nan without a time array)."""
    x_static: float
    """Final x displacement (residual, after springback)."""
    y_static: float
    """Final y displacement."""
    z_static: float
    """Final z displacement."""
    resultant_static: float
    """Final resultant displacement."""
    along_dynamic: float
    """Largest displacement along ``direction`` (positive: in the
    direction); nan without a direction."""
    along_static: float
    """Final displacement along ``direction``; nan without one."""
    t_along_ms: float
    """Time of ``along_dynamic``, ms (nan without time or direction)."""
    reference_fit_error: float
    """Largest RMS distance of the reference points from their best
    rigid fit (``"frame"`` only, else 0). A large value means the
    reference points deform and are not a good reference."""
    displacement: Array
    """Displacement history, shape (n, 3), in the reference's initial
    axes."""
    time: Array | None
    """Time, s (None if not given)."""

    @property
    def resultant(self) -> Array:
        """Resultant displacement history."""
        return np.asarray(np.linalg.norm(self.displacement, axis=1))


def _peak_signed(values: Array) -> float:
    return float(values[int(np.argmax(np.abs(values)))])


def intrusion(
    point: ArrayLike,
    reference: ArrayLike | Sequence[ArrayLike] | None = None,
    time: ArrayLike | None = None,
    direction: Direction | None = None,
    static_window_ms: float | None = None,
) -> IntrusionResult:
    """Return the intrusion (displacement) of a point.

    Parameters
    ----------
    point:
        Coordinates of the point, shape (n, 3): a time history, or two
        rows (before and after) for a static measurement.
    reference:
        What the displacement is measured against:

        - None: the global (ground) system, so vehicle motion is
          included. Useful for barriers and impactors, not for
          intrusions.
        - One node, shape (n, 3): its translation is removed. Rotation
          of the vehicle (pitch, yaw) is not, so use a node close to the
          point or a frame.
        - Three or more nodes, shape (k, n, 3) or a list of (n, 3)
          arrays: a frame that moves and rotates with them (for example
          the rear seat cross member, B-pillar bases and sills);
          translation and rotation are removed by a least-squares rigid
          fit. Two nodes are not enough (the rotation about the line
          through them is unknown).
    time:
        Time in s, one value per row. Needed for times and
        ``static_window_ms``.
    direction:
        Direction for ``along_*`` (a vector or ``"x"``, ``"-x"`` ...),
        in the reference's initial axes.
    static_window_ms:
        Average the last ``static_window_ms`` for the static values (to
        smooth springback oscillation). Default: the last sample.

    Returns
    -------
    IntrusionResult
    """
    p = _track(point, "point")
    n = len(p)
    t = _time(time, n)

    fit_error = 0.0
    if reference is None:
        kind = "global"
        disp = p - p[0]
    else:
        ref = np.asarray(reference, dtype=float)
        if ref.ndim == 2:
            r = _track(ref, "reference")
            if len(r) != n:
                raise ValueError("point and reference need the same rows.")
            kind = "node"
            disp = (p - r) - (p[0] - r[0])
        elif ref.ndim == 3:
            if ref.shape[1:] != (n, 3):
                raise ValueError(
                    f"reference nodes must have shape (k, {n}, 3), not {ref.shape}."
                )
            if ref.shape[0] < 3:
                raise ValueError(
                    "A reference frame needs at least three nodes (not on one "
                    "line); with two, the rotation about their line is unknown."
                )
            if not np.all(np.isfinite(ref)):
                raise ValueError("reference must contain only finite values.")
            spread = np.linalg.svd(ref[:, 0, :] - ref[:, 0, :].mean(axis=0),
                                   compute_uv=False)
            if spread[1] <= 1e-9 * max(spread[0], 1e-300):
                raise ValueError("The reference nodes lie on one line.")
            kind = "frame"
            rot, c0, c, rms = _rigid_fit(ref)
            local = np.einsum("nji,nj->ni", rot, p - c) + c0   # R^T (p - c) + c0
            disp = local - p[0]
            fit_error = float(np.max(rms))
        else:
            raise ValueError("reference must be (n, 3) or (k, n, 3).")

    res = np.linalg.norm(disp, axis=1)
    i_res = int(np.argmax(res))
    final = _final(disp, t, static_window_ms)

    def ms(i: int) -> float:
        return math.nan if t is None else float(t[i] - t[0]) * 1000.0

    along_dyn = along_static = t_along = math.nan
    if direction is not None:
        along = disp @ _unit(direction)
        i_al = int(np.argmax(along))
        along_dyn = float(along[i_al])
        along_static = float(final @ _unit(direction))
        t_along = ms(i_al)

    return IntrusionResult(
        reference=kind,
        x_dynamic=_peak_signed(disp[:, 0]),
        y_dynamic=_peak_signed(disp[:, 1]),
        z_dynamic=_peak_signed(disp[:, 2]),
        resultant_dynamic=float(res[i_res]),
        t_dynamic_ms=ms(i_res),
        x_static=float(final[0]),
        y_static=float(final[1]),
        z_static=float(final[2]),
        resultant_static=float(np.linalg.norm(final)),
        along_dynamic=along_dyn,
        along_static=along_static,
        t_along_ms=t_along,
        reference_fit_error=fit_error,
        displacement=np.asarray(disp),
        time=t,
    )


def intrusions(
    points: Mapping[str, ArrayLike],
    reference: ArrayLike | Sequence[ArrayLike] | None = None,
    time: ArrayLike | None = None,
    direction: Direction | Mapping[str, Direction] | None = None,
    static_window_ms: float | None = None,
) -> dict[str, IntrusionResult]:
    """Return `intrusion` for many points against one reference.

    ``direction`` may be one direction for all points or a dict
    ``{point name: direction}`` (for example ``"-x"`` for the pedals and
    ``"z"`` for the steering column). ``flatten(intrusions(...))`` gives
    columns such as ``"brake_pedal.along_dynamic"``.
    """
    out: dict[str, IntrusionResult] = {}
    for name, coords in points.items():
        d = direction.get(name) if isinstance(direction, Mapping) else direction
        out[name] = intrusion(coords, reference, time, d, static_window_ms)
    return out


# --- Distance between two points --------------------------------------------


@dataclass(frozen=True)
class DistanceResult:
    """Distance between two points over time."""

    initial: float
    """Distance at the first sample."""
    final: float
    """Final (static, residual) distance: the remaining space."""
    minimum: float
    """Smallest distance during the event."""
    maximum: float
    """Largest distance during the event."""
    closing_dynamic: float
    """Largest reduction of the distance, ``initial - minimum``."""
    closing_static: float
    """Final reduction, ``initial - final`` (negative if it opened)."""
    opening_dynamic: float
    """Largest increase, ``maximum - initial``."""
    t_minimum_ms: float
    """Time of the smallest distance, ms (nan without time)."""
    distance: Array
    """Distance history."""
    time: Array | None
    """Time, s (None if not given)."""


def node_distance(
    a: ArrayLike,
    b: ArrayLike,
    time: ArrayLike | None = None,
    static_window_ms: float | None = None,
) -> DistanceResult:
    """Return the distance between two points over time.

    The distance does not depend on any reference frame, so it suits
    survival-space checks (steering wheel to seat, door to B-pillar,
    roof to head form) and gaps that must not close.

    Parameters
    ----------
    a, b:
        Coordinates of the two points, shape (n, 3), or two rows for a
        static before/after measurement.
    time:
        Time in s, one value per row.
    static_window_ms:
        Average the last ``static_window_ms`` for the final distance.
    """
    pa, pb = _track(a, "a"), _track(b, "b")
    if pa.shape != pb.shape:
        raise ValueError("a and b need the same shape.")
    t = _time(time, len(pa))
    dist = np.linalg.norm(pa - pb, axis=1)
    final = float(_final(dist, t, static_window_ms))
    i_min = int(np.argmin(dist))
    initial = float(dist[0])
    return DistanceResult(
        initial=initial,
        final=final,
        minimum=float(dist[i_min]),
        maximum=float(np.max(dist)),
        closing_dynamic=initial - float(dist[i_min]),
        closing_static=initial - final,
        opening_dynamic=float(np.max(dist)) - initial,
        t_minimum_ms=math.nan if t is None else float(t[i_min] - t[0]) * 1000.0,
        distance=np.asarray(dist),
        time=t,
    )
