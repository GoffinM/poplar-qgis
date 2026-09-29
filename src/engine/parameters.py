"""Parameters that vary in space and time (spec §2.3).

A parameter is given at one or more pivot years. Between pivots the value
is interpolated linearly; outside them it is held constant (default) or
extended linearly.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

CONSTANT = "constant"
LINEAR = "linear"
DEFAULT_KEY = "*"

DENSITY_FACTORS = {"hab/km2": 1.0, "hab/ha": 100.0}


def to_hab_per_km2(values, unit: str):
    """Convert densities to the internal unit (inhabitants per km2)."""
    try:
        return np.asarray(values, dtype=np.float64) * DENSITY_FACTORS[unit]
    except KeyError:
        raise ValueError(f"unknown density unit: {unit!r} (expected one of {sorted(DENSITY_FACTORS)})") from None


def from_hab_per_km2(values, unit: str):
    return np.asarray(values, dtype=np.float64) / DENSITY_FACTORS[unit]


@dataclass
class TimeSeries:
    """Piecewise linear function of time defined by pivot years."""

    years: Tuple[float, ...]
    values: Tuple[float, ...]
    extrapolation: str = CONSTANT

    def __post_init__(self) -> None:
        if len(self.years) == 0 or len(self.years) != len(self.values):
            raise ValueError("a time series needs as many values as pivot years (at least one)")
        order = np.argsort(self.years)
        years = tuple(float(self.years[i]) for i in order)
        if len(set(years)) != len(years):
            raise ValueError(f"duplicate pivot years: {years}")
        self.years = years
        self.values = tuple(float(self.values[i]) for i in order)
        if self.extrapolation not in (CONSTANT, LINEAR):
            raise ValueError(f"unknown extrapolation: {self.extrapolation}")

    @classmethod
    def constant(cls, value: float) -> "TimeSeries":
        return cls((0.0,), (float(value),))

    def value_at(self, year):
        """Value at ``year`` (scalar or array)."""
        t = np.asarray(year, dtype=np.float64)
        years = np.array(self.years)
        values = np.array(self.values)
        result = np.interp(t, years, values)
        if self.extrapolation == LINEAR and len(years) > 1:
            head = (values[1] - values[0]) / (years[1] - years[0])
            tail = (values[-1] - values[-2]) / (years[-1] - years[-2])
            result = np.where(t < years[0], values[0] + head * (t - years[0]), result)
            result = np.where(t > years[-1], values[-1] + tail * (t - years[-1]), result)
        return result if result.ndim else float(result)

    def mean(self, start: float, end: float) -> float:
        """Exact mean of the function over [start, end] (spec §5.1, S4)."""
        if end < start:
            raise ValueError("end must not precede start")
        if end == start:
            return self.value_at(start)
        inner = [y for y in self.years if start < y < end]
        points = np.array([start] + inner + [end])
        values = self.value_at(points)
        integral = np.sum((values[1:] + values[:-1]) / 2.0 * np.diff(points))
        return float(integral / (end - start))


@dataclass
class ParameterTable:
    """One parameter, given per key (a typology class) with an optional default.

    The key ``"*"`` applies to every class that has no value of its own.
    """

    name: str
    series: Dict[str, TimeSeries] = field(default_factory=dict)

    def for_key(self, key: Optional[str]) -> TimeSeries:
        if key is not None and key in self.series:
            return self.series[key]
        if DEFAULT_KEY in self.series:
            return self.series[DEFAULT_KEY]
        raise KeyError(f"parameter {self.name!r} has no value for class {key!r} and no default ('*')")

    def value_by_class(self, class_names: Sequence[str], year: float) -> np.ndarray:
        return np.array([self.for_key(name).value_at(year) for name in class_names], dtype=np.float64)

    def mean_by_class(self, class_names: Sequence[str], start: float, end: float) -> np.ndarray:
        return np.array([self.for_key(name).mean(start, end) for name in class_names], dtype=np.float64)


def per_unit(class_index: np.ndarray, by_class: np.ndarray, name: str) -> np.ndarray:
    """Spread per-class values to units; units without class are rejected."""
    if np.any(class_index < 0):
        raise ValueError(f"some units have no typology class, so {name!r} cannot be assigned to them")
    return by_class[class_index]


def check_bounds(values: np.ndarray, name: str, lower: float, inclusive: bool = False) -> Tuple[np.ndarray, List[str]]:
    """Clamp values below ``lower`` (linear extrapolation can overshoot) and report it."""
    bad = values < lower if inclusive else values <= lower
    warnings = []
    if np.any(bad):
        warnings.append(f"{name}: {int(bad.sum())} value(s) out of bounds, clamped to {lower}")
        values = np.where(bad, lower, values)
    return values, warnings


def load_parameters_csv(path: str, extrapolation: str = CONSTANT) -> Dict[str, ParameterTable]:
    """Read parameters in long format: ``key, year, parameter, value``.

    ``key`` is a typology class or ``*``; an empty ``year`` means a value
    that does not change over time.
    """
    rows: Dict[Tuple[str, str], List[Tuple[float, float]]] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for line in csv.DictReader(handle):
            parameter = line["parameter"].strip()
            key = line["key"].strip() or DEFAULT_KEY
            year = line.get("year", "").strip()
            rows.setdefault((parameter, key), []).append((float(year) if year else 0.0, float(line["value"])))
    tables: Dict[str, ParameterTable] = {}
    for (parameter, key), points in rows.items():
        years, values = zip(*points)
        tables.setdefault(parameter, ParameterTable(parameter)).series[key] = TimeSeries(years, values, extrapolation)
    return tables
