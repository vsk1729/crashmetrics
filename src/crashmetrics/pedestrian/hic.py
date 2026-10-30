"""Head Injury Criterion (HIC) calculations."""

import warnings
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

_MAX_SAMPLE_CANDIDATES = 20_000


@dataclass(frozen=True)
class HICResult:
    """Result of a HIC calculation.

    ``start_time`` and ``end_time`` are in seconds, like the input
    time; the ``*_ms`` properties give the same values in
    milliseconds.
    """

    value: float
    """HIC value (dimensionless by convention)."""

    start_time: float
    """Start of the critical interval in seconds."""

    end_time: float
    """End of the critical interval in seconds."""

    @property
    def start_time_ms(self) -> float:
        """Start of the critical interval in milliseconds."""
        return self.start_time * 1000.0

    @property
    def end_time_ms(self) -> float:
        """End of the critical interval in milliseconds."""
        return self.end_time * 1000.0

    @property
    def duration_ms(self) -> float:
        """Duration of the critical interval in milliseconds."""
        return (self.end_time - self.start_time) * 1000.0


def calculate_hic(
    time: ArrayLike,
    acceleration: ArrayLike,
    window_ms: float = 15.0,
    resolution_ms: float = 0.1,
    method: str = "grid",
) -> HICResult:
    """Calculate HIC using a refined, linearly interpolated time grid.

    Parameters
    ----------
    time:
        One-dimensional time array in seconds.
    acceleration:
        One-dimensional non-negative resultant acceleration in g.
    window_ms:
        Maximum interval duration in milliseconds. If the signal is
        shorter than this, a ``UserWarning`` is issued and the search
        is limited to the signal duration.
    resolution_ms:
        Spacing of the refined time grid in milliseconds.
    method:
        ``"grid"`` (default): maximum over endpoints on the refined
        grid. ``"exact"``: the maximum over all continuous endpoints of
        the linearly interpolated signal, found from the stationary
        conditions (see Notes); the grid result is its starting bound.

    Returns
    -------
    HICResult
        Approximate maximum HIC and its interval.

    Notes
    -----
    The acceleration is treated as linear between samples, and its
    integral is computed exactly. With ``method="grid"`` the maximum is
    searched over end points on a uniform grid of ``resolution_ms``
    (plus the samples themselves, except for records of more than
    20 000 samples that are over four times as dense as the grid), so
    the result is a lower bound of the exact value whose accuracy
    depends on resolution_ms (typically within 0.1 % at 0.1 ms; see the
    HIC accuracy page of the documentation).

    With ``method="exact"``, ``HIC(t1, t2) = (t2 - t1) [I / (t2 - t1)]^2.5``
    with ``I`` the integral of the linear interpolation is maximised over
    all continuous endpoints. ``HIC`` is continuously differentiable in
    both endpoints, so the maximum is either a stationary point,
    where ``a(t1) = a(t2) = 0.6 I / (t2 - t1)``, or lies on the
    boundary ``t2 - t1 = window`` (where ``a(t1) = a(t2)``), at the start
    or the end of the record. On every pair of linear segments these
    conditions reduce to quadratic equations, which are solved in closed
    form; segment pairs that cannot beat the grid result are skipped.

    This numerical method is not, by itself, evidence of compliance
    with a regulatory assessment protocol.
    """
    t = np.asarray(time, dtype=float)
    a = np.asarray(acceleration, dtype=float)

    if t.ndim != 1 or a.ndim != 1:
        raise ValueError("time and acceleration must be 1D arrays.")

    if len(t) != len(a) or len(t) < 2:
        raise ValueError(
            "time and acceleration must have equal lengths "
            "and contain at least two samples."
        )

    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(a)):
        raise ValueError("Inputs must contain only finite values.")

    if np.any(np.diff(t) <= 0):
        raise ValueError("Time values must be strictly increasing.")

    if np.any(a < 0):
        raise ValueError(
            "Acceleration must be a non-negative resultant magnitude in g."
        )

    if not np.isfinite(window_ms) or window_ms <= 0:
        raise ValueError("window_ms must be positive and finite.")

    if not np.isfinite(resolution_ms) or resolution_ms <= 0:
        raise ValueError("resolution_ms must be positive and finite.")

    if method not in ("grid", "exact"):
        raise ValueError("method must be 'grid' or 'exact'.")

    duration = t[-1] - t[0]
    max_duration = window_ms / 1000.0
    step = resolution_ms / 1000.0

    if duration <= 0:
        raise ValueError("The input time duration must be positive.")

    if duration < max_duration:
        # HIC is the maximum over intervals of at most window_ms, so a
        # shorter record still has a well-defined value: the search is
        # limited to the available duration.
        warnings.warn(
            f"The input signal spans {duration * 1000.0:.3f} ms, which is "
            f"shorter than window_ms={window_ms:g}. HIC is evaluated over "
            "the available duration only; check that the record contains "
            "the whole impact.",
            UserWarning,
            stacklevel=2,
        )
        max_duration = duration

    signal = _Signal(t, a)

    # Uniform refinement grid, including the final time.
    base_grid = np.arange(t[0], t[-1], step)
    base_grid = np.append(base_grid, t[-1])
    parts = [base_grid, base_grid - max_duration]

    # Keep the original samples (the breakpoints of the linear
    # interpolation) as candidate end points. Long, densely sampled
    # records (more than 20 000 samples and more than four times as
    # dense as the grid) use the grid alone, so the search stays fast;
    # the integral is exact either way.
    if len(t) <= max(4 * len(base_grid), _MAX_SAMPLE_CANDIDATES):
        parts += [t, t - max_duration]

    grid = np.unique(np.concatenate(parts))
    grid = grid[(grid >= t[0]) & (grid <= t[-1])]

    # Integral of the piecewise-linear signal at the grid points (exact).
    cumulative = signal.integral(grid)

    best_value, best_start, best_end = _grid_search(
        grid, cumulative, max_duration, step)

    if method == "exact" and best_value >= 0:
        best_value, best_start, best_end = _exact_search(
            signal, max_duration, (best_value, best_start, best_end))

    if best_value < 0:
        raise ValueError("No valid HIC interval could be evaluated.")

    return HICResult(
        value=best_value,
        start_time=best_start,
        end_time=best_end,
    )


