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


def test_default_model_fits_the_roof_area_per_inhabitant(tmp_path):
    """Whole inhabitants per class from one roof area per inhabitant, fitted to the census (29/09/2026)."""
    model = _Model.load(_scenario(tmp_path, {"census": CENSUS, "census_year": 2024}))
    report = model.calibration_report
    assert not report["recalibrated"]
    for group, stratum in (("Rural", RURAL), ("Urbain1", URBAN)):
        entry, settings = report["groups"][group], report["groups"][group]["settings"]
        assert settings["method"] == "steps" and settings["classes"] == {"method": "breaks", "count": 8}
        assert entry["area_per_person_fitted"] and 3 < entry["area_per_person"] < 40
        values = entry["retained_values"]
        assert all(float(v).is_integer() for v in values) and values == sorted(values)
        assert abs(entry["gap_percent"]) < 2 and not entry["alert"]            # within the alert threshold
        # steps: the table of classes is exactly what the roofs receive
        assert entry["population_before_recalibration"] == pytest.approx(
            sum(n * v for n, v in zip(entry["class_counts"], values)))
        assert report["strata"][stratum]["factor"] == 1.0
        assert report["strata"][stratum]["proposed_factor"] == pytest.approx(
            CENSUS[stratum] / report["strata"][stratum]["computed"])
        limits = entry["limits"]
        assert limits["floor"] < 15 and 90 < limits["ceiling"] < 200 and limits["exclude_above"] == 450
        assert entry["cumulative"]["roofs"][-1] > 0.9


def test_recalibration_when_asked(tmp_path):
    model = _Model.load(_scenario(tmp_path, {"census": CENSUS, "census_year": 2024, "recalibrate": True}))
    assert model.calibration_report["strata"][RURAL]["population"] == pytest.approx(136_759)
    assert model.calibration_report["strata"][URBAN]["population"] == pytest.approx(34_251)


def test_census_carried_to_the_target_year_with_a_growth_rate(tmp_path):
    calibration = {"census": CENSUS, "census_year": 2024, "gap_growth_rate": 2.2, "recalibrate": True}
    model = _Model.load(_scenario(tmp_path, calibration, base_year=2023, first_migration_year=2024))
    assert model.p0.sum() == pytest.approx(sum(CENSUS.values()) / 1.022, rel=1e-9)
    assert model.calibration_report["target_year"] == 2023


@pytest.mark.parametrize("cut", ["breaks", "equal", "quantile"])
def test_class_cuts_floor_and_ceiling(tmp_path, cut):
    group = {"classes": {"method": cut, "count": 6}, "floor": {"value": 12}, "ceiling": {"percentile": 80},
             "exclude_above": None, "min_per_roof": 1, "max_per_roof": 12}
    calibration = {"strata": None, "census": {"*": 171_010}, "groups": {"*": group}}
    model = _Model.load(_scenario(tmp_path, calibration))
    entry = model.calibration_report["groups"]["*"]
    edges = entry["curve"]["edges"]
    assert edges[0] == 12 and len(edges) <= 7 and edges == sorted(edges)
    assert entry["limits"]["exclude_above"] is None and entry["excluded_large"] == 0
    assert edges[-1] == pytest.approx(entry["limits"]["ceiling"])
    assert abs(entry["gap_percent"]) < 3


def test_no_floor_no_ceiling_and_manual_overrides(tmp_path):
    group = {"classes": {"method": "manual", "edges": [0, 20, 40, 60, 80]}, "floor": None, "ceiling": None,
             "values_from": "area_per_person", "area_per_person": 12, "overrides": {"3": 9}}
    model = _Model.load(_scenario(tmp_path, {"strata": None, "groups": {"*": group}}))
    entry = model.calibration_report["groups"]["*"]
    assert entry["excluded_small"] == 0 and entry["area_per_person"] == 12
    assert entry["proposed_values"] == [1.0, 3.0, 4.0, 6.0] and entry["retained_values"] == [1.0, 3.0, 4.0, 9.0]
    assert entry["overridden"] == [3]


def test_invalid_group_settings_are_explained(tmp_path):
    from engine.scenario import ScenarioError

    with pytest.raises(ScenarioError, match="classes.method"):
        _scenario(tmp_path, {"groups": {"*": {"classes": {"method": "random"}}}})
    with pytest.raises(ScenarioError, match="values is required"):
        _scenario(tmp_path, {"groups": {"*": {"values_from": "manual"}}})


def test_a_run_from_the_roofs_writes_the_calibration_report(tmp_path):
    result = run(_scenario(tmp_path, {"census": CENSUS, "census_year": 2024, "recalibrate": True}))
    assert result.status in ("success", "success_with_adjustments")
    assert result.initial_population == pytest.approx(171_010)
    with open(os.path.join(result.directory, "calibration.json"), encoding="utf-8") as handle:
        report = json.load(handle)
    assert set(report["groups"]) == {"Rural", "Urbain1"} and report["recalibrated"]
    population = read_raster(os.path.join(result.directory, "population_2024.tif")).values
    assert np.nansum(np.where(population >= 0, population, 0)) == 171_010


def test_a_missing_raster_is_ignored_with_roofs_and_named_otherwise(tmp_path):
    from engine.scenario import ScenarioError

    scenario = _scenario(tmp_path, {"census": CENSUS, "census_year": 2024})
    scenario.base_population_raster = "//sher/Transfert_tempo/absent.tif"
    model = _Model.load(scenario)
    assert "raster_ignored" in [w.code for w in model.warnings]
    assert model.p0.sum() > 170_000
    scenario.population_source = "raster"
    with pytest.raises(ScenarioError) as error:
        _Model.load(scenario)
    assert [m.code for m in error.value.messages] == ["file_not_found_raster"]
    assert "onglet Données" in error.value.messages[0].render("fr")
