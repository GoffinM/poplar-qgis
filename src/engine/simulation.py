"""Full simulation, from the start year to the end year (spec §5).

Everything comes from a :class:`~engine.scenario.Scenario`: no manual step.
Each sub-step applies, in order: dated exclusions that start, growth,
optional recalibration on projections, and migration with the chosen
non-convergence policy. Results are written for every output year.
"""

from __future__ import annotations

import json
import os
import time as clock
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
from osgeo import gdal

from . import __version__
from .base_population import base_population_from_density
from .grid import Grid
from .growth import grow
from .i18n import Message, message
from .indicators import Indicator, create_indicator
from .nonconvergence import (
    FAILED, SINK, SUCCESS, DmaxProposal, MigrationSettings, NonConvergenceError, Sink, migrate_with_policy,
)
from .html_report import write_html_report
from .outputs import summary_rows, write_summary, write_year_rasters
from .runs import finish_run, new_run_directory
from .parameters import DEFAULT_KEY, KEY_SEPARATOR, TimeSeries, to_hab_per_km2, unit_means, unit_values
from ._gdal import srs_from_epsg, srs_from_wkt
from .crs import choose_crs, native_pixel_m, population_to_density, reproject_density
from .raster_io import read_raster
from .report import StepReport
from .scenario import NO_INFLOW, OUTSIDE, PROJECTION, RELOCATE, Scenario, ScenarioError, VectorInput
from .timeline import PER_STEP, build_timeline
from .units import NO_VALUE, Layer, Zone, build_sink_units, build_units
from .roof_population import parse_calibration, population_from_roofs, strata_from_features
from .roofs import read_roofs
from .tables import TableError, read_projections
from .vector_io import BufferRequired, read_features, union_all

STATUS_ORDER = ["success", "success_with_adjustments", "partial", "failed"]
WGS84_WKT = srs_from_epsg(4326).ExportToWkt()


def _crs_name(wkt: str) -> str:
    srs = srs_from_wkt(wkt)
    code = srs.GetAuthorityCode(None)
    name = srs.GetName() or "?"
    return f"EPSG:{code} ({name})" if code else name


@dataclass
class RunResult:
    status: str
    steps: List[StepReport]
    warnings: List[Message]
    outputs: List[str]
    directory: str
    final_population: float
    initial_population: float = 0.0
    events: List[Message] = field(default_factory=list)
    failure: Optional[NonConvergenceError] = None
    """Set when the run stopped for lack of room: deficit and proposed ``dmax`` increase."""
    failure_year: Optional[float] = None


def calibrate(scenario: Scenario):
    """Calibration alone, for the Calibration tab: (report, roofs of each group).

    The starting population is computed from the roofs whatever the choice
    of the scenario, so the calibration can be prepared before it is used.
    """
    model = _Model.load(replace(scenario, population_source="buildings"))
    return model.calibration_report, model.calibration_groups


