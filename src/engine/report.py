"""Step report, as JSON for machines and plain text for people (spec §8.3)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import List

from .i18n import DEFAULT_LANGUAGE, Message, format_number, translate
from .nonconvergence import StepOutcome



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
    messages: List[Message] = field(default_factory=list)

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

    def to_dict(self, language: str = DEFAULT_LANGUAGE) -> dict:
        data = asdict(self)
        data["messages"] = [m.to_dict(language) for m in self.messages]
        data["balance_error"] = self.balance_error
        return data

    def to_json(self, language: str = DEFAULT_LANGUAGE) -> str:
        return json.dumps(self.to_dict(language), ensure_ascii=False, indent=2)

    def to_text(self, language: str = DEFAULT_LANGUAGE) -> str:
        def fmt(value: float) -> str:
            return format_number(value, language, decimals=0)

        def line(code: str, value: str) -> str:
            return f"  {translate(code, language):<30}: {value}"

        status = translate(f"status_{self.status}", language)
        lines = [
            translate("report_step", language, start=f"{self.start:g}", end=f"{self.end:g}", status=status),
            line("report_population_before_growth", fmt(self.population_before_growth)),
            line("report_population_after_growth", fmt(self.population_after_growth)),
            line("report_population_after_migration", fmt(self.population_after_migration)),
            line("report_moved", f"{fmt(self.moved)} ({translate('report_iterations', language, iterations=self.iterations)})"),
        ]
        if self.placed_in_sink:
            lines.append(line("report_placed_in_sink", fmt(self.placed_in_sink)))
        if self.unallocated:
            lines.append(line("report_unallocated", fmt(self.unallocated)))
        if self.dmax_factor != 1.0:
            lines.append(line("report_dmax_factor", f"{format_number((self.dmax_factor - 1) * 100, language)} %"))
        lines.append(line("report_balance_error",
                          f"{format_number(self.balance_error, language, decimals=6)} {translate('report_inhabitant', language)}"))
        lines.extend(f"  • {m.render(language)}" for m in self.messages)
        return "\n".join(lines)
