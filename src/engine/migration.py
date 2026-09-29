"""Migration of the population above capacity (spec §6).

Conservative mode (default): each unit whose population exceeds its
capacity sends its excess, in equal shares, to its k nearest units that
still have free capacity; it is then brought back to its capacity. The
receivers' free capacity is not checked (as in the current tool), so an
overfilled receiver becomes a source at the next iteration. Iterations go
on until no unit exceeds its capacity by ``tolerance`` or more.

The population is conserved exactly: it is only moved, never rounded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.spatial import cKDTree


EPSILON = 1e-9
"""Numerical zero, in inhabitants."""


@dataclass
class MigrationResult:
    population: np.ndarray
    iterations: int
    converged: bool
    moved: float
    """Total population moved (a person moved twice counts twice)."""
    remaining_excess: float
    """Excess still above capacity; below ``tolerance`` per unit when converged."""
    receivers_exhausted: bool
    """True if migration stopped because no unit had free capacity left."""


def migrate(
    population: np.ndarray,
    capacity: np.ndarray,
    receivable: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    k: int = 3,
    tolerance: float = 1.0,
    max_iterations: int = 10_000,
    export_all: Optional[np.ndarray] = None,
) -> MigrationResult:
    """Move the excess population to the nearest units with free capacity.

    ``receivable`` marks the units allowed to receive population (false for
    no-inflow and evacuated units). A unit is a source if its excess is at
    least ``tolerance`` inhabitants, and a receiver if it is receivable and
    has at least ``tolerance`` free places.

    Units flagged in ``export_all`` (no-inflow zones) send away all their
    excess, even below the tolerance, so that their population never
    exceeds their ceiling (decision of 29/09/2026).
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    if tolerance < 1 or int(tolerance) != tolerance:
        raise ValueError("the tolerance is a whole number of inhabitants (at least 1)")
    population = np.array(population, dtype=np.float64)
    capacity = np.asarray(capacity, dtype=np.float64)
    receivable = np.asarray(receivable, dtype=bool)
    coords = np.column_stack([np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)])
    strict = np.zeros(len(population), dtype=bool) if export_all is None else np.asarray(export_all, dtype=bool)

    def is_source(excess: np.ndarray) -> np.ndarray:
        return (excess >= tolerance) | (strict & (excess > EPSILON))

    moved = 0.0
    iterations = 0
    exhausted = False
    while True:
        excess = population - capacity
        sources = np.flatnonzero(is_source(excess))
        if len(sources) == 0:
            break
        receivers = np.flatnonzero(receivable & (capacity - population >= tolerance))
        if len(receivers) == 0:
            exhausted = True
            break
        if iterations >= max_iterations:
            break
        iterations += 1

        n = min(k, len(receivers))
        targets = nearest_receivers(coords[sources], coords[receivers], receivers, n)
        shares = excess[sources] / n
        # All transfers of an iteration are computed from the same state, then applied.
        np.add.at(population, targets.ravel(), np.repeat(shares, n))
        population[sources] = capacity[sources]
        moved += float(excess[sources].sum())

    remaining = float(np.maximum(population - capacity, 0).sum())
    converged = not np.any(is_source(population - capacity))
    return MigrationResult(population, iterations, converged, moved, remaining, exhausted)


def nearest_receivers(
    source_xy: np.ndarray, receiver_xy: np.ndarray, receiver_ids: np.ndarray, n: int
) -> np.ndarray:
    """Indices of the ``n`` nearest receivers of each source, ties broken by lowest index.

    ``receiver_ids`` must be sorted, so that the lowest position is also the
    lowest unit index (spec §6.3). The query window is widened until the
    n-th distance is strictly below the last one fetched, so that no tied
    receiver is left out.
    """
    tree = cKDTree(receiver_xy)
    total = len(receiver_ids)
    window = min(total, n + 8)
    pending = np.arange(len(source_xy))
    result = np.empty((len(source_xy), n), dtype=np.int64)
    while len(pending):
        dist, pos = tree.query(source_xy[pending], k=window)
        dist = dist.reshape(len(pending), window)
        pos = pos.reshape(len(pending), window)
        rows = np.repeat(np.arange(len(pending)), window)
        # Sort each row by distance, then by receiver position (flat indices, rows kept in order).
        order = np.lexsort((pos.ravel(), dist.ravel(), rows)).reshape(len(pending), window) % window
        dist = np.take_along_axis(dist, order, axis=1)
        pos = np.take_along_axis(pos, order, axis=1)
        complete = (window == total) | (dist[:, n - 1] < dist[:, -1])
        result[pending[complete]] = receiver_ids[pos[complete, :n]]
        pending = pending[~complete]
        window = min(total, window * 2)
    return result


@dataclass
class LegacyResult:
    density: np.ndarray
    iterations: int
    converged: bool


def migrate_legacy(
    density: np.ndarray,
    pmax: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    k: int = 3,
    max_iterations: int = 10_000,
) -> LegacyResult:
    """Reproduction of ``legacy/CAM12_migration.py``, for comparison only.

    Transfers are made in density (hab/km2) whatever the area of the units,
    and every value is rounded to an integer at each iteration, as the QGIS
    integer fields did. This mode does not conserve the population.
    """
    p_sum = _round_half_away(np.asarray(density, dtype=np.float64))
    pmax = np.asarray(pmax, dtype=np.float64)
    coords = np.column_stack([x, y]).astype(np.float64)
    valid = np.isfinite(pmax)
    iterations = 0
    while iterations < max_iterations:
        d_p = _round_half_away(pmax - p_sum)
        sources = np.flatnonzero(valid & (d_p < 0))
        if len(sources) == 0:
            return LegacyResult(p_sum, iterations, True)
        receivers = np.flatnonzero(valid & (d_p > 0))
        if len(receivers) == 0:
            return LegacyResult(p_sum, iterations, False)
        iterations += 1
        n = min(k, len(receivers))
        targets = nearest_receivers(coords[sources], coords[receivers], receivers, n)
        gain_per_pair = _round_half_away(d_p[sources] / n)
        gain = np.zeros_like(p_sum)
        np.add.at(gain, targets.ravel(), np.repeat(gain_per_pair, n))
        p_sum = _round_half_away(p_sum + np.abs(gain))
        p_sum[sources] = _round_half_away(pmax[sources])
    return LegacyResult(p_sum, iterations, False)


def _round_half_away(values: np.ndarray) -> np.ndarray:
    """Rounding of QGIS when a real is stored in an integer field."""
    return np.sign(values) * np.floor(np.abs(values) + 0.5)
