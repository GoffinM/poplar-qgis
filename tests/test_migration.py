import numpy as np
import pytest

from engine.capacity import capacity
from engine.migration import migrate, migrate_legacy, nearest_receivers
from engine.nonconvergence import (
    PARTIAL, RAISE_DMAX, SINK, STOP, SUCCESS, SUCCESS_WITH_ADJUSTMENTS, UNALLOCATED,
    MigrationSettings, NonConvergenceError, Sink, migrate_with_policy,
)
from engine.report import StepReport

LINE_X = np.arange(5, dtype=float)
LINE_Y = np.zeros(5)


def test_t4_single_iteration():
    result = migrate([0, 0, 25, 0, 0], [10] * 5, [True] * 5, LINE_X, LINE_Y)
    np.testing.assert_allclose(result.population, [5, 5, 10, 5, 0])
    assert (result.iterations, result.converged, result.moved) == (1, True, 15)


def test_t5_cascade():
    result = migrate([0, 0, 46, 0, 0], [10] * 5, [True] * 5, LINE_X, LINE_Y)
    np.testing.assert_allclose(result.population, [10, 10, 10, 10, 6])
    assert result.iterations == 2
    assert result.population.sum() == pytest.approx(46)


def test_t6_incomplete_unit_conserves_population():
    area = np.array([1.0, 0.25])
    cap = capacity(area, np.array([10.0, 0.0]), np.array([10.0, 10.0]), np.array([False, False]))
    result = migrate([12.0, 0.0], cap, [True, True], [0.0, 1.0], [0.0, 0.0], k=1)
    np.testing.assert_allclose(result.population, [10, 2])
    assert result.population[1] / area[1] == pytest.approx(8.0)


def test_t6_legacy_mode_loses_population():
    area = np.array([1.0, 0.25])
    legacy = migrate_legacy([12.0, 0.0], [10.0, 10.0], [0.0, 1.0], [0.0, 0.0], k=1)
    np.testing.assert_allclose(legacy.density, [10, 2])
    assert (legacy.density * area).sum() == pytest.approx(10.5)


def test_t7_no_inflow_unit_exports_its_growth_and_receives_nothing():
    no_inflow = np.array([True, False])
    area = np.ones(2)
    cap = capacity(area, np.array([10.0, 0.0]), np.array([10.0, 10.0]), no_inflow)
    result = migrate([11.0, 0.0], cap, ~no_inflow, [0.0, 1.0], [0.0, 0.0])
    np.testing.assert_allclose(result.population, [10, 1])


def test_t8_overloaded_unit_keeps_its_base_density():
    cap = capacity(np.ones(2), np.array([12.0, 0.0]), np.array([10.0, 10.0]), np.array([False, False]))
    result = migrate([13.2, 0.0], cap, [True, True], [0.0, 1.0], [0.0, 0.0])
    np.testing.assert_allclose(result.population, [12, 1.2])


def test_excess_below_one_inhabitant_stays_in_place():
    result = migrate([10.8, 0.0], [10.0, 10.0], [True, True], [0.0, 1.0], [0.0, 0.0])
    np.testing.assert_allclose(result.population, [10.8, 0.0])
    assert result.converged and result.iterations == 0


def test_no_inflow_units_export_even_a_fraction_of_an_inhabitant():
    no_inflow = np.array([True, False])
    result = migrate([10.4, 0.0], [10.0, 10.0], ~no_inflow, [0.0, 1.0], [0.0, 0.0], export_all=no_inflow)
    np.testing.assert_allclose(result.population, [10.0, 0.4])
    assert result.converged


def test_tolerance_must_be_a_whole_number():
    with pytest.raises(ValueError):
        migrate([1.0], [1.0], [True], [0.0], [0.0], tolerance=0.5)


# --- T9: non-convergence -----------------------------------------------------------

T9 = dict(
    population=np.array([15.0, 10.0]),
    area_km2=np.ones(2),
    base_population=np.array([8.0, 8.0]),
    dmax_hab_km2=np.array([10.0, 10.0]),
    no_inflow=np.array([False, False]),
    x=np.array([0.0, 1.0]),
    y=np.zeros(2),
)


def test_t9_stop():
    with pytest.raises(NonConvergenceError) as error:
        migrate_with_policy(**T9, settings=MigrationSettings(policy=STOP))
    assert error.value.deficit == pytest.approx(5)


def test_t9_raise_dmax_approved():
    proposals = []

    def approve(proposal):
        proposals.append(proposal)
        return True

    outcome = migrate_with_policy(**T9, settings=MigrationSettings(policy=RAISE_DMAX, approve=approve))
    assert proposals[0].minimal_factor == pytest.approx(1.25, abs=1e-9)
    assert proposals[0].increase_percent == pytest.approx(25)
    np.testing.assert_allclose(outcome.population, [12.5, 12.5])
    assert outcome.status == SUCCESS_WITH_ADJUSTMENTS
    assert outcome.dmax_factor == pytest.approx(1.25)


