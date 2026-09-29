"""Migration with a non-convergence policy (spec §7).

Before migrating, the total excess is compared with the total free
capacity of the units that may receive population. If it cannot fit, the
chosen policy applies:

- ``stop``: raise :class:`NonConvergenceError` with the diagnostics;
- ``raise_dmax``: compute the smallest increase of ``dmax`` that makes room,
  round it up to the next step (5 %), and apply it only once approved;
- ``sink``: add a ring of sink cells around the study area as receivers;
- ``unallocated``: migrate as far as possible and record the population
  that could not be placed, where it stands.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import numpy as np

from .capacity import capacity as unit_capacity
from .migration import EPSILON, MigrationResult, migrate

STOP = "stop"
RAISE_DMAX = "raise_dmax"
SINK = "sink"
UNALLOCATED = "unallocated"
POLICIES = (STOP, RAISE_DMAX, SINK, UNALLOCATED)

SUCCESS = "success"
SUCCESS_WITH_ADJUSTMENTS = "success_with_adjustments"
PARTIAL = "partial"
FAILED = "failed"


class NonConvergenceError(RuntimeError):
    """The population cannot be placed under the current constraints."""

    def __init__(self, message: str, deficit: float, proposal: Optional["DmaxProposal"] = None):
        super().__init__(message)
        self.deficit = deficit
        self.proposal = proposal


@dataclass
class DmaxProposal:
    minimal_factor: float
    """Exact smallest factor on ``dmax`` that makes room for everybody."""
    factor: float
    """Proposed factor, rounded up to the next step (e.g. 1.25 for +25 %)."""
    deficit: float
    scope_units: int

    @property
    def increase_percent(self) -> float:
        return round((self.factor - 1.0) * 100.0, 6)


@dataclass
class Sink:
    """Ring of sink cells around the study area (spec §7.2, S5).

    Its population persists from one step to the next.
    """

    x: np.ndarray
    y: np.ndarray
    capacity: np.ndarray
    population: np.ndarray


@dataclass
class MigrationSettings:
    k: int = 3
    tolerance: int = 1
    max_iterations: int = 10_000
    policy: str = STOP
    max_auto_increase: float = 0.0
    """Largest ``dmax`` increase applied without approval (0.25 = +25 %)."""
    dmax_step: float = 0.05
    approve: Optional[Callable[[DmaxProposal], bool]] = None
    """Interactive approval of a ``dmax`` increase (used by the plugin)."""
    dmax_scope: Optional[np.ndarray] = None
    """Units where ``dmax`` may be raised (all receivable units if None)."""

    def __post_init__(self) -> None:
        if self.policy not in POLICIES:
            raise ValueError(f"unknown policy {self.policy!r} (expected one of {POLICIES})")


@dataclass
class StepOutcome:
    population: np.ndarray
    capacity: np.ndarray
    unallocated: np.ndarray
    """Population that could not be placed in this step, per unit."""
    migration: MigrationResult
    status: str
    dmax_factor: float = 1.0
    sink_population: Optional[np.ndarray] = None
    messages: List[str] = field(default_factory=list)


def capacity_deficit(population, capacity, receivable) -> float:
    """Total excess minus the total free capacity of receivable units (> 0: cannot fit)."""
    excess = np.maximum(population - capacity, 0).sum()
    free = np.maximum(capacity - population, 0)[receivable].sum()
    return float(excess - free)


def minimal_dmax_factor(
    population, area_km2, base_population, dmax, no_inflow, receivable, scope, tolerance: float
) -> float:
    """Smallest factor on ``dmax`` (inside ``scope``) such that the excess fits."""

    def deficit(factor: float) -> float:
        scaled = np.where(scope, dmax * factor, dmax)
        cap = unit_capacity(area_km2, base_population, scaled, no_inflow)
        return capacity_deficit(population, cap, receivable)

    low, high = 1.0, 2.0
    while deficit(high) > 0:
        high *= 2.0
        if high > 1e6:
            raise NonConvergenceError(
                "no increase of the maximum densities can make room for the population "
                "(the units that may receive population have no area)",
                deficit(1.0),
            )
    for _ in range(100):
        middle = (low + high) / 2.0
        if deficit(middle) > 0:
            low = middle
        else:
            high = middle
    return high


def migrate_with_policy(
    population: np.ndarray,
    area_km2: np.ndarray,
    base_population: np.ndarray,
    dmax_hab_km2: np.ndarray,
    no_inflow: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    settings: MigrationSettings,
    evacuated: Optional[np.ndarray] = None,
    sink: Optional[Sink] = None,
) -> StepOutcome:
    """One migration step, with the capacity check and the non-convergence policy.

    ``evacuated`` units (a zone that becomes uninhabitable, X1 ``relocate``)
    get a capacity of zero and receive nobody, so all their inhabitants move.
    """
    population = np.asarray(population, dtype=np.float64)
    no_inflow = np.asarray(no_inflow, dtype=bool)
    evacuated = np.zeros(len(population), dtype=bool) if evacuated is None else np.asarray(evacuated, dtype=bool)
    dmax = np.asarray(dmax_hab_km2, dtype=np.float64)
    receivable = ~no_inflow & ~evacuated
    cap = _capacity(area_km2, base_population, dmax, no_inflow, evacuated)
    messages: List[str] = []
    factor = 1.0
    status = SUCCESS

    deficit = capacity_deficit(population, cap, receivable)
    if deficit >= settings.tolerance:
        messages.append(
            f"Capacité insuffisante : {deficit:,.0f} habitants ne peuvent pas être placés "
            "avec les densités maximales actuelles.".replace(",", " ")
        )
        if settings.policy == STOP:
            raise NonConvergenceError(messages[-1], deficit)
        if settings.policy == RAISE_DMAX:
            scope = receivable if settings.dmax_scope is None else (np.asarray(settings.dmax_scope, bool) & receivable)
            exact = minimal_dmax_factor(population, area_km2, base_population, dmax, no_inflow, receivable, scope,
                                        settings.tolerance)
            steps = math.ceil(round((exact - 1.0) / settings.dmax_step, 9))
            proposal = DmaxProposal(exact, 1.0 + steps * settings.dmax_step, deficit, int(scope.sum()))
            approved = (
                settings.approve(proposal) if settings.approve is not None
                else proposal.factor - 1.0 <= settings.max_auto_increase + 1e-12
            )
            if not approved:
                raise NonConvergenceError(
                    messages[-1] + f" Une hausse de {proposal.increase_percent:g} % des densités maximales "
                    "permettrait de les placer ; elle n'a pas été validée.",
                    deficit, proposal,
                )
            factor = proposal.factor
            dmax = np.where(scope, dmax * factor, dmax)
            cap = _capacity(area_km2, base_population, dmax, no_inflow, evacuated)
            status = SUCCESS_WITH_ADJUSTMENTS
            messages.append(f"Densités maximales relevées de {proposal.increase_percent:g} % "
                            f"sur {proposal.scope_units} unités.")
        if settings.policy == SINK:
            if sink is None:
                raise ValueError("the 'sink' policy needs a ring of sink cells")
            return _migrate_with_sink(population, cap, receivable, x, y, settings, sink, messages)

    result = migrate(population, cap, receivable, x, y, settings.k, settings.tolerance, settings.max_iterations,
                     export_all=~receivable)
    unallocated = np.zeros(len(population))
    if not result.converged:
        excess = result.population - cap
        leftover = np.where((excess >= settings.tolerance) | (~receivable & (excess > EPSILON)), excess, 0.0)
        reason = ("plus aucune unité n'a de place libre" if result.receivers_exhausted
                  else f"nombre maximal d'itérations atteint ({settings.max_iterations})")
        message = f"La migration n'a pas convergé ({reason}) : {leftover.sum():,.0f} habitants en excès.".replace(",", " ")
        if settings.policy != UNALLOCATED:
            raise NonConvergenceError(message, float(leftover.sum()))
        unallocated = leftover
        result.population = result.population - leftover
        status = PARTIAL
        messages.append(message + " Ils sont enregistrés comme population non relocalisée.")
    return StepOutcome(result.population, cap, unallocated, result, status, factor, None, messages)


def _migrate_with_sink(population, cap, receivable, x, y, settings, sink, messages) -> StepOutcome:
    n = len(population)
    all_population = np.concatenate([population, sink.population])
    all_capacity = np.concatenate([cap, sink.capacity])
    all_receivable = np.concatenate([receivable, np.ones(len(sink.x), dtype=bool)])
    result = migrate(
        all_population, all_capacity, all_receivable,
        np.concatenate([x, sink.x]), np.concatenate([y, sink.y]),
        settings.k, settings.tolerance, settings.max_iterations,
        export_all=~all_receivable,
    )
    if not result.converged:
        raise NonConvergenceError(
            "La couronne de mailles puits ne suffit pas à placer toute la population.",
            result.remaining_excess,
        )
    placed = float(result.population[n:].sum() - sink.population.sum())
    messages.append(f"{placed:,.0f} habitants placés dans la couronne de mailles puits.".replace(",", " "))
    migration = MigrationResult(result.population[:n], result.iterations, True, result.moved,
                                result.remaining_excess, result.receivers_exhausted)
    return StepOutcome(result.population[:n], cap, np.zeros(n), migration, SUCCESS_WITH_ADJUSTMENTS, 1.0,
                       result.population[n:], messages)


def _capacity(area_km2, base_population, dmax, no_inflow, evacuated) -> np.ndarray:
    cap = unit_capacity(area_km2, base_population, dmax, no_inflow)
    return np.where(evacuated, 0.0, cap)
