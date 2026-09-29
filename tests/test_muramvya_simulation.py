"""Muramvya from 2024 to 2060 with the example scenario, compared with the legacy final output."""

import os

import numpy as np
import pytest
from osgeo import ogr

from conftest import MURAMVYA, REFERENCE
from engine.growth import growth_factor
from engine.raster_io import read_raster
from engine.scenario import load_scenario
from engine.simulation import run


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    scenario = load_scenario(os.path.join(MURAMVYA, "scenario_muramvya.json"))
    scenario.output_directory = str(tmp_path_factory.mktemp("muramvya"))
    return run(scenario), scenario


def _raster(result, name):
    return np.nan_to_num(read_raster(os.path.join(result.directory, name)).values)


def test_run_succeeds_and_conserves_the_population(result):
    run_result, scenario = result
    assert run_result.status == "success"
    assert all(abs(step.balance_error) < 1e-6 for step in run_result.steps)
    rates = scenario.parameter_tables()["growth_rate"].for_key("Rural")
    expected = np.prod([growth_factor(rates.mean(y, y + 1), 1) for y in range(2024, 2060)])
    assert run_result.final_population / run_result.initial_population == pytest.approx(expected, rel=1e-9)


def test_growth_matches_the_legacy_final_output(result):
    run_result, _ = result
    ours = _raster(run_result, "population_2060.tif").sum() / _raster(run_result, "population_2024.tif").sum()
    assert ours == pytest.approx(309_642 / 164_805, rel=1e-3)


def test_spatial_pattern_matches_the_legacy_final_output(result):
    run_result, _ = result
    raster = read_raster(os.path.join(run_result.directory, "population_2060.tif"))
    ours = np.nan_to_num(raster.values)
    x0, y0 = raster.geotransform[0], raster.geotransform[3]
    reference = np.zeros_like(ours)
    datasource = ogr.Open(os.path.join(REFERENCE, "pentree_final.shp"))
    for feature in datasource.GetLayer(0):
        geometry = feature.GetGeometryRef()
        if geometry is None or geometry.GetArea() == 0:
            continue
        point = geometry.PointOnSurface()
        row, col = int((y0 - point.GetY()) // 250), int((point.GetX() - x0) // 250)
        reference[row, col] += feature.GetField("Pop2060") or 0
    compared = reference > 0
    assert np.corrcoef(ours[compared], reference[compared])[0, 1] > 0.95


def test_water_demand_is_written(result):
    run_result, _ = result
    population = _raster(run_result, "population_2060.tif").sum()
    domestic = _raster(run_result, "water_domestic_2060.tif").sum()
    assert domestic == pytest.approx(population * 20 / 1000, rel=1e-3)
    production = _raster(run_result, "water_production_mean_2060.tif").sum()
    assert production == pytest.approx(domestic * 1.10 / 0.75, rel=1e-3)
