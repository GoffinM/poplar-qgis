"""Starting population from the roofs, on Muramvya (plan of phase 6, step 6.3)."""

import json
import os

import numpy as np
import pytest

from engine.calibration import legacy_curve
from engine.raster_io import read_raster
from engine.scenario import scenario_from_dict
from engine.simulation import _Model, run
from paths import MURAMVYA

RURAL, URBAN = "MURAMVYA  RURAL", "MURAMVYA URBAIN"   # names of the communes in the layer (two spaces)
CENSUS = {RURAL: 136_759, URBAN: 34_251}              # 2024 populations of the former workbooks


def _scenario(tmp_path, calibration, **time):
    with open(os.path.join(MURAMVYA, "scenario_muramvya.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    data["base_population"] = {"source": "buildings", "raster": "pop2023_muramvya.tif"}
    data["calibration"] = dict({
        "buildings": {"source": "buildings_muramvya.gpkg", "area_field": "area_m2"},
        "strata": {"source": "commune_muramvya.shp", "field": "COMMUNES", "group_field": "Type"},
    }, **calibration)
    data["time"].update(dict({"end_year": 2026, "output_years": [2024, 2026]}, **time))
    data["output"] = {"directory": str(tmp_path / "out")}
    return scenario_from_dict(data, MURAMVYA)


LEGACY = {"groups": {"Rural": legacy_curve("Rural").to_dict(), "Urbain1": legacy_curve("Urbain").to_dict()},
          "recalibrate": False}


def test_legacy_mode_gives_the_population_of_the_workbooks(tmp_path):
    model = _Model.load(_scenario(tmp_path, LEGACY))
    strata = model.calibration_report["strata"]
    assert strata[RURAL]["population"] == pytest.approx(139_099.65, abs=0.05)
    assert strata[URBAN]["population"] == pytest.approx(33_253.08, abs=0.05)
    assert model.p0.sum() == pytest.approx(172_352.74, abs=0.1)
    assert model.calibration_report["roofs"]["outside_study_area"] == 0


def test_legacy_mode_rebuilds_the_2023_raster(tmp_path):
    """État des lieux §11.3: POP2023 is the sum of the roofs per 250 m pixel divided by its area."""
    model = _Model.load(_scenario(tmp_path, LEGACY))
    units = model.units
    per_cell = units.per_cell(model.p0)
    area = units.per_cell(units.area_km2)
    raster = read_raster(os.path.join(MURAMVYA, "pop2023_muramvya.tif"))
    grid = model.grid
    col0 = int(round((grid.x0 - raster.geotransform[0]) / raster.pixel_width))
    row0 = int(round((raster.geotransform[3] - grid.y0) / raster.pixel_height))
    reference = np.full((grid.nrows, grid.ncols), np.nan)             # the raster on the grid of the model
    rows, cols = np.indices(reference.shape)
    r, c = rows + row0, cols + col0
    ok = (r >= 0) & (r < raster.nrows) & (c >= 0) & (c < raster.ncols)
    reference[ok] = raster.values[r[ok], c[ok]] * raster.pixel_area_m2 / 1e6
    whole = np.isclose(area, (grid.cell_size / 1000) ** 2) & (np.nan_to_num(reference) > 5)
    ratio = reference[whole] / per_cell[whole]                        # raster / roofs, as in §11.3
    assert np.median(ratio) == pytest.approx(1.002, abs=0.002)
    assert np.mean((ratio > 0.99) & (ratio < 1.02)) > 0.97          # 97.8 % (98 % in §11.3)


def test_improved_mode_is_recalibrated_on_the_census(tmp_path):
    model = _Model.load(_scenario(tmp_path, {"census": CENSUS, "census_year": 2024}))
    report = model.calibration_report
    assert report["strata"][RURAL]["population"] == pytest.approx(136_759)
    assert report["strata"][URBAN]["population"] == pytest.approx(34_251)
    for group in report["groups"].values():
        assert group["curve"]["method"] == "segments" and group["values_from"] == "hypothesis"
        assert group["diagnostics"]["monotone"]


def test_census_carried_to_the_target_year_with_a_growth_rate(tmp_path):
    calibration = {"census": CENSUS, "census_year": 2024, "gap_growth_rate": 2.2}
    model = _Model.load(_scenario(tmp_path, calibration, base_year=2023, first_migration_year=2024))
    assert model.p0.sum() == pytest.approx(sum(CENSUS.values()) / 1.022, rel=1e-9)
    assert model.calibration_report["target_year"] == 2023


def test_natural_breaks_and_one_stratum_for_the_whole_area(tmp_path):
    calibration = {"strata": None, "census": {"*": 171_010},
                   "groups": {"*": {"edges_from": "breaks", "n_classes": 6, "values_from": "hypothesis"}}}
    model = _Model.load(_scenario(tmp_path, calibration))
    group = model.calibration_report["groups"]["*"]
    assert len(group["breaks"]) == 7 and group["breaks"][0] == 10 and group["breaks"][-1] == 450
    assert model.p0.sum() == pytest.approx(171_010)


def test_a_run_from_the_roofs_writes_the_calibration_report(tmp_path):
    result = run(_scenario(tmp_path, {"census": CENSUS, "census_year": 2024}))
    assert result.status in ("success", "success_with_adjustments")
    assert result.initial_population == pytest.approx(171_010)
    with open(os.path.join(result.directory, "calibration.json"), encoding="utf-8") as handle:
        report = json.load(handle)
    assert set(report["groups"]) == {"Rural", "Urbain1"} and report["recalibrated"]
    population = read_raster(os.path.join(result.directory, "population_2024.tif")).values
    assert np.nansum(np.where(population >= 0, population, 0)) == 171_010
