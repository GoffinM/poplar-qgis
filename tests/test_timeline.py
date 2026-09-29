import pytest

from engine.timeline import PER_STEP, build_timeline


def _ends(steps):
    return [(s.start, s.end) for s in steps]


def test_annual_substeps_within_five_year_steps():
    steps = build_timeline(2025, 2035, 5)
    assert len(steps) == 10
    assert [s.end for s in steps if s.output] == [2030, 2035]


def test_per_step_migration():
    steps = build_timeline(2025, 2035, 5, migration_frequency=PER_STEP)
    assert _ends(steps) == [(2025, 2030), (2030, 2035)]
    assert all(s.migrate and s.output for s in steps)


def test_output_and_event_years_fall_on_boundaries():
    steps = build_timeline(2024, 2040, 10, output_years=[2030, 2037, 2040], migration_frequency=PER_STEP,
                           event_years=[2032])
    assert _ends(steps) == [(2024, 2030), (2030, 2032), (2032, 2034), (2034, 2037), (2037, 2040)]
    assert [s.end for s in steps if s.output] == [2030, 2037, 2040]


def test_last_step_is_shortened_to_the_end_year():
    steps = build_timeline(2024, 2030, 4, migration_frequency=PER_STEP)
    assert _ends(steps) == [(2024, 2028), (2028, 2030)]


def test_sub_annual_step():
    steps = build_timeline(2024, 2025, 0.25)
    assert len(steps) == 4
    assert steps[0].duration == pytest.approx(0.25)


def test_t14_first_migration_year():
    steps = build_timeline(2024, 2027, 1, first_migration_year=2026)
    assert [(s.end, s.migrate) for s in steps] == [(2025, False), (2026, True), (2027, True)]


def test_invalid_calendar():
    with pytest.raises(ValueError):
        build_timeline(2030, 2024, 1)
    with pytest.raises(ValueError):
        build_timeline(2024, 2030, 0)
