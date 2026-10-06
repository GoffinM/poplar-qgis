"""Attraction of the roads (plan_demande_et_routes.md, B): attractiveness, felt distance, colonisation, runs."""

import json
import os

import numpy as np
import pytest
from osgeo import ogr

from engine._gdal import srs_from_epsg
from engine.migration import attracted_receivers, migrate, shared_receivers
from engine.raster_io import read_raster
from engine.roads import attractiveness, read_road_points, weight_of
from engine.scenario import ScenarioError, load_scenario, scenario_from_dict
from engine.simulation import run
from world import X0, Y0, box, make_world

CELL = 250.0


def write_roads(path, lines, field="classe"):
    """lines: [(class, [(col, row) in cells, ...])] (centres of the cells given)."""
    datasource = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    layer = datasource.CreateLayer("routes", srs_from_epsg(32735), ogr.wkbLineString)
    layer.CreateField(ogr.FieldDefn(field, ogr.OFTString))
    for value, points in lines:
        feature = ogr.Feature(layer.GetLayerDefn())
        coords = ", ".join(f"{X0 + (c + 0.5) * CELL} {Y0 - (r + 0.5) * CELL}" for c, r in points)
        feature.SetGeometry(ogr.CreateGeometryFromWkt(f"LINESTRING({coords})"))
        feature.SetField(field, value)
        layer.CreateFeature(feature)
    datasource = None
    return str(path)


def test_attractiveness_formula():
    points = {1.0: np.array([[0.0, 0.0]]), 0.3: np.array([[0.0, 100.0]])}
    a = attractiveness(np.array([0.0, 500.0, 0.0, 1e6]), np.array([0.0, 0.0, 100.0, 0.0]), points, 500.0)
    assert a[0] == pytest.approx(2.0)                                   # on the national road
    assert a[1] == pytest.approx(1 + np.exp(-1))                        # 500 m away: 1 + 1/e
    assert a[2] == pytest.approx(max(1 + np.exp(-0.2), 1.3))            # the largest term is kept
    assert a[3] == pytest.approx(1.0)                                   # far from any road
    assert weight_of("nationale", {"nationale": 1, "autre": 0.3}, True) == 1
    assert weight_of("piste", {"nationale": 1}, True) == 0              # no weight, no « * »: 0
    assert weight_of("piste", {"*": 0.2}, True) == 0.2
    assert weight_of(None, {}, False) == 1                              # no class field: every road 1


def test_road_points_follow_the_lines_and_report_lengths(tmp_path):
    path = write_roads(tmp_path / "r.gpkg", [("nationale", [(0, 0), (8, 0)]), ("sentier", [(0, 4), (4, 4)])])
    srs = srs_from_epsg(32735).ExportToWkt()
    points, count, lengths, unknown = read_road_points(path, None, None, "classe", {"nationale": 1.0}, srs,
                                                       (X0 - 1e4, Y0 - 1e4, X0 + 1e4, Y0 + 1e4))
    assert count == 2 and unknown == ["sentier"]
    assert lengths == {"nationale": 2.0, "sentier": 1.0}
    assert list(points) == [1.0]                                        # weight 0: no points
    gaps = np.hypot(*np.diff(points[1.0], axis=0).T)
    assert gaps.max() <= 20.0 + 1e-9 and len(points[1.0]) >= 100


def test_felt_distance_brings_migrants_to_the_road():
    # One source at the origin; a receiver at 300 m on a road (attractiveness 2) beats one at 200 m off-road.
    x = np.array([0.0, 200.0, 300.0, -400.0])
    y = np.zeros(4)
    xy = np.column_stack([x, y])
    receivers = np.array([1, 2, 3])
    origin, targets, weights = attracted_receivers(xy[:1], xy[1:], receivers, 1, np.array([1.0, 2.0, 1.0]))
    assert targets.tolist() == [2] and weights.tolist() == [1.0]
    # Without attraction (all 1), the same as the nearest receivers.
    rng = np.random.default_rng(3)
    pts = rng.uniform(0, 1000, (60, 2))
    ids = np.arange(10, 70)
    a = attracted_receivers(pts[:5], pts, ids, 3, np.ones(60))
    b = shared_receivers(pts[:5], pts, ids, 3)
    np.testing.assert_allclose(a[1][np.lexsort((a[1], a[0]))], b[1][np.lexsort((b[1], b[0]))])


