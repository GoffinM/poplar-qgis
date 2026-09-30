"""The cell layer of a run (mailles.gpkg / mailles.shp): every cell of the study area, every result."""

import csv
import os

import numpy as np
import pytest
from osgeo import ogr

from engine.raster_io import read_raster
from engine.scenario import ScenarioError, load_scenario
from engine.simulation import run
from world import box, make_world

UNIFORM = np.full((10, 10), 1000.0)


def _run(tmp_path, grid_layer, **kwargs):
    scenario = load_scenario(make_world(str(tmp_path), UNIFORM, output={"directory": "out", "grid_layer": grid_layer},
                                        time={"base_year": 2024, "end_year": 2030, "time_step": 1,
                                              "first_migration_year": 2025, "output_years": [2025, 2030]},
                                        **kwargs))
    return run(scenario)


def _features(path):
    datasource = ogr.Open(path)
    layer = datasource.GetLayer(0)
    definition = layer.GetLayerDefn()
    names = [definition.GetFieldDefn(i).GetName() for i in range(definition.GetFieldCount())]
    rows = [{name: f.GetField(name) for name in names} for f in layer]
    return names, rows


def test_every_cell_with_every_result(tmp_path):
    zones = [(box(0, 0, 5, 10), "Rural"), (box(5, 0, 10, 10), "Urbain")]
    result = _run(tmp_path, "gpkg", zones=zones)
    path = os.path.join(result.directory, "mailles.gpkg")
    assert path in result.outputs and not os.path.exists(os.path.join(result.directory, "mailles.shp"))
    names, rows = _features(path)
    assert names[:6] == ["cell_id", "row", "col", "area_km2", "class", "admin"]
    assert {"population_2024", "population_2030", "density_2030", "capacity_2025"} <= set(names)
    assert len(rows) == 100                                                     # every cell, empty or not
    for year in ("2024", "2025", "2030"):
        raster = np.nan_to_num(read_raster(os.path.join(result.directory, f"population_{year}.tif")).values)
        assert sum(r[f"population_{year}"] for r in rows) == raster.sum()
    by_cell = {r["cell_id"]: r for r in rows}
    assert by_cell[0]["class"] == "Rural" and by_cell[9]["class"] == "Urbain" and by_cell[0]["row"] == 0
    assert by_cell[0]["area_km2"] == pytest.approx(0.01)


def test_shapefile_names_and_their_table(tmp_path):
    result = _run(tmp_path, "both")
    names, rows = _features(os.path.join(result.directory, "mailles.shp"))
    assert all(len(n) <= 10 for n in names) and {"pop2025", "den2030", "cap2024"} <= set(names)
    with open(os.path.join(result.directory, "mailles_champs.csv"), encoding="utf-8-sig") as handle:
        table = {row["champ_shp"]: row for row in csv.DictReader(handle, delimiter=";")}
    assert table["den2030"]["grandeur"] == "density" and table["den2030"]["unite"] == "hab/km2"
    assert os.path.exists(os.path.join(result.directory, "mailles.gpkg"))


def test_no_layer_on_request_and_invalid_choice(tmp_path):
    result = _run(tmp_path / "a", "none")
    assert not [p for p in result.outputs if "mailles" in p]
    with pytest.raises(ScenarioError) as error:
        _run(tmp_path / "b", "kml")
    assert "output.grid_layer" in str(error.value)