def run(
    scenario: Scenario,
    approve: Optional[Callable[[DmaxProposal], bool]] = None,
    progress: Optional[Callable[[float], None]] = None,
    is_canceled: Optional[Callable[[], bool]] = None,
) -> RunResult:
    """Run the scenario and write every output in its output directory."""
    started = clock.time()
    language = scenario.language
    out_dir = scenario.path(scenario.output_directory)
    os.makedirs(out_dir, exist_ok=True)
    model = _Model.load(scenario)
    if scenario.output_per_run:  # after loading: invalid data leaves no empty run folder
        out_dir = new_run_directory(out_dir)
    warnings = list(model.warnings)

    # Starting point: census, or a projection year (spec §5.3).
    population = model.p0.copy()
    t0 = scenario.time.base_year
    if scenario.time.start_mode == PROJECTION:
        t0 = float(scenario.time.start_year)
        population = model.recalibrate(population, t0)
        warnings.append(message("start_from_projection", year=f"{t0:g}"))
    base = population.copy()  # ceiling of overloaded units (A4) and of no-inflow units (A7-bis c1)
    base_start = population.sum()

    timeline = build_timeline(
        t0, scenario.time.end_year, scenario.time.time_step, scenario.time.output_years,
        scenario.time.migration_frequency, scenario.time.first_migration_year,
        event_years=[e.year for e in scenario.exclusions if e.year is not None],
    )
    warnings.extend(model.resolution_warnings(scenario))

    settings = MigrationSettings(
        k=scenario.migration.k, tolerance=scenario.migration.tolerance,
        max_iterations=scenario.migration.max_iterations, policy=scenario.migration.policy,
        max_auto_increase=scenario.migration.max_auto_increase, approve=approve,
    )
    units = model.units
    n = len(units)
    dated_no_inflow = np.zeros(n, dtype=bool)
    evacuated = np.zeros(n, dtype=bool)
    active_events = set()
    multiplier = np.ones(n)
    unallocated = np.zeros(n)
    capacity_now = np.zeros(n)
    steps: List[StepReport] = []
    events: List[Message] = []
    outputs: List[str] = []
    rows: List[Dict[str, object]] = []
    status = SUCCESS
    failure, failure_year = None, None

    def write(year: float) -> None:
        indicator_values = model.indicator_values(population, year)
        outputs.extend(write_year_rasters(out_dir, year, units, population, unallocated, capacity_now,
                                          scenario.density_unit, indicator_values))
        rows.extend(summary_rows(year, units, population, unallocated, scenario.density_unit, indicator_values))

    capacity_now = model.capacity(base, t0, multiplier, dated_no_inflow, evacuated)
    write(t0)
    for index, step in enumerate(timeline):
        if is_canceled is not None and is_canceled():
            events.append(message("run_canceled", year=f"{step.start:g}"))
            status = FAILED
            break
        # Exclusions dated Y apply to the step that ends on Y: the results of year Y
        # already show them (spec §2.4, X1).
        for i, exclusion in enumerate(scenario.exclusions):
            if exclusion.year is None or i in active_events or exclusion.year > step.end + 1e-9:
                continue
            active_events.add(i)
            members = model.event_units(i)
            if exclusion.behaviour == RELOCATE:
                evacuated |= members
                events.append(message("exclusion_relocated", name=exclusion.name, year=f"{exclusion.year:g}",
                                      population=round(float(population[members].sum()))))
            else:
                dated_no_inflow |= members
                base = np.where(members, population, base)
                events.append(message("exclusion_frozen", name=exclusion.name, year=f"{exclusion.year:g}"))

        before = float(population.sum())
        rates = unit_means(model.tables["growth_rate"], units, step.start, step.end)
        population = grow(population, rates, step.duration)
        if model.sink is not None:
            mean_rate = float(np.average(rates, weights=np.maximum(population, 1e-12)))
            model.sink.population = grow(model.sink.population, mean_rate, step.duration)
        if model.projections and scenario.projections.recalibrate:
            population = model.recalibrate(population, step.end)
        after_growth = float(population.sum())

        must_migrate = step.migrate or bool((evacuated & (population > 0)).any())
        capacity_now = model.capacity(base, step.end, multiplier, dated_no_inflow, evacuated)
        if must_migrate:
            sink_before = float(model.sink.population.sum()) if model.sink is not None else 0.0
            try:
                outcome = migrate_with_policy(
                    population, units.area_km2, base, model.dmax(step.end) * multiplier,
                    units.no_inflow | dated_no_inflow, units.cx, units.cy, settings,
                    evacuated=evacuated, sink=model.sink,
                )
            except NonConvergenceError as error:
                steps.append(StepReport(step.start, step.end, before, after_growth, after_growth, 0.0, 0.0, 0.0, 0,
                                        False, 1.0, FAILED, list(error.messages)))
                status = FAILED
                failure, failure_year = error, step.end
                break
            if outcome.dmax_factor != 1.0:
                multiplier = np.where(~(units.no_inflow | dated_no_inflow | evacuated),
                                      multiplier * outcome.dmax_factor, multiplier)
            if outcome.sink_population is not None:
                model.sink.population = outcome.sink_population
            population = outcome.population
            unallocated = unallocated + outcome.unallocated
            capacity_now = outcome.capacity
            report = StepReport.from_outcome(step.start, step.end, before, after_growth, outcome, sink_before)
        else:
            report = StepReport(step.start, step.end, before, after_growth, after_growth, 0.0, 0.0, 0.0, 0,
                                True, 1.0, SUCCESS, [])
        steps.append(report)
        status = max(status, report.status, key=STATUS_ORDER.index)
        if step.output:
            write(step.end)
        if progress is not None:
            progress((index + 1) / len(timeline))

    summary_path = os.path.join(out_dir, "summary.csv")
    write_summary(summary_path, rows, language, model.column_units(scenario))
    outputs.append(summary_path)
    result = RunResult(status, steps, warnings, outputs, out_dir, float(population.sum()), float(base_start), events,
                       failure, failure_year)
    _write_run_report(scenario, result, model, clock.time() - started)
    scenario.save(os.path.join(out_dir, "scenario_used.json"))
    if model.calibration_report is not None:
        with open(os.path.join(out_dir, "calibration.json"), "w", encoding="utf-8") as handle:
            json.dump(model.calibration_report, handle, ensure_ascii=False, indent=1)
        outputs.append(os.path.join(out_dir, "calibration.json"))
    try:  # the HTML report is a convenience: it never makes a run fail
        outputs.append(write_html_report(out_dir, language))
    except Exception:  # pragma: no cover
        pass
    if scenario.output_per_run:
        finish_run(out_dir, scenario.name, result.status, _output_years(result.outputs))
    return result


