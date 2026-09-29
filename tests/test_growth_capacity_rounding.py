import numpy as np
import pytest

from engine.capacity import capacity
from engine.growth import grow, growth_factor
from engine.parameters import TimeSeries
from engine.rounding import round_preserving_total


def test_t1_constant_rate():
    assert grow(np.array([100.0]), 2.0, 5)[0] == pytest.approx(110.40808032, rel=1e-10)


def test_t1_step_size_does_not_matter_at_constant_rate():
    one_step = growth_factor(2.0, 5)
    five_steps = growth_factor(2.0, 1) ** 5
    assert one_step == pytest.approx(five_steps, rel=1e-9)


def test_t3_variable_rate_uses_the_mean_over_the_step():
    rates = TimeSeries((2026, 2040), (3.0, 2.0))
    mean = rates.mean(2026, 2031)
    assert mean == pytest.approx(2.8214285714, rel=1e-9)
    assert grow(np.array([1000.0]), mean, 5)[0] == pytest.approx(1149.2597, abs=1e-4)


def test_t3_sensitivity_to_the_step_is_tiny():
    rates = TimeSeries((2026, 2040), (3.0, 2.0))
    coarse = growth_factor(rates.mean(2026, 2031), 5)
    fine = np.prod([growth_factor(rates.mean(y, y + 1), 1) for y in range(2026, 2031)])
    assert fine * 1000 == pytest.approx(1149.2569, abs=1e-4)
    assert abs(coarse / fine - 1) < 1e-4


def test_rates_at_or_below_minus_100_percent_are_rejected():
    with pytest.raises(ValueError):
        growth_factor(-100.0, 1)


def test_t8_overloaded_unit_keeps_its_base_density():
    # Unit 0: d0 = 12 > dmax = 10, so its ceiling is 12. Unit 1: empty, ceiling 10.
    area = np.array([1.0, 1.0])
    p0 = np.array([12.0, 0.0])
    cap = capacity(area, p0, np.array([10.0, 10.0]), np.array([False, False]))
    np.testing.assert_allclose(cap, [12.0, 10.0])
    after_growth = grow(p0, 10.0, 1)
    np.testing.assert_allclose(after_growth, [13.2, 0.0])
    np.testing.assert_allclose(np.maximum(after_growth - cap, 0), [1.2, 0.0])


def test_t7_no_inflow_unit_ceiling_is_its_base_population():
    area = np.array([1.0, 1.0])
    p0 = np.array([10.0, 0.0])
    cap = capacity(area, p0, np.array([10.0, 10.0]), np.array([True, False]))
    np.testing.assert_allclose(cap, [10.0, 10.0])
    after_growth = grow(p0, 10.0, 1)
    np.testing.assert_allclose(np.maximum(after_growth - cap, 0), [1.0, 0.0])


def test_t13_capacity_of_a_cell_split_between_two_classes():
    area = np.array([0.75, 0.25])
    p0 = np.array([600.0, 200.0])
    cap = capacity(area, p0, np.array([1000.0, 4000.0]), np.array([False, False]))
    np.testing.assert_allclose(cap, [750.0, 1000.0])
    assert cap.sum() == pytest.approx(1750.0)


def test_t10_largest_remainder():
    np.testing.assert_array_equal(round_preserving_total(np.array([1.4, 1.4, 1.2])), [2, 1, 1])


def test_rounding_preserves_the_total_on_random_values():
    values = np.random.default_rng(0).gamma(2.0, 50.0, size=10_000)
    rounded = round_preserving_total(values)
    assert rounded.sum() == round(values.sum())
    assert np.all(np.abs(rounded - values) < 1)


def test_rounding_rejects_negative_populations():
    with pytest.raises(ValueError):
        round_preserving_total(np.array([-1.0]))
