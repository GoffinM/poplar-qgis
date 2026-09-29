"""Roofs → inhabitants: calibration curves (spec §3 ter, decisions of 29/09/2026).

A roof of area S (m²) holds p(S) inhabitants. Roofs are grouped in area
classes; each class has a number of inhabitants (the « calibration points »,
the solver values of the former Excel workbooks). The curve through these
points takes one of four forms:

- ``steps`` (default): every roof of a class holds the (whole) number of
  inhabitants of its class, roofs above the last class the value of the
  last class — the table of classes is exactly what the roofs receive;
- ``segments``: straight segments between the points, placed at
  the mean roof area of each class (F22), non-decreasing (F21) and flat
  beyond the last class;
- ``polynomial``: least-squares polynomial through the same points, in full
  precision (F20), flat beyond the last point;
- ``legacy``: the Excel method exactly (upper class bounds, rounded
  coefficients of the degree-3 trend line, value p(80) from 70 m²).

Below ``min_area`` (the floor) and above ``max_area`` (exclusion of large,
non-residential buildings; None for no exclusion) a roof holds nobody. Every function works on
numpy arrays, so millions of roofs are processed at once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

STEPS = "steps"
SEGMENTS = "segments"
POLYNOMIAL = "polynomial"
LEGACY = "legacy"
METHODS = (STEPS, SEGMENTS, POLYNOMIAL, LEGACY)

# Former workbooks legacy/calage/demand_conso_Muramvya-*.xlsx (état des lieux §11.2)
LEGACY_EDGES = (0.0, 5.0, 10.0, 15.0, 30.0, 35.0, 40.0, 50.0, 60.0, 70.0, 80.0)
LEGACY_VALUES = {"Rural": (0, 0, 1, 2, 3, 3, 4, 5, 5, 5), "Urbain": (0, 0, 1, 2, 4, 4, 5, 6, 7, 7)}
LEGACY_COEFFICIENTS = {"Rural": (-2e-5, 0.0018, 0.0497, -0.3632), "Urbain": (-2e-5, 0.0022, 0.0569, -0.4777)}
LEGACY_CAP_AREA = 70.0
LEGACY_CAP_VALUE_AREA = 80.0

# Assumptions of the sheet « Classes_detaillees »
AREA_PER_PERSON = 6.5
MAX_PEOPLE = 10


@dataclass
class Curve:
    """Inhabitants per roof as a function of the roof area."""

    method: str = SEGMENTS
    edges: Tuple[float, ...] = LEGACY_EDGES
    """Class limits (m²), increasing: class k is [edges[k], edges[k+1])."""
    values: Tuple[float, ...] = LEGACY_VALUES["Rural"]
    """Inhabitants per roof of each class (calibration points)."""
    min_area: float = 10.0
    max_area: Optional[float] = 450.0
    node_areas: Optional[Tuple[float, ...]] = None
    """Area of each point: mean roof area of the class (set by :meth:`with_data`); class middle otherwise."""
    degree: int = 3
    coefficients: Optional[Tuple[float, ...]] = None
    """Polynomial coefficients, highest degree first (fitted when missing; given as is in legacy mode)."""
    cap_area: Optional[float] = None
    cap_value_area: Optional[float] = None

    def __post_init__(self) -> None:
        if self.method not in METHODS:
            raise ValueError(f"unknown calibration method {self.method!r} (expected {', '.join(METHODS)})")
        edges = np.asarray(self.edges, dtype=float)
        if len(edges) < 2 or np.any(np.diff(edges) <= 0):
            raise ValueError("class limits must increase")
        if len(self.values) != len(edges) - 1:
            raise ValueError(f"{len(edges) - 1} classes but {len(self.values)} values")
        if self.max_area is not None and self.min_area >= self.max_area:
            raise ValueError("min_area must be below max_area")

    # --- points -------------------------------------------------------------------

    @property
    def n_classes(self) -> int:
        return len(self.edges) - 1

    def nodes(self) -> Tuple[np.ndarray, np.ndarray]:
        """(area, inhabitants) of the calibration points."""
        edges = np.asarray(self.edges, dtype=float)
        if self.method == LEGACY:
            x = edges[1:]                                          # upper class bounds, as in Excel (F22)
        elif self.node_areas is not None:
            x = np.asarray(self.node_areas, dtype=float)
        else:
            x = (edges[:-1] + edges[1:]) / 2
        return x, np.asarray(self.values, dtype=float)

    def with_data(self, areas: np.ndarray) -> "Curve":
        """Same curve with its points at the mean roof area of each class (F22)."""
        edges = np.asarray(self.edges, dtype=float)
        index = np.searchsorted(edges, areas, side="right") - 1
        inside = (index >= 0) & (index < self.n_classes)
        sums = np.bincount(index[inside], weights=areas[inside], minlength=self.n_classes)
        counts = np.bincount(index[inside], minlength=self.n_classes)
        middle = (edges[:-1] + edges[1:]) / 2
        means = np.where(counts > 0, sums / np.maximum(counts, 1), middle)
        return _replace(self, node_areas=tuple(float(v) for v in means))

    def fitted(self) -> "Curve":
        """Polynomial coefficients fitted in full precision on the points (F20); other methods unchanged."""
        if self.method != POLYNOMIAL:
            return self
        x, y = self.nodes()
        degree = min(self.degree, len(x) - 1)
        return _replace(self, coefficients=tuple(float(c) for c in np.polyfit(x, y, degree)))

    # --- inhabitants --------------------------------------------------------------

    def population(self, areas) -> np.ndarray:
        """Inhabitants of each roof."""
        s = np.asarray(areas, dtype=float)
        outside = s < self.min_area
        if self.max_area is not None:
            outside |= s > self.max_area
        if self.method == LEGACY:
            coefficients = self.coefficients or np.polyfit(*self.nodes(), 3)
            cap_area = LEGACY_CAP_AREA if self.cap_area is None else self.cap_area
            cap_value = LEGACY_CAP_VALUE_AREA if self.cap_value_area is None else self.cap_value_area
            value = np.where(s >= cap_area, np.polyval(coefficients, cap_value), np.polyval(coefficients, s))
        elif self.method == POLYNOMIAL:
            curve = self if self.coefficients is not None else self.fitted()
            x, _ = curve.nodes()
            cap = x[-1] if self.cap_area is None else self.cap_area
            value = np.maximum(np.polyval(curve.coefficients, np.minimum(s, cap)), 0.0)
        elif self.method == STEPS:
            y = np.maximum.accumulate(np.asarray(self.values, dtype=float))
            index = np.clip(np.searchsorted(np.asarray(self.edges, dtype=float), s, side="right") - 1, 0, len(y) - 1)
            value = y[index]                                       # below the first limit: first class; above: last
        else:
            x, y = self.nodes()
            value = np.interp(s, x, np.maximum.accumulate(y))     # flat before the first and after the last point
        return np.where(outside, 0.0, value)

    def diagnostics(self, areas=None) -> Dict[str, object]:
        """Monotony, negative values and share of roofs at the ceiling (spec §3 ter.2)."""
        grid = np.linspace(self.min_area, min(self._top(), max(self.edges[-1], self.min_area + 1)), 400)
        values = self.population(grid)
        result = {
            "monotone": bool(np.all(np.diff(values) >= -1e-9)),
            "negative": bool(np.any(values < -1e-9)),
            "points_monotone": bool(np.all(np.diff(self.values) >= 0)),
        }
        if areas is not None and len(areas):
            s = np.asarray(areas, dtype=float)
            kept = (s >= self.min_area) & (s <= self._top())
            if self.method == LEGACY:
                ceiling = self.cap_area or LEGACY_CAP_AREA
            elif self.method == STEPS:
                ceiling = self.edges[-1]
            else:
                ceiling = self.nodes()[0][-1]
            result["share_capped"] = float(np.mean(s[kept] >= ceiling)) if kept.any() else 0.0
            result["share_excluded_small"] = float(np.mean(s < self.min_area))
            result["share_excluded_large"] = float(np.mean(s > self._top()))
        return result

    def _top(self) -> float:
        return float("inf") if self.max_area is None else self.max_area

    def samples(self, step: float = 1.0, until: Optional[float] = None) -> Dict[str, List[float]]:
        """The curve sampled every ``step`` m², for plots and reports."""
        top = until or min(self._top(), max(2 * self.edges[-1], self.edges[-1] + 20))
        x = np.arange(0.0, top + step / 2, step)
        return {"area": x.round(6).tolist(), "inhabitants": self.population(x).round(6).tolist()}

    def to_dict(self) -> Dict[str, object]:
        data = {"method": self.method, "edges": list(self.edges), "values": list(self.values),
                "min_area": self.min_area, "max_area": self.max_area}
        for key in ("node_areas", "coefficients", "cap_area", "cap_value_area"):
            if getattr(self, key) is not None:
                data[key] = list(getattr(self, key)) if isinstance(getattr(self, key), tuple) else getattr(self, key)
        if self.method == POLYNOMIAL:
            data["degree"] = self.degree
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Curve":
        keys = set(cls.__dataclass_fields__)
        values = {k: (tuple(v) if isinstance(v, list) else v) for k, v in data.items() if k in keys}
        return cls(**values)


def legacy_curve(stratum: str) -> Curve:
    """The curve of a former workbook (« Rural » or « Urbain »), with its rounded coefficients."""
    return Curve(LEGACY, LEGACY_EDGES, LEGACY_VALUES[stratum], coefficients=LEGACY_COEFFICIENTS[stratum],
                 cap_area=LEGACY_CAP_AREA, cap_value_area=LEGACY_CAP_VALUE_AREA)


def _replace(curve: Curve, **changes) -> Curve:
    data = {k: getattr(curve, k) for k in curve.__dataclass_fields__}
    data.update(changes)
    return Curve(**data)


# --- classes -----------------------------------------------------------------------------

def class_counts(areas: np.ndarray, edges: Sequence[float]) -> np.ndarray:
    """Number of roofs in each class."""
    edges = np.asarray(edges, dtype=float)
    index = np.searchsorted(edges, areas, side="right") - 1
    inside = (index >= 0) & (index < len(edges) - 1)
    return np.bincount(index[inside], minlength=len(edges) - 1)


def hypothesis_values(edges: Sequence[float], area_per_person: float = AREA_PER_PERSON,
                      max_people: int = MAX_PEOPLE) -> Tuple[float, ...]:
    """Inhabitants per class from living-space assumptions (sheet « Classes_detaillees »).

    Mean of the people that fit under the lower and the upper class limit,
    ``floor(area / area_per_person)``, at most ``max_people``.
    """
    edges = np.asarray(edges, dtype=float)
    people = np.minimum(np.floor(edges / area_per_person), max_people)
    return tuple(float(v) for v in (people[:-1] + people[1:]) / 2)


def area_distribution(areas: np.ndarray, step: float = 1.0, until: Optional[float] = None,
                      bandwidth: float = 3.0) -> Dict[str, List[float]]:
    """Histogram of roof areas and a smoothed density, for the class-limit plot (C7)."""
    areas = np.asarray(areas, dtype=float)
    top = until if until else (float(np.percentile(areas, 99.5)) if len(areas) else 100.0)
    edges = np.arange(0.0, top + step, step)
    counts, _ = np.histogram(areas, edges)
    radius = max(1, int(round(3 * bandwidth / step)))
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) * step / bandwidth) ** 2)
    smooth = np.convolve(counts, kernel / kernel.sum(), mode="same")
    total = max(counts.sum(), 1)
    return {"area": ((edges[:-1] + edges[1:]) / 2).round(6).tolist(), "count": counts.tolist(),
            "density": (smooth / total / step).round(8).tolist()}


def natural_breaks(areas: np.ndarray, n_classes: int, lower: float, upper: float, step: float = 1.0) -> Tuple[float, ...]:
    """Class limits from the distribution of roof areas (C3): Fisher-Jenks natural breaks.

    The areas in [lower, upper] are binned every ``step`` m² and the optimal
    breaks are found on the weighted bins, so the cost does not depend on
    the number of roofs (millions are fine). Returns ``n_classes + 1`` limits.
    """
    areas = np.asarray(areas, dtype=float)
    areas = areas[(areas >= lower) & (areas <= upper)]
    edges = np.arange(lower, upper + step, step)
    weights, _ = np.histogram(areas, edges)
    centres = (edges[:-1] + edges[1:]) / 2
    keep = weights > 0
    x, w = centres[keep], weights[keep].astype(float)
    n = len(x)
    if n_classes < 1:
        raise ValueError("at least one class is needed")
    if n <= n_classes:
        inner = [(x[i] + x[i + 1]) / 2 for i in range(n - 1)]
        return tuple([float(lower)] + [float(round(v / step) * step) for v in inner] + [float(upper)])
    cw = np.concatenate([[0.0], np.cumsum(w)])
    cwx = np.concatenate([[0.0], np.cumsum(w * x)])
    cwx2 = np.concatenate([[0.0], np.cumsum(w * x * x)])

    def sse(start, end):  # bins start..end-1 (arrays of starts, one end)
        weight = cw[end] - cw[start]
        return cwx2[end] - cwx2[start] - (cwx[end] - cwx[start]) ** 2 / np.maximum(weight, 1e-12)

    cost = np.full((n_classes + 1, n + 1), np.inf)
    split = np.zeros((n_classes + 1, n + 1), dtype=np.int64)
    cost[0, 0] = 0.0
    for k in range(1, n_classes + 1):
        for end in range(k, n + 1):
            starts = np.arange(k - 1, end)
            total = cost[k - 1, starts] + sse(starts, end)
            best = int(np.argmin(total))
            cost[k, end], split[k, end] = total[best], starts[best]
    limits, end = [], n
    for k in range(n_classes, 0, -1):
        start = split[k, end]
        if k > 1:
            limits.append(float(round(((x[start - 1] + x[start]) / 2) / step) * step))
        end = start
    return tuple([float(lower)] + sorted(limits) + [float(upper)])


# --- fitting on census populations ------------------------------------------------------

@dataclass
class RegressionResult:
    values: Tuple[float, ...]
    fitted: Tuple[float, ...]
    r2: float
    rmse: float
    mape: float
    determined: bool
    """False when there are fewer strata than classes: the values are one solution among many."""


def regress_values(counts: np.ndarray, census: np.ndarray) -> RegressionResult:
    """Inhabitants per class from several strata: census_s ≈ Σ_k counts[s, k] × value_k.

    Values are non-negative and non-decreasing: they are written as sums of
    non-negative steps and solved by non-negative least squares (scipy).
    """
    from scipy.optimize import nnls

    counts = np.asarray(counts, dtype=float)
    census = np.asarray(census, dtype=float)
    k = counts.shape[1]
    steps_to_values = np.tril(np.ones((k, k)))
    steps, _ = nnls(counts @ steps_to_values, census)
    values = steps_to_values @ steps
    fitted = counts @ values
    residual = census - fitted
    total = float(np.sum((census - census.mean()) ** 2))
    r2 = 1.0 - float(np.sum(residual ** 2)) / total if total > 0 else float(np.allclose(residual, 0))
    rmse = float(np.sqrt(np.mean(residual ** 2)))
    mape = float(np.mean(np.abs(residual) / np.maximum(census, 1e-9)))
    return RegressionResult(tuple(values.tolist()), tuple(fitted.tolist()), r2, rmse, mape,
                            determined=counts.shape[0] >= k)


def census_at(census: float, census_year: float, target_year: float, growth_rate_percent: float) -> float:
    """Census population carried to ``target_year`` with a growth rate over the gap (C6)."""
    return float(census) * (1.0 + growth_rate_percent / 100.0) ** (target_year - census_year)


def recalibration_factors(computed: Dict[str, float], targets: Dict[str, float]) -> Dict[str, float]:
    """Factor bringing each stratum exactly to its census (C4); 1 where there is no census."""
    factors = {}
    for key, value in computed.items():
        target = targets.get(key)
        factors[key] = target / value if target is not None and value > 0 else 1.0
    return factors


# --- classes from the data: floor, ceiling and cut (decisions of 29/09/2026) --------------

BREAKS, EQUAL, QUANTILE, MANUAL_CUT = "breaks", "equal", "quantile", "manual"
CUTS = (BREAKS, EQUAL, QUANTILE, MANUAL_CUT)


def resolve_limit(spec, areas: np.ndarray) -> Optional[float]:
    """A floor or ceiling: ``None`` (no limit), a value in m², ``{"value": v}`` or ``{"percentile": p}``."""
    if spec is None or spec == "":
        return None
    if isinstance(spec, (int, float)):
        return float(spec)
    if "value" in spec and spec["value"] is not None:
        return float(spec["value"])
    if "percentile" in spec and spec["percentile"] is not None:
        if not len(areas):
            return None
        return float(np.round(np.percentile(areas, float(spec["percentile"])), 1))
    raise ValueError(f"floor or ceiling: a value, a percentile or nothing is expected, not {spec!r}")


def cut_classes(areas: np.ndarray, n_classes: int, method: str, lower: float, upper: float,
                weights: Optional[np.ndarray] = None) -> Tuple[float, ...]:
    """``n_classes + 1`` class limits from ``lower`` to ``upper``.

    ``breaks``: natural breaks of the distribution (Fisher-Jenks); ``equal``:
    classes of equal width; ``quantile``: classes holding the same number of
    roofs (percentiles). Limits are rounded to the m².
    """
    if method not in (BREAKS, EQUAL, QUANTILE):
        raise ValueError(f"class cut: {BREAKS} | {EQUAL} | {QUANTILE}")
    if upper <= lower:
        raise ValueError("the ceiling must be above the floor")
    areas = np.asarray(areas, dtype=float)
    inside = areas[(areas >= lower) & (areas < upper)]
    if method == BREAKS:
        return natural_breaks(inside, n_classes, lower, upper)
    if method == EQUAL:
        inner = [lower + (upper - lower) * i / n_classes for i in range(1, n_classes)]
    else:
        inner = list(np.percentile(inside, [100.0 * i / n_classes for i in range(1, n_classes)])) if len(inside) else []
    limits = sorted({round(float(v)) for v in inner if lower < round(float(v)) < upper})
    return tuple([float(lower)] + [float(v) for v in limits] + [float(upper)])


def occupants_per_class(means: Sequence[float], area_per_person: float, min_per_roof: int = 1,
                        max_per_roof: int = 15) -> Tuple[int, ...]:
    """Whole inhabitants of each class: mean roof area ÷ roof area per inhabitant, rounded,
    between the minimum and the maximum per roof, never fewer than the class before."""
    values, previous = [], 0
    for mean in means:
        value = int(min(max_per_roof, max(min_per_roof, round(float(mean) / area_per_person))))
        previous = max(previous, value)
        values.append(previous)
    return tuple(values)


def fit_area_per_person(counts: Sequence[float], means: Sequence[float], target: float, min_per_roof: int = 1,
                        max_per_roof: int = 15, low: float = 1.0, high: float = 200.0) -> Tuple[float, float]:
    """Roof area per inhabitant whose whole occupants give ``target`` best: (area, population obtained).

    ``counts`` are the (usage-weighted) roofs counted in each class, the last
    class holding the roofs above the ceiling too. A coarse then a fine scan
    of the area is enough: the population is a step function of it.
    """
    counts = np.asarray(counts, dtype=float)

    def population(area):
        return float(counts @ np.asarray(occupants_per_class(means, area, min_per_roof, max_per_roof), dtype=float))

    best, best_error = low, np.inf
    for area in np.arange(low, high, 0.1):
        error = abs(population(area) - target)
        if error < best_error:
            best, best_error = float(area), error
    for area in np.arange(max(low, best - 0.1), best + 0.1, 0.005):
        error = abs(population(area) - target)
        if error < best_error - 1e-9:
            best, best_error = float(area), error
    best = round(best, 3)
    return best, population(best)


def cumulative_distribution(areas: np.ndarray, per_roof: np.ndarray, step: float = 1.0,
                            until: Optional[float] = None) -> Dict[str, List[float]]:
    """Cumulated share of the roofs and of the population by roof area (the « cumul » view)."""
    areas = np.asarray(areas, dtype=float)
    top = until if until else (float(np.percentile(areas, 99.5)) if len(areas) else 100.0)
    edges = np.arange(0.0, top + step, step)
    roofs, _ = np.histogram(areas, edges)
    people, _ = np.histogram(areas, edges, weights=per_roof)
    n, total = max(len(areas), 1), max(float(np.sum(per_roof)), 1e-12)
    return {"area": edges[1:].round(6).tolist(), "roofs": (np.cumsum(roofs) / n).round(6).tolist(),
            "population": (np.cumsum(people) / total).round(6).tolist()}
