"""End-to-end runs on synthetic data sets (phase 3)."""

import csv
import json
import os

import numpy as np
import pytest

from engine.raster_io import read_raster
from engine.scenario import load_scenario
from engine.simulation import run
from world import box, make_world

UNIFORM = np.full((10, 10), 1000.0)  # 100 m cells: 10 inhabitants each, 1 000 in total


def _population(directory, year):
    return np.nan_to_num(read_raster(os.path.join(directory, f"population_{year}.tif")).values)


def _run(tmp_path, density=UNIFORM, **kwargs):
    scenario = load_scenario(make_world(str(tmp_path), density, **kwargs))
    return run(scenario), scenario


def test_growth_and_outputs(tmp_path):
    result, _ = _run(tmp_path)
    assert result.status == "success"
    assert result.final_population == pytest.approx(1000 * 1.02 ** 6, rel=1e-12)
    for year in range(2024, 2031):
        population = _population(result.directory, year)
        assert population.sum() == round(1000 * 1.02 ** (year - 2024))            # I6
        assert population.min() >= 0                                               # I7
    names = set(os.listdir(result.directory))
    assert {"population_2030.tif", "density_2030.tif", "capacity_2030.tif", "unallocated_2030.tif",
            "summary.csv", "report.json", "report.txt", "scenario_used.json"} <= names


def test_t14_first_migration_year(tmp_path):
    density = UNIFORM.copy()
    density[5, 5] = 20_000.0  # already above dmax at the base year: its ceiling is its base density (A4)
    result, _ = _run(tmp_path, density, time={"first_migration_year": 2026})
    assert [s.moved > 0 for s in result.steps[:3]] == [False, True, True]


def test_zone_relocated_from_a_given_year(tmp_path):
    zone = box(0, 0, 3, 10)
    result, _ = _run(tmp_path, exclusions=[("barrage", zone, "relocate", 2027)])
    assert _population(result.directory, 2026)[:, :3].sum() > 0
    assert _population(result.directory, 2027)[:, :3].sum() == 0
    assert _population(result.directory, 2030).sum() == round(1000 * 1.02 ** 6)
    assert [e.code for e in result.events] == ["exclusion_relocated"]


def test_zone_closed_to_migration_from_a_given_year(tmp_path):
    zone = box(0, 0, 3, 10)
    result, _ = _run(tmp_path, exclusions=[("périmètre", zone, "no_inflow", 2027)])
    frozen = _population(result.directory, 2026)[:, :3].sum() * 1.0  # population when the zone closes
    later = _population(result.directory, 2030)[:, :3].sum()
    assert abs(later - frozen) <= 30  # per-cell rounding only
    assert _population(result.directory, 2030).sum() == round(1000 * 1.02 ** 6)


def test_migration_frequency(tmp_path):
    annual, _ = _run(tmp_path / "annual", time={"time_step": 3})
    coarse, _ = _run(tmp_path / "coarse", time={"time_step": 3, "migration_frequency": "time_step"})
    assert annual.final_population == pytest.approx(coarse.final_population, rel=1e-12)
    assert len(annual.steps) == 6 and len(coarse.steps) == 2
    assert "resolution_coarse_time" in [w.code for w in coarse.warnings]


def test_start_on_a_projection_year_with_recalibration(tmp_path):
    (tmp_path / "projections.csv").write_text(
        "admin,year,population\nA,2026,800\nA,2030,1000\nB,2026,600\nB,2030,700\n", encoding="utf-8")
    result, _ = _run(
        tmp_path,
        admin=[(box(0, 0, 5, 10), "A"), (box(5, 0, 10, 10), "B")],
        projections={"csv": "projections.csv", "recalibrate": True},
        time={"start_mode": "projection", "start_year": 2026},
    )
    with open(os.path.join(result.directory, "summary.csv"), encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle, delimiter=";"))[1:]
    totals = {(r[0], r[1]): int(r[2]) for r in rows}
    assert totals[("2026", "A")] == 800 and totals[("2026", "B")] == 600
    assert totals[("2028", "A")] == 900 and totals[("2028", "B")] == 650
    assert totals[("2030", "A")] == 1000 and totals[("2030", "B")] == 700


def test_non_convergence_stops_the_run_and_is_reported(tmp_path):
    result, _ = _run(tmp_path, parameters={"growth_rate": 2.0, "dmax": 500})
    assert result.status == "failed"
    assert result.steps[-1].messages[0].code == "capacity_insufficient"
    with open(os.path.join(result.directory, "report.json"), encoding="utf-8") as handle:
        assert json.load(handle)["status"] == "failed"


