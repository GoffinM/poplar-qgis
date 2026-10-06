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
from typing import Optional, Tuple

import numpy as np
from scipy.spatial import cKDTree


EPSILON = 1e-9
"""Numerical zero, in inhabitants."""


@dataclass
class Inflow:
    """Population received by each unit from each label (polygon) during a step: gross, every iteration."""

    keys: np.ndarray
    """Sorted ``unit * nlabels + label``."""
    amounts: np.ndarray
    nlabels: int

    @classmethod
    def empty(cls, nlabels: int = 1) -> "Inflow":
        return cls(np.zeros(0, dtype=np.int64), np.zeros(0), max(1, nlabels))

    @classmethod
    def from_transfers(cls, receivers: np.ndarray, labels: np.ndarray, amounts: np.ndarray,
                       nlabels: int) -> "Inflow":
        nlabels = max(1, int(nlabels))
        receivers = np.asarray(receivers, dtype=np.int64)
        labels = np.asarray(labels, dtype=np.int64)
        amounts = np.asarray(amounts, dtype=np.float64)
        keep = labels >= 0
        keys, inverse = np.unique(receivers[keep] * nlabels + labels[keep], return_inverse=True)
        totals = np.bincount(inverse.ravel(), weights=amounts[keep], minlength=len(keys))
        return cls(keys, totals, nlabels)

    def received(self, units: np.ndarray, labels: np.ndarray) -> np.ndarray:
        """What each unit received from the matching label (0 where nothing)."""
        keys = np.asarray(units, dtype=np.int64) * self.nlabels + np.asarray(labels, dtype=np.int64)
        if len(self.keys) == 0:
            return np.zeros(len(keys))
        position = np.minimum(np.searchsorted(self.keys, keys), len(self.keys) - 1)
        return np.where(self.keys[position] == keys, self.amounts[position], 0.0)

    def total(self) -> float:
        return float(self.amounts.sum())


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
    inflow: Optional[Inflow] = None
    """What each unit received from each label, when ``labels`` were given."""


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
    labels: Optional[np.ndarray] = None,
    share_ties: bool = False,
    attraction: Optional[np.ndarray] = None,
) -> MigrationResult:
    """Move the excess population to the nearest units with free capacity.

    ``receivable`` marks the units allowed to receive population (false for
    no-inflow and evacuated units). A unit is a source if its excess is at
    least ``tolerance`` inhabitants, and a receiver if it is receivable and
    has at least ``tolerance`` free places.

    Units flagged in ``export_all`` (no-inflow zones) send away all their
    excess, even below the tolerance, so that their population never
    exceeds their ceiling (decision of 29/09/2026).

    ``labels`` (one integer per unit, e.g. its polygon; negative for none)
    turns on the record of what each unit receives from each label; it
    changes nothing else. ``share_ties`` splits the last share equally
    between the receivers tied at the k-th distance, instead of giving it to
    the lowest index (free strata mode, decision P16): fronts then grow
    without a preferred direction.

    ``attraction`` (one value >= 1 per unit; roads, plan B) changes the
    distance a migrant « feels »: the real distance divided by the
    attractiveness of the arrival unit. Without it, the nearest units by
    real distance receive, as before.
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
    if attraction is not None:
        attraction = np.asarray(attraction, dtype=np.float64)
        if len(attraction) != len(population) or np.any(attraction < 1 - 1e-12):
            raise ValueError("attraction: one value >= 1 per unit is expected")

    def is_source(excess: np.ndarray) -> np.ndarray:
        return (excess >= tolerance) | (strict & (excess > EPSILON))

    moved = 0.0
    iterations = 0
    exhausted = False
    record = labels is not None
    if record:
        labels = np.asarray(labels, dtype=np.int64)
        nlabels = int(labels.max(initial=-1)) + 1
        got_units, got_labels, got_amounts = [], [], []
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
        if attraction is not None:
            origin, targets, weights = attracted_receivers(coords[sources], coords[receivers], receivers, n,
                                                           attraction[receivers], share_ties)
            amounts = excess[sources][origin] * weights
        elif share_ties:
            origin, targets, weights = shared_receivers(coords[sources], coords[receivers], receivers, n)
            amounts = excess[sources][origin] * weights
        else:
            targets = nearest_receivers(coords[sources], coords[receivers], receivers, n).ravel()
            origin = np.repeat(np.arange(len(sources)), n)
            amounts = np.repeat(excess[sources] / n, n)
        # All transfers of an iteration are computed from the same state, then applied.
        np.add.at(population, targets, amounts)
        population[sources] = capacity[sources]
        moved += float(excess[sources].sum())
        if record:
            got_units.append(targets)
            got_labels.append(labels[sources][origin])
            got_amounts.append(amounts)

    remaining = float(np.maximum(population - capacity, 0).sum())
    converged = not np.any(is_source(population - capacity))
    inflow = None
    if record:
        inflow = (Inflow.from_transfers(np.concatenate(got_units), np.concatenate(got_labels),
                                        np.concatenate(got_amounts), nlabels)
                  if got_units else Inflow.empty(nlabels))
    return MigrationResult(population, iterations, converged, moved, remaining, exhausted, inflow)


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


def shared_receivers(
    source_xy: np.ndarray, receiver_xy: np.ndarray, receiver_ids: np.ndarray, n: int
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The ``n`` nearest receivers of each source, ties at the n-th distance sharing the last share.

    Returns ``(source position, receiver id, weight)``, one row per transfer;
    the weights of a source add up to 1. Receivers strictly closer than the
    n-th distance get ``1/n`` each; those at the n-th distance share the rest.
    """
    tree = cKDTree(receiver_xy)
    total = len(receiver_ids)
    window = min(total, n + 8)
    pending = np.arange(len(source_xy))
    origins, targets, weights = [], [], []
    while len(pending):
        dist, pos = tree.query(source_xy[pending], k=window)
        dist = dist.reshape(len(pending), window)
        pos = pos.reshape(len(pending), window)
        complete = (window == total) | (dist[:, n - 1] < dist[:, -1] * (1 - 1e-12))
        rows = np.flatnonzero(complete)
        if len(rows):
            d = dist[rows]
            nth = d[:, n - 1:n]
            closer = d < nth * (1 - 1e-12)
            tied = ~closer & (d <= nth * (1 + 1e-12))
            m = closer.sum(axis=1, keepdims=True)
            t = tied.sum(axis=1, keepdims=True)
            weight = np.where(closer, 1.0 / n, np.where(tied, (n - m) / (n * t), 0.0))
            r, c = np.nonzero(weight > 0)
            origins.append(pending[rows][r])
            targets.append(receiver_ids[pos[rows][r, c]])
            weights.append(weight[r, c])
        pending = pending[~complete]
        window = min(total, window * 2)
    return np.concatenate(origins), np.concatenate(targets), np.concatenate(weights)