class _Model:
    """Data prepared once for a run: units, base population, parameters, indicators."""

    @classmethod
    def load(cls, scenario: Scenario) -> "_Model":
        self = cls()
        self.warnings: List[Message] = []
        from_roofs = scenario.population_source == "buildings"
        source_raster = None
        if scenario.base_population_raster:  # optional with roofs: it then only aligns the grid
            raster_path = scenario.path(scenario.base_population_raster)
            _check_file(raster_path)
            source_raster = read_raster(raster_path)

        # Calculation CRS: projected, in metres (spec §3). Input layers are reprojected to it.
        study_lonlat = union_all(f.geometry for f in _read(scenario, scenario.study_area, WGS84_WKT))
        xmin_d, xmax_d, ymin_d, ymax_d = study_lonlat.GetEnvelope()
        try:
            choice = choose_crs(scenario.crs, source_raster.crs_wkt if source_raster else "",
                                (xmin_d, ymin_d, xmax_d, ymax_d))
        except ValueError:
            raise ScenarioError([message("crs_not_metric", crs=str(scenario.crs))]) from None
        crs = choice.wkt
        self.crs_choice = choice
        self.warnings.append(message("crs_used", name=_crs_name(crs), source=choice.source))
        if choice.suggestion is not None:
            self.warnings.append(message("crs_area_distortion", distortion=round(choice.max_area_distortion * 100, 2)))

        # Population raster as a density in hab/km2, in the calculation CRS.
        self.raster = None
        if source_raster is not None:
            density = population_to_density(source_raster, scenario.population_value_type,
                                            float(to_hab_per_km2(1.0, scenario.density_unit)))
            if not srs_from_wkt(source_raster.crs_wkt).IsSame(srs_from_wkt(crs)):
                pixel = min(native_pixel_m(source_raster), scenario.cell_size)
                density, ratio = reproject_density(density, crs, pixel)
                self.warnings.append(message("raster_reprojected", name=_crs_name(crs), pixel=round(pixel, 1),
                                             correction=round((ratio - 1) * 100, 3)))
            self.raster = density

        study = union_all(f.geometry for f in _read(scenario, scenario.study_area, crs))
        outside = [g for e in scenario.exclusions if e.behaviour == OUTSIDE for g in _read_exclusion(scenario, e, crs)]
        if outside:
            study = study.Difference(union_all(outside))
        typology = scenario.typology
        zones = [Zone(f.geometry, str(f.attributes[typology.field])) for f in _read(scenario, typology, crs)]
        no_inflow = [g for e in scenario.exclusions if e.behaviour == NO_INFLOW and e.year is None
                     for g in _read_exclusion(scenario, e, crs)]

        layers = []
        dated_geoms, dated_values = [], []
        for i, e in enumerate(scenario.exclusions):
            if e.behaviour == RELOCATE and e.year is None:
                e.year = scenario.time.start_year if scenario.time.start_mode == PROJECTION else scenario.time.base_year
            if e.year is not None:
                for g in _read_exclusion(scenario, e, crs):
                    dated_geoms.append(g)
                    dated_values.append(i)
        if dated_geoms:
            layers.append(Layer("event", dated_geoms, dated_values))
        # Attribute layers (parameter zones, strata, administrative units): a file used by several
        # of them is cut with the cells once, and each attribute is derived from that single cut.
        shared = _SharedLayers(scenario, crs)
        if scenario.parameter_zones is not None:
            shared.add("param_zone", scenario.parameter_zones, scenario.parameter_zones.field)
        parameter_layers: Dict[str, Tuple[str, ...]] = {}  # parameters linked to their own zones (spec §2.3 bis)
        zone_names: Dict[Tuple, str] = {}
        for name in scenario.parameters:
            names = []
            for spec in scenario.parameter_zones_of(name):
                key = (scenario.path(spec.source), spec.layer, spec.where, spec.field)
                if key not in zone_names:
                    zone_names[key] = f"zones_{len(zone_names)}"
                    shared.add(zone_names[key], spec, spec.field)
                names.append(zone_names[key])
            if names:
                parameter_layers[name] = tuple(names)
        calibration, strata_groups, strata_census = None, {}, {}
        if from_roofs:
            calibration = parse_calibration(scenario.calibration or {})
            if calibration.strata is not None:
                spec = calibration.strata
                vector = VectorInput(spec.source, spec.layer, spec.where, spec.field)
                shared.add("stratum", vector, spec.field)
                _, _, strata_groups, strata_census = strata_from_features(shared.features(vector), spec)
        if scenario.admin_units is not None:
            shared.add("admin", scenario.admin_units, scenario.admin_units.field)
        layers.extend(shared.layers())

        xmin, xmax, ymin, ymax = study.GetEnvelope()
        margin = 0.0
        if scenario.migration.policy == SINK:
            margin = (scenario.migration.sink_width_cells + 1) * scenario.cell_size
        origin = (self.raster.geotransform[0], self.raster.geotransform[3]) if self.raster else (0.0, 0.0)
        self.grid = Grid.covering((xmin - margin, ymin - margin, xmax + margin, ymax + margin),
                                  scenario.cell_size, crs, origin=origin)
        self.units = build_units(self.grid, study, zones, union_all(no_inflow) if no_inflow else None, layers)
        shared.derive(self.units)
        if self.units.report.unclassified_area_km2 > 0.01:
            self.warnings.append(message("typology_gaps", area=round(self.units.report.unclassified_area_km2, 2)))
        self.calibration_report = None
        self.calibration_groups = {}
        if not from_roofs:
            self.p0, _ = base_population_from_density(self.units, self.raster, "hab/km2", scenario.boundary_mode)

        self.tables = scenario.parameter_tables()
        for name, names in parameter_layers.items():
            self.tables[name].layers = names
            self.warnings.extend(_unused_keys(self.tables[name], self.units))
        self.density_unit = scenario.density_unit
        if from_roofs:
            self.p0 = self._population_from_roofs(scenario, calibration, crs, study, strata_groups, strata_census)
        for name in ("growth_rate", "dmax"):
            try:
                unit_values(self.tables[name], self.units, scenario.time.base_year)
            except KeyError as error:
                raise ScenarioError([message("scenario_parameter_missing", parameter=name, detail=str(error))]) from None

        self.indicators: List[Indicator] = [
            create_indicator(spec.type, scenario.indicator_tables(spec)) for spec in scenario.indicators
        ]
        self.projections = _load_projections(scenario) if scenario.projections else None

        self.sink = None
        if scenario.migration.policy == SINK:
            sink_units = build_sink_units(self.grid, study, scenario.migration.sink_width_cells)
            sink_dmax = scenario.migration.sink_dmax
            if sink_dmax is None:
                sink_dmax = float(np.min(unit_values(self.tables["dmax"], self.units, scenario.time.base_year)))
            capacity = sink_units.area_km2 * float(to_hab_per_km2(sink_dmax, scenario.density_unit))
            self.sink = Sink(sink_units.cx, sink_units.cy, capacity, np.zeros(len(sink_units)))
        return self

    def _population_from_roofs(self, scenario, calibration, crs, study, strata_groups, strata_census) -> np.ndarray:
        """Starting population from the roofs calibrated on the census (plan of phase 6, step 6.3)."""
        roof_source = calibration.buildings
        roof_source.source = scenario.path(roof_source.source)
        _check_file(roof_source.source)
        xmin, xmax, ymin, ymax = study.GetEnvelope()
        try:
            roofs = read_roofs(roof_source, crs, extent=(xmin, ymin, xmax, ymax))
        except (ValueError, RuntimeError) as error:
            raise ScenarioError([message("roofs_unreadable", path=roof_source.source, detail=str(error))]) from None
        calibration.census = {**strata_census, **calibration.census}
        start = scenario.time.start_year if scenario.time.start_mode == PROJECTION else scenario.time.base_year
        target_year = float(calibration.target_year if calibration.target_year is not None else start)
        default_growth = None
        growth = self.tables["growth_rate"].series.get("*")
        if growth is not None and calibration.census_year is not None and calibration.census_year != target_year:
            low, high = sorted((float(calibration.census_year), target_year))
            default_growth = growth.mean(low, high)
        stratum_of_unit = self.units.values("stratum") if calibration.strata is not None else None
        result = population_from_roofs(calibration, roofs, self.units, stratum_of_unit, strata_groups, target_year,
                                       default_growth)
        self.calibration_report = result.report
        self.calibration_groups = result.groups
        report = result.report
        self.warnings.append(message("roofs_calibrated", kept=report["roofs"]["kept"], read=report["roofs"]["read"],
                                     population=round(report["total"])))
        for name in report["roofs"].get("unknown_usage") or []:
            self.warnings.append(message("roofs_unknown_usage", category=name or "∅"))
        return result.per_unit

    def dmax(self, year: float) -> np.ndarray:
        return to_hab_per_km2(unit_values(self.tables["dmax"], self.units, year), self.density_unit)

    def capacity(self, base, year, multiplier, dated_no_inflow, evacuated) -> np.ndarray:
        from .capacity import capacity

        cap = capacity(self.units.area_km2, base, self.dmax(year) * multiplier, self.units.no_inflow | dated_no_inflow)
        return np.where(evacuated, 0.0, cap)

    def event_units(self, index: int) -> np.ndarray:
        if "event" not in self.units.codes:
            return np.zeros(len(self.units), dtype=bool)
        labels = self.units.labels["event"]
        if index not in labels:
            return np.zeros(len(self.units), dtype=bool)
        return self.units.codes["event"] == labels.index(index)

    def recalibrate(self, population: np.ndarray, year: float) -> np.ndarray:
        """Scale the population of each administrative unit to its projected total (spec §5.2)."""
        admin = np.array(self.units.values("admin"), dtype=object)
        result = population.copy()
        for key, series in self.projections.items():
            members = admin == key
            total = population[members].sum()
            if total > 0:
                result[members] = population[members] * series.value_at(year) / total
        return result

    def indicator_values(self, population: np.ndarray, year: float) -> Dict[str, np.ndarray]:
        values: Dict[str, np.ndarray] = {}
        for indicator in self.indicators:
            values.update(indicator.compute(self.units, population, year))
        return values

    def column_units(self, scenario: Scenario) -> Dict[str, str]:
        units = {"area_km2": "km2", "density": scenario.density_unit}
        for indicator in self.indicators:
            units.update({o.key: o.unit for o in indicator.outputs})
        return units

    def resolution_warnings(self, scenario: Scenario) -> List[Message]:
        warnings = []
        if self.raster is not None and scenario.cell_size > max(self.raster.pixel_width, self.raster.pixel_height) + 1e-9:
            warnings.append(message("resolution_coarse_cell", cell=scenario.cell_size,
                                    pixel=self.raster.pixel_width))
        if scenario.time.migration_frequency == PER_STEP and scenario.time.time_step > 1:
            warnings.append(message("resolution_coarse_time", step=scenario.time.time_step))
        return warnings


