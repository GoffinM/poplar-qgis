"""Colonisation rule of the free strata mode, unit by unit (plan_polygones_libres.md §3c, §8)."""

import numpy as np
import pytest
from osgeo import ogr

from engine._gdal import srs_from_epsg
from engine.grid import Grid, rectangle
from engine.polygons import (NO_CELL, NO_POLYGON, PART_LAYER, ColonisationRules, Inflow, Stratum, at_capacity,
                             cell_membership, colonise, initial_polygons, part_layer, saturation_shares)
from engine.units import Layer, Zone, build_units

CELL = 250.0
X0, Y0 = 500_000.0, 9_600_000.0
STRATA = {"U": Stratum(rank=2), "R": Stratum(rank=1), "Camp": Stratum(rank=1, colonizable=False)}


def cells_box(c0, r0, c1, r1):
    """Rectangle over columns c0..c1 and rows r0..r1 (exclusive)."""
    return rectangle(X0 + c0 * CELL, Y0 - r1 * CELL, X0 + c1 * CELL, Y0 - r0 * CELL)


def polygon(points):
    """Polygon from (column, row) corner coordinates in cell units."""
    ring = ogr_ring([(X0 + c * CELL, Y0 - r * CELL) for c, r in points])
    result = ogr.Geometry(ogr.wkbPolygon)
    result.AddGeometry(ring)
    return result


def ogr_ring(points):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in points + [points[0]]:
        ring.AddPoint_2D(x, y)
    return ring


def world(n, zones, no_inflow=None, layers=()):
    grid = Grid(X0, Y0, CELL, n, n, srs_from_epsg(32735).ExportToWkt())
    study = cells_box(0, 0, n, n)
    zone_list = [Zone(g, name) for g, name in zones]
    units = build_units(grid, study, zone_list, no_inflow, [part_layer(zone_list), *layers])
    pid, table = initial_polygons(units, zone_list, STRATA)
    return units, pid, table


def cell_units(units, row, col):
    return np.flatnonzero(units.cell_id == row * units.grid.ncols + col)


def square_city(n=21, centre=10, exclusion=True):
    """§8.1: a 3 x 3 city in the middle, rural around, a no-inflow band east of the city."""
    city = cells_box(centre - 1, centre - 1, centre + 2, centre + 2)
    rural = cells_box(0, 0, n, n).Difference(city)
    band = cells_box(centre + 2, centre - 3, centre + 4, centre + 4) if exclusion else None
    return world(n, [(city, "U"), (rural, "R")], band)


def polygon_of(table, name):
    return table.stratum.index(name)


def state(units, pid, table, city_fill=625.0, rural_fill=156.25):
    """Every unit at capacity: city 625, rural 156.25 inhabitants per whole cell."""
    u = polygon_of(table, "U")
    capacity = np.where(pid == u, 10000.0, 2500.0) * units.area_km2
    population = capacity * np.where(pid == u, city_fill / 625.0, rural_fill / 156.25)
    return population, capacity


def inflow_to(units, table, cells, amount, source="U"):
    receivers = np.concatenate([cell_units(units, r, c) for r, c in cells])
    return Inflow.from_transfers(receivers, np.full(len(receivers), polygon_of(table, source)),
                                 np.full(len(receivers), float(amount)), len(table))


def run(units, pid, table, population, capacity, inflow, min_inflow=0.1, saturation=0.8, **rules):
    protected = units.no_inflow
    return colonise(units, pid, table, population, capacity, protected, inflow,
                    np.full(len(table), min_inflow), np.full(len(table), saturation), ColonisationRules(**rules))


def colonised_cells(units, result):
    return {tuple(int(v) for v in divmod(int(c), units.grid.ncols)) for c in result.cells}


# --- initial state and views --------------------------------------------------------------------


def test_one_polygon_per_connected_part():
    two_parts = ogr.Geometry(ogr.wkbMultiPolygon)
    two_parts.AddGeometry(cells_box(1, 1, 3, 3))
    two_parts.AddGeometry(cells_box(6, 6, 8, 8))
    rural = cells_box(0, 0, 10, 10).Difference(two_parts)
    units, pid, table = world(10, [(two_parts, "U"), (rural, "R")])
    assert table.stratum == ["U", "U", "R"]
    assert pid[cell_units(units, 1, 1)][0] != pid[cell_units(units, 6, 6)][0]
    assert set(pid.tolist()) == {0, 1, 2}


def test_cell_membership_majority_and_outside():
    units, pid, table = square_city(n=9, centre=4, exclusion=False)
    raster = cell_membership(units, pid)
    assert raster[4, 4] == polygon_of(table, "U") and raster[0, 0] == polygon_of(table, "R")
    assert (raster != NO_CELL).all()


