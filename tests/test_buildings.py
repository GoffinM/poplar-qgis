import gzip

import numpy as np
import pytest
from osgeo import ogr

from engine._gdal import srs_from_epsg
from engine.buildings import (
    Buildings, assign_to_units, per_unit_totals, read_footprints, read_open_buildings_csv,
)
from engine.grid import Grid
from engine.units import Zone, build_units
from helpers import square


def _write_polygons(path, squares, epsg=32735):
    driver = ogr.GetDriverByName("GPKG")
    datasource = driver.CreateDataSource(str(path))
    layer = datasource.CreateLayer("buildings", srs_from_epsg(epsg), ogr.wkbPolygon)
    for xmin, ymin, size in squares:
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(square(xmin, ymin, xmin + size, ymin + size))
        layer.CreateFeature(feature)
    datasource = None


def test_read_polygons_gives_centroid_and_area(tmp_path, utm35s_wkt):
    path = tmp_path / "roofs.gpkg"
    _write_polygons(path, [(0, 0, 10), (100, 100, 5)])
    buildings = read_footprints(str(path), utm35s_wkt)
    np.testing.assert_allclose(buildings.x, [5, 102.5])
    np.testing.assert_allclose(buildings.area_m2, [100, 25])


def test_spatial_filter_on_the_extent(tmp_path, utm35s_wkt):
    path = tmp_path / "roofs.gpkg"
    _write_polygons(path, [(0, 0, 10), (5000, 5000, 10)])
    buildings = read_footprints(str(path), utm35s_wkt, extent=(-100, -100, 100, 100))
    assert len(buildings) == 1


def test_points_with_an_area_field(tmp_path, utm35s_wkt):
    path = tmp_path / "points.gpkg"
    datasource = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    layer = datasource.CreateLayer("points", srs_from_epsg(32735), ogr.wkbPoint)
    layer.CreateField(ogr.FieldDefn("area_m2", ogr.OFTReal))
    feature = ogr.Feature(layer.GetLayerDefn())
    point = ogr.Geometry(ogr.wkbPoint)
    point.AddPoint_2D(10, 20)
    feature.SetGeometry(point)
    feature.SetField("area_m2", 42.0)
    layer.CreateFeature(feature)
    datasource = None
    buildings = read_footprints(str(path), utm35s_wkt, area_field="area_m2")
    assert (buildings.x[0], buildings.y[0], buildings.area_m2[0]) == (10, 20, 42)
    with pytest.raises(ValueError):
        read_footprints(str(path), utm35s_wkt)


def test_polygons_in_degrees_are_measured_in_metres(tmp_path, utm35s_wkt):
    # A ~10 m x 10 m square near Muramvya, stored in WGS 84.
    path = tmp_path / "roofs_wgs84.gpkg"
    lon, lat, d = 29.6, -3.27, 10 / 111_320
    datasource = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    layer = datasource.CreateLayer("b", srs_from_epsg(4326), ogr.wkbPolygon)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(square(lon, lat, lon + d, lat + d))
    layer.CreateFeature(feature)
    datasource = None
    buildings = read_footprints(str(path), utm35s_wkt)
    assert buildings.area_m2[0] == pytest.approx(100, rel=0.01)
    assert 780_000 < buildings.x[0] < 800_000
    assert 9_630_000 < buildings.y[0] < 9_650_000


def test_open_buildings_csv(tmp_path, utm35s_wkt):
    path = tmp_path / "tile.csv.gz"
    rows = [
        "latitude,longitude,area_in_meters,confidence,geometry,full_plus_code",
        "-3.27,29.60,35.5,0.81,POLYGON((...)),6G8J+22",
        "-3.28,29.61,12.0,0.62,POLYGON((...)),6G8J+33",
        "10.0,10.0,50.0,0.9,POLYGON((...)),XXXX+XX",
    ]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(rows) + "\n")
    extent = (780_000, 9_630_000, 800_000, 9_650_000)
    buildings = read_open_buildings_csv(str(path), utm35s_wkt, extent=extent)
    assert len(buildings) == 2
    np.testing.assert_allclose(buildings.area_m2, [35.5, 12.0])
    np.testing.assert_allclose(buildings.confidence, [0.81, 0.62], rtol=1e-6)
    confident = read_open_buildings_csv(str(path), utm35s_wkt, extent=extent, min_confidence=0.7)
    assert len(confident) == 1


def test_assignment_to_whole_and_split_cells(utm35s_wkt):
    grid = Grid.covering((0, 0, 500, 250), 250, utm35s_wkt)
    zones = [Zone(square(0, 0, 400, 250), "Rural"), Zone(square(400, 0, 500, 250), "Urbain")]
    units = build_units(grid, square(0, 0, 500, 250), zones)
    buildings = Buildings(
        x=np.array([100.0, 300.0, 450.0, 600.0]),
        y=np.array([100.0, 100.0, 100.0, 100.0]),
        area_m2=np.array([10.0, 20.0, 30.0, 40.0]),
    )
    index = assign_to_units(buildings, units)
    assert index[3] == -1  # outside the grid
    assert units.class_name(index[0]) == "Rural"
    assert units.class_name(index[1]) == "Rural"
    assert units.class_name(index[2]) == "Urbain"
    totals = per_unit_totals(index, buildings.area_m2, len(units))
    assert totals.sum() == pytest.approx(60.0)


def test_point_outside_the_study_part_of_a_split_cell(utm35s_wkt):
    grid = Grid.covering((0, 0, 250, 250), 250, utm35s_wkt)
    units = build_units(grid, square(0, 0, 100, 250), [Zone(square(0, 0, 100, 250), "R")])
    buildings = Buildings(np.array([50.0, 200.0]), np.array([50.0, 50.0]), np.array([1.0, 1.0]))
    np.testing.assert_array_equal(assign_to_units(buildings, units), [0, -1])