class _SharedLayers:
    """Attribute layers grouped by source: each source is read and cut with the cells once."""

    def __init__(self, scenario: Scenario, crs: str):
        self.scenario, self.crs = scenario, crs
        self.sources: Dict[Tuple, Tuple[str, list]] = {}
        self.attributes: List[Tuple[str, Tuple, str]] = []

    def _key(self, spec) -> Tuple:
        return (self.scenario.path(spec.source), spec.layer, spec.where)

    def features(self, spec) -> list:
        key = self._key(spec)
        if key not in self.sources:
            self.sources[key] = (f"source_{len(self.sources)}", _read(self.scenario, spec, self.crs))
        return self.sources[key][1]

    def add(self, name: str, spec, field: str) -> None:
        features = self.features(spec)
        if features and field not in features[0].attributes:
            raise ScenarioError([message("scenario_field_missing", field=field, path=self._key(spec)[0])])
        self.attributes.append((name, self._key(spec), field))

    def layers(self) -> List[Layer]:
        return [Layer(name, [f.geometry for f in features], list(range(len(features))))
                for name, features in self.sources.values()]

    def derive(self, units) -> None:
        """Codes of each attribute from the feature index of its source (then the source codes are dropped)."""
        for name, key, field in self.attributes:
            source_name, features = self.sources[key]
            values = [str(f.attributes[field]) for f in features]
            labels = sorted(set(values))
            lookup = np.array([labels.index(v) for v in values] + [NO_VALUE], dtype=np.int64)
            index = units.labels[source_name]
            codes = units.codes[source_name]
            feature = np.array(index + [len(values)], dtype=np.int64)[np.where(codes >= 0, codes, -1)]
            units.codes[name] = lookup[feature]
            units.labels[name] = labels
        for source_name, _ in self.sources.values():
            units.codes.pop(source_name, None)
            units.labels.pop(source_name, None)
        units.__dict__.pop("_combination_cache", None)