def test_at_capacity_uses_the_migration_tolerance():
    assert at_capacity(np.array([99.5, 99.0, 98.9]), np.array([100.0, 100.0, 100.0]), 1.0).tolist() == \
        [True, False, False]


def test_saturation_share_counts_area_and_leaves_exclusions_out():
    pid = np.array([0, 0, 0, 1])
    area = np.array([1.0, 1.0, 2.0, 1.0])
    full = np.array([True, False, True, False])
    protected = np.array([False, False, True, False])
    shares = saturation_shares(pid, area, full, protected, 2)
    assert shares[0] == pytest.approx(0.5) and shares[1] == 0.0


# --- §8.1 at the unit level ---------------------------------------------------------------------


def test_export_below_the_threshold_colonises_nothing():
    units, pid, table = square_city()
    population, capacity = state(units, pid, table)
    inflow = inflow_to(units, table, [(2, 2)], 15.0)             # exported far away: 15 < 10 % of 156.25
    assert len(run(units, pid, table, population, capacity, inflow).cells) == 0
    inflow = inflow_to(units, table, [(2, 2)], 16.0)
    assert colonised_cells(units, run(units, pid, table, population, capacity, inflow)) == {(8, 10), (12, 10), (10, 8)}


def test_what_a_polygon_sends_to_its_own_units_is_not_exported():
    units, pid, table = square_city()
    population, capacity = state(units, pid, table)
    inflow = inflow_to(units, table, [(10, 10)], 1000.0)         # inside the city
    assert len(run(units, pid, table, population, capacity, inflow).cells) == 0


def test_square_city_colonises_the_three_free_mid_sides():
    units, pid, table = square_city()
    population, capacity = state(units, pid, table)
    # Inflows of year 1 (plan §8.1): mid-sides and corner neighbours about 21, diagonal about 10.
    received = {(8, 10): 41.7, (12, 10): 31.3, (10, 8): 31.3, (8, 9): 20.8, (8, 11): 31.3, (8, 8): 10.4}
    receivers = np.concatenate([cell_units(units, r, c) for r, c in received])
    amounts = np.concatenate([np.full(len(cell_units(units, r, c)), v) for (r, c), v in received.items()])
    inflow = Inflow.from_transfers(receivers, np.full(len(receivers), polygon_of(table, "U")), amounts, len(table))
    result = run(units, pid, table, population, capacity, inflow)
    assert colonised_cells(units, result) == {(8, 10), (12, 10), (10, 8)}
    assert (result.winners == polygon_of(table, "U")).all()
    changed = np.flatnonzero(result.changed)
    assert set(units.cell_id[changed]) == {8 * 21 + 10, 12 * 21 + 10, 10 * 21 + 8}


@pytest.mark.parametrize("breaking", ["candidate_not_full", "inflow_too_small", "colonizer_not_saturated",
                                      "too_few_neighbours", "rank"])
def test_each_condition_alone_prevents_the_colonisation(breaking):
    units, pid, table = square_city()
    population, capacity = state(units, pid, table)
    inflow = inflow_to(units, table, [(8, 10)], 20.8)
    options = {}
    target = cell_units(units, 8, 10)
    if breaking == "candidate_not_full":
        population[target] -= 10.0
    elif breaking == "inflow_too_small":
        options["min_inflow"] = 0.2                              # 31.25 needed, 20.8 received
    elif breaking == "colonizer_not_saturated":
        city = np.flatnonzero(pid == polygon_of(table, "U"))
        population[city[:3]] -= 100.0                            # 6/9 of the city at capacity
    elif breaking == "too_few_neighbours":
        options["min_neighbors"] = 4
    elif breaking == "rank":
        table.rank[polygon_of(table, "U")] = 1
    result = run(units, pid, table, population, capacity, inflow, **options)
    if breaking == "candidate_not_full":                         # the other mid-sides are full: only this one waits
        assert (8, 10) not in colonised_cells(units, result) and len(result.cells) == 2
    else:
        assert len(result.cells) == 0 and not result.changed.any()


def test_corner_neighbours_and_diagonals_stay_rural():
    units, pid, table = square_city()
    population, capacity = state(units, pid, table)
    result = run(units, pid, table, population, capacity,
                 inflow_to(units, table, [(8, 9), (8, 11), (9, 8), (8, 8)], 40.0))
    assert colonised_cells(units, result) == {(8, 10), (12, 10), (10, 8)}           # the pressure reaches every mid-side, nothing else


