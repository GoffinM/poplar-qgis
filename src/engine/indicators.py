"""Indicators derived from the population (spec §8.4).

An indicator turns the population of each unit into one or more
quantities, using its own parameters (given like the other parameters: a
single value, per class, per zone, and per pivot year). New uses are added
by writing a subclass of :class:`Indicator` and registering it in
:data:`REGISTRY`; nothing else in the engine changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Type

import numpy as np

from .parameters import ParameterTable, TimeSeries, unit_series, unit_values


@dataclass(frozen=True)
class Output:
    key: str
    """Used in file names (``<key>_<year>.tif``) and message codes (``indicator_<key>``)."""
    unit: str


class Indicator:
    code: str = ""
    outputs: List[Output] = []
    required: List[str] = []
    defaults: Dict[str, float] = {}

    def __init__(self, parameters: Mapping[str, ParameterTable]):
        missing = [name for name in self.required if name not in parameters and name not in self.defaults]
        if missing:
            raise ValueError(f"indicator {self.code!r}: missing parameter(s) {missing}")
        self.parameters = dict(parameters)
        for name, value in self.defaults.items():
            table = self.parameters.setdefault(name, ParameterTable(name, {}))
            # The default also covers the zones and classes the user did not list.
            table.series.setdefault("*", TimeSeries.constant(value))

    def compute(self, units, population: np.ndarray, year: float) -> Dict[str, np.ndarray]:
        """Value of every output for each unit."""
        raise NotImplementedError

    def value(self, name: str, units, year: float) -> np.ndarray:
        return unit_values(self.parameters[name], units, year)


class WaterDemand(Indicator):
    """Drinking-water demand (spec §8.4, decisions X2 of 29/09/2026).

    - domestic consumption = population x per-capita allowance / 1000 (m3/day)
    - mean consumption = domestic + non-domestic (share of the domestic
      consumption, plus fixed volumes per zone shared pro rata population)
    - mean production = mean consumption / network efficiency
    - peak-day production = mean production x peak-day factor
    - peak-hour flow = mean consumption x peak-day x peak-hour factors / 24 (m3/hour);
      the network efficiency applies to daily demand only
    """

    code = "water"
    outputs = [
        Output("water_domestic", "m3/d"),
        Output("water_consumption_mean", "m3/d"),
        Output("water_production_mean", "m3/d"),
        Output("water_production_peak_day", "m3/d"),
        Output("water_peak_hour", "m3/h"),
    ]
    required = ["water_per_capita"]
    defaults = {
        "non_domestic_share": 0.0,
        "non_domestic_volume": 0.0,
        "network_efficiency": 100.0,
        "peak_day_factor": 1.0,
        "peak_hour_factor": 1.0,
    }

    def compute(self, units, population, year):
        population = np.asarray(population, dtype=np.float64)
        domestic = population * self.value("water_per_capita", units, year) / 1000.0
        non_domestic = domestic * self.value("non_domestic_share", units, year) / 100.0
        non_domestic += self._fixed_volumes(units, population, year)
        consumption = domestic + non_domestic
        efficiency = self.value("network_efficiency", units, year) / 100.0
        if np.any(efficiency <= 0) or np.any(efficiency > 1):
            raise ValueError("the network efficiency must be in ]0, 100] %")
        production = consumption / efficiency
        peak_day = self.value("peak_day_factor", units, year)
        return {
            "water_domestic": domestic,
            "water_consumption_mean": consumption,
            "water_production_mean": production,
            "water_production_peak_day": production * peak_day,
            "water_peak_hour": consumption * peak_day * self.value("peak_hour_factor", units, year) / 24.0,
        }

    def _fixed_volumes(self, units, population, year):
        """Fixed non-domestic volumes (m3/d) given per zone or class, shared pro rata population."""
        series, group = unit_series(self.parameters["non_domestic_volume"], units)
        result = np.zeros(len(population))
        for g, s in enumerate(series):
            volume = s.value_at(year)
            if volume == 0:
                continue
            members = group == g
            total = population[members].sum()
            if total > 0:
                result[members] = volume * population[members] / total
        return result


REGISTRY: Dict[str, Type[Indicator]] = {WaterDemand.code: WaterDemand}


def create_indicator(code: str, parameters: Mapping[str, ParameterTable]) -> Indicator:
    try:
        return REGISTRY[code](parameters)
    except KeyError:
        raise ValueError(f"unknown indicator {code!r} (available: {sorted(REGISTRY)})") from None