def _grid_search(
    grid: NDArray[np.float64],
    cumulative: NDArray[np.float64],
    max_duration: float,
    step: float,
) -> tuple[float, float, float]:
    """Largest HIC over endpoint pairs on the grid (vectorised by offset)."""
    n = len(grid)
    tolerance = max_duration + step * 1e-8
    first = np.searchsorted(grid, grid - tolerance, side="left")
    offsets = np.arange(n) - first                     # starts per end point
    best = np.full(n, -1.0)
    best_start = np.zeros(n, dtype=np.intp)
    ends = np.arange(n)
    for k in range(1, int(np.max(offsets, initial=0)) + 1):
        active = ends[offsets >= k]
        starts = active - k
        duration = grid[active] - grid[starts]
        # Rounding can make the integral of a zero signal slightly negative.
        mean = np.maximum((cumulative[active] - cumulative[starts]) / duration, 0.0)
        values = duration * mean ** 2.5
        better = values > best[active]
        best[active[better]] = values[better]
        best_start[active[better]] = starts[better]
    j = int(np.argmax(best))
    return float(best[j]), float(grid[best_start[j]]), float(grid[j])


# --- Exact maximum for the linearly interpolated signal ------------------------

class _Signal:
    """Piecewise-linear acceleration and its piecewise-quadratic integral."""

    def __init__(self, t: NDArray[np.float64], a: NDArray[np.float64]):
        self.t, self.a = t, a
        self.slope = np.diff(a) / np.diff(t)
        self.c = np.concatenate(
            ([0.0], np.cumsum(0.5 * (a[:-1] + a[1:]) * np.diff(t))))

    def seg(self, x: NDArray[np.float64]) -> NDArray[np.intp]:
        i = np.searchsorted(self.t, x, side="right") - 1
        return np.clip(i, 0, len(self.t) - 2)

    def acc(self, x: NDArray[np.float64], i: NDArray[np.intp] | None = None
            ) -> NDArray[np.float64]:
        i = self.seg(x) if i is None else i
        return self.a[i] + self.slope[i] * (x - self.t[i])

    def integral(self, x: NDArray[np.float64], i: NDArray[np.intp] | None = None
                 ) -> NDArray[np.float64]:
        i = self.seg(x) if i is None else i
        tau = x - self.t[i]
        return self.c[i] + self.a[i] * tau + 0.5 * self.slope[i] * tau * tau

    def hic(self, t1: NDArray[np.float64], t2: NDArray[np.float64]
            ) -> NDArray[np.float64]:
        d = t2 - t1
        area = self.integral(t2) - self.integral(t1)
        ok = (d > 0) & (area > 0)
        out = np.zeros(len(t1))
        out[ok] = d[ok] * (area[ok] / d[ok]) ** 2.5
        return out


