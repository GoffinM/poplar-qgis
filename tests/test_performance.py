"""Performance on one million buildings (spec §3 bis). Run with: pytest -m slow"""

import gzip
import time

import numpy as np
import pytest
from osgeo import ogr

from engine._gdal import srs_from_epsg
from engine.buildings import assign_to_units, read_footprints, read_open_buildings_csv
from engine.grid import Grid
from engine.units import Zone, build_units
from helpers import square

N = 1_000_000
SIDE = 50_000.0  # 50 km x 50 km, 250 m cells: 40 000 cells
X0, Y0 = 700_000.0, 9_600_000.0
TIME_LIMIT_S = 120.0

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def units(utm35s_wkt):
    grid = Grid.covering((X0, Y0, X0 + SIDE, Y0 + SIDE), 250, utm35s_wkt, origin=(X0, Y0 + SIDE))
    # A diagonal typology boundary and a round no-inflow zone create many split cells.
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in ((X0, Y0), (X0 + SIDE, Y0), (X0, Y0 + SIDE), (X0, Y0)):
        ring.AddPoint_2D(x, y)
    lower = ogr.Geometry(ogr.wkbPolygon)
    lower.AddGeometry(ring)
    study = square(X0, Y0, X0 + SIDE, Y0 + SIDE)
    upper = study.Difference(lower)
    center = ogr.Geometry(ogr.wkbPoint)
    center.AddPoint_2D(X0 + SIDE / 2, Y0 + SIDE / 2)
    zones = [Zone(lower, "Rural"), Zone(upper, "Urbain")]
    return build_units(grid, study, zones, center.Buffer(5_000))


@pytest.fixture(scope="module")
def points():
    rng = np.random.default_rng(42)
    return X0 + rng.random(N) * SIDE, Y0 + rng.random(N) * SIDE, rng.gamma(2.0, 30.0, N) + 5


def test_one_million_polygons_from_geopackage(tmp_path_factory, units, points, utm35s_wkt):
    path = str(tmp_path_factory.mktemp("perf") / "roofs.gpkg")
    x, y, area = points
    side = np.sqrt(area)
    datasource = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    layer = datasource.CreateLayer("roofs", srs_from_epsg(32735), ogr.wkbPolygon)
    layer.StartTransaction()
    definition = layer.GetLayerDefn()
    for i in range(N):
        feature = ogr.Feature(definition)
        h = side[i] / 2
        feature.SetGeometry(square(x[i] - h, y[i] - h, x[i] + h, y[i] + h))
        layer.CreateFeature(feature)
    layer.CommitTransaction()
    datasource = None

    start = time.perf_counter()
    buildings = read_footprints(path, utm35s_wkt)
    index = assign_to_units(buildings, units)
    elapsed = time.perf_counter() - start
    print(f"\n1M polygons (GeoPackage): read + assign in {elapsed:.1f} s")
    assert len(buildings) == N
    assert np.all(index >= 0)
    np.testing.assert_allclose(np.sort(buildings.area_m2), np.sort(area), rtol=1e-9)
    assert elapsed < TIME_LIMIT_S


def test_one_million_open_buildings_rows(tmp_path_factory, units, points, utm35s_wkt):
    from osgeo import osr

    x, y, area = points
    transform = osr.CoordinateTransformation(srs_from_epsg(32735), srs_from_epsg(4326))
    lonlat = np.array(transform.TransformPoints(np.column_stack([x, y]).tolist()))
    path = str(tmp_path_factory.mktemp("perf") / "open_buildings.csv.gz")
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("latitude,longitude,area_in_meters,confidence,geometry,full_plus_code\n")
        for i in range(N):
            handle.write(f"{lonlat[i, 1]:.7f},{lonlat[i, 0]:.7f},{area[i]:.2f},0.8,POLYGON EMPTY,X\n")

    start = time.perf_counter()
    buildings = read_open_buildings_csv(path, utm35s_wkt)
    index = assign_to_units(buildings, units)
    elapsed = time.perf_counter() - start
    print(f"\n1M rows (Open Buildings CSV.gz): read + assign in {elapsed:.1f} s")
    assert len(buildings) == N
    assert (index >= 0).mean() > 0.9999  # points exactly on the outer edge may fall outside
    assert elapsed < TIME_LIMIT_S


def test_migration_on_2_25_million_units():
    from engine.migration import migrate

    side = 1500
    rng = np.random.default_rng(7)
    xs, ys = np.meshgrid(np.arange(side, dtype=float) * 100, np.arange(side, dtype=float) * 100)
    n = side * side
    cap = np.full(n, 100.0)
    population = rng.uniform(0, 90, n)
    overloaded = rng.random(n) < 0.05
    population[overloaded] = rng.uniform(100, 400, overloaded.sum())
    start = time.perf_counter()
    result = migrate(population, cap, np.ones(n, bool), xs.ravel(), ys.ravel())
    elapsed = time.perf_counter() - start
    print(f"\nMigration, 2.25M units, 5 % overloaded: {elapsed:.1f} s, {result.iterations} iterations")
    assert result.converged
    assert result.population.sum() == pytest.approx(population.sum(), rel=1e-12)
    assert elapsed < 60.0