def test_t9_raise_dmax_refused_or_above_the_automatic_limit():
    with pytest.raises(NonConvergenceError) as error:
        migrate_with_policy(**T9, settings=MigrationSettings(policy=RAISE_DMAX, max_auto_increase=0.20))
    assert error.value.proposal.factor == pytest.approx(1.25)
    with pytest.raises(NonConvergenceError):
        migrate_with_policy(**T9, settings=MigrationSettings(policy=RAISE_DMAX, approve=lambda p: False))
    outcome = migrate_with_policy(**T9, settings=MigrationSettings(policy=RAISE_DMAX, max_auto_increase=0.25))
    np.testing.assert_allclose(outcome.population, [12.5, 12.5])


def test_proposal_is_rounded_up_to_the_next_step():
    case = dict(T9, population=np.array([15.2, 10.0]))  # exact factor 1.26
    outcome = migrate_with_policy(**case, settings=MigrationSettings(policy=RAISE_DMAX, approve=lambda p: True))
    assert outcome.dmax_factor == pytest.approx(1.30)


def test_t9_unallocated():
    outcome = migrate_with_policy(**T9, settings=MigrationSettings(policy=UNALLOCATED))
    np.testing.assert_allclose(outcome.population, [10, 10])
    np.testing.assert_allclose(outcome.unallocated, [5, 0])
    assert outcome.status == PARTIAL
    assert outcome.population.sum() + outcome.unallocated.sum() == pytest.approx(25)


def test_t9_sink():
    sink = Sink(x=np.array([2.0]), y=np.zeros(1), capacity=np.array([100.0]), population=np.zeros(1))
    outcome = migrate_with_policy(**T9, settings=MigrationSettings(policy=SINK), sink=sink)
    np.testing.assert_allclose(outcome.population, [10, 10])
    np.testing.assert_allclose(outcome.sink_population, [5])


def test_sink_too_small():
    sink = Sink(x=np.array([2.0]), y=np.zeros(1), capacity=np.array([2.0]), population=np.zeros(1))
    with pytest.raises(NonConvergenceError):
        migrate_with_policy(**T9, settings=MigrationSettings(policy=SINK), sink=sink)


def test_evacuated_units_move_all_their_inhabitants():
    outcome = migrate_with_policy(
        population=np.array([5.0, 0.0, 0.0]), area_km2=np.ones(3), base_population=np.array([5.0, 0.0, 0.0]),
        dmax_hab_km2=np.full(3, 10.0), no_inflow=np.zeros(3, bool), x=np.arange(3.0), y=np.zeros(3),
        settings=MigrationSettings(), evacuated=np.array([True, False, False]),
    )
    np.testing.assert_allclose(outcome.population, [0, 2.5, 2.5])
    assert outcome.status == SUCCESS


# --- Determinism and invariants -----------------------------------------------------

def test_t12_determinism_with_ties():
    # 7 x 7 grid, one overloaded cell in the middle: many receivers at equal distance.
    xs, ys = np.meshgrid(np.arange(7.0), np.arange(7.0))
    population = np.zeros(49)
    population[24] = 100.0
    runs = [migrate(population, np.full(49, 10.0), np.ones(49, bool), xs.ravel(), ys.ravel()).population
            for _ in range(2)]
    np.testing.assert_array_equal(runs[0], runs[1])
    # Ties at distance 1 are broken by the lowest index: cells 17, 23, 25 (not 31).
    first = nearest_receivers(np.array([[3.0, 3.0]]), np.column_stack([xs.ravel(), ys.ravel()])[[17, 23, 25, 31]],
                              np.array([17, 23, 25, 31]), 3)
    np.testing.assert_array_equal(first, [[17, 23, 25]])


@pytest.mark.parametrize("seed", range(5))
def test_invariants_on_random_grids(seed):
    rng = np.random.default_rng(seed)
    n = 900
    xs, ys = np.meshgrid(np.arange(30.0), np.arange(30.0))
    area = rng.uniform(0.2, 1.0, n)
    p0 = rng.gamma(1.5, 100.0, n) * area
    no_inflow = rng.random(n) < 0.1
    dmax = np.full(n, 400.0)
    cap = capacity(area, p0, dmax, no_inflow)
    grown = p0 * 1.3
    result = migrate(grown, cap, ~no_inflow, xs.ravel(), ys.ravel(), export_all=no_inflow)
    assert result.converged
    assert result.population.sum() == pytest.approx(grown.sum(), rel=1e-12)          # I1
    assert np.all(result.population - cap < 1)                                          # I2
    assert np.all(result.population[no_inflow] <= grown[no_inflow] + 1e-9)            # I3: never receive
    assert np.all(result.population[no_inflow] <= cap[no_inflow] + 1e-6)              # I3: back to P0
    assert np.all(result.population >= 0)                                               # I7


def test_step_report():
    outcome = migrate_with_policy(**T9, settings=MigrationSettings(policy=UNALLOCATED))
    report = StepReport.from_outcome(2024, 2025, 22.0, 25.0, outcome)
    assert report.balance_error == pytest.approx(0)
    assert "partiel" in report.to_text()
    assert '"status": "partial"' in report.to_json()


