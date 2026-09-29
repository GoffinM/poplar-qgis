import json
import os

import pytest

from paths import MURAMVYA
from engine.scenario import ScenarioError, load_scenario, parse_parameter, scenario_from_dict

EXAMPLE = os.path.join(MURAMVYA, "scenario_muramvya.json")


def _example_dict():
    with open(EXAMPLE, encoding="utf-8") as handle:
        return json.load(handle)


def test_example_scenario_loads():
    scenario = load_scenario(EXAMPLE)
    assert scenario.typology.field == "Type"
    assert scenario.exclusions[0].behaviour == "no_inflow"
    tables = scenario.parameter_tables()
    assert tables["dmax"].for_key("Urbain1").value_at(2030) == 10000
    assert tables["growth_rate"].for_key("Rural").value_at(2030) == pytest.approx(2.184)  # between 2027.5 (2.231) and 2032.5 (2.137)
    assert scenario.path(scenario.base_population_raster).endswith("pop2023_muramvya.tif")


def test_save_and_reload_without_loss(tmp_path):
    scenario = load_scenario(EXAMPLE)
    path = tmp_path / "copy.json"
    scenario.save(str(path))
    reloaded = scenario_from_dict(json.loads(path.read_text(encoding="utf-8")), scenario.base_dir)
    assert reloaded.to_dict() == scenario.to_dict()


def test_every_problem_is_reported_at_once():
    data = _example_dict()
    del data["typology"]
    data["time"]["migration_frequency"] = "monthly"
    data["migration"]["tolerance"] = 0.5
    data["migration"]["policy"] = "panic"
    with pytest.raises(ScenarioError) as error:
        scenario_from_dict(data)
    codes = [m.code for m in error.value.messages]
    assert codes == ["scenario_missing_key"]  # structure first
    data = _example_dict()
    data["time"]["migration_frequency"] = "monthly"
    data["migration"]["tolerance"] = 0.5
    data["migration"]["policy"] = "panic"
    data["exclusions"][0]["year"] = 2030
    data["exclusions"][0]["behaviour"] = "outside"
    with pytest.raises(ScenarioError) as error:
        scenario_from_dict(data)
    codes = [m.code for m in error.value.messages]
    assert codes.count("scenario_invalid_value") == 3
    assert "scenario_dated_outside" in codes
    assert "tolérance" not in str(error.value)  # messages name the entries, e.g. migration.tolerance
    assert "migration.tolerance" in str(error.value)


def test_projection_start_needs_projections_and_admin_units():
    data = _example_dict()
    data["time"]["start_mode"] = "projection"
    data["time"]["start_year"] = 2026
    del data["admin_units"]
    with pytest.raises(ScenarioError) as error:
        scenario_from_dict(data)
    assert "scenario_projection_needs_data" in [m.code for m in error.value.messages]


def test_parameter_forms():
    assert parse_parameter("r", 2.5).for_key("x").value_at(2050) == 2.5
    table = parse_parameter("r", {"*": {"2026": 3, "2040": 2}, "Urbain": 4})
    assert table.for_key("Rural").value_at(2033) == pytest.approx(2.5)
    assert table.for_key("Urbain").value_at(2033) == 4
    with pytest.raises(ValueError):
        parse_parameter("r", "fast")


def test_connections_are_not_paths_and_passwords_are_never_saved(tmp_path):
    from engine.scenario import is_connection, scenario_from_dict

    assert is_connection("PG:dbname='gis' host='srv'") and is_connection("https://example.org/wfs")
    assert not is_connection("C:\\data\\zones.shp") and not is_connection("zones.shp")
    source = "PG:dbname='gis' host='srv' user='sher' password='s3cret'"
    data = {
        "study_area": {"source": source, "layer": "public.communes(geom)"},
        "typology": {"source": "C:\\data\\typo.shp", "field": "Type"},
        "base_population": {"raster": "pop.tif"},
        "time": {"base_year": 2024, "end_year": 2030},
        "parameters": {"growth_rate": 2.0, "dmax": {"zones": [{"source": source, "field": "type"}], "values": {"*": 1}}},
    }
    scenario = scenario_from_dict(data, str(tmp_path))
    assert scenario.path(scenario.study_area.source) == source          # used as is, with its password
    saved = scenario.to_dict()
    assert saved["study_area"]["source"] == "PG:dbname='gis' host='srv' user='sher'"
    assert "s3cret" not in str(saved)