def test_exclusion_zone_is_never_colonised():
    units, pid, table = square_city()
    population, capacity = state(units, pid, table)
    result = run(units, pid, table, population, capacity, inflow_to(units, table, [(10, 12)], 100.0))
    assert (10, 12) not in colonised_cells(units, result)
    assert colonised_cells(units, result) == {(8, 10), (12, 10), (10, 8)}


def test_inflow_in_inhabitants():
    units, pid, table = square_city()
    population, capacity = state(units, pid, table)
    inflow = inflow_to(units, table, [(8, 10)], 20.8)
    assert len(run(units, pid, table, population, capacity, inflow, min_inflow=20.0,
                   min_inflow_unit="inhabitants").cells) == 3
    assert len(run(units, pid, table, population, capacity, inflow, min_inflow=21.0,
                   min_inflow_unit="inhabitants").cells) == 0


def test_rural_never_colonises_the_city():
    units, pid, table = square_city()
    population, capacity = state(units, pid, table)
    result = run(units, pid, table, population, capacity, inflow_to(units, table, [(10, 10)], 500.0, source="R"))
    assert len(result.cells) == 0


def test_strata_that_cannot_be_colonised_stay_out():
    camp = cells_box(10, 7, 11, 8)
    city = cells_box(9, 9, 12, 12)
    rural = cells_box(0, 0, 21, 21).Difference(city).Difference(camp)
    units, pid, table = world(21, [(city, "U"), (camp, "Camp"), (rural, "R")])
    population, capacity = state(units, pid, table)
    result = run(units, pid, table, population, capacity, inflow_to(units, table, [(7, 10)], 50.0),
                 min_neighbors=0)
    assert len(result.cells) > 0                                 # rural cells around the city are taken
    camp = cell_units(units, 7, 10)
    assert (result.polygon_id[camp] == pid[camp]).all()          # the camp never


def test_conflict_goes_to_the_higher_rank_then_to_the_larger_export():
    # Two cities touch the same cell (row 5, column 5) with three neighbours each.
    west = cells_box(2, 4, 5, 7)
    east = cells_box(6, 4, 9, 7)
    rural = cells_box(0, 0, 11, 11).Difference(west).Difference(east)
    units, pid, table = world(11, [(west, "U"), (east, "U"), (rural, "R")])
    population, capacity = state(units, pid, table)
    target = cell_units(units, 5, 5)
    w, e = int(pid[cell_units(units, 5, 3)][0]), int(pid[cell_units(units, 5, 7)][0])
    inflow = Inflow.from_transfers(np.concatenate([target, target]), np.array([w, e]), np.array([20.0, 30.0]),
                                   len(table))
    result = run(units, pid, table, population, capacity, inflow)
    assert 5 * 11 + 5 in result.cells
    assert result.polygon_id[target][0] == e                     # same rank: the larger export wins
    table.rank[w] = 3
    result = run(units, pid, table, population, capacity, inflow)
    assert result.polygon_id[target][0] == w                     # a higher rank wins first


def test_one_ring_per_step():
    units, pid, table = square_city(exclusion=False)
    population, capacity = state(units, pid, table)
    # A large export reaches the first ring only: the cells two rows away wait for the next step.
    result = run(units, pid, table, population, capacity, inflow_to(units, table, [(7, 10)], 100.0))
    assert colonised_cells(units, result) == {(8, 10), (12, 10), (10, 8), (10, 12)}


# --- §8.2 cells cut by a slanted boundary (B2) ------------------------------------------------


K = 0


def slanted(no_inflow=None, admin=None):
    """City = {column - row > K + 0.5} on a 12 x 12 grid: the cut cells are split 7/8 - 1/8."""
    n = 12
    city = polygon([(K + 0.5, 0), (n, 0), (n, n - K - 0.5)])
    rural = cells_box(0, 0, n, n).Difference(city)
    layers = [admin] if admin is not None else []
    return world(n, [(city, "U"), (rural, "R")], no_inflow, layers)


def test_membership_of_slanted_cells():
    units, pid, table = slanted()
    u, r = polygon_of(table, "U"), polygon_of(table, "R")
    raster = cell_membership(units, pid, 0.5)
    assert raster[3, 3 + K + 1] == u                              # 7/8 in the city
    assert raster[3, 3 + K] == r                                  # 1/8 in the city
    assert cell_membership(units, pid, 0.9)[3, 3 + K + 1] == NO_POLYGON