def _unused_keys(table, units) -> List[Message]:
    """Keys of a parameter that match no zone of its layers (a typo, or a class absent from the area)."""
    present = [set(map(str, units.labels.get(name, []))) for name in table.layers]
    unused = []
    for key in table.series:
        if key == DEFAULT_KEY:
            continue
        parts = key.split(KEY_SEPARATOR) if len(present) > 1 else [key]
        if len(parts) != len(present) or any(p != DEFAULT_KEY and p not in values for p, values in zip(parts, present)):
            unused.append(key)
    return [message("parameter_key_unused", parameter=table.name, key=key) for key in unused]


def _check_file(path: str) -> None:
    if not os.path.exists(path) and "://" not in path and not path.upper().startswith(("PG:", "WFS:")):
        raise ScenarioError([message("scenario_file_not_found", path=path)])


def _read(scenario: Scenario, spec, crs: str):
    path = scenario.path(spec.source)
    _check_file(path)
    features = read_features(path, spec.layer, spec.where, target_crs_wkt=crs)
    if spec.field and features and spec.field not in features[0].attributes:
        raise ScenarioError([message("scenario_field_missing", field=spec.field, path=path)])
    return features


def _read_exclusion(scenario: Scenario, exclusion, crs: str):
    path = scenario.path(exclusion.source)
    _check_file(path)
    try:
        features = read_features(path, exclusion.layer, exclusion.where, crs, exclusion.buffer_m)
    except BufferRequired:
        raise ScenarioError([message("exclusion_needs_buffer", name=exclusion.name or path)]) from None
    return [f.geometry for f in features]


