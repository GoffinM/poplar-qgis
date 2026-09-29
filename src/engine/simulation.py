"""Full simulation, from the start year to the end year (spec §5).

Everything comes from a :class:`~engine.scenario.Scenario`: no manual step.
Each sub-step applies, in order: dated exclusions that start, growth,
optional recalibration on projections, and migration with the chosen
non-convergence policy. Results are written for every output year.
"""

from __future__ import annotations

import csv
import json
import os
import time as clock
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

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
from .outputs import summary_rows, write_summary, write_year_rasters
from .runs import finish_run, new_run_directory
from .parameters import TimeSeries, to_hab_per_km2, unit_means, unit_values
from ._gdal import srs_from_epsg, srs_from_wkt
from .crs import choose_crs, native_pixel_m, population_to_density, reproject_density
from .raster_io import read_raster
from .report import StepReport
from .scenario import NO_INFLOW, OUTSIDE, PROJECTION, RELOCATE, Scenario, ScenarioError
from .timeline import PER_STEP, build_timeline
from .units import Layer, Zone, build_sink_units, build_units
from .vector_io import read_features, union_all

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
    if scenario.output_per_run:
        finish_run(out_dir, scenario.name, result.status, _output_years(result.outputs))
    return result


class _Model:
    """Data prepared once for a run: units, base population, parameters, indicators."""

    @classmethod
    def load(cls, scenario: Scenario) -> "_Model":
        self = cls()
        self.warnings: List[Message] = []
        raster_path = scenario.path(scenario.base_population_raster)
        _check_file(raster_path)
        source_raster = read_raster(raster_path)

        # Calculation CRS: projected, in metres (spec §3). Input layers are reprojected to it.
        study_lonlat = union_all(f.geometry for f in _read(scenario, scenario.study_area, WGS84_WKT))
        xmin_d, xmax_d, ymin_d, ymax_d = study_lonlat.GetEnvelope()
        try:
            choice = choose_crs(scenario.crs, source_raster.crs_wkt, (xmin_d, ymin_d, xmax_d, ymax_d))
        except ValueError:
            raise ScenarioError([message("crs_not_metric", crs=str(scenario.crs))]) from None
        crs = choice.wkt
        self.crs_choice = choice
        self.warnings.append(message("crs_used", name=_crs_name(crs), source=choice.source))
        if choice.suggestion is not None:
            self.warnings.append(message("crs_area_distortion", distortion=round(choice.max_area_distortion * 100, 2)))

        # Population raster as a density in hab/km2, in the calculation CRS.
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
        if scenario.parameter_zones is not None:
            spec = scenario.parameter_zones
            features = _read(scenario, spec, crs)
            layers.append(Layer("param_zone", [f.geometry for f in features],
                                [str(f.attributes[spec.field]) for f in features]))
        if scenario.admin_units is not None:
            spec = scenario.admin_units
            features = _read(scenario, spec, crs)
            layers.append(Layer("admin", [f.geometry for f in features],
                                [str(f.attributes[spec.field]) for f in features]))

        xmin, xmax, ymin, ymax = study.GetEnvelope()
        margin = 0.0
        if scenario.migration.policy == SINK:
            margin = (scenario.migration.sink_width_cells + 1) * scenario.cell_size
        origin = (self.raster.geotransform[0], self.raster.geotransform[3])
        self.grid = Grid.covering((xmin - margin, ymin - margin, xmax + margin, ymax + margin),
                                  scenario.cell_size, crs, origin=origin)
        self.units = build_units(self.grid, study, zones, union_all(no_inflow) if no_inflow else None, layers)
        if self.units.report.unclassified_area_km2 > 0.01:
            self.warnings.append(message("typology_gaps", area=round(self.units.report.unclassified_area_km2, 2)))
        self.p0, _ = base_population_from_density(self.units, self.raster, "hab/km2", scenario.boundary_mode)

        self.tables = scenario.parameter_tables()
        self.density_unit = scenario.density_unit
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
        if scenario.cell_size > max(self.raster.pixel_width, self.raster.pixel_height) + 1e-9:
            warnings.append(message("resolution_coarse_cell", cell=scenario.cell_size,
                                    pixel=self.raster.pixel_width))
        if scenario.time.migration_frequency == PER_STEP and scenario.time.time_step > 1:
            warnings.append(message("resolution_coarse_time", step=scenario.time.time_step))
        return warnings


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
    return [f.geometry for f in read_features(path, exclusion.layer, exclusion.where, crs, exclusion.buffer_m)]


def _load_projections(scenario: Scenario) -> Dict[str, TimeSeries]:
    """Projection table: ``admin, year, population`` (one row per unit and year)."""
    path = scenario.path(scenario.projections.csv)
    _check_file(path)
    points: Dict[str, List] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            points.setdefault(row["admin"].strip(), []).append((float(row["year"]), float(row["population"])))
    return {key: TimeSeries(tuple(y for y, _ in pts), tuple(v for _, v in pts)) for key, pts in points.items()}


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
