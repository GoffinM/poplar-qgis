"""Phase 2 on Muramvya: growth then migration, and comparison with the legacy algorithm."""

import numpy as np
import pytest

from engine.base_population import base_population_from_density
from engine.capacity import capacity
from engine.growth import grow
from engine.migration import migrate_legacy
from engine.nonconvergence import SUCCESS, MigrationSettings, migrate_with_policy
from engine.report import StepReport

DMAX = {"Rural": 2500.0, "Urbain1": 10000.0}


@pytest.fixture(scope="module")
def start(muramvya_case):
    raster, _, units = muramvya_case
    p0, _ = base_population_from_density(units, raster)
    dmax = np.array([DMAX[name] for name in units.class_names])[units.class_index]
    return units, p0, dmax


def test_one_step_2024_2025(start):
    units, p0, dmax = start
    grown = grow(p0, 2.2, 1)
    outcome = migrate_with_policy(grown, units.area_km2, p0, dmax, units.no_inflow, units.cx, units.cy,
                                  MigrationSettings())
    report = StepReport.from_outcome(2024, 2025, p0.sum(), grown.sum(), outcome)
    assert outcome.status == SUCCESS
    assert abs(report.balance_error) < 1e-6                                  # I1
    eligible = ~units.no_inflow
    assert np.all(outcome.population[eligible] - outcome.capacity[eligible] < 1)   # I2
    np.testing.assert_allclose(outcome.population[units.no_inflow], p0[units.no_inflow], atol=1e-6)  # I3
    assert report.moved > 0


def test_thirty_six_annual_steps_stay_consistent(start):
    units, p0, dmax = start
    population = p0.copy()
    for _ in range(36):
        grown = grow(population, 2.2, 1)
        outcome = migrate_with_policy(grown, units.area_km2, p0, dmax, units.no_inflow, units.cx, units.cy,
                                      MigrationSettings())
        assert outcome.population.sum() == pytest.approx(grown.sum(), rel=1e-12)
        population = outcome.population
    assert population.sum() == pytest.approx(p0.sum() * 1.022 ** 36, rel=1e-12)
    cap = capacity(units.area_km2, p0, dmax, units.no_inflow)
    assert np.all(population - cap < 1)
    # No-inflow units export all their excess, even below one inhabitant (A7-bis c1).
    forest = units.no_inflow
    np.testing.assert_allclose(population[forest], p0[forest], atol=1e-6)


def test_legacy_algorithm_loses_population_where_the_new_one_conserves_it(start):
    units, p0, dmax = start
    eligible = ~units.no_inflow
    grown = grow(p0, 2.2, 1)
    area = units.area_km2[eligible]
    density = grown[eligible] / area
    pmax = np.maximum(p0[eligible] / area, dmax[eligible])
    legacy = migrate_legacy(density, pmax, units.cx[eligible], units.cy[eligible])
    assert legacy.converged
    legacy_total = (legacy.density * area).sum()
    assert legacy_total < grown[eligible].sum() - 10
