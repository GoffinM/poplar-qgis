"""Source of the roofs, usage coefficients and confidence threshold (plan of phase 6, step 6.1)."""

import gzip

import numpy as np
import pytest
from osgeo import ogr

from engine._gdal import srs_from_epsg
from engine.roofs import RoofSource, is_open_buildings, read_roofs, usage_weights
from helpers import square


def _roofs(path, rows):
    """rows: (x, y, size, usage, confidence) squares in UTM 35S."""
    datasource = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    layer = datasource.CreateLayer("roofs", srs_from_epsg(32735), ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("usage", ogr.OFTString))
    layer.CreateField(ogr.FieldDefn("confidence", ogr.OFTReal))
    for x, y, size, usage, confidence in rows:
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(square(x, y, x + size, y + size))
        if usage is not None:
            feature.SetField("usage", usage)
        feature.SetField("confidence", confidence)
        layer.CreateFeature(feature)
    datasource = None
    return str(path)


ROWS = [(0, 0, 6, "habitation", 0.9), (20, 0, 8, "mixte", 0.8), (40, 0, 10, "commerce", 0.95),
        (60, 0, 7, "église", 0.7), (80, 0, 5, None, 0.6)]


def test_usage_coefficients_and_unknown_categories(tmp_path, utm35s_wkt):
    path = _roofs(tmp_path / "roofs.gpkg", ROWS)
    spec = RoofSource(path, usage_field="usage",
                      usage_coefficients={"habitation": 1, "mixte": 0.5, "commerce": 0})
    roofs = read_roofs(spec, utm35s_wkt)
    assert roofs.report["read"] == 5 and roofs.report["usage_zero"] == 1 and roofs.report["kept"] == 4
    assert roofs.report["unknown_usage"] == ["", "église"]               # T1: default 1, listed in the report
    assert sorted(roofs.weight.tolist()) == [0.5, 1, 1, 1]
    np.testing.assert_allclose(sorted(roofs.buildings.area_m2), [25, 36, 49, 64])


def test_confidence_threshold_is_off_by_default(tmp_path, utm35s_wkt):
    path = _roofs(tmp_path / "roofs.gpkg", ROWS)
    assert read_roofs(RoofSource(path), utm35s_wkt).report["kept"] == 5
    roofs = read_roofs(RoofSource(path, confidence_field="confidence", min_confidence=0.75), utm35s_wkt)
    assert roofs.report["low_confidence"] == 2 and roofs.report["kept"] == 3
    with pytest.raises(ValueError):
        read_roofs(RoofSource(path, min_confidence=0.75), utm35s_wkt)


def test_open_buildings_tiles_are_recognised(tmp_path, utm35s_wkt):
    path = tmp_path / "tile.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("latitude,longitude,area_in_meters,confidence,geometry,full_plus_code\n")
        handle.write("-3.26,29.61,42.5,0.81,POLYGON EMPTY,6GF3\n-3.27,29.62,30.0,0.66,POLYGON EMPTY,6GF4\n")
    assert is_open_buildings(str(path))
    roofs = read_roofs(RoofSource(str(path), min_confidence=0.75), utm35s_wkt)
    assert roofs.report["source"] == "open_buildings" and roofs.report["kept"] == 1
    assert roofs.buildings.area_m2.tolist() == [42.5]


def test_usage_weights_without_a_usage_field():
    assert usage_weights(None, {"*": 0.5}) == (None, [])
