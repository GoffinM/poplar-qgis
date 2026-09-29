"""Integration tests on the Muramvya data set (phase 1).

Reference: reference_outputs/muramvya/p2023_entree (output of the current
model). The reference removed the forest (no-migration zone); the new
engine keeps it as no-inflow units (A7 = c), so comparisons exclude it.
"""

import os

import numpy as np
import pytest
from osgeo import ogr

from conftest import MURAMVYA, REFERENCE
from engine.base_population import AREA_WEIGHTED, RENORMALIZED, base_population_from_density
from engine.buildings import Buildings, assign_to_units, per_unit_totals, read_footprints
from engine.capacity import capacity
from engine.grid import Grid
from engine.growth import grow
from engine.parameters import ParameterTable, TimeSeries, per_unit
from engine.raster_io import read_raster
from engine.units import NO_CLASS, Zone, build_units
from engine.vector_io import read_features, union_all

RASTER_TOTAL = 171_280.40  # sum of POP2023 x 0.0625 km2
DMAX = ParameterTable("dmax", {"Rural": TimeSeries.constant(2500), "Urbain1": TimeSeries.constant(10000)})


@pytest.fixture(scope="module")
def case(muramvya_case):
    return muramvya_case


@pytest.fixture(scope="module")
def reference():
    datasource = ogr.Open(os.path.join(REFERENCE, "p2023_entree.shp"))
    rows = []
    for feature in datasource.GetLayer(0):
        geometry = feature.GetGeometryRef()
        if geometry is None or geometry.GetArea() == 0:
            continue
        point = geometry.PointOnSurface()
        rows.append((point.GetX(), point.GetY(), geometry.GetArea() / 1e6,
                     feature.GetField("P2023value"), feature.GetField("Pmax")))
    return np.array(rows)


def test_units_cover_the_commune(case):
    _, _, units = case
    assert units.area_km2.sum() == pytest.approx(256.53, abs=0.01)
    assert set(units.class_names) == {"Rural", "Urbain1"}
    assert not np.any(units.class_index == NO_CLASS)
    assert units.area_km2[units.no_inflow].sum() == pytest.approx(41.12, abs=0.01)
    assert units.report.dropped_area_km2 < 1e-5


def test_renormalized_base_population_keeps_the_raster_total(case):
    raster, _, units = case
    population, report = base_population_from_density(units, raster, boundary_mode=RENORMALIZED)
    assert population.sum() == pytest.approx(RASTER_TOTAL, abs=0.5)
    assert report.raster_population_touching == pytest.approx(RASTER_TOTAL, abs=0.5)


def test_area_weighted_base_population_loses_boundary_pixel_parts(case):
    raster, _, units = case
    population, report = base_population_from_density(units, raster, boundary_mode=AREA_WEIGHTED)
    lost = report.raster_population_touching - population.sum()
    assert 0 < lost < 0.005 * RASTER_TOTAL


def test_forest_population_is_kept(case):
    raster, _, units = case
    population, _ = base_population_from_density(units, raster, boundary_mode=AREA_WEIGHTED)
    # The current model deleted these inhabitants; the engine keeps them (A7 = c).
    assert population[units.no_inflow].sum() == pytest.approx(9746, abs=5)


def test_population_per_cell_matches_the_reference(case, reference):
    raster, grid, units = case
    population, _ = base_population_from_density(units, raster, boundary_mode=AREA_WEIGHTED)
    x, y, area, density = reference[:, 0], reference[:, 1], reference[:, 2], reference[:, 3]
    row, col, _ = grid.locate(x, y)
    ref_cell = np.bincount(row * grid.ncols + col, weights=density * area, minlength=grid.ncells)
    ours = np.where(units.no_inflow, 0.0, population)
    our_cell = np.bincount(units.cell_id, weights=ours, minlength=grid.ncells)
    diff = our_cell - ref_cell
    mismatched = np.flatnonzero(np.abs(diff) > 0.5)
    # Six pixels carry population in the reference but are nodata in the raster
    # supplied: the reference was produced from a slightly different raster.
    assert len(mismatched) == 6
    assert np.all(our_cell[mismatched] == 0)
    assert ref_cell[mismatched].sum() == pytest.approx(556, abs=2)


def test_capacity_matches_the_reference_pmax(case, reference):
    raster, _, units = case
    population, _ = base_population_from_density(units, raster, boundary_mode=AREA_WEIGHTED)
    fragments = Buildings(reference[:, 0], reference[:, 1], reference[:, 2])
    index = assign_to_units(fragments, units)
    keep = index >= 0
    keep[keep] = ~units.no_inflow[index[keep]]
    dmax = per_unit(units.class_index, DMAX.value_by_class(units.class_names, 2024), "dmax")
    cap = capacity(units.area_km2, population, dmax, units.no_inflow)
    cap_density = cap / units.area_km2
    ref_pmax = reference[:, 4]
    relative = np.abs(cap_density[index[keep]] - ref_pmax[keep]) / ref_pmax[keep]
    assert keep.sum() > 4300
    assert (relative > 0.001).sum() <= 1  # one fragment lies on a pixel that is nodata here (see above)


def test_growth_and_capacity_are_consistent(case):
    raster, _, units = case
    population, _ = base_population_from_density(units, raster, boundary_mode=RENORMALIZED)
    dmax = per_unit(units.class_index, DMAX.value_by_class(units.class_names, 2024), "dmax")
    cap = capacity(units.area_km2, population, dmax, units.no_inflow)
    assert np.all(cap >= population - 1e-9)
    grown = grow(population, 2.2, 1)
    assert grown.sum() == pytest.approx(population.sum() * 1.022, rel=1e-12)
    excess = np.maximum(grown - cap, 0)
    assert excess[units.no_inflow].sum() == pytest.approx(0.022 * population[units.no_inflow].sum(), rel=1e-9)


def test_buildings_are_all_assigned(case):
    raster, _, units = case
    buildings = read_footprints(
        os.path.join(MURAMVYA, "buildings_muramvya.gpkg"), raster.crs_wkt, area_field="area_m2"
    )
    assert len(buildings) == 38_942
    index = assign_to_units(buildings, units)
    assert np.all(index >= 0)
    roofs = per_unit_totals(index, buildings.area_m2, len(units))
    assert roofs.sum() == pytest.approx(buildings.area_m2.sum())


def test_legacy_building_population_matches_the_workbooks():
    datasource = ogr.Open(os.path.join(MURAMVYA, "buildings_muramvya.gpkg"))
    totals = {}
    for feature in datasource.GetLayer(0):
        stratum = feature.GetField("stratum")
        totals[stratum] = totals.get(stratum, 0.0) + feature.GetField("legacy_pop")
    assert totals["Rural"] == pytest.approx(139_099.65, abs=0.01)
    assert totals["Urbain"] == pytest.approx(33_253.08, abs=0.01)
