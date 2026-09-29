import numpy as np
import pytest

from engine.parameters import (
    LINEAR, ParameterTable, TimeSeries, check_bounds, load_parameters_csv, per_unit, to_hab_per_km2,
)

RATES = TimeSeries((2026, 2040), (3.0, 2.0))


def test_t2_linear_interpolation():
    assert RATES.value_at(2033) == pytest.approx(2.5)


def test_t2_constant_extrapolation():
    assert RATES.value_at(2020) == pytest.approx(3.0)
    assert RATES.value_at(2060) == pytest.approx(2.0)


def test_t2_linear_extrapolation():
    linear = TimeSeries((2026, 2040), (3.0, 2.0), extrapolation=LINEAR)
    assert linear.value_at(2060) == pytest.approx(0.5714285714, rel=1e-9)
    assert linear.value_at(2019) == pytest.approx(3.5)


def test_single_pivot_is_constant():
    series = TimeSeries((2024,), (4.9,))
    assert series.value_at(1990) == series.value_at(2100) == pytest.approx(4.9)


def test_mean_is_midpoint_value_on_a_linear_segment():
    assert RATES.mean(2026, 2031) == pytest.approx(RATES.value_at(2028.5))


def test_mean_across_a_pivot_year():
    series = TimeSeries((2030,), (2.0,))
    assert series.mean(2025, 2035) == pytest.approx(2.0)
    kinked = TimeSeries((2020, 2030, 2040), (0.0, 10.0, 10.0))
    # Mean over [2025, 2035]: triangle-trapezoid 5..10 then flat 10.
    assert kinked.mean(2025, 2035) == pytest.approx((7.5 * 5 + 10 * 5) / 10)


def test_mean_with_linear_extrapolation():
    linear = TimeSeries((2026, 2040), (3.0, 2.0), extrapolation=LINEAR)
    assert linear.mean(2040, 2054) == pytest.approx(1.5)


def test_parameter_table_default_and_class_values():
    table = ParameterTable("dmax", {"*": TimeSeries.constant(2500), "Urbain1": TimeSeries.constant(10000)})
    values = table.value_by_class(["Rural", "Urbain1"], 2030)
    np.testing.assert_allclose(values, [2500, 10000])


def test_parameter_table_missing_class_without_default():
    table = ParameterTable("dmax", {"Urbain1": TimeSeries.constant(10000)})
    with pytest.raises(KeyError):
        table.for_key("Rural")


def test_units_without_class_are_rejected():
    with pytest.raises(ValueError):
        per_unit(np.array([0, -1]), np.array([1.0]), "dmax")


def test_density_units():
    np.testing.assert_allclose(to_hab_per_km2([25.0], "hab/ha"), [2500.0])
    with pytest.raises(ValueError):
        to_hab_per_km2([1.0], "hab/m2")


def test_bounds_are_clamped_and_reported():
    values, warnings = check_bounds(np.array([10.0, -5.0]), "dmax", 0.0)
    np.testing.assert_allclose(values, [10.0, 0.0])
    assert len(warnings) == 1


def test_load_parameters_csv(tmp_path):
    path = tmp_path / "parameters.csv"
    path.write_text(
        "key,year,parameter,value\n"
        "*,2026,growth_rate,3\n"
        "*,2040,growth_rate,2\n"
        "Rural,,dmax,2500\n"
        "Urbain1,,dmax,10000\n",
        encoding="utf-8",
    )
    tables = load_parameters_csv(str(path))
    assert tables["growth_rate"].for_key("Rural").value_at(2033) == pytest.approx(2.5)
    assert tables["dmax"].for_key("Urbain1").value_at(2050) == pytest.approx(10000)


def test_zone_value_takes_precedence_over_class_and_default(utm35s_wkt):
    from engine.grid import Grid
    from engine.parameters import unit_means, unit_values
    from engine.units import Layer, Zone, build_units
    from helpers import square

    grid = Grid.covering((0, 0, 750, 250), 250, utm35s_wkt)
    typology = [Zone(square(0, 0, 500, 250), "Rural"), Zone(square(500, 0, 750, 250), "Urbain")]
    zones = Layer("param_zone", [square(0, 0, 250, 250)], ["pole"])
    units = build_units(grid, square(0, 0, 750, 250), typology, layers=[zones])
    rates = ParameterTable("growth_rate", {
        "*": TimeSeries.constant(2.0),
        "Urbain": TimeSeries.constant(4.0),
        "pole": TimeSeries((2026, 2040), (6.0, 3.0)),
    })
    values = unit_values(rates, units, 2033)
    np.testing.assert_allclose(values, [4.5, 2.0, 4.0])
    np.testing.assert_allclose(unit_means(rates, units, 2026, 2040), [4.5, 2.0, 4.0])
