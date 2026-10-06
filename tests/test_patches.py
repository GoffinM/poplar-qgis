"""Built-up patches as starting polygons of the free mode (decision D1, plan_polygones_libres.md §15)."""

import json
import os

import numpy as np
import pytest
from osgeo import ogr

from engine.patches import PatchRules, find_patches, prepare
from engine.scenario import load_scenario
from engine.simulation import _Model, run
from world import box, make_world

CELL = 250.0


def town_world(directory, village=4):
    """20 x 20 cells: an urban commune (columns and rows 4 to 15) with a dense core of 6 x 6 cells at
    4 000 hab/km² (a hole in the middle and a notch on its north side, both at 500), the rest of the
    commune at 500, rural land at 300, and a dense village of ``village`` x ``village`` cells outside."""
    density = np.full((20, 20), 300.0)
    density[4:16, 4:16] = 500.0
    density[6:12, 6:12] = 4000.0
    density[8, 8] = 500.0                                          # hole: filled
    density[6, 8] = 500.0                                          # notch with 5 dense neighbours: filled
    density[0:village, 20 - village:20] = 4000.0
    commune = box(4, 4, 16, 16, CELL)
    rural = box(0, 0, 20, 20, CELL).Difference(commune)
    return make_world(directory, density, cell=CELL, zones=[(commune, "U"), (rural, "R")],
                      parameters={"growth_rate": {"U": 3.0, "R": 1.0}, "dmax": {"U": 10000, "R": 2500}},
                      time={"base_year": 2024, "end_year": 2030, "time_step": 1, "first_migration_year": 2025},
                      migration={"k": 3, "tolerance": 1, "policy": "unallocated"})


def patches_of(path, **rules):
    model = _Model.load(load_scenario(path))
    return model, find_patches(model.units, model.p0, PatchRules(**rules))


def test_dense_core_becomes_the_urban_patch_and_the_rest_of_the_commune_transition(tmp_path):
    _, result = patches_of(town_world(str(tmp_path)))
    classes = result.classes
    assert result.urban_classes == ["U"]
    assert (classes[6:12, 6:12] == "U").all()                    # hole and notch filled
    assert classes[8, 8] == "U" and classes[6, 8] == "U"
    assert (classes[4:16, 4:16] == "Transition").sum() == 144 - 36
    assert (classes[0:4, 16:20] == "R").all()                    # village of 4 000 inhabitants: too small
    (patch,) = result.patches
    assert patch.stratum == "U" and patch.cells == 36 and patch.inside_share == 1.0
    assert patch.population == pytest.approx(34 * 250 + 2 * 31.25)


def test_smaller_patches_as_a_second_level(tmp_path):
    _, result = patches_of(town_world(str(tmp_path)), secondary_min_population=2000)
    assert (result.classes[0:4, 16:20] == "Urbain2").all()
    village = [p for p in result.patches if p.stratum == "Urbain2"]
    assert len(village) == 1 and village[0].inside_share == 0.0


def test_large_dense_village_outside_the_commune_is_urban_unless_inside_only(tmp_path):
    path = town_world(str(tmp_path), village=5)                   # 25 cells x 250 = 6 250 inhabitants
    _, result = patches_of(path)
    assert (result.classes[0:5, 15:20] == "Urbain2").all()       # decision Q-b
    _, inside = patches_of(path, inside_only=True)
    assert not (inside.classes == "Urbain2").any()


def test_prepare_writes_the_typology_and_a_scenario_in_free_mode(tmp_path):
    path = town_world(str(tmp_path))
    files = prepare(path)
    assert all(os.path.isfile(p) for p in files.values())
    datasource = ogr.Open(files["typology"])
    layer = datasource.GetLayerByName("typologie")
    found = {}
    for feature in layer:
        if feature.GetField("origine") == "tache":                # one patch: one piece, nothing else
            assert feature.GetGeometryRef().GetGeometryCount() == 1
        found[feature.GetField("type")] = found.get(feature.GetField("type"), 0.0) + feature.GetGeometryRef().GetArea()
    assert found["U"] / 1e6 == pytest.approx(36 * 0.0625)
    assert found["Transition"] / 1e6 == pytest.approx(108 * 0.0625)
    assert sum(found.values()) / 1e6 == pytest.approx(400 * 0.0625)        # the whole study area, no gap
    datasource = None
    with open(files["scenario"], encoding="utf-8") as handle:
        copy = json.load(handle)
    assert copy["strata"]["mode"] == "free"
    assert copy["strata"]["classes"]["Transition"]["rank"] == 2 and copy["strata"]["classes"]["U"]["rank"] == 4
    assert copy["strata"]["urban_rank"] == 3
    assert copy["parameters"]["dmax"]["Transition"] == 2500                 # rural maximum density (Q-c)
    assert copy["parameters"]["growth_rate"]["Transition"] == 3.0           # urban growth rate (Q-c)
    with open(files["report"], encoding="utf-8") as handle:
        report = json.load(handle)
    assert len(report["patches"]) == 1 and report["outside_urban_limits"] == []


def test_the_scenario_copy_runs_in_both_modes(tmp_path):
    path = town_world(str(tmp_path))
    copy = prepare(path)["scenario"]
    free = run(load_scenario(copy))
    assert free.status == "success" and free.polygons is not None
    strata = set(free.polygons.table.stratum)
    assert {"U", "Transition", "R"} <= strata
    with open(copy, encoding="utf-8") as handle:
        data = json.load(handle)
    data["strata"]["mode"] = "planned"
    data["output"]["directory"] += "_planifie"
    planned_path = os.path.join(os.path.dirname(copy), "planifie.json")
    with open(planned_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    planned = run(load_scenario(planned_path))
    assert planned.status == "success" and planned.polygons is None


def test_parameters_linked_to_the_typology_file_follow_the_new_layer(tmp_path):
    path = town_world(str(tmp_path))
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data["parameters"]["dmax"] = {"zones": [{"source": "zones.gpkg", "field": "type"}],
                                  "values": {"U": 10000, "R": 2500}}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    with open(prepare(path)["scenario"], encoding="utf-8") as handle:
        copy = json.load(handle)
    zone = copy["parameters"]["dmax"]["zones"][0]
    assert zone["source"] == "typologie_taches.gpkg" and zone["layer"] == "typologie"
    assert copy["parameters"]["dmax"]["values"]["Transition"] == 2500


def test_patches_command(tmp_path, capsys):
    from engine.__main__ import main

    path = town_world(str(tmp_path))
    assert main(["patches", path, "--density", "3000"]) == 0
    assert "typologie_taches.gpkg" in capsys.readouterr().out
