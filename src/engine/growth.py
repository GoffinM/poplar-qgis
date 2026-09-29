"""Natural growth over a time step (spec §5.1)."""

from __future__ import annotations

import numpy as np


def growth_factor(mean_rate_percent, duration_years: float):
    """``(1 + r/100) ** duration``, where ``r`` is the mean annual rate over the step."""
    if duration_years < 0:
        raise ValueError("the duration of a step cannot be negative")
    rate = np.asarray(mean_rate_percent, dtype=np.float64)
    if np.any(rate <= -100):
        raise ValueError("a growth rate must stay above -100 %")
    return (1.0 + rate / 100.0) ** duration_years


def grow(population: np.ndarray, mean_rate_percent, duration_years: float) -> np.ndarray:
    return np.asarray(population, dtype=np.float64) * growth_factor(mean_rate_percent, duration_years)