def _roots(x0: NDArray[np.float64], x2: NDArray[np.float64],
           q0: NDArray[np.float64], q1: NDArray[np.float64],
           q2: NDArray[np.float64]) -> tuple[NDArray[np.float64], ...]:
    """Roots in [x0, x2] of the quadratic through (x0, q0), (midpoint,
    q1), (x2, q2); NaN where there is none."""
    c0, c1, c2 = q1, (q2 - q0) / 2.0, (q2 + q0) / 2.0 - q1
    scale = np.maximum(np.maximum(np.abs(q0), np.abs(q1)), np.abs(q2))
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        linear = np.abs(c2) <= 1e-12 * scale
        disc = c1 * c1 - 4.0 * c2 * c0
        sq = np.sqrt(np.where(disc >= 0, disc, np.nan))
        qq = -0.5 * (c1 + np.copysign(sq, c1))
        u1 = np.where(linear, -c0 / c1, qq / c2)
        u2 = np.where(linear, np.nan, c0 / qq)
    mid, half = (x0 + x2) / 2.0, (x2 - x0) / 2.0
    out = []
    for u in (u1, u2):
        ok = np.isfinite(u) & (u >= -1.0 - 1e-9) & (u <= 1.0 + 1e-9)
        out.append(np.where(ok, mid + np.clip(u, -1.0, 1.0) * half, np.nan))
    return tuple(out)


def _solve_end(s: _Signal, t1: NDArray[np.float64], j: NDArray[np.intp]
               ) -> tuple[NDArray[np.float64], ...]:
    """t2 in segment j with a(t2) (t2 - t1) = 0.6 I, for fixed t1."""
    x0, x2 = s.t[j], s.t[j + 1]
    a1 = s.integral(t1)

    def q(x: NDArray[np.float64]) -> NDArray[np.float64]:
        return s.acc(x, j) * (x - t1) - 0.6 * (s.integral(x, j) - a1)

    return _roots(x0, x2, q(x0), q((x0 + x2) / 2.0), q(x2))


def _solve_start(s: _Signal, t2: NDArray[np.float64], i: NDArray[np.intp]
                 ) -> tuple[NDArray[np.float64], ...]:
    """t1 in segment i with a(t1) (t2 - t1) = 0.6 I, for fixed t2."""
    x0, x2 = s.t[i], s.t[i + 1]
    a2 = s.integral(t2)

    def q(x: NDArray[np.float64]) -> NDArray[np.float64]:
        return s.acc(x, i) * (t2 - x) - 0.6 * (a2 - s.integral(x, i))

    return _roots(x0, x2, q(x0), q((x0 + x2) / 2.0), q(x2))


