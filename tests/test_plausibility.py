"""Plausibility indicators and comparison of the two modes (plan_polygones_libres.md §6, decision Q11)."""

import csv
import os

import pytest

from engine.comparison import NotComparable, compare, write as write_comparison
from engine.plausibility import CAPPED_YEARS, load, mass_balance
from engine.scenario import load_scenario
from engine.simulation import run
from test_free_polygons import square_city_world


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    folder = tmp_path_factory.mktemp("modes")
    free = run(load_scenario(square_city_world(str(folder / "free"), years=20)))
    planned = run(load_scenario(square_city_world(str(folder / "planned"), mode="planned", years=20)))
    return planned, free


def test_indicators_are_written_and_read_back(runs):
    _, free = runs
    for name in ("plausibilite.csv", "plausibilite.json"):
        assert os.path.isfile(os.path.join(free.directory, name))
    indicators = load(free.directory)
    assert indicators["speed_cap_m_per_year"] == 250.0 and indicators["urban_rank"] == 2
    assert indicators["colonised_cells"] == len(free.polygons.events)
    with open(os.path.join(free.directory, "plausibilite.csv"), encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    assert rows and "vitesse_front_m_an" in rows[0]


def test_fronts_stay_under_the_cap_and_move_when_cells_are_gained(runs):
    _, free = runs
    city = [h for h in load(free.directory)["horizons"] if h["urban"]]
    assert all(h["front_speed_m_per_year"] is None or 0 <= h["front_speed_m_per_year"] <= 250.0 for h in city)
    moving = [h for h in city if h["area_end_km2"] > h["area_start_km2"]]
    assert moving and all(h["front_speed_m_per_year"] > 0 and h["reading"] in ("etalement", "densification")
                          for h in moving)
    filling = [h for h in city if h["area_end_km2"] == h["area_start_km2"]]
    assert filling and all(h["reading"] == "densification" for h in filling)    # the city fills its new cells
    assert not any(h["capped"] for h in city)                                    # one wave every 4 to 6 years


def test_rural_polygon_retreats(runs):
    _, free = runs
    rural = [h for h in load(free.directory)["horizons"] if not h["urban"] and h["area_end_km2"] < h["area_start_km2"]]
    assert rural and all(h["reading"] == "recul" for h in rural)


def test_mass_balance_is_zero(runs):
    _, free = runs
    balance = load(free.directory)["mass_balance"]
    assert balance and all(abs(row["gap"]) < 1e-6 for row in balance)


def test_capped_front_needs_three_years_in_a_row():
    from engine.plausibility import _row
    from engine.polygons import PolygonTable, Stratum

    table = PolygonTable()
    table.add("U", {"U": Stratum(rank=2)})
    start = {"area_km2": 1.0, "population": 100.0, "perimeter_cells_m": 4000.0}
    end = {"area_km2": 1.5, "population": 150.0, "perimeter_cells_m": 5000.0}
    row = lambda years: _row(0, table, 2030, 2035, 5, start, end, set(years), 250.0, 2)  # noqa: E731
    assert CAPPED_YEARS == 3
    assert row([2031, 2032, 2033])["capped"]
    assert not row([2031, 2033, 2035])["capped"]
    assert row([2031])["front_speed_m_per_year"] == pytest.approx(0.5e6 / (4500 * 5))


def test_mass_balance_counts_growth_and_unallocated():
    from engine.report import StepReport

    steps = [StepReport(2024, 2025, 100, 110, 105, 5, 0, 0, 0, True, 1.0, "partial"),
             StepReport(2025, 2026, 105, 115, 115, 0, 0, 0, 0, True, 1.0, "success")]
    (row,) = mass_balance(steps, [2024, 2026])
    assert (row["growth"], row["unallocated"], row["end"], row["gap"]) == (20, 5, 115, 0)


def test_report_has_the_polygon_section(runs):
    _, free = runs
    with open(os.path.join(free.directory, "report.html"), encoding="utf-8") as handle:
        page = handle.read()
    assert "indicateurs de plausibilité" in page and "Bilan de masse" in page


def test_comparison_of_the_two_modes(runs):
    planned, free = runs
    rows = compare(planned.directory, free.directory)
    first, last = rows[0], rows[-1]
    assert first["urban_area_planned_km2"] == first["urban_area_free_km2"] == pytest.approx(9 * 0.0625)
    assert last["urban_area_planned_km2"] == pytest.approx(9 * 0.0625)
    assert last["urban_area_free_km2"] > last["urban_area_planned_km2"]
    assert last["outside_planned_perimeter"] > 0
    assert any(row["front_speed_max"] > 0 for row in rows)
    paths = write_comparison(planned.directory, free.directory)
    assert all(os.path.isfile(p) for p in paths)
    with pytest.raises(NotComparable):
        compare(free.directory, planned.directory)


def test_compare_command(runs, capsys):
    from engine.__main__ import main

    planned, free = runs
    assert main(["compare", planned.directory, free.directory]) == 0
    assert "comparaison_modes.csv" in capsys.readouterr().out


def test_birth_of_a_nucleus_is_not_a_front():
    from engine.plausibility import _row
    from engine.polygons import PolygonTable, Stratum

    table = PolygonTable()
    table.add("U", {"U": Stratum(rank=2)})
    end = {"area_km2": 0.25, "population": 600.0, "perimeter_cells_m": 2000.0}
    row = _row(0, table, 2030, 2035, 5, None, end, {2033}, 250.0, 2)
    assert row["front_speed_m_per_year"] is None and row["reading"] == "naissance"
