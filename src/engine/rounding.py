"""Integer populations for the outputs (spec §8.2)."""

from __future__ import annotations

import numpy as np


def round_preserving_total(values: np.ndarray) -> np.ndarray:
    """Largest-remainder rounding: integers whose sum is ``round(sum(values))``.

    Ties between equal remainders go to the lowest index, so the result is
    deterministic. Only outputs are rounded, never the internal state.
    """
    values = np.asarray(values, dtype=np.float64)
    if np.any(values < 0):
        raise ValueError("populations cannot be negative")
    floors = np.floor(values)
    missing = int(round(values.sum())) - int(floors.sum())
    result = floors.astype(np.int64)
    if missing > 0:
        remainders = values - floors
        order = np.lexsort((np.arange(len(values)), -remainders))
        result[order[:missing]] += 1
    return result