def test_cut_cell_is_colonised_except_its_exclusion_piece_and_keeps_its_commune():
    exclusion = cells_box(4, 4, 4.5, 5)                          # west half of cell (4, 4 + K)
    admin = Layer("admin", [cells_box(0, 0, 12, 4.5), cells_box(0, 4.5, 12, 12)], ["north", "south"])
    units, pid, table = slanted(no_inflow=exclusion, admin=admin)
    population, capacity = state(units, pid, table)
    target = cell_units(units, 4, 4 + K)
    inflow = inflow_to(units, table, [(4, 4 + K)], 30.0)
    before_admin = units.codes["admin"][target].copy()
    result = run(units, pid, table, population, capacity, inflow)
    assert 4 * 12 + 4 + K in result.cells
    u = polygon_of(table, "U")
    protected = units.no_inflow[target]
    assert protected.any() and (~protected).sum() >= 2
    assert (result.polygon_id[target][~protected] == u).all()
    assert (result.polygon_id[target][protected] == pid[target][protected]).all()
    assert (units.codes["admin"][target] == before_admin).all()


def test_residue_in_a_city_cell_is_colonised_without_neighbours():
    units, pid, table = slanted()
    population, capacity = state(units, pid, table)
    target = cell_units(units, 3, 3 + K + 1)                     # 7/8 city, 1/8 rural residue
    inflow = inflow_to(units, table, [(3, 3 + K + 1)], 5.0)      # 10 % of the residue's capacity is 2
    result = run(units, pid, table, population, capacity, inflow, min_neighbors=8)
    assert (result.polygon_id[target] == polygon_of(table, "U")).all()


def test_part_layer_cuts_cells_like_the_typology():
    with_part, _, _ = slanted()
    grid = with_part.grid
    zones = [Zone(polygon([(K + 0.5, 0), (12, 0), (12, 12 - K - 0.5)]), "U")]
    zones.append(Zone(cells_box(0, 0, 12, 12).Difference(zones[0].geometry), "R"))
    without = build_units(grid, cells_box(0, 0, 12, 12), zones)
    assert np.array_equal(with_part.cell_id, without.cell_id)
    assert np.allclose(with_part.area_km2, without.area_km2)
    assert PART_LAYER in with_part.codes


# --- New nuclei (P8/P17) ----------------------------------------------------------------------------


def test_new_nucleus_with_its_flags():
    from engine.polygons import NucleusRules, new_nuclei

    units, pid, table = square_city()
    population, capacity = state(units, pid, table, rural_fill=100.0)
    block = np.concatenate([cell_units(units, r, c) for r in range(1, 3) for c in range(1, 3)])
    population[block] = capacity[block]                           # a full 2 x 2 block far from the city
    rules = NucleusRules(enabled=True, stratum="U", min_cells=4, enclave_km2=50.0)
    new_pid, found = new_nuclei(units, pid, table, population, capacity, units.no_inflow, None, rules, STRATA, 2030)
    assert len(found) == 1 and len(found[0].cells) == 4
    assert (new_pid[block] == found[0].polygon).all() and table.stratum[found[0].polygon] == "U"
    assert found[0].flags == ["enclave"]                          # 21 x 21 cells = 27.6 km2 < 50 km2
    rules = NucleusRules(enabled=True, stratum="U", min_cells=5)
    assert new_nuclei(units, pid, table, population, capacity, units.no_inflow, None, rules, STRATA, 2030)[1] == []


def test_no_nucleus_next_to_the_city_nor_when_the_rule_is_off():
    from engine.polygons import NucleusRules, new_nuclei

    units, pid, table = square_city()
    population, capacity = state(units, pid, table)                # everything full, city included
    found = new_nuclei(units, pid, table, population, capacity, units.no_inflow, None,
                       NucleusRules(enabled=True, stratum="U", min_cells=4), STRATA, 2030)[1]
    cells = [divmod(int(x), 21) for n in found for x in n.cells]
    assert cells and all(not (8 <= r <= 12 and 8 <= c <= 12) for r, c in cells)      # never next to the city
    assert new_nuclei(units, pid, table, population, capacity, units.no_inflow, None, NucleusRules(), STRATA,
                      2030)[1] == []


# --- Smoothing and contacts (plan §5) ---------------------------------------------------------------


def test_chaikin_keeps_fixed_vertices_and_straight_fixed_edges():
    from engine.polygon_outputs import _chaikin

    square = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    points, flags = _chaikin(square, [True, True, False, False])
    assert (0.0, 0.0) in points and (4.0, 0.0) in points
    assert all(not (0 < x < 4 and y == 0.0) for x, y in points)    # the fixed edge stays straight
    assert len(points) == 2 + 4 and flags.count(True) == 2


