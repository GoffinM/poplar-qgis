"""Step report, as JSON for machines and plain text for people (spec §8.3)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import List

from .nonconvergence import StepOutcome

STATUS_LABELS = {
    "success": "réussi",
    "success_with_adjustments": "réussi avec ajustements",
    "partial": "partiel (population non relocalisée)",
    "failed": "échec",
}


@dataclass
class StepReport:
    start: float
    end: float
    population_before_growth: float
    population_after_growth: float
    population_after_migration: float
    unallocated: float
    placed_in_sink: float
    moved: float
    iterations: int
    converged: bool
    dmax_factor: float
    status: str
    messages: List[str] = field(default_factory=list)

    @classmethod
    def from_outcome(
        cls, start: float, end: float, before_growth: float, after_growth: float,
        outcome: StepOutcome, sink_before: float = 0.0,
    ) -> "StepReport":
        sink_after = float(outcome.sink_population.sum()) if outcome.sink_population is not None else sink_before
        return cls(
            start=start,
            end=end,
            population_before_growth=before_growth,
            population_after_growth=after_growth,
            population_after_migration=float(outcome.population.sum()),
            unallocated=float(outcome.unallocated.sum()),
            placed_in_sink=sink_after - sink_before,
            moved=outcome.migration.moved,
            iterations=outcome.migration.iterations,
            converged=outcome.migration.converged,
            dmax_factor=outcome.dmax_factor,
            status=outcome.status,
            messages=list(outcome.messages),
        )

    @property
    def balance_error(self) -> float:
        """Population after growth minus everything accounted for afterwards (should be ~0)."""
        return self.population_after_growth - (
            self.population_after_migration + self.unallocated + self.placed_in_sink
        )

    def to_json(self) -> str:
        data = asdict(self)
        data["balance_error"] = self.balance_error
        return json.dumps(data, ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        def fmt(value: float) -> str:
            return f"{value:,.0f}".replace(",", " ")

        lines = [
            f"Pas {self.start:g} → {self.end:g} : {STATUS_LABELS.get(self.status, self.status)}",
            f"  Population avant croissance : {fmt(self.population_before_growth)}",
            f"  Population après croissance : {fmt(self.population_after_growth)}",
            f"  Population après migration  : {fmt(self.population_after_migration)}",
            f"  Habitants déplacés          : {fmt(self.moved)} ({self.iterations} itérations)",
        ]
        if self.placed_in_sink:
            lines.append(f"  Placés en couronne          : {fmt(self.placed_in_sink)}")
        if self.unallocated:
            lines.append(f"  Non relocalisés             : {fmt(self.unallocated)}")
        if self.dmax_factor != 1.0:
            lines.append(f"  Densités max relevées de    : {(self.dmax_factor - 1) * 100:g} %")
        lines.append(f"  Écart de bilan              : {self.balance_error:.6f} habitant")
        lines.extend(f"  • {message}" for message in self.messages)
        return "\n".join(lines)
