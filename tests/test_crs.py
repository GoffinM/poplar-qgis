"""Calculation CRS, metric areas and reprojection of the population raster."""

import json
import os

import numpy as np
import pytest

from engine._gdal import srs_from_epsg, srs_from_wkt
from engine.crs import (
    AUTO_EQUAL_AREA, band_area_km2, choose_crs, ellipsoid_area_m2, max_area_distortion,
    population_to_density, reproject_density,
)
from engine.raster_io import Raster, write_raster
from engine.scenario import ScenarioError, load_scenario
from engine.simulation import run
from world import X0, Y0, make_world

WGS84 = srs_from_epsg(4326).ExportToWkt()
UTM35S = srs_from_epsg(32735).ExportToWkt()
MURAMVYA_LONLAT = (29.5, -3.4, 29.8, -3.2)
UKRAINE_LONLAT = (22.0, 44.0, 40.0, 52.0)


def _epsg(wkt):
    return srs_from_wkt(wkt).GetAuthorityCode(None)


def test_ellipsoidal_areas():
    assert band_area_km2(0, 1, 1) == pytest.approx(12_308.46, rel=1e-4)  # 1° x 1° at the equator
    lon = np.array([0.0, 1.0, 1.0, 0.0])
    lat = np.array([0.0, 0.0, 1.0, 1.0])
    assert ellipsoid_area_m2(lon, lat) / 1e6 == pytest.approx(12_308.46, rel=1e-4)


def test_raster_crs_is_kept_when_it_is_metric():
    choice = choose_crs(None, UTM35S, MURAMVYA_LONLAT)
    assert choice.source == "raster" and _epsg(choice.wkt) == "32735"
    assert choice.max_area_distortion < 0.005 and choice.suggestion is None


def test_raster_in_degrees_gives_the_utm_zone_of_the_study_area():
    choice = choose_crs(None, WGS84, MURAMVYA_LONLAT)
    assert choice.source == "auto-utm" and _epsg(choice.wkt) == "32735"


def test_a_crs_in_degrees_is_refused():
    with pytest.raises(ValueError):
        choose_crs("EPSG:4326", UTM35S, MURAMVYA_LONLAT)


def test_area_distortion_on_large_extents():
    assert max_area_distortion(srs_from_epsg(3857).ExportToWkt(), UKRAINE_LONLAT) > 1.0  # Web Mercator: > 100 %
    utm = choose_crs("EPSG:32635", UTM35S, UKRAINE_LONLAT)
    assert utm.max_area_distortion > 0.02 and utm.suggestion is not None
    equal_area = choose_crs(AUTO_EQUAL_AREA, UTM35S, UKRAINE_LONLAT)
    assert equal_area.max_area_distortion < 1e-6


def test_count_raster_becomes_a_density():
    raster = Raster(np.full((2, 2), 62.5), (0, 250, 0, 500, 0, -250), UTM35S)
    np.testing.assert_allclose(population_to_density(raster, "count").values, 1000.0)
    np.testing.assert_allclose(population_to_density(raster, "density", 100.0).values, 6250.0)


def test_count_raster_in_degrees_uses_the_true_pixel_areas():
    raster = Raster(np.full((1, 1), 12_308.46), (0, 1, 0, 1, 0, -1), WGS84)  # 1 inhabitant per km2
    assert population_to_density(raster, "count").values[0, 0] == pytest.approx(1.0, rel=1e-4)


def test_reprojection_preserves_densities_and_population():
    # 40 x 40 pixels of 0.005° (about 550 m) around Muramvya, 1 000 hab/km2.
    raster = Raster(np.full((40, 40), 1000.0), (29.5, 0.005, 0, -3.2, 0, -0.005), WGS84)
    total = (1000.0 * band_area_km2(-3.2 - 0.005 * np.arange(40), -3.2 - 0.005 * np.arange(1, 41), 0.005)).sum() * 40
    projected, ratio = reproject_density(raster, UTM35S, 250.0)
    assert np.nansum(projected.values) * 0.0625 == pytest.approx(total, rel=0.01)
    assert abs(ratio - 1) < 0.01
    interior = projected.values[5:-5, 5:-5]
    assert np.nanmedian(interior) == pytest.approx(1000.0, rel=0.02)


def test_simulation_with_a_worldpop_like_raster(tmp_path):
    # Study area in UTM 35S; population raster in degrees, as inhabitants per pixel.
    path = make_world(str(tmp_path), np.full((20, 20), 1000.0), cell=100.0)
    with open(path, encoding="utf-8") as handle:
        scenario = json.load(handle)
    to_geo = __import__("osgeo.osr", fromlist=["osr"]).CoordinateTransformation(
        srs_from_epsg(32735), srs_from_epsg(4326))
    lon0, lat0, _ = to_geo.TransformPoint(X0 - 500, Y0 + 500)
    pixel = 0.001  # about 110 m
    rows = cols = 30
    counts = np.full((rows, cols), 1.0)  # one inhabitant per pixel
    counts_path = os.path.join(str(tmp_path), "worldpop.tif")
    write_raster(counts_path, counts, (lon0, pixel, 0, lat0, 0, -pixel), WGS84)
    scenario["base_population"] = {"raster": "worldpop.tif", "value_type": "count"}
    scenario["time"]["end_year"] = 2025
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(scenario, handle)
    result = run(load_scenario(path))
    density = 1.0 / band_area_km2(lat0 - pixel * 15, lat0 - pixel * 16, pixel)  # hab/km2 at the centre
    expected = density * 4.0  # study area: 2 km x 2 km
    assert result.initial_population == pytest.approx(expected, rel=0.01)
    codes = [w.code for w in result.warnings]
    assert "crs_used" in codes and "raster_reprojected" in codes


def test_degrees_requested_for_the_calculation_are_reported(tmp_path):
    path = make_world(str(tmp_path), np.full((5, 5), 1000.0), crs="EPSG:4326")
    with pytest.raises(ScenarioError) as error:
        run(load_scenario(path))
    assert error.value.messages[0].code == "crs_not_metric"