def test_unallocated_population_is_mapped(tmp_path):
    result, _ = _run(tmp_path, parameters={"growth_rate": 2.0, "dmax": 500}, migration={"policy": "unallocated"})
    assert result.status == "partial"
    unallocated = np.nan_to_num(read_raster(os.path.join(result.directory, "unallocated_2030.tif")).values)
    # Every cell is at its ceiling from the start: its growth is excess. An excess below
    # one inhabitant stays in place (tolerance), so it is recorded once it reaches one
    # inhabitant, after 5 years here (10 x 1.02^5 - 10 = 1.04 per cell).
    assert unallocated.sum() == pytest.approx(100 * 10 * (1.02 ** 5 - 1), rel=1e-6)


def test_report_and_tables_in_english(tmp_path):
    result, _ = _run(tmp_path, language="en")
    with open(os.path.join(result.directory, "report.txt"), encoding="utf-8") as handle:
        assert handle.readline().startswith("Run report")
    with open(os.path.join(result.directory, "summary.csv"), encoding="utf-8-sig") as handle:
        assert handle.readline().startswith("Year,Administrative unit,Population")


def test_failure_carries_the_proposed_increase(tmp_path):
    density = UNIFORM.copy()
    density[:, :5] = 200.0  # room on the left half, but not enough for the whole growth
    result, _ = _run(tmp_path, density, parameters={"growth_rate": 2.0, "dmax": 300})
    assert result.status == "failed"
    assert result.failure.proposal is not None and result.failure.proposal.factor > 1.0
    assert result.failure_year is not None


def _exclusion_layer(tmp_path, name, geometry, buffer_m=None, behaviour="relocate", year=2027):
    from world import write_polygons

    tmp_path.mkdir(parents=True, exist_ok=True)
    write_polygons(str(tmp_path / f"{name}.gpkg"), [(geometry, name)])
    spec = {"name": name, "source": f"{name}.gpkg", "behaviour": behaviour, "year": year}
    if buffer_m is not None:
        spec["buffer_m"] = buffer_m
    return spec


def test_line_exclusion_with_buffer(tmp_path):
    from osgeo import ogr
    from world import X0, Y0

    road = ogr.CreateGeometryFromWkt(f"LINESTRING ({X0 + 550} {Y0 + 10}, {X0 + 550} {Y0 - 1010})")  # centre of column 5
    spec = _exclusion_layer(tmp_path, "route", road, buffer_m=60)                                  # 120 m wide strip
    result, _ = _run(tmp_path, exclusion_specs=[spec])
    before, after = _population(result.directory, 2026), _population(result.directory, 2027)
    assert before[:, 5].sum() > 0 and after[:, 5].sum() == 0           # the road cells are emptied
    assert after[:, 4].sum() > 0 and after[:, 6].sum() > 0              # only 10 m of columns 4 and 6 are in it
    assert after.sum() == round(1000 * 1.02 ** 3)                      # nobody is lost
    assert [e.code for e in result.events] == ["exclusion_relocated"]


def test_point_exclusion_with_buffer(tmp_path):
    from osgeo import ogr
    from world import X0, Y0

    borehole = ogr.CreateGeometryFromWkt(f"POINT ({X0 + 250} {Y0 - 250})")  # centre of cell (2, 2)
    spec = _exclusion_layer(tmp_path, "forage", borehole, buffer_m=50, behaviour="outside", year=None)
    result, _ = _run(tmp_path, exclusion_specs=[spec])
    share = np.pi * 50 ** 2 / 100 ** 2                                     # the circle covers 78.5 % of the cell
    assert _population(result.directory, 2024)[2, 2] == pytest.approx(10 * (1 - share), abs=1)


def test_polygon_exclusion_widened_by_the_buffer(tmp_path):
    spec = _exclusion_layer(tmp_path, "lac", box(4, 4, 6, 6), buffer_m=100, behaviour="outside", year=None)
    result, _ = _run(tmp_path, exclusion_specs=[spec])
    population = _population(result.directory, 2024)
    assert population[3:7, 4:6].sum() == 0 and population[4:6, 3:7].sum() == 0  # 100 m around the lake
    assert population[3, 3] > 0                                                   # rounded corner


def test_line_exclusion_without_buffer_is_explained(tmp_path):
    from osgeo import ogr
    from engine.scenario import ScenarioError
    from world import X0, Y0

    road = ogr.CreateGeometryFromWkt(f"LINESTRING ({X0} {Y0 - 500}, {X0 + 1000} {Y0 - 500})")
    spec = _exclusion_layer(tmp_path, "route", road)
    with pytest.raises(ScenarioError) as error:
        _run(tmp_path, exclusion_specs=[spec])
    assert [m.code for m in error.value.messages] == ["exclusion_needs_buffer"]
