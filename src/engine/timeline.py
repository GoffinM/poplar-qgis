"""Calendar of the simulation (spec §5).

The simulation runs from the start year to the end year in steps of
``time_step`` years. Output years and event years (exclusions that start
on a given year) always fall on a step boundary. With
``migration_frequency = "annual"``, each step is cut into sub-steps of at
most one year, each with growth then migration; with ``"time_step"``, the
whole step is handled at once (faster, coarser).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

ANNUAL = "annual"
PER_STEP = "time_step"
_EPS = 1e-9


@dataclass(frozen=True)
class SubStep:
    start: float
    end: float
    migrate: bool
    output: bool
    """True on the last sub-step of a step ending on an output year."""

    @property
    def duration(self) -> float:
        return self.end - self.start


def build_timeline(
    start_year: float,
    end_year: float,
    time_step: float,
    output_years: Optional[Sequence[float]] = None,
    migration_frequency: str = ANNUAL,
    first_migration_year: Optional[float] = None,
    event_years: Iterable[float] = (),
) -> List[SubStep]:
    """Sub-steps from ``start_year`` to ``end_year``.

    Without ``output_years``, results are written at the end of every step.
    Migration happens in a sub-step whose end is at or after
    ``first_migration_year`` (from the start if it is None).
    """
    if end_year <= start_year:
        raise ValueError("the end year must be after the start year")
    if time_step <= 0:
        raise ValueError("the time step must be positive")
    if migration_frequency not in (ANNUAL, PER_STEP):
        raise ValueError(f"unknown migration frequency: {migration_frequency!r}")

    boundaries = {float(start_year), float(end_year)}
    count = int(math.floor((end_year - start_year) / time_step + _EPS))
    boundaries.update(start_year + i * time_step for i in range(1, count + 1))
    outputs = None if output_years is None else {float(y) for y in output_years if start_year < y <= end_year}
    if outputs:
        boundaries.update(outputs)
    boundaries.update(float(y) for y in event_years if start_year < y < end_year)
    edges = _unique_sorted(y for y in boundaries if start_year - _EPS <= y <= end_year + _EPS)

    substeps: List[SubStep] = []
    for start, end in zip(edges[:-1], edges[1:]):
        parts = max(1, math.ceil(end - start - _EPS)) if migration_frequency == ANNUAL else 1
        cuts = [start + (end - start) * i / parts for i in range(parts + 1)]
        is_output = outputs is None or any(abs(end - y) < _EPS for y in outputs)
        for i, (a, b) in enumerate(zip(cuts[:-1], cuts[1:])):
            migrate = first_migration_year is None or b >= first_migration_year - _EPS
            substeps.append(SubStep(a, b, migrate, is_output and i == parts - 1))
    return substeps


def _unique_sorted(values: Iterable[float]) -> List[float]:
    result: List[float] = []
    for value in sorted(values):
        if not result or value - result[-1] > _EPS:
            result.append(value)
    return result
