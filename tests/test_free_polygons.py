"""Free strata mode, end to end (plan_polygones_libres.md §8): synthetic worlds run by the simulation."""

import json
import os

import numpy as np
import pytest

from engine.raster_io import read_raster
from engine.scenario import load_scenario
from engine.simulation import run
from world import box, make_world, write_polygons

CELL = 250.0

FREE = {
    "mode": "free",
    "min_neighbors": 3,
    "cell_membership_share": 0.5,
    "min_inflow_unit": "share_of_capacity",
    "classes": {"U": {"rank": 2}, "R": {"rank": 1}},
}
PARAMETERS = {
    "growth_rate": {"U": 5.0, "R": 0.0},
    "dmax": {"U": 10000, "R": 2500},
    "colonization_min_inflow": {"*": 0.1},
    "saturation_share": {"*": 0.8},
}


def square_city_world(directory, mode="free", years=4):
    """§8.1: 21 x 21 cells of 250 m; 3 x 3 city at its maximum density; rural at 2 400 hab/km2;
    a no-inflow band of 2 columns east of the city."""
    density = np.full((21, 21), 2400.0)
    density[9:12, 9:12] = 10000.0
    city = box(9, 9, 12, 12, CELL)
    rural = box(0, 0, 21, 21, CELL).Difference(city)
    overrides = {
        "parameters": PARAMETERS,
        "time": {"base_year": 2024, "end_year": 2024 + years, "time_step": 1, "first_migration_year": 2025},
        "migration": {"k": 3, "tolerance": 1, "policy": "unallocated"},
    }
    if mode is not None:
        overrides["strata"] = {**FREE, "mode": mode}
    return make_world(directory, density, cell=CELL, zones=[(city, "U"), (rural, "R")],
                      exclusions=[("band", box(12, 7, 14, 14, CELL), "no_inflow", None)], **overrides)


def events_by_year(result):
    found = {}
    for event in result.polygons.events:
        found.setdefault(int(event["year"]), set()).add((event["row"], event["col"]))
    return found


def test_square_city_grows_ring_by_ring(tmp_path):
    result = run(load_scenario(square_city_world(str(tmp_path))))
    polygons = result.polygons
    events = events_by_year(result)
    # Year 1: the three free mid-sides only (the east one is in the no-inflow band).
    assert events.get(2025) == {(8, 10), (12, 10), (10, 8)}
    # Year 2: the city must first fill its new cells (9/12 of its area at capacity < 80 %).
    assert not events.get(2026)
    city = polygons.table.stratum.index("U")
    for year, cells in events.items():
        before = polygons.membership[year - 1]
        for row, col in cells:
            around = before[row - 1:row + 2, col - 1:col + 2]
            assert (around == city).sum() >= 3                    # one ring per step, from the state at t
    band = [(r, c) for r in range(7, 14) for c in range(12, 14)]
    assert all((r, c) not in cells for cells in events.values() for r, c in band)
    # The rural polygon never takes a city cell.
    assert (polygons.membership[2024 + 4][9:12, 9:12] == city).all()


def test_colonised_cells_inherit_the_city_parameters(tmp_path):
    result = run(load_scenario(square_city_world(str(tmp_path), years=2)))
    capacity = read_raster(os.path.join(result.directory, "capacity_2026.tif")).values
    assert capacity[8, 10] == pytest.approx(625.0)              # 10 000 hab/km2 x 0.0625 km2
    assert capacity[8, 9] == pytest.approx(156.25)              # still rural


def test_population_is_conserved_every_year(tmp_path):
    result = run(load_scenario(square_city_world(str(tmp_path))))
    for step in result.steps:
        assert step.population_after_migration + step.unallocated + step.placed_in_sink == pytest.approx(
            step.population_after_growth, rel=1e-9)


def test_planned_mode_is_the_current_engine(tmp_path):
    planned = run(load_scenario(square_city_world(str(tmp_path / "planned"), mode="planned")))
    current = run(load_scenario(square_city_world(str(tmp_path / "current"), mode=None)))
    for year in (2025, 2026, 2027, 2028):
        a = read_raster(os.path.join(planned.directory, f"population_{year}.tif")).values
        b = read_raster(os.path.join(current.directory, f"population_{year}.tif")).values
        assert np.array_equal(a, b)
    assert getattr(planned, "polygons", None) is None


# --- §8.2 slanted boundary -----------------------------------------------------------------------


def slanted_world(directory):
    """12 x 12 cells; the city is the triangle above a 45° line that cuts cells 7/8 - 1/8;
    a slanted no-inflow strip and a slanted commune boundary cross the front."""
    from osgeo import ogr

    from world import X0, Y0

    def poly(points):
        ring = ogr.Geometry(ogr.wkbLinearRing)
        for c, r in points + [points[0]]:
            ring.AddPoint_2D(X0 + c * CELL, Y0 - r * CELL)
        geometry = ogr.Geometry(ogr.wkbPolygon)
        geometry.AddGeometry(ring)
        return geometry

    n = 12
    city = poly([(0.5, 0), (n, 0), (n, n - 0.5)])
    rural = box(0, 0, n, n, CELL).Difference(city)
    density = np.full((n, n), 2400.0)
    for r in range(n):
        for c in range(n):
            if c - r >= 1:
                density[r, c] = 10000.0
    strip = poly([(2, 6), (3, 6), (7, 10), (6, 10)])
    north = poly([(0, 0), (n, 0), (n, 3), (0, 9)])
    south = box(0, 0, n, n, CELL).Difference(north)
    overrides = {
        "parameters": PARAMETERS,
        "time": {"base_year": 2024, "end_year": 2034, "time_step": 1, "first_migration_year": 2025},
        "migration": {"k": 3, "tolerance": 1, "policy": "unallocated"},
        "strata": FREE,
    }
    return make_world(directory, density, cell=CELL, zones=[(city, "U"), (rural, "R")],
                      exclusions=[("strip", strip, "no_inflow", None)],
                      admin=[(north, "north"), (south, "south")], **overrides)


def test_slanted_front_keeps_exclusions_and_communes(tmp_path):
    result = run(load_scenario(slanted_world(str(tmp_path))))
    polygons = result.polygons
    units = polygons.units
    assert polygons.events                                       # the city did grow
    protected = units.no_inflow
    assert np.array_equal(polygons.final[protected], polygons.initial[protected])
    # A colonised cell has no lower-rank, colonisable piece left behind.
    city = polygons.table.stratum.index("U")
    for event in polygons.events:
        pieces = (units.cell_id == event["cell"]) & ~protected
        assert (polygons.final[pieces] == city).all()
    for step in result.steps:
        assert step.population_after_migration + step.unallocated + step.placed_in_sink == pytest.approx(
            step.population_after_growth, rel=1e-9)


def test_front_keeps_moving_after_the_first_ring(tmp_path):
    """Decision B (06/10): the pressure is what the city exports, so the front moves on in waves,
    each one once the city has filled the cells it gained (no unallocated population)."""
    result = run(load_scenario(square_city_world(str(tmp_path), years=20)))
    years = sorted({int(e["year"]) for e in result.polygons.events})
    assert years[0] == 2025 and len(years) >= 4 and years[-1] > 2035
    assert all(b - a >= 2 for a, b in zip(years, years[1:]))      # a pause while the new cells fill
    assert sum(step.unallocated for step in result.steps) == 0
