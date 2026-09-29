"""Capacity of each unit, in inhabitants (spec §4)."""

from __future__ import annotations

import numpy as np


def capacity(
    area_km2: np.ndarray,
    base_population: np.ndarray,
    dmax_hab_km2: np.ndarray,
    no_inflow: np.ndarray,
) -> np.ndarray:
    """``C = a x max(d0, dmax)``, or ``C = P0`` in no-inflow units (A4, A7-bis c1).

    A unit already above ``dmax`` at the base year keeps its base density as
    its ceiling.
    """
    area = np.asarray(area_km2, dtype=np.float64)
    p0 = np.asarray(base_population, dtype=np.float64)
    ceiling = np.maximum(p0, area * np.asarray(dmax_hab_km2, dtype=np.float64))
    return np.where(np.asarray(no_inflow, dtype=bool), p0, ceiling)
