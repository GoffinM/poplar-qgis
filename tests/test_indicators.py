import numpy as np
import pytest

from engine.grid import Grid
from engine.indicators import REGISTRY, Indicator, Output, create_indicator
from engine.parameters import ParameterTable, TimeSeries
from engine.units import Zone, build_units
from helpers import square


def _table(name, **by_key):
    return ParameterTable(name, {k: TimeSeries.constant(v) for k, v in by_key.items()})


@pytest.fixture
def two_units(utm35s_wkt):
    grid = Grid.covering((0, 0, 500, 250), 250, utm35s_wkt)
    zones = [Zone(square(0, 0, 250, 250), "Rural"), Zone(square(250, 0, 500, 250), "Urbain")]
    return build_units(grid, square(0, 0, 500, 250), zones)


def test_water_demand_formulas(two_units):
    water = create_indicator("water", {
        "water_per_capita": _table("water_per_capita", Rural=20, Urbain=60),
        "non_domestic_share": _table("non_domestic_share", **{"*": 10}),
        "network_efficiency": _table("network_efficiency", **{"*": 75}),
        "peak_day_factor": _table("peak_day_factor", **{"*": 1.3}),
        "peak_hour_factor": _table("peak_hour_factor", **{"*": 1.8}),
    })
    result = water.compute(two_units, np.array([1000.0, 500.0]), 2030)
    np.testing.assert_allclose(result["water_domestic"], [20.0, 30.0])
    np.testing.assert_allclose(result["water_consumption_mean"], [22.0, 33.0])
    np.testing.assert_allclose(result["water_production_mean"], [22.0 / 0.75, 44.0])
    np.testing.assert_allclose(result["water_production_peak_day"], [22.0 / 0.75 * 1.3, 44.0 * 1.3])
    np.testing.assert_allclose(result["water_peak_hour"], [22.0 * 1.3 * 1.8 / 24, 33.0 * 1.3 * 1.8 / 24])


def test_fixed_non_domestic_volume_is_shared_pro_rata(two_units):
    water = create_indicator("water", {
        "water_per_capita": _table("water_per_capita", **{"*": 20}),
        "non_domestic_volume": _table("non_domestic_volume", Urbain=15),
    })
    result = water.compute(two_units, np.array([1000.0, 500.0]), 2030)
    np.testing.assert_allclose(result["water_consumption_mean"], [20.0, 10.0 + 15.0])


def test_missing_allowance_is_rejected():
    with pytest.raises(ValueError):
        create_indicator("water", {})
    with pytest.raises(ValueError):
        create_indicator("unknown", {})


def test_new_uses_can_be_registered(two_units):
    class SchoolPlaces(Indicator):
        code = "schools"
        outputs = [Output("school_places", "places")]
        required = ["school_ratio"]

        def compute(self, units, population, year):
            return {"school_places": population * self.value("school_ratio", units, year)}

    REGISTRY["schools"] = SchoolPlaces
    try:
        schools = create_indicator("schools", {"school_ratio": _table("school_ratio", **{"*": 0.2})})
        np.testing.assert_allclose(schools.compute(two_units, np.array([100.0, 50.0]), 2030)["school_places"],
                                   [20.0, 10.0])
    finally:
        del REGISTRY["schools"]