def _load_projections(scenario: Scenario) -> Dict[str, TimeSeries]:
    """Projections by administrative unit (CSV or spreadsheet, long or wide layout; see engine.tables)."""
    spec = scenario.projections
    path = scenario.path(spec.file)
    _check_file(path)
    try:
        table = read_projections(path, spec.sheet, spec.unit_column, spec.year_column, spec.value_column)
    except (TableError, RuntimeError) as error:
        raise ScenarioError([message("projections_unreadable", path=path, detail=str(error))]) from None
    return {key: TimeSeries(tuple(y for y, _ in pts), tuple(v for _, v in pts)) for key, pts in table.series.items()}


def _output_years(paths: List[str]) -> List[str]:
    prefix = "population_"
    years = {os.path.basename(p)[len(prefix):-4] for p in paths if os.path.basename(p).startswith(prefix)}
    return sorted(years, key=float)


def _write_run_report(scenario: Scenario, result: RunResult, model: _Model, seconds: float) -> None:
    language = scenario.language
    data = {
        "name": scenario.name,
        "engine_version": __version__,
        "gdal_version": gdal.__version__,
        "status": result.status,
        "duration_s": round(seconds, 2),
        "units": len(model.units),
        "cells": int((model.units.per_cell(model.units.area_km2) > 0).sum()),
        "base_population": float(model.p0.sum()),
        "final_population": result.final_population,
        "warnings": [m.to_dict(language) for m in result.warnings],
        "events": [m.to_dict(language) for m in result.events],
        "steps": [s.to_dict(language) for s in result.steps],
        "outputs": [os.path.basename(p) for p in result.outputs],
    }
    with open(os.path.join(result.directory, "report.json"), "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    from .i18n import format_number, translate

    lines = [
        translate("run_title", language, name=scenario.name or "-"),
        translate("run_status", language, status=translate(f"status_{result.status}", language)),
        translate("run_population", language, start=format_number(float(model.p0.sum()), language, 0),
                  end=format_number(result.final_population, language, 0)),
        translate("run_units", language, units=len(model.units), cells=data["cells"], cell_size=scenario.cell_size),
        translate("run_duration", language, seconds=round(seconds, 1)),
        "",
    ]
    for m in result.warnings + result.events:
        lines.append(f"! {m.render(language)}")
    lines.append("")
    for step in result.steps:
        lines.append(step.to_text(language))
    with open(os.path.join(result.directory, "report.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
