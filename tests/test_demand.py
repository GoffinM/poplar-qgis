"""Demand computed again on a finished run (plan_demande_et_routes.md, A)."""

import csv
import json
import os

import numpy as np
import pytest

from engine.__main__ import main
from engine.demand import FILE, PARAMETERS, latest_demand, recompute_demand
from engine.grid_layer import GridMismatch
from engine.raster_io import read_raster
from engine.scenario import load_scenario, scenario_from_dict
from engine.simulation import run
from test_free_polygons import square_city_world
from world import box, make_world

DENSITY = np.full((10, 10), 1000.0)
DENSITY[2:4, 2:4] = 3000.0
HALVES = [(box(0, 0, 5, 10), "A"), (box(5, 0, 10, 10), "B")]


def _water(a=20, b=60):
    return {"type": "water", "parameters": {"water_per_capita": {"A": a, "B": b}, "network_efficiency": {"*": 80}}}


def _grid(directory, key, year):
    return np.nan_to_num(read_raster(os.path.join(directory, f"{key}_{year}.tif")).values)


def _summary(directory):
    with open(os.path.join(directory, "summary.csv"), encoding="utf-8") as handle:
        return list(csv.reader(handle, delimiter=";"))


def _scenario(path, **changes):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data.update(changes)
    return scenario_from_dict(data, os.path.dirname(path))


@pytest.fixture
def water_run(tmp_path):
    path = make_world(str(tmp_path), DENSITY, zones=HALVES, indicators=[_water()],
                      time={"end_year": 2027, "output_years": [2024, 2026, 2027]})
    return run(load_scenario(path)), path


def test_each_run_keeps_its_population_per_unit(water_run):
    result, _ = water_run
    with np.load(os.path.join(result.directory, FILE)) as data:
        years = list(data["years"])
        population = data[f"population_{years[-1]}"]
        assert len(data["cell_id"]) == len(population) == len(data[f"classes_{years[-1]}"])
    assert years == ["2024", "2026", "2027"]
    assert population.sum() == pytest.approx(_grid(result.directory, "population", 2027).sum(), abs=0.5)


def test_same_parameters_give_the_same_demand(water_run):
    result, path = water_run
    demand = recompute_demand(result.directory, load_scenario(path))
    assert not demand.approximated
    assert demand.years == ["2024", "2026", "2027"]
    assert os.path.dirname(demand.directory) == result.directory
    assert os.path.basename(demand.directory).startswith("demande_")
    for key in ("water_domestic", "water_production_mean", "water_peak_hour"):
        np.testing.assert_allclose(_grid(demand.directory, key, 2027), _grid(result.directory, key, 2027))
    # Only the demand: the population stays in the run folder.
    names = os.listdir(demand.directory)
    assert not [n for n in names if n.startswith(("population_", "density_", "capacity_", "unallocated_"))]
    assert _summary(demand.directory) == _summary(result.directory)
    record = json.load(open(os.path.join(demand.directory, PARAMETERS), encoding="utf-8"))
    assert record["indicators"][0]["type"] == "water" and record["approximated"] is False
    assert latest_demand(result.directory) == demand.directory


def test_new_allowance_changes_only_the_demand(water_run):
    result, path = water_run
    demand = recompute_demand(result.directory, _scenario(path, indicators=[_water(a=40, b=60)]))
    before = _grid(result.directory, "water_domestic", 2027)
    domestic = _grid(demand.directory, "water_domestic", 2027)
    np.testing.assert_allclose(domestic[:, :5], 2 * before[:, :5], rtol=1e-6)
    np.testing.assert_allclose(domestic[:, 5:], before[:, 5:], rtol=1e-6)
    # The run itself is not overwritten, and a second set of parameters goes to another folder.
    np.testing.assert_allclose(_grid(result.directory, "water_domestic", 2027), before)
    again = recompute_demand(result.directory, load_scenario(path))
    assert again.directory != demand.directory and latest_demand(result.directory) == again.directory


def test_runs_written_before_share_the_cell_population(water_run):
    result, path = water_run
    os.remove(os.path.join(result.directory, FILE))
    demand = recompute_demand(result.directory, load_scenario(path))
    assert demand.approximated
    # Whole cells: exact, but for the rasters' populations rounded to the inhabitant.
    population = _grid(result.directory, "population", 2026)
    np.testing.assert_allclose(_grid(demand.directory, "water_domestic", 2026)[:, 5:], population[:, 5:] * 60 / 1000,
                               rtol=1e-6)
    gap = _grid(demand.directory, "water_domestic", 2026) - _grid(result.directory, "water_domestic", 2026)
    assert np.abs(gap).max() <= 60 / 1000 + 1e-6                                # 1 inhabitant at most
    assert gap.sum() == pytest.approx(0, abs=0.06)
    record = json.load(open(os.path.join(demand.directory, PARAMETERS), encoding="utf-8"))
    assert record["approximated"] is True and record["note"]


def test_another_grid_is_refused(water_run):
    result, path = water_run
    with pytest.raises(GridMismatch):
        recompute_demand(result.directory, _scenario(path, cell_size=50.0))


def test_a_scenario_without_indicator_is_refused(water_run):
    result, path = water_run
    with pytest.raises(ValueError):
        recompute_demand(result.directory, _scenario(path, indicators=[]))


def test_an_indicator_can_be_added_to_a_run_without_one(tmp_path):
    path = make_world(str(tmp_path), DENSITY, zones=HALVES, time={"end_year": 2026})
    result = run(load_scenario(path))
    assert not [n for n in os.listdir(result.directory) if n.startswith("water_")]
    demand = recompute_demand(result.directory, _scenario(path, indicators=[_water()]))
    assert not demand.approximated
    population = _grid(result.directory, "population", 2026)
    domestic = _grid(demand.directory, "water_domestic", 2026)
    assert domestic[:, 5:].sum() == pytest.approx(population[:, 5:].sum() * 60 / 1000, abs=0.06)
    assert domestic[0, 0] == pytest.approx(20 / 60 * domestic[0, 9])


def test_free_mode_uses_the_class_of_each_year(tmp_path):
    # Colonised cells take the urban allowance of their new polygon (decision A-c).
    path = square_city_world(str(tmp_path), years=3)
    water = {"type": "water", "parameters": {"water_per_capita": {"U": 80, "R": 20}}}
    data = json.load(open(path, encoding="utf-8"))
    data["indicators"] = [water]
    json.dump(data, open(path, "w", encoding="utf-8"))
    result = run(load_scenario(path))
    assert result.polygons.events                                          # some cells were colonised
    demand = recompute_demand(result.directory, load_scenario(path))
    for year in (2025, 2027):
        np.testing.assert_allclose(_grid(demand.directory, "water_domestic", year),
                                   _grid(result.directory, "water_domestic", year))
    row, col = result.polygons.events[0]["row"], result.polygons.events[0]["col"]
    population = _grid(result.directory, "population", 2027)
    assert _grid(demand.directory, "water_domestic", 2027)[row, col] == pytest.approx(population[row, col] * 80 / 1000,
                                                                                      abs=0.08)


def test_command_line(water_run, capsys):
    result, _ = water_run
    assert main(["demand", result.directory]) == 0
    assert latest_demand(result.directory) in capsys.readouterr().out
    assert main(["demand", os.path.join(result.directory, "nowhere")]) == 1