def test_attracted_receivers_match_a_brute_force():
    rng = np.random.default_rng(7)
    pts = rng.uniform(0, 5000, (300, 2))
    attraction = 1 + rng.uniform(0, 1.5, 300)
    sources = rng.uniform(0, 5000, (20, 2))
    ids = np.arange(300)
    origin, targets, weights = attracted_receivers(sources, pts, ids, 3, attraction)
    for s in range(20):
        felt = np.hypot(*(pts - sources[s]).T) / attraction
        expected = set(np.argsort(felt)[:3])
        assert set(targets[origin == s]) == expected
        assert weights[origin == s].sum() == pytest.approx(1.0)


def test_migration_conserves_the_population_with_attraction():
    population = np.array([100.0, 0.0, 0.0, 0.0])
    capacity = np.array([40.0, 30.0, 30.0, 30.0])
    x = np.array([0.0, 100.0, 300.0, 600.0])
    result = migrate(population, capacity, np.ones(4, bool), x, np.zeros(4), k=1,
                     attraction=np.array([1.0, 1.0, 4.0, 1.0]))
    assert result.population.sum() == pytest.approx(100.0)
    assert result.population[2] == pytest.approx(30.0)                  # felt at 75 m: filled first
    with pytest.raises(ValueError):
        migrate(population, capacity, np.ones(4, bool), x, np.zeros(4), attraction=np.array([1.0, 0.5, 1, 1]))


def city_world(directory, roads=True, years=25, weight=None, **road_options):
    """A 3 x 3 city at its ceiling in rural land at 1 500 hab/km2 (room left), a national road east-west."""
    n = 31
    c = n // 2
    density = np.full((n, n), 1500.0)
    density[c - 1:c + 2, c - 1:c + 2] = 10000.0
    city = box(c - 1, c - 1, c + 2, c + 2, CELL)
    rural = box(0, 0, n, n, CELL).Difference(city)
    strata = {"mode": "free", "min_neighbors": 3, "classes": {"U": {"rank": 2}, "R": {"rank": 1}}}
    if roads:
        os.makedirs(directory, exist_ok=True)
        write_roads(os.path.join(directory, "routes.gpkg"), [("nationale", [(0, c), (n - 1, c)])])
        strata["roads"] = {"source": "routes.gpkg", "field": "classe", **road_options}
        if weight is not None:
            strata["roads"]["weights"] = {"nationale": weight}
    return make_world(directory, density, cell=CELL, zones=[(city, "U"), (rural, "R")],
                      parameters={"growth_rate": {"U": 5.0, "R": 0.0}, "dmax": {"U": 10000, "R": 2500},
                                  "colonization_min_inflow": {"*": 0.1}, "saturation_share": {"*": 0.8}},
                      time={"base_year": 2024, "end_year": 2024 + years, "time_step": 1, "first_migration_year": 2025},
                      migration={"k": 3, "tolerance": 1, "policy": "unallocated"}, strata=strata)


def _extent(result):
    history = result.polygons
    membership = history.membership[max(history.membership)]
    rows, cols = np.nonzero(membership == history.table.stratum.index("U"))
    return cols.max() - cols.min() + 1, rows.max() - rows.min() + 1


