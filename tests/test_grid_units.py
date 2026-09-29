import numpy as np
import pytest

from engine.grid import Grid
from engine.units import NO_CLASS, Zone, build_units
from helpers import square


def test_grid_is_aligned_on_the_origin(utm35s_wkt):
    grid = Grid.covering((1010, 990, 1740, 1510), 250, utm35s_wkt, origin=(0, 2000))
    assert (grid.x0, grid.y0) == (1000, 1750)
    assert (grid.ncols, grid.nrows) == (3, 4)
    row, col, inside = grid.locate(np.array([1001, 1749, 5000]), np.array([1749, 1001, 0]))
    np.testing.assert_array_equal(row, [0, 2, 7])
    np.testing.assert_array_equal(col, [0, 2, 16])
    np.testing.assert_array_equal(inside, [True, True, False])


def test_t13_cell_split_between_two_classes(utm35s_wkt):
    grid = Grid.covering((0, 0, 1000, 1000), 1000, utm35s_wkt)
    zones = [Zone(square(0, 0, 750, 1000), "Rural"), Zone(square(750, 0, 1000, 1000), "Urbain")]
    units = build_units(grid, square(0, 0, 1000, 1000), zones)
    assert len(units) == 2
    by_class = {units.class_name(i): units.area_km2[i] for i in range(len(units))}
    assert by_class == pytest.approx({"Rural": 0.75, "Urbain": 0.25})
    rural = [i for i in range(len(units)) if units.class_name(i) == "Rural"][0]
    assert (units.cx[rural], units.cy[rural]) == pytest.approx((375, 500))


def test_whole_cells_need_no_geometry(utm35s_wkt):
    grid = Grid.covering((0, 0, 2000, 2000), 250, utm35s_wkt)
    zones = [Zone(square(0, 0, 2000, 2000), "Rural")]
    study = square(-100, -100, 2100, 2100)
    units = build_units(grid, study, zones)
    assert len(units) == 64
    # Cells touched by a boundary line are cut; the 6 x 6 interior cells stay whole.
    assert units.whole_cell.sum() >= 36
    np.testing.assert_allclose(units.area_km2, 0.0625)
    assert units.area_km2.sum() == pytest.approx(4.0)


def test_study_area_and_no_inflow_pieces(utm35s_wkt):
    grid = Grid.covering((0, 0, 1000, 1000), 250, utm35s_wkt)
    study = square(0, 0, 900, 1000)  # the last column is cut at 900
    zones = [Zone(square(0, 0, 1000, 1000), "Rural")]
    no_inflow = square(0, 0, 100, 100)
    units = build_units(grid, study, zones, no_inflow)
    assert units.area_km2.sum() == pytest.approx(0.9)
    assert units.area_km2[units.no_inflow].sum() == pytest.approx(0.01)
    corner = np.flatnonzero(units.cell_id == 12)  # bottom-left cell: two pieces
    assert len(corner) == 2
    assert sorted(units.area_km2[corner]) == pytest.approx([0.01, 0.0525])


def test_gaps_in_the_typology_give_unclassified_units(utm35s_wkt):
    grid = Grid.covering((0, 0, 500, 500), 250, utm35s_wkt)
    units = build_units(grid, square(0, 0, 500, 500), [Zone(square(0, 0, 500, 400), "Rural")])
    assert units.report.unclassified_area_km2 == pytest.approx(0.05)
    assert np.all(units.area_km2[units.class_index == NO_CLASS] == pytest.approx(0.025))


def test_overlapping_zones_are_counted_once_and_reported(utm35s_wkt):
    grid = Grid.covering((0, 0, 250, 250), 250, utm35s_wkt)
    zones = [Zone(square(0, 0, 150, 250), "A"), Zone(square(100, 0, 250, 250), "B")]
    units = build_units(grid, square(0, 0, 250, 250), zones)
    assert units.area_km2.sum() == pytest.approx(0.0625)
    assert units.report.overlap_area_km2 == pytest.approx(0.0125)


def test_slivers_are_merged_into_the_largest_piece(utm35s_wkt):
    grid = Grid.covering((0, 0, 250, 250), 250, utm35s_wkt)
    zones = [Zone(square(0, 0, 249.999, 250), "A"), Zone(square(249.999, 0, 250, 250), "B")]
    units = build_units(grid, square(0, 0, 250, 250), zones, min_unit_area_m2=1.0)
    assert len(units) == 1
    assert units.area_km2[0] == pytest.approx(0.0625)
    assert units.class_name(0) == "A"


def test_per_cell_sums(utm35s_wkt):
    grid = Grid.covering((0, 0, 1000, 1000), 1000, utm35s_wkt)
    zones = [Zone(square(0, 0, 750, 1000), "Rural"), Zone(square(750, 0, 1000, 1000), "Urbain")]
    units = build_units(grid, square(0, 0, 1000, 1000), zones)
    assert units.per_cell(units.area_km2)[0, 0] == pytest.approx(1.0)