def test_contact_between_two_polygons_of_the_same_rank():
    from engine.polygon_outputs import _contacts
    from engine.polygons import PolygonHistory, PolygonTable

    table = PolygonTable()
    for name in ("U", "U", "R"):
        table.add(name, STRATA)
    apart = np.array([[0, 2, 1], [2, 2, 2]])
    touching = np.array([[0, 1, 1], [2, 2, 2]])
    history = PolygonHistory(None, table, None, None, membership={2024: apart, 2030: touching}, start_year=2024)
    rows = _contacts(history)
    assert [(r["id"], r["autre_id"], r["annee"]) for r in rows] == [(0, 1, 2030)]


def test_nuclei_need_one_square_kilometre_by_default():
    from engine.polygons import NucleusRules

    assert NucleusRules().min_cells == 16 and not NucleusRules().enabled          # decision D2


def test_rank_colours_go_from_light_to_petrol():
    from engine.polygon_outputs import rank_colour

    assert [rank_colour(r, [1, 2]) for r in (1, 2)] == ["#e5ece9", "#1f6f6a"]
    assert [rank_colour(r, [1, 2, 3, 4]) for r in (1, 2, 3, 4)] == ["#e5ece9", "#f1dfbd", "#c98a36", "#1f6f6a"]
    assert rank_colour(9, [1, 2]) == "#c8c8c8"


def _grid_of(membership, size=250.0):
    from engine.grid import Grid

    rows, cols = membership.shape
    return Grid(0.0, rows * size, size, cols, rows, "")


def _smoothed_partition(membership, passes=3, study=None):
    from engine.polygon_outputs import _smooth, _vectorise

    grid = _grid_of(membership)
    return {p: _smooth(g, membership, p, grid, passes, 0.0, study) for p, g in _vectorise(membership, grid).items()}


def test_smoothing_turns_a_staircase_into_a_straight_line():
    # A city whose border with the rural polygon is a diagonal staircase: it becomes a straight diagonal.
    n = 12
    membership = np.fromfunction(lambda r, c: np.where(c > r, 1, 0), (n, n), dtype=int).astype(np.int32)
    city = _smoothed_partition(membership)[1]
    # Along the diagonal, far from the corners, the outline is within a few metres of the line y = H - x - 125.
    ring = city.GetGeometryRef(0).GetGeometryRef(0)
    points = [ring.GetPoint_2D(k) for k in range(ring.GetPointCount())]
    middle = [(x, y) for x, y in points if 750 < x < 2250 and 750 < (n * 250 - y) < 2250]
    assert middle
    for x, y in middle:
        assert abs((n * 250 - y) - (x - 125)) < 5.0       # through the middles of the steps


def test_smoothed_neighbours_stay_joined_without_gap_or_overlap():
    rng = np.random.default_rng(5)
    membership = np.zeros((20, 20), dtype=np.int32)
    membership[5:14, 4:15] = 1
    membership[8:11, 15:19] = 1                                     # a finger along a road
    membership[2:6, 12:17] = 2                                      # a third polygon touching the city
    membership[rng.random((20, 20)) < 0.03] = 1
    membership[12, 3] = 2
    membership[13, 2] = 2                                           # diagonal contact (checkerboard corner)
    shapes = _smoothed_partition(membership)
    total = sum(g.GetArea() for g in shapes.values())
    assert total == pytest.approx(20 * 20 * 250 ** 2, rel=1e-9)     # the grid edge stays where it is
    for a in shapes:
        for b in shapes:
            if a < b:
                assert shapes[a].Intersection(shapes[b]).GetArea() < 1.0
    union = shapes[0]
    for g in shapes.values():
        union = union.Union(g)
    assert union.GetArea() == pytest.approx(total, rel=1e-9)
    raw = _smoothed_partition(membership, passes=0)
    assert raw[1].GetArea() == pytest.approx((membership == 1).sum() * 250 ** 2)
    assert abs(shapes[1].GetArea() - raw[1].GetArea()) < 0.1 * raw[1].GetArea()


def test_smoothed_outline_follows_the_real_limit_of_the_study_area():
    from helpers import square

    membership = np.full((6, 6), 0, dtype=np.int32)
    membership[2:4, 2:4] = 1
    study = square(100.0, 100.0, 1400.0, 1400.0)                   # not on the cell edges
    shapes = _smoothed_partition(membership, study=study)
    assert sum(g.GetArea() for g in shapes.values()) == pytest.approx(study.GetArea(), rel=1e-9)
    assert shapes[0].Within(study.Buffer(1e-6))