def attracted_receivers(
    source_xy: np.ndarray, receiver_xy: np.ndarray, receiver_ids: np.ndarray, n: int,
    receiver_attraction: np.ndarray, share_ties: bool = True,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The ``n`` receivers of each source with the smallest « felt » distance (real distance / attractiveness).

    Same output as :func:`shared_receivers`. With ``share_ties``, receivers tied at the n-th felt distance
    share the last share; otherwise the lowest index wins. Receivers are fetched by real distance until
    no receiver further away can be felt closer: a receiver at real distance ``d`` is felt at least at
    ``d / max(attractiveness)``.
    """
    tree = cKDTree(receiver_xy)
    total = len(receiver_ids)
    top = float(receiver_attraction.max())
    window = min(total, 4 * n + 8)
    pending = np.arange(len(source_xy))
    origins, targets, weights = [], [], []
    while len(pending):
        dist, pos = tree.query(source_xy[pending], k=window)
        dist = dist.reshape(len(pending), window)
        pos = pos.reshape(len(pending), window)
        felt = dist / receiver_attraction[pos]
        rows = np.repeat(np.arange(len(pending)), window)
        order = np.lexsort((pos.ravel(), felt.ravel(), rows)).reshape(len(pending), window) % window
        felt = np.take_along_axis(felt, order, axis=1)
        pos = np.take_along_axis(pos, order, axis=1)
        nth = felt[:, n - 1:n]
        complete = (window == total) | (dist[:, -1] / top > nth[:, 0] * (1 + 1e-12))
        done = np.flatnonzero(complete)
        if len(done):
            f, p, d = felt[done], pos[done], nth[done]
            if share_ties:
                closer = f < d * (1 - 1e-12)
                tied = ~closer & (f <= d * (1 + 1e-12))
                m = closer.sum(axis=1, keepdims=True)
                t = tied.sum(axis=1, keepdims=True)
                weight = np.where(closer, 1.0 / n, np.where(tied, (n - m) / (n * t), 0.0))
            else:
                weight = np.zeros(f.shape)
                weight[:, :n] = 1.0 / n
            r, c = np.nonzero(weight > 0)
            origins.append(pending[done][r])
            targets.append(receiver_ids[p[r, c]])
            weights.append(weight[r, c])
        pending = pending[~complete]
        window = min(total, window * 2)
    return np.concatenate(origins), np.concatenate(targets), np.concatenate(weights)


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