def test_the_city_stretches_along_the_road(tmp_path):
    ring = run(load_scenario(city_world(str(tmp_path / "ring"), roads=False)))
    assert _extent(ring) == (7, 7)                                      # no road: as wide as high
    weak = run(load_scenario(city_world(str(tmp_path / "weak"), weight=1.0)))
    width, height = _extent(weak)
    assert width > height                                               # weight 1 (validated first): 9 x 7
    roads = run(load_scenario(city_world(str(tmp_path / "road"))))
    assert _extent(roads) == (9, 5)                                     # default, national 2: a longer finger
    for result in (weak, roads):                                       # population never lost
        assert result.status == "success"
        balance = json.load(open(os.path.join(result.directory, "plausibilite.json"), encoding="utf-8"))
        assert all(abs(row["gap"]) < 1e-6 for row in balance["mass_balance"])
    out = roads.directory
    attraction = read_raster(os.path.join(out, "attractivite.tif")).values
    assert attraction[15, 3] == pytest.approx(3.0, abs=0.06) and attraction[0, 3] < 1.01
    indicators = json.load(open(os.path.join(out, "plausibilite.json"), encoding="utf-8"))["roads"]
    assert indicators["extensions"] > 0
    assert indicators["extensions_near_share"] > indicators["baseline_near_share"]
    codes = [w.code for w in roads.warnings]
    assert "roads_used" in codes
    html = open(os.path.join(out, "report.html"), encoding="utf-8").read()
    assert "route principale" in html


def test_each_action_can_be_switched_off(tmp_path):
    off = run(load_scenario(city_world(str(tmp_path / "off"), years=6, migration=False, colonization=False)))
    ring = run(load_scenario(city_world(str(tmp_path / "ring"), roads=False, years=6)))
    np.testing.assert_array_equal(read_raster(os.path.join(off.directory, "population_2030.tif")).values,
                                  read_raster(os.path.join(ring.directory, "population_2030.tif")).values)


def test_planned_mode_ignores_the_roads_unless_asked(tmp_path):
    def planned(directory, **options):
        path = city_world(directory, years=4, **options)
        data = json.load(open(path, encoding="utf-8"))
        data["strata"]["mode"] = "planned"
        json.dump(data, open(path, "w", encoding="utf-8"))
        return run(load_scenario(path))

    plain = planned(str(tmp_path / "plain"))
    ring = run(load_scenario(city_world(str(tmp_path / "ring"), roads=False, years=4)))
    assert not os.path.exists(os.path.join(plain.directory, "attractivite.tif"))
    assert "roads_used" not in [w.code for w in plain.warnings]
    asked = planned(str(tmp_path / "asked"), in_planned_mode=True)
    assert os.path.exists(os.path.join(asked.directory, "attractivite.tif"))
    a = read_raster(os.path.join(asked.directory, "population_2028.tif")).values
    b = read_raster(os.path.join(plain.directory, "population_2028.tif")).values
    assert a.sum() == pytest.approx(b.sum()) and not np.array_equal(a, b)
    del ring


def test_road_settings_are_checked(tmp_path):
    path = city_world(str(tmp_path), years=2)
    data = json.load(open(path, encoding="utf-8"))
    roads = data["strata"]["roads"]
    scenario = scenario_from_dict(data, str(tmp_path))
    assert scenario.strata.roads.weights == {"nationale": 2.0, "provinciale": 0.6, "autre": 0.3}
    assert scenario.strata.roads.reach_m == 500 and scenario.strata.roads.min_neighbors == 2
    assert scenario.to_dict()["strata"]["roads"]["source"] == "routes.gpkg"
    for change, key in (({"reach_m": 0}, "strata.roads.reach_m"), ({"min_neighbors": 9}, "strata.roads.min_neighbors"),
                        ({"weights": {"nationale": -1}}, "strata.roads.weights.nationale"),
                        ({"speed": 3}, "strata.roads"), ({"source": ""}, "strata.roads.source")):
        bad = json.loads(json.dumps(data))
        bad["strata"]["roads"] = {**roads, **change}
        with pytest.raises(ScenarioError) as error:
            scenario_from_dict(bad, str(tmp_path))
        assert key in str(error.value), key
    data["strata"]["roads"]["source"] = "missing.gpkg"
    with pytest.raises(ScenarioError) as error:
        run(scenario_from_dict(data, str(tmp_path)))
    assert [m.code for m in error.value.messages] == ["roads_unreadable"]
