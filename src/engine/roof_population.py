"""Starting population from the roofs (plan of phase 6, step 6.3).

The chain of the former workbooks, inside the tool:

    roofs → usage and confidence → stratum of each roof (centroid, T4)
          → curve of its regression group → inhabitants per roof
          → recalibration on the census of each stratum (C4, C6)
          → population of each calculation unit

Strata come from a polygon layer (one census each); several strata can
share one regression through a group field. Without a strata layer, the
whole study area is one stratum. Every figure is kept for the calibration
report (``calibration.json``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .buildings import assign_to_units, per_unit_totals
from .calibration import (
    BREAKS, CUTS, LEGACY, LEGACY_EDGES, MANUAL_CUT, METHODS, STEPS, Curve, area_distribution, census_at,
    class_counts, cumulative_distribution, cut_classes, fit_area_per_person, hypothesis_values,
    occupants_per_class, recalibration_factors, regress_values, resolve_limit,
)
from .roofs import RoofSet, RoofSource

WHOLE_AREA = "*"
"""Stratum (and group) of the whole study area when there is no strata layer."""
MANUAL, HYPOTHESIS, REGRESSION, AREA_PER_PERSON = "manual", "hypothesis", "regression", "area_per_person"
VALUE_SOURCES = (AREA_PER_PERSON, MANUAL, HYPOTHESIS, REGRESSION)
ALERT_PERCENT = 2.0
"""Gap to the census (without recalibration) above which the report raises an alert (29/09/2026)."""


@dataclass
class StrataSpec:
    source: str
    field: str
    layer: Optional[str] = None
    where: Optional[str] = None
    group_field: Optional[str] = None
    census_field: Optional[str] = None


@dataclass
class GroupSettings:
    """How the inhabitants per roof of one regression group are obtained (decisions of 29/09/2026).

    Classes run from the floor to the ceiling (each: a percentile of the roof
    areas, a value in m², or None for no limit); roofs below the floor hold
    nobody, roofs above the ceiling take the value of the last class, roofs
    above ``exclude_above`` (non-residential) hold nobody. The whole
    inhabitants of each class come from one roof area per inhabitant, fitted
    to the census when it is not given; any class can be overridden by hand.
    """

    method: str = STEPS
    cut: str = BREAKS
    n_classes: int = 8
    edges: Optional[Tuple[float, ...]] = None
    floor: Any = field(default_factory=lambda: {"percentile": 1})
    ceiling: Any = field(default_factory=lambda: {"percentile": 90})
    exclude_above: Optional[float] = 450.0
    values_from: str = AREA_PER_PERSON
    area_per_person: Optional[float] = None
    min_per_roof: int = 1
    max_per_roof: int = 15
    values: Optional[Tuple[float, ...]] = None
    overrides: Dict[int, float] = field(default_factory=dict)
    legacy: Dict[str, Any] = field(default_factory=dict)
    """Fixed curve of the former format (coefficients, cap…), used as is."""

    @classmethod
    def from_dict(cls, name: str, spec: Dict[str, Any]) -> "GroupSettings":
        spec = dict(spec)
        where = f"calibration.groups.{name}"
        if "classes" not in spec and ("edges" in spec or spec.get("method") == LEGACY):
            return cls._former(spec)                       # format of the first version of the phase
        classes = spec.get("classes") or {}
        group = cls(
            method=spec.get("method", STEPS), cut=classes.get("method", BREAKS),
            n_classes=int(classes.get("count", 8)),
            edges=tuple(float(v) for v in classes["edges"]) if classes.get("edges") else None,
            floor=spec.get("floor", {"percentile": 1}), ceiling=spec.get("ceiling", {"percentile": 90}),
            exclude_above=spec.get("exclude_above", 450.0), values_from=spec.get("values_from", AREA_PER_PERSON),
            area_per_person=spec.get("area_per_person"), min_per_roof=int(spec.get("min_per_roof", 1)),
            max_per_roof=int(spec.get("max_per_roof", 15)),
            values=tuple(float(v) for v in spec["values"]) if spec.get("values") else None,
            overrides={int(k): float(v) for k, v in (spec.get("overrides") or {}).items()},
        )
        if group.method not in METHODS:
            raise ValueError(f"{where}.method: {' | '.join(METHODS)}")
        if group.cut not in CUTS:
            raise ValueError(f"{where}.classes.method: {' | '.join(CUTS)}")
        if group.cut == MANUAL_CUT and not group.edges:
            raise ValueError(f"{where}.classes.edges is required for a manual cut")
        if group.values_from not in VALUE_SOURCES:
            raise ValueError(f"{where}.values_from: {' | '.join(VALUE_SOURCES)}")
        if group.values_from == MANUAL and not group.values:
            raise ValueError(f"{where}.values is required when values_from is manual")
        if group.n_classes < 1 or group.min_per_roof > group.max_per_roof:
            raise ValueError(f"{where}: at least one class, and min_per_roof <= max_per_roof")
        return group

    @classmethod
    def _former(cls, spec: Dict[str, Any]) -> "GroupSettings":
        curve = {k: spec[k] for k in ("coefficients", "cap_area", "cap_value_area", "node_areas", "degree") if k in spec}
        edges = tuple(float(v) for v in spec.get("edges", LEGACY_EDGES[2:]))
        values_from = spec.get("values_from", MANUAL if "values" in spec else HYPOTHESIS)
        return cls(method=spec.get("method", "segments"), cut=BREAKS if spec.get("edges_from") == "breaks" else MANUAL_CUT,
                   n_classes=int(spec.get("n_classes", len(edges) - 1)), edges=edges,
                   floor=spec.get("min_area", 10.0), ceiling=None, exclude_above=spec.get("max_area", 450.0),
                   values_from=values_from, values=tuple(spec["values"]) if "values" in spec else None, legacy=curve)

    def to_dict(self) -> Dict[str, Any]:
        classes: Dict[str, Any] = {"method": self.cut, "count": self.n_classes}
        if self.edges:
            classes["edges"] = list(self.edges)
        data = {"method": self.method, "classes": classes, "floor": self.floor, "ceiling": self.ceiling,
                "exclude_above": self.exclude_above, "values_from": self.values_from,
                "min_per_roof": self.min_per_roof, "max_per_roof": self.max_per_roof}
        if self.area_per_person is not None:
            data["area_per_person"] = self.area_per_person
        if self.values:
            data["values"] = list(self.values)
        if self.overrides:
            data["overrides"] = {str(k): v for k, v in self.overrides.items()}
        return data


@dataclass
class CalibrationSettings:
    buildings: RoofSource
    strata: Optional[StrataSpec] = None
    census: Dict[str, float] = field(default_factory=dict)
    census_year: Optional[float] = None
    target_year: Optional[float] = None
    gap_growth_rate: Any = None
    """% per year over the gap between the census year and the target year (number or {stratum: rate}) (C6)."""
    recalibrate: bool = False
    """Apply the recalibration factor (proposed and reported in any case; 1 by default, 29/09/2026)."""
    groups: Dict[str, GroupSettings] = field(default_factory=dict)

    def group(self, name: str) -> GroupSettings:
        return self.groups.get(name) or self.groups.get(WHOLE_AREA) or GroupSettings()


def parse_calibration(data: Dict[str, Any]) -> CalibrationSettings:
    """Settings from the ``calibration`` section of a scenario (raises ValueError with the problem)."""
    if not isinstance(data, dict) or not isinstance(data.get("buildings"), dict) or not data["buildings"].get("source"):
        raise ValueError("calibration.buildings.source is required")
    strata = None
    if data.get("strata"):
        spec = data["strata"]
        if not spec.get("source") or not spec.get("field"):
            raise ValueError("calibration.strata needs a source and a field")
        strata = StrataSpec(spec["source"], spec["field"], spec.get("layer"), spec.get("where"),
                            spec.get("group_field"), spec.get("census_field"))
    groups = {str(name): GroupSettings.from_dict(str(name), spec) for name, spec in (data.get("groups") or {}).items()}
    return CalibrationSettings(
        RoofSource.from_dict(data["buildings"]), strata,
        {str(k): float(v) for k, v in (data.get("census") or {}).items()},
        data.get("census_year"), data.get("target_year"), data.get("gap_growth_rate"),
        bool(data.get("recalibrate", False)), groups,
    )


@dataclass
class GroupData:
    """Roofs of one regression group, kept so that an interface can recompute the curve instantly."""

    areas: np.ndarray
    weights: np.ndarray
    target: Optional[float]
    strata: List[str]
    stratum_of_roof: Optional[np.ndarray] = None
    targets: Dict[str, float] = field(default_factory=dict)

    def curve(self, group: "GroupSettings"):
        """(curve, report) of the group with other settings: what an interface shows while it is edited."""
        strata_roofs = {}
        if self.stratum_of_roof is not None:
            strata_roofs = {s: (self.areas[self.stratum_of_roof == s], self.weights[self.stratum_of_roof == s])
                            for s in self.strata}
        curve, report = group_curve(group, self.areas, self.weights, self.target, strata_roofs, self.targets)
        population = float((curve.population(self.areas) * self.weights).sum())
        report["population_before_recalibration"] = population
        if self.target:
            report["gap_percent"] = 100.0 * (population / self.target - 1.0)
            report["alert"] = abs(report["gap_percent"]) > ALERT_PERCENT
        return curve, report


@dataclass
class RoofPopulation:
    per_unit: np.ndarray
    per_roof: np.ndarray
    report: Dict[str, Any]
    groups: Dict[str, GroupData] = field(default_factory=dict)


def growth_over_gap(settings: CalibrationSettings, stratum: str, default_rate: Optional[float]) -> float:
    rate = settings.gap_growth_rate
    if isinstance(rate, dict):
        rate = rate.get(stratum, rate.get(WHOLE_AREA))
    if rate is None:
        rate = default_rate
    return float(rate or 0.0)


def population_from_roofs(settings: CalibrationSettings, roofs: RoofSet, units,
                          stratum_of_unit: Optional[List[Optional[str]]], group_of_stratum: Dict[str, str],
                          target_year: float, default_growth: Optional[float] = None) -> RoofPopulation:
    """Inhabitants of each roof and of each unit, with the calibration report.

    ``stratum_of_unit`` is None without a strata layer: the whole study area
    is then a single stratum (``*``).
    """
    buildings = roofs.buildings
    unit_index = assign_to_units(buildings, units)
    inside = unit_index >= 0
    if stratum_of_unit is None:
        strata = np.where(inside, WHOLE_AREA, None).astype(object)
    else:
        labels = np.array(list(stratum_of_unit) + [None], dtype=object)
        strata = labels[np.where(inside, unit_index, -1)]
    report: Dict[str, Any] = {"roofs": dict(roofs.report, outside_study_area=int((~inside).sum()),
                                            without_stratum=int((inside & (strata == None)).sum())),  # noqa: E711
                              "target_year": target_year, "census_year": settings.census_year,
                              "buildings_year": settings.buildings.year, "groups": {}, "strata": {}}

    # Census of each stratum, carried to the target year (C6)
    known = sorted({s for s in strata if s is not None} | set(settings.census))
    targets, rates = {}, {}
    for stratum in known:
        if stratum in settings.census:
            rates[stratum] = growth_over_gap(settings, stratum, default_growth)
            year = settings.census_year if settings.census_year is not None else target_year
            targets[stratum] = census_at(settings.census[stratum], year, target_year, rates[stratum])

    per_roof = np.zeros(len(buildings))
    group_data: Dict[str, GroupData] = {}
    groups: Dict[str, List[str]] = {}
    for stratum in known:
        groups.setdefault(group_of_stratum.get(stratum, stratum), []).append(stratum)
    for group_name, members in sorted(groups.items()):
        in_group = np.isin(strata, members)
        target = sum(targets[s] for s in members if s in targets) if any(s in targets for s in members) else None
        curve, group_report = group_curve(settings.group(group_name), buildings.area_m2[in_group],
                                          roofs.weight[in_group], target,
                                          {s: (buildings.area_m2[strata == s], roofs.weight[strata == s])
                                           for s in members}, targets)
        per_roof[in_group] = curve.population(buildings.area_m2[in_group]) * roofs.weight[in_group]
        areas = buildings.area_m2[in_group]
        group_data[group_name] = GroupData(areas, roofs.weight[in_group], target, members, strata[in_group],
                                           {m: targets[m] for m in members if m in targets})
        group_report.update({
            "strata": members, "roofs": int(in_group.sum()),
            "population_before_recalibration": float(per_roof[in_group].sum()),
            "census_at_target": target,
            "cumulative": cumulative_distribution(areas, per_roof[in_group], until=curve.edges[-1] * 1.5)
            if len(areas) else {},
        })
        if target:
            gap = 100.0 * (group_report["population_before_recalibration"] / target - 1.0)
            group_report["gap_percent"] = gap
            group_report["alert"] = abs(gap) > ALERT_PERCENT
        report["groups"][group_name] = group_report

    computed = {s: float(per_roof[strata == s].sum()) for s in known}
    proposed = recalibration_factors(computed, targets)
    factors = proposed if settings.recalibrate else {s: 1.0 for s in known}
    for stratum in known:
        members = strata == stratum
        per_roof[members] *= factors[stratum]
        entry = {"group": group_of_stratum.get(stratum, stratum), "roofs": int(members.sum()),
                 "computed": computed[stratum], "factor": factors[stratum], "proposed_factor": proposed[stratum],
                 "population": float(per_roof[members].sum())}
        if stratum in settings.census:
            entry.update({"census": settings.census[stratum], "census_at_target": targets[stratum],
                          "gap_growth_rate": rates[stratum],
                          "gap_percent": 100.0 * (computed[stratum] / targets[stratum] - 1.0) if targets[stratum] else None})
            entry["alert"] = entry["gap_percent"] is not None and abs(entry["gap_percent"]) > ALERT_PERCENT
        report["strata"][stratum] = entry
    report["total_before_recalibration"] = float(sum(computed.values()))
    report["total"] = float(per_roof.sum())
    report["recalibrated"] = settings.recalibrate
    report["alert_percent"] = ALERT_PERCENT
    per_unit = per_unit_totals(unit_index, per_roof, len(units))
    return RoofPopulation(per_unit, per_roof, report, group_data)


def group_curve(group: GroupSettings, areas: np.ndarray, weights: np.ndarray, target: Optional[float],
                strata_roofs: Dict[str, Tuple[np.ndarray, np.ndarray]], targets: Dict[str, float]):
    """Curve of one regression group, and its part of the calibration report."""
    report: Dict[str, Any] = {"settings": group.to_dict()}
    if group.method == LEGACY or group.legacy:
        curve = Curve.from_dict(dict(group.legacy, method=group.method, edges=list(group.edges),
                                     values=list(group.values or hypothesis_values(group.edges)),
                                     min_area=float(group.floor), max_area=group.exclude_above))
        if group.values_from == HYPOTHESIS:
            curve = Curve.from_dict(dict(curve.to_dict(), values=list(hypothesis_values(curve.edges))))
        if curve.method != LEGACY:
            kept = areas[(areas >= curve.min_area) & (areas <= curve._top())]
            curve = curve.with_data(kept) if len(kept) else curve
        curve = curve.fitted()
        report.update(_curve_report(curve, areas))
        return curve, report

    # Floor, exclusion and ceiling, from the roofs of the group
    exclude = group.exclude_above
    usable = areas if exclude is None else areas[areas <= exclude]
    floor = resolve_limit(group.floor, usable)
    above_floor = usable if floor is None else usable[usable >= floor]
    ceiling = resolve_limit(group.ceiling, above_floor)
    lower = 0.0 if floor is None else floor
    upper = ceiling if ceiling is not None else (float(np.ceil(above_floor.max())) + 1.0 if len(above_floor) else lower + 1)
    report["limits"] = {"floor": floor, "ceiling": ceiling, "exclude_above": exclude}
    if group.cut == MANUAL_CUT and group.edges:
        edges = tuple(group.edges)
    else:
        cut = group.cut if group.cut != MANUAL_CUT else BREAKS    # manual without limits yet: natural breaks
        edges = cut_classes(above_floor, group.n_classes, cut, lower, upper) if len(above_floor) else \
            tuple(np.linspace(lower, upper, group.n_classes + 1))
    edges_array = np.asarray(edges, dtype=float)

    # Roofs of each class (the last class also holds the roofs above the ceiling) and mean area inside the class
    kept = (areas >= edges_array[0]) if floor is not None else np.ones(len(areas), dtype=bool)
    if exclude is not None:
        kept &= areas <= exclude
    index = np.clip(np.searchsorted(edges_array, areas, side="right") - 1, 0, len(edges) - 2)
    counts = np.bincount(index[kept], weights=weights[kept], minlength=len(edges) - 1)
    inside = kept & (areas < edges_array[-1])
    sums = np.bincount(index[inside], weights=areas[inside], minlength=len(edges) - 1)
    numbers = np.bincount(index[inside], minlength=len(edges) - 1)
    means = np.where(numbers > 0, sums / np.maximum(numbers, 1), (edges_array[:-1] + edges_array[1:]) / 2)

    area_per_person = group.area_per_person
    if group.values_from == AREA_PER_PERSON:
        if area_per_person is None:
            if target:
                area_per_person, _ = fit_area_per_person(counts, means, target, group.min_per_roof, group.max_per_roof)
                report["area_per_person_fitted"] = True
            else:
                area_per_person = 10.0
                report["area_per_person_default"] = True        # no census to fit it on
        values = occupants_per_class(means, area_per_person, group.min_per_roof, group.max_per_roof)
        report["area_per_person"] = area_per_person
    elif group.values_from == HYPOTHESIS:
        values = hypothesis_values(edges)
    elif group.values_from == REGRESSION:
        with_census = [s for s in strata_roofs if s in targets]
        matrix = np.array([np.bincount(np.clip(np.searchsorted(edges_array, a, side="right") - 1, 0, len(edges) - 2)[
            (a >= edges_array[0]) & (a <= (exclude or np.inf))], weights=w[(a >= edges_array[0]) & (a <= (exclude or np.inf))],
            minlength=len(edges) - 1) for a, w in (strata_roofs[s] for s in with_census)])
        if not with_census:
            raise ValueError("a regression needs the census of the strata of the group")
        regression = regress_values(matrix, np.array([targets[s] for s in with_census]))
        values = regression.values
        report["regression"] = {"r2": regression.r2, "rmse": regression.rmse, "mape": regression.mape,
                                "determined": regression.determined, "strata": with_census,
                                "fitted": dict(zip(with_census, regression.fitted))}
    else:
        values = group.values
    if len(values) != len(edges) - 1:
        raise ValueError(f"{len(edges) - 1} classes but {len(values)} values")
    proposed = tuple(float(v) for v in values)
    retained = list(proposed)
    for k, value in group.overrides.items():
        if 0 <= k < len(retained):
            retained[k] = float(value)
    curve = Curve(group.method, tuple(float(v) for v in edges), tuple(retained), min_area=lower if floor is not None else 0.0,
                  max_area=exclude, node_areas=tuple(float(m) for m in means))
    curve = curve.fitted()
    report.update(_curve_report(curve, areas))
    report.update({"proposed_values": list(proposed), "retained_values": retained,
                   "overridden": sorted(group.overrides), "class_counts": counts.round(6).tolist(),
                   "class_means": means.round(3).tolist()})
    return curve, report


def _curve_report(curve: Curve, areas: np.ndarray) -> Dict[str, Any]:
    return {
        "curve": curve.to_dict(),
        "class_counts": class_counts(areas, curve.edges).tolist(),
        "excluded_small": int((areas < curve.min_area).sum()),
        "excluded_large": int((areas > curve._top()).sum()),
        "diagnostics": curve.diagnostics(areas),
        "samples": curve.samples(),
        "distribution": area_distribution(areas, until=min(curve._top(), curve.edges[-1] * 1.5)) if len(areas) else {},
    }


def strata_from_features(features, spec: StrataSpec) -> Tuple[List[Any], List[str], Dict[str, str], Dict[str, float]]:
    """(geometries, stratum ids, group of each stratum, census from the layer) from the strata features."""
    geometries, ids, groups, census = [], [], {}, {}
    for feature in features:
        stratum = str(feature.attributes[spec.field])
        geometries.append(feature.geometry)
        ids.append(stratum)
        if spec.group_field:
            groups[stratum] = str(feature.attributes[spec.group_field])
        if spec.census_field and feature.attributes.get(spec.census_field) not in (None, ""):
            census[stratum] = census.get(stratum, 0.0) + float(feature.attributes[spec.census_field])
    return geometries, ids, groups, census
