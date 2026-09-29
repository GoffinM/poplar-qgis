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
    LEGACY_EDGES, SEGMENTS, Curve, area_distribution, census_at, class_counts, hypothesis_values,
    natural_breaks, recalibration_factors, regress_values,
)
from .roofs import RoofSet, RoofSource

WHOLE_AREA = "*"
"""Stratum (and group) of the whole study area when there is no strata layer."""
MANUAL, HYPOTHESIS, REGRESSION = "manual", "hypothesis", "regression"
BREAKS = "breaks"


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
    curve: Curve
    values_from: str = MANUAL
    """``manual`` (values as given), ``hypothesis`` (living space) or ``regression`` (several strata)."""
    edges_from: str = MANUAL
    """``manual`` or ``breaks`` (natural breaks of the roof areas, C3)."""
    n_classes: int = 10


@dataclass
class CalibrationSettings:
    buildings: RoofSource
    strata: Optional[StrataSpec] = None
    census: Dict[str, float] = field(default_factory=dict)
    census_year: Optional[float] = None
    target_year: Optional[float] = None
    gap_growth_rate: Any = None
    """% per year over the gap between the census year and the target year (number or {stratum: rate}) (C6)."""
    recalibrate: bool = True
    groups: Dict[str, GroupSettings] = field(default_factory=dict)

    def group(self, name: str) -> GroupSettings:
        return self.groups.get(name) or self.groups.get(WHOLE_AREA) or GroupSettings(
            Curve(SEGMENTS, LEGACY_EDGES[2:], hypothesis_values(LEGACY_EDGES[2:])), values_from=HYPOTHESIS)


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
    groups = {}
    for name, spec in (data.get("groups") or {}).items():
        spec = dict(spec)
        extra = {key: spec.pop(key) for key in ("values_from", "edges_from", "n_classes") if key in spec}
        spec.setdefault("method", SEGMENTS)
        spec.setdefault("edges", list(LEGACY_EDGES[2:]))       # 10 to 80 m² by default: roofs below 10 m² count 0
        if "values" not in spec:
            spec["values"] = hypothesis_values(spec["edges"])
            extra.setdefault("values_from", HYPOTHESIS)
        groups[str(name)] = GroupSettings(Curve.from_dict(spec), **extra)
    for name, group in groups.items():
        if group.values_from not in (MANUAL, HYPOTHESIS, REGRESSION):
            raise ValueError(f"calibration.groups.{name}.values_from: manual | hypothesis | regression")
        if group.edges_from not in (MANUAL, BREAKS):
            raise ValueError(f"calibration.groups.{name}.edges_from: manual | breaks")
    return CalibrationSettings(
        RoofSource.from_dict(data["buildings"]), strata,
        {str(k): float(v) for k, v in (data.get("census") or {}).items()},
        data.get("census_year"), data.get("target_year"), data.get("gap_growth_rate"),
        bool(data.get("recalibrate", True)), groups,
    )


@dataclass
class RoofPopulation:
    per_unit: np.ndarray
    per_roof: np.ndarray
    report: Dict[str, Any]


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
    groups: Dict[str, List[str]] = {}
    for stratum in known:
        groups.setdefault(group_of_stratum.get(stratum, stratum), []).append(stratum)
    for group_name, members in sorted(groups.items()):
        settings_group = settings.group(group_name)
        in_group = np.isin(strata, members)
        areas = buildings.area_m2[in_group]
        curve = settings_group.curve
        group_report: Dict[str, Any] = {"strata": members, "roofs": int(in_group.sum()),
                                        "values_from": settings_group.values_from,
                                        "edges_from": settings_group.edges_from}
        if settings_group.edges_from == BREAKS and len(areas):
            edges = natural_breaks(areas, settings_group.n_classes, curve.min_area, curve.max_area)
            curve = Curve.from_dict(dict(curve.to_dict(), edges=list(edges), values=list(hypothesis_values(edges)),
                                         node_areas=None))
            group_report["breaks"] = list(edges)
        if settings_group.values_from == HYPOTHESIS:
            curve = Curve.from_dict(dict(curve.to_dict(), values=list(hypothesis_values(curve.edges))))
        elif settings_group.values_from == REGRESSION:
            with_census = [s for s in members if s in targets]
            counts = np.array([class_counts(buildings.area_m2[strata == s] * 1.0, curve.edges) for s in with_census])
            weights = np.array([targets[s] for s in with_census])
            if len(with_census):
                regression = regress_values(counts, weights)
                curve = Curve.from_dict(dict(curve.to_dict(), values=list(regression.values)))
                group_report["regression"] = {"r2": regression.r2, "rmse": regression.rmse, "mape": regression.mape,
                                              "determined": regression.determined, "strata": with_census,
                                              "fitted": dict(zip(with_census, regression.fitted))}
        if curve.method != "legacy":
            curve = curve.with_data(areas[(areas >= curve.min_area) & (areas <= curve.max_area)]) \
                if len(areas) else curve
        curve = curve.fitted()
        per_roof[in_group] = curve.population(areas) * roofs.weight[in_group]
        excluded = (areas < curve.min_area) | (areas > curve.max_area)
        group_report.update({
            "curve": curve.to_dict(),
            "class_counts": class_counts(areas, curve.edges).tolist(),
            "excluded_small": int((areas < curve.min_area).sum()),
            "excluded_large": int((areas > curve.max_area).sum()),
            "diagnostics": curve.diagnostics(areas),
            "samples": curve.samples(),
            "distribution": area_distribution(areas, until=curve.max_area) if len(areas) else {},
            "population_before_recalibration": float(per_roof[in_group].sum()),
            "roofs_counted": int((~excluded).sum()),
        })
        report["groups"][group_name] = group_report

    computed = {s: float(per_roof[strata == s].sum()) for s in known}
    factors = recalibration_factors(computed, targets) if settings.recalibrate else {s: 1.0 for s in known}
    for stratum in known:
        members = strata == stratum
        per_roof[members] *= factors[stratum]
        entry = {"group": group_of_stratum.get(stratum, stratum), "roofs": int(members.sum()),
                 "computed": computed[stratum], "factor": factors[stratum], "population": float(per_roof[members].sum())}
        if stratum in settings.census:
            entry.update({"census": settings.census[stratum], "census_at_target": targets[stratum],
                          "gap_growth_rate": rates[stratum],
                          "gap_percent": 100.0 * (computed[stratum] / targets[stratum] - 1.0) if targets[stratum] else None})
        report["strata"][stratum] = entry
    report["total_before_recalibration"] = float(sum(computed.values()))
    report["total"] = float(per_roof.sum())
    report["recalibrated"] = settings.recalibrate
    per_unit = per_unit_totals(unit_index, per_roof, len(units))
    return RoofPopulation(per_unit, per_roof, report)


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