def _pair_candidates(s: _Signal, i: NDArray[np.intp], j: NDArray[np.intp]
                     ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Stationary points with t1 in segment i and t2 in segment j."""
    t1s, t2s = [], []
    mi, mj = s.slope[i], s.slope[j]
    sloped = mj != 0.0
    # a(t1) = a(t2) maps t1 to t2 linearly; then a(t1) D = 0.6 I is a
    # quadratic in t1.
    if np.any(sloped):
        ii, jj = i[sloped], j[sloped]

        def t2_of(x: NDArray[np.float64]) -> NDArray[np.float64]:
            return s.t[jj] + (s.acc(x, ii) - s.a[jj]) / s.slope[jj]

        def q(x: NDArray[np.float64]) -> NDArray[np.float64]:
            x2 = t2_of(x)
            return (s.acc(x, ii) * (x2 - x)
                    - 0.6 * (s.integral(x2, jj) - s.integral(x, ii)))

        x0, x2 = s.t[ii], s.t[ii + 1]
        for r in _roots(x0, x2, q(x0), q((x0 + x2) / 2.0), q(x2)):
            with np.errstate(invalid="ignore"):
                t2 = t2_of(r)
            keep = np.isfinite(r) & np.isfinite(t2)
            t1s.append(r[keep])
            t2s.append(t2[keep])
    flat = ~sloped
    if np.any(flat):
        ii, jj = i[flat], j[flat]
        # a(t1) must equal the flat level of segment j
        with np.errstate(divide="ignore", invalid="ignore"):
            t1 = s.t[ii] + (s.a[jj] - s.a[ii]) / s.slope[ii]
        ok = (mi[flat] != 0) & (t1 >= s.t[ii]) & (t1 <= s.t[ii + 1])
        fixed = [np.where(ok, t1, np.nan)]
        both_flat = mi[flat] == 0
        fixed += [np.where(both_flat, s.t[ii], np.nan),
                  np.where(both_flat, s.t[ii + 1], np.nan)]
        for t1 in fixed:
            keep = np.isfinite(t1)
            t1k = t1[keep]
            for r in _solve_end(s, t1k, jj[keep]):
                good = np.isfinite(r)
                t1s.append(t1k[good])
                t2s.append(r[good])
        for t2 in (s.t[jj], s.t[jj + 1]):
            t2k = t2[both_flat]
            for r in _solve_start(s, t2k, ii[both_flat]):
                good = np.isfinite(r)
                t1s.append(r[good])
                t2s.append(t2k[good])
    if not t1s:
        return np.empty(0), np.empty(0)
    return np.concatenate(t1s), np.concatenate(t2s)


def _exact_search(
    s: _Signal,
    max_duration: float,
    grid_best: tuple[float, float, float],
    block: int = 64,
) -> tuple[float, float, float]:
    """Exact HIC maximum of the linear interpolation of the samples.

    Candidates: the window boundary, the start and end of the record and
    the stationary points of every pair of segments (t1 in one, t2 in
    another). Pairs are screened in blocks with an upper bound, so only
    the neighbourhood of the maximum is solved in detail.
    """
    t, a = s.t, s.a
    n_seg = len(t) - 1
    w = max_duration
    t0, tn = float(t[0]), float(t[-1])
    best = list(grid_best)
    eps = 1e-12 * max(abs(tn), abs(t0), w)

    def consider(t1: NDArray[np.float64], t2: NDArray[np.float64]) -> None:
        t1 = np.asarray(t1, dtype=float)
        t2 = np.asarray(t2, dtype=float)
        ok = (np.isfinite(t1) & np.isfinite(t2) & (t1 >= t0 - eps)
              & (t2 <= tn + eps) & (t2 > t1) & (t2 - t1 <= w + eps))
        if not np.any(ok):
            return
        t1c = np.clip(t1[ok], t0, tn)
        t2c = np.minimum(np.clip(t2[ok], t0, tn), t1c + w)
        values = s.hic(t1c, t2c)
        k = int(np.argmax(values))
        if values[k] > best[0]:
            best[:] = [float(values[k]), float(t1c[k]), float(t2c[k])]

    # Boundary t2 - t1 = window: a(t1) = a(t1 + window) on each piece.
    if tn - t0 >= w:
        points = np.unique(np.concatenate((t, t - w)))
        points = points[(points >= t0) & (points <= tn - w)]
        consider(points, points + w)
        g = s.acc(points + w) - s.acc(points)
        lo, hi, g0, g1 = points[:-1], points[1:], g[:-1], g[1:]
        cross = g0 * g1 < 0
        root = lo[cross] + g0[cross] / (g0[cross] - g1[cross]) * (
            hi[cross] - lo[cross])
        consider(root, root + w)
    else:
        consider(np.array([t0]), np.array([tn]))

    # Boundaries t1 = start and t2 = end of the record.
    j = np.arange(n_seg)
    j = j[t[j] <= t0 + w]
    for r in _solve_end(s, np.full(len(j), t0), j):
        consider(np.full(len(j), t0), r)
    i = np.arange(n_seg)
    i = i[t[i + 1] >= tn - w]
    for r in _solve_start(s, np.full(len(i), tn), i):
        consider(r, np.full(len(i), tn))

    # Interior stationary points. Upper bound of HIC for t1 in [p, q],
    # t2 in [u, v]: I <= A(v) - A(p) = Iu, and D >= max(u - q, Iu / amax),
    # so HIC = I^2.5 / D^1.5 <= Iu^2.5 / max(u - q, Iu / amax)^1.5.
    def bound(p: NDArray[np.float64], q: NDArray[np.float64],
              u: NDArray[np.float64], v: NDArray[np.float64],
              amax: NDArray[np.float64]) -> NDArray[np.float64]:
        iu = s.integral(v) - s.integral(p)
        with np.errstate(divide="ignore", invalid="ignore"):
            d = np.maximum(u - q, np.where(amax > 0, iu / amax, np.inf))
            out = np.where((iu > 0) & (d > 0), iu ** 2.5 / d ** 1.5,
                           np.where(iu > 0, np.inf, 0.0))
        return out

    starts = np.arange(0, n_seg, block)
    ends = np.minimum(starts + block, n_seg)          # segment ranges
    n_blk = len(starts)
    blk_max = np.maximum.reduceat(a, starts)          # samples start..
    blk_max = np.maximum(blk_max, a[ends])            # ..end inclusive
    t_lo, t_hi = t[starts], t[ends]
    run_max = blk_max.copy()          # max over blocks p .. p + off
    for off in range(n_blk):
        if off:
            run_max[:n_blk - off] = np.maximum(run_max[:n_blk - off],
                                               blk_max[off:])
        p_blk = np.arange(n_blk - off)
        q_blk = p_blk + off
        gap = t_lo[q_blk] - t_hi[p_blk]
        near = gap <= w
        if not np.any(near):
            break
        p_blk, q_blk = p_blk[near], q_blk[near]
        amax = run_max[p_blk]
        live = bound(t_lo[p_blk], t_hi[p_blk], t_lo[q_blk], t_hi[q_blk],
                     amax) > best[0] * (1.0 + 1e-12)
        for pb, qb in zip(p_blk[live], q_blk[live], strict=True):
            mesh_i, mesh_j = np.meshgrid(np.arange(starts[pb], ends[pb]),
                                         np.arange(starts[qb], ends[qb]),
                                         indexing="ij")
            ii, jj = mesh_i.ravel(), mesh_j.ravel()
            keep = (jj >= ii) & (t[jj] - t[ii + 1] <= w)
            ii, jj = ii[keep], jj[keep]
            if ii.size == 0:
                continue
            seg_max = _range_max(a, ii, jj + 1)
            ok = bound(t[ii], t[ii + 1], t[jj], t[jj + 1],
                       seg_max) > best[0] * (1.0 + 1e-12)
            if np.any(ok):
                consider(*_pair_candidates(s, ii[ok], jj[ok]))
    return best[0], best[1], best[2]


def _range_max(a: NDArray[np.float64], lo: NDArray[np.intp],
               hi: NDArray[np.intp]) -> NDArray[np.float64]:
    """max(a[lo..hi]) for short ranges (within one or two blocks)."""
    out = a[lo].copy()
    span = int(np.max(hi - lo, initial=0))
    for k in range(1, span + 1):
        idx = np.minimum(lo + k, hi)
        out = np.maximum(out, a[idx])
    return out
