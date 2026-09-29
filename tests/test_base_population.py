import numpy as np
import pytest

from engine.base_population import AREA_WEIGHTED, RENORMALIZED, base_population_from_density
from engine.grid import Grid
from engine.units import Zone, build_units
from helpers import square, uniform_raster


def test_t11_aggregation_to_a_coarser_grid(utm35s_wkt):
    raster = uniform_raster(utm35s_wkt, 0, 1000, 250, 4, 4, 1000.0)
    grid = Grid.covering((0, 0, 1000, 1000), 500, utm35s_wkt, origin=(0, 1000))
    units = build_units(grid, square(-1, -1, 1001, 1001), [Zone(square(-1, -1, 1001, 1001), "R")])
    population, report = base_population_from_density(units, raster)
    np.testing.assert_allclose(population, [250.0] * 4)
    assert report.allocated_population == pytest.approx(1000.0)


def test_t13_population_of_a_split_cell(utm35s_wkt):
    raster = uniform_raster(utm35s_wkt, 0, 1000, 500, 2, 2, 800.0)
    grid = Grid.covering((0, 0, 1000, 1000), 1000, utm35s_wkt, origin=(0, 1000))
    zones = [Zone(square(0, 0, 750, 1000), "Rural"), Zone(square(750, 0, 1000, 1000), "Urbain")]
    units = build_units(grid, square(0, 0, 1000, 1000), zones)
    population, _ = base_population_from_density(units, raster)
    by_class = {units.class_name(i): population[i] for i in range(len(units))}
    assert by_class == pytest.approx({"Rural": 600.0, "Urbain": 200.0})


def test_non_aligned_grid_and_raster(utm35s_wkt):
    # 100 m pixels, 130 m cells: every overlap is fractional.
    raster = uniform_raster(utm35s_wkt, 0, 1300, 100, 13, 13, 2000.0)
    grid = Grid.covering((0, 0, 1300, 1300), 130, utm35s_wkt, origin=(0, 1300))
    units = build_units(grid, square(-1, -1, 1301, 1301), [Zone(square(-1, -1, 1301, 1301), "R")])
    population, _ = base_population_from_density(units, raster)
    assert population.sum() == pytest.approx(2000.0 * 1.69)
    np.testing.assert_allclose(population, 2000.0 * 0.0169)


def test_boundary_pixels_area_weighted_versus_renormalized(utm35s_wkt):
    # One 250 m pixel of 1000 hab/km2 (62.5 inhabitants); the domain covers its left 60 %.
    raster = uniform_raster(utm35s_wkt, 0, 250, 250, 1, 1, 1000.0)
    grid = Grid.covering((0, 0, 250, 250), 250, utm35s_wkt, origin=(0, 250))
    study = square(0, 0, 150, 250)
    units = build_units(grid, study, [Zone(study, "R")])
    weighted, report_w = base_population_from_density(units, raster, boundary_mode=AREA_WEIGHTED)
    renormalized, report_r = base_population_from_density(units, raster, boundary_mode=RENORMALIZED)
    assert weighted.sum() == pytest.approx(37.5)
    assert renormalized.sum() == pytest.approx(62.5)
    assert report_w.raster_population_touching == pytest.approx(62.5)


def test_density_unit_hab_per_ha(utm35s_wkt):
    raster = uniform_raster(utm35s_wkt, 0, 250, 250, 1, 1, 10.0)  # 10 hab/ha = 1000 hab/km2
    grid = Grid.covering((0, 0, 250, 250), 250, utm35s_wkt, origin=(0, 250))
    units = build_units(grid, square(-1, -1, 251, 251), [Zone(square(-1, -1, 251, 251), "R")])
    population, _ = base_population_from_density(units, raster, density_unit="hab/ha")
    assert population.sum() == pytest.approx(62.5)


def test_nodata_counts_as_zero_and_is_reported(utm35s_wkt):
    raster = uniform_raster(utm35s_wkt, 0, 250, 250, 2, 1, 1000.0)
    raster.values[0, 1] = np.nan
    grid = Grid.covering((0, 0, 500, 250), 250, utm35s_wkt, origin=(0, 250))
    units = build_units(grid, square(-1, -1, 501, 251), [Zone(square(-1, -1, 501, 251), "R")])
    population, report = base_population_from_density(units, raster)
    assert population.sum() == pytest.approx(62.5)
    assert report.nodata_area_km2 == pytest.approx(0.0625)


def test_different_crs_is_rejected(utm35s_wkt):
    from engine._gdal import srs_from_epsg

    raster = uniform_raster(srs_from_epsg(32736).ExportToWkt(), 0, 250, 250, 1, 1, 1.0)
    grid = Grid.covering((0, 0, 250, 250), 250, utm35s_wkt)
    units = build_units(grid, square(0, 0, 250, 250), [Zone(square(0, 0, 250, 250), "R")])
    with pytest.raises(ValueError):
        base_population_from_density(units, raster)


def test_raster_write_read_roundtrip(tmp_path, utm35s_wkt):
    from engine.raster_io import read_raster, write_raster

    values = np.array([[1.5, np.nan], [3.0, 4.0]])
    path = str(tmp_path / "density.tif")
    write_raster(path, values, (0, 250, 0, 500, 0, -250), utm35s_wkt, nodata=-9999.0)
    raster = read_raster(path)
    np.testing.assert_allclose(raster.values, values)
    assert raster.pixel_area_m2 == 62500