# --- Free strata mode: record of the inflows, ties shared (plan_polygones_libres.md §3b, P16) ----------

def random_grid(seed):
    rng = np.random.default_rng(seed)
    n = 900
    xs, ys = np.meshgrid(np.arange(30.0), np.arange(30.0))
    area = rng.uniform(0.2, 1.0, n)
    p0 = rng.gamma(1.5, 100.0, n) * area
    no_inflow = rng.random(n) < 0.1
    cap = capacity(area, p0, np.full(n, 400.0), no_inflow)
    labels = rng.integers(-1, 4, n)
    return p0 * 1.3, cap, no_inflow, xs.ravel(), ys.ravel(), labels


@pytest.mark.parametrize("seed", range(3))
def test_recording_the_inflows_changes_nothing(seed):
    grown, cap, no_inflow, x, y, labels = random_grid(seed)
    plain = migrate(grown, cap, ~no_inflow, x, y, export_all=no_inflow)
    recorded = migrate(grown, cap, ~no_inflow, x, y, export_all=no_inflow, labels=labels)
    np.testing.assert_array_equal(plain.population, recorded.population)
    assert plain.inflow is None
    # Every inhabitant moved is recorded once per move, under the label of the unit that sent it.
    sent_by_labelled = recorded.inflow.total()
    assert sent_by_labelled <= recorded.moved + 1e-6
    unlabelled = migrate(grown, cap, ~no_inflow, x, y, export_all=no_inflow, labels=np.zeros(900, int))
    assert unlabelled.inflow.total() == pytest.approx(unlabelled.moved, rel=1e-12)


def test_inflow_is_credited_to_the_direct_sender():
    # Unit 0 (label 7) overflows into unit 1 (label 3), which overflows into unit 2 (label 3).
    result = migrate([30.0, 0.0, 0.0], [10.0, 10.0, 100.0], [True] * 3, [0.0, 1.0, 2.0], [0.0] * 3, k=1,
                     labels=np.array([7, 3, 3]))
    inflow = result.inflow
    assert inflow.received(np.array([1]), np.array([7]))[0] == pytest.approx(20.0)
    assert inflow.received(np.array([2]), np.array([7]))[0] == 0.0
    assert inflow.received(np.array([2]), np.array([3]))[0] == pytest.approx(10.0)


def test_ties_shared_equally():
    # One source, four receivers at distance 1, k = 3: each receives a quarter instead of a third
    # for the three lowest indices.
    xs, ys = np.meshgrid(np.arange(3.0), np.arange(3.0))
    population = np.zeros(9)
    population[4] = 22.0
    cap = np.full(9, 10.0)
    cap[[0, 2, 6, 8]] = 0.0                                       # the corners take nobody
    shared = migrate(population, cap, cap > 0, xs.ravel(), ys.ravel(), share_ties=True)
    np.testing.assert_allclose(shared.population[[1, 3, 5, 7]], [3.0, 3.0, 3.0, 3.0])
    assert shared.population.sum() == pytest.approx(22.0)
    lowest = migrate(population, cap, cap > 0, xs.ravel(), ys.ravel())
    np.testing.assert_allclose(lowest.population[[1, 3, 5, 7]], [4.0, 4.0, 4.0, 0.0])


def test_ties_beyond_the_closer_receivers_share_what_is_left():
    # Receivers at distances 1, 2, 2, 2 (k = 3): the closest gets 1/3, the three tied share 2/3.
    population = np.array([12.0, 0.0, 0.0, 0.0, 0.0])
    x = np.array([0.0, 1.0, 2.0, -2.0, 0.0])
    y = np.array([0.0, 0.0, 0.0, 0.0, 2.0])
    result = migrate(population, [9.0, 10.0, 10.0, 10.0, 10.0], [True] * 5, x, y, share_ties=True)
    np.testing.assert_allclose(result.population, [9.0, 1.0, 2.0 / 3, 2.0 / 3, 2.0 / 3])


@pytest.mark.parametrize("seed", range(3))
def test_shared_ties_keep_the_invariants(seed):
    grown, cap, no_inflow, x, y, labels = random_grid(seed)
    result = migrate(grown, cap, ~no_inflow, x, y, export_all=no_inflow, share_ties=True, labels=labels)
    assert result.converged
    assert result.population.sum() == pytest.approx(grown.sum(), rel=1e-12)
    assert np.all(result.population - cap < 1)
    assert np.all(result.population[no_inflow] <= grown[no_inflow] + 1e-9)


def test_policy_migration_returns_the_inflows_without_the_sink():
    sink = Sink(x=np.array([2.0]), y=np.zeros(1), capacity=np.array([100.0]), population=np.zeros(1))
    outcome = migrate_with_policy(**T9, settings=MigrationSettings(policy=SINK), sink=sink, labels=np.array([0, 1]))
    assert outcome.inflow is not None
    assert (outcome.inflow.keys < 2 * outcome.inflow.nlabels).all()
    plain = migrate_with_policy(**T9, settings=MigrationSettings(policy=UNALLOCATED), labels=np.array([0, 1]))
    assert plain.inflow is not None and plain.inflow.total() >= 0
