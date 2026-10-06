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
from .growth import grow, growth_factor
from .i18n import Message, message
from .indicators import Indicator, create_indicator
from .nonconvergence import (
    FAILED, SINK, SUCCESS, DmaxProposal, MigrationSettings, NonConvergenceError, Sink, migrate_with_policy,
)
from .grid_layer import cells_of, save_cells, write_grid_layer
from .html_report import write_html_report
from .outputs import summary_rows, write_summary, write_year_rasters, year_label
from .demand import save_populations
from .runs import finish_run, new_run_directory
from .parameters import DEFAULT_KEY, KEY_SEPARATOR, TimeSeries, to_hab_per_km2, unit_means, unit_values
from .polygons import (NO_POLYGON, NO_RANK, ColonisationRules, NucleusRules, PolygonHistory, Stratum,
                       cell_membership, colonise, initial_polygons, new_nuclei, part_layer)
from . import plausibility, polygon_outputs
from ._gdal import srs_from_epsg, srs_from_wkt
from .crs import choose_crs, native_pixel_m, population_to_density, reproject_density
from .raster_io import read_raster, write_raster
from .report import StepReport
from .scenario import (
    COLONIZATION_PARAMETERS, NO_INFLOW, OUTSIDE, PROJECTION, RELOCATE, Scenario, ScenarioError, VectorInput,
    parameter_zone_inputs,
)
from .timeline import ANNUAL, PER_STEP, build_timeline
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
    polygons: Optional[PolygonHistory] = None
    """Free strata mode only: polygon of each unit, colonisations, views of the cells."""


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

    free = model.free
    timeline = build_timeline(
        t0, scenario.time.end_year, scenario.time.time_step, scenario.time.output_years,
        ANNUAL if free else scenario.time.migration_frequency, scenario.time.first_migration_year,
        event_years=[e.year for e in scenario.exclusions if e.year is not None],
    )
    warnings.extend(model.resolution_warnings(scenario))

    settings = MigrationSettings(
        k=scenario.migration.k, tolerance=scenario.migration.tolerance,
        max_iterations=scenario.migration.max_iterations, policy=scenario.migration.policy,
        max_auto_increase=scenario.migration.max_auto_increase, approve=approve, share_ties=free,
        attraction=model.migration_attraction(),
    )
    if model.roads is not None:
        attraction_path = os.path.join(out_dir, "attractivite.tif")
        write_raster(attraction_path, model.roads.cell, model.grid.geotransform, model.grid.crs_wkt, nodata=-9999.0)
        outputs_first = [attraction_path]
    else:
        outputs_first = []
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
    outputs: List[str] = list(outputs_first)
    rows: List[Dict[str, object]] = []
    status = SUCCESS
    failure, failure_year = None, None

    history = model.start_history(t0) if free else None

    kept_populations: Dict[str, Dict[str, np.ndarray]] = {}

    def write(year: float) -> None:
        kept_populations[year_label(year)] = {"population": population.copy(), "unallocated": unallocated.copy(),
                                              "classes": units.codes["class"].copy()}
        if history is not None:
            key = int(round(year))
            history.membership[key] = cell_membership(units, model.polygon_id, scenario.strata.cell_membership_share)
            history.ids[key] = model.polygon_id.copy()
            history.stats.extend(polygon_outputs.polygon_stats(
                history, year, population, capacity_now, units.no_inflow | dated_no_inflow | evacuated,
                model.polygon_id, scenario.migration.tolerance, unallocated))
            admin = units.values("admin") if "admin" in units.codes else [None] * len(units)
            totals: Dict[str, float] = {}
            for name, value in zip(admin, history.reclassification.tolist()):
                totals[name or "–"] = totals.get(name or "–", 0.0) + value
            history.reclassification_by_admin.extend({"year": float(year), "admin": name, "effect": value}
                                                     for name, value in sorted(totals.items()))
            outputs.extend(polygon_outputs.write_year(out_dir, history, year, model.urban_rank))
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
        if history is not None:
            model.measure_reclassification(history, population, rates, step)
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
                    evacuated=evacuated, sink=model.sink, labels=model.polygon_id if free else None,
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
            balance = report.population_after_migration + report.unallocated + report.placed_in_sink
            if abs(balance - after_growth) > 1e-6 * max(1.0, abs(after_growth)):
                raise RuntimeError(message("conservation_failed", year=f"{step.end:g}",
                                           difference=f"{balance - after_growth:.3f}").render(scenario.language))
            if history is not None:
                colonised = model.colonise(history, population, capacity_now,
                                           units.no_inflow | dated_no_inflow | evacuated, outcome.inflow, step.end)
                if colonised:
                    events.append(message("strata_colonised", year=f"{step.end:g}", cells=colonised))
        else:
            report = StepReport(step.start, step.end, before, after_growth, after_growth, 0.0, 0.0, 0.0, 0,
                                True, 1.0, SUCCESS, [])
        steps.append(report)
        status = max(status, report.status, key=STATUS_ORDER.index)
        if step.output:
            write(step.end)
        if progress is not None:
            progress((index + 1) / len(timeline))

    if history is not None:
        history.final = model.polygon_id.copy()
        try:  # display layers of the polygons: a failure is a warning, the results are in the rasters
            outputs.extend(polygon_outputs.write_final(out_dir, history, scenario.cell_size,
                                                       scenario.strata.min_patch_area_km2,
                                                       scenario.strata.smoothing_passes))
        except Exception as error:  # pragma: no cover
            warnings.append(message("polygon_outputs_failed", detail=str(error)))
        try:
            outputs.extend(plausibility.write(out_dir, plausibility.compute(history, steps, scenario.cell_size,
                                                                            model.urban_rank)))
        except Exception as error:  # pragma: no cover
            warnings.append(message("plausibility_failed", detail=str(error)))
    try:  # population of each unit at the output years: the demand can be computed again (engine.demand)
        outputs.append(save_populations(out_dir, units, kept_populations))
    except Exception as error:  # pragma: no cover
        warnings.append(message("populations_not_saved", detail=str(error)))
    summary_path = os.path.join(out_dir, "summary.csv")
    write_summary(summary_path, rows, language, model.column_units(scenario))
    outputs.append(summary_path)
    try:  # one layer of the cells with every result (mailles.gpkg): never a failed run
        cells = cells_of(units)
        outputs.append(save_cells(out_dir, cells))     # small: the layer can be written again at once, on demand
        outputs.extend(write_grid_layer(out_dir, cells, scenario.output_grid_layer, scenario.density_unit,
                                        model.column_units(scenario)))
    except Exception as error:  # pragma: no cover
        warnings.append(message("grid_layer_failed", detail=str(error)))
    result = RunResult(status, steps, warnings, outputs, out_dir, float(population.sum()), float(base_start), events,
                       failure, failure_year, history)
    _write_run_report(scenario, result, model, clock.time() - started)
    used = scenario.to_dict()
    used["base_dir"] = scenario.base_dir                  # its relative paths, for grid_layer.rebuild
    with open(os.path.join(out_dir, "scenario_used.json"), "w", encoding="utf-8") as handle:
        json.dump(used, handle, ensure_ascii=False, indent=2)
    if model.calibration_report is not None:
        with open(os.path.join(out_dir, "calibration.json"), "w", encoding="utf-8") as handle:
            json.dump(model.calibration_report, handle, ensure_ascii=False, indent=1)
        outputs.append(os.path.join(out_dir, "calibration.json"))
        try:  # the workbook is a convenience too: a failure is a warning, never a failed run
            from .calibration_excel import write_calibration_workbook

            outputs.append(write_calibration_workbook(model.calibration_report, os.path.join(out_dir, "calage.xlsx"),
                                                      language, scenario.calibration, scenario.name))
        except Exception as error:  # pragma: no cover
            result.warnings.append(message("calibration_excel_failed", detail=str(error)))
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
    def load(cls, scenario: Scenario, units_only: bool = False, population: bool = True) -> "_Model":
        """Everything a run needs; with ``units_only``, only the grid and its cells cut by the layers.

        ``population=False`` skips the starting population (raster or roofs): enough to compute the demand
        of a finished run again (engine.demand).
        """
        self = cls()
        self.warnings: List[Message] = []
        from_roofs = scenario.population_source == "buildings"
        source_raster = None
        raster_warning = None
        if scenario.base_population_raster:  # optional with roofs: it then only aligns the grid
            raster_path = scenario.path(scenario.base_population_raster)
            if from_roofs and _missing(raster_path):
                raster_warning = message("raster_ignored", path=raster_path)
            else:
                _check_file(raster_path, "raster")
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
        if raster_warning is not None:
            self.warnings.append(raster_warning)
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

        self.free = scenario.strata.free
        typology_key = (scenario.path(typology.source), typology.layer, typology.where, typology.field)

        def zone_layers(specs) -> Tuple[str, ...]:
            names = []
            for spec in specs:
                if self.free and (scenario.path(spec.source), spec.layer, spec.where, spec.field) == typology_key:
                    names.append("class")        # linked to the strata: follows the polygon (plan §2.1, P3)
                    continue
                key = (scenario.path(spec.source), spec.layer, spec.where, spec.field)
                if key not in zone_names:
                    zone_names[key] = f"zones_{len(zone_names)}"
                    shared.add(zone_names[key], spec, spec.field)
                names.append(zone_names[key])
            return tuple(names)

        for name in scenario.parameters:
            names = zone_layers(scenario.parameter_zones_of(name))
            if names:
                parameter_layers[name] = names
        # Indicator parameters have their own zones too, each from any layer (a water allowance by
        # settlement type, a network efficiency by service area…).
        indicator_layers: Dict[Tuple[int, str], Tuple[str, ...]] = {}
        for index, indicator in enumerate(scenario.indicators):
            for name, spec in indicator.parameters.items():
                names = zone_layers(parameter_zone_inputs(spec))
                if names:
                    indicator_layers[(index, name)] = names
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

        if self.free:
            layers.append(part_layer(zones))      # one polygon per connected part (P2)
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
        if self.free:
            self._start_polygons(scenario, zones)
        if units_only:                       # enough to rebuild the cell layer of a run (grid_layer.rebuild)
            return self
        self.calibration_report = None
        self.calibration_groups = {}
        self.p0 = None
        if not from_roofs and population:
            self.p0, _ = base_population_from_density(self.units, self.raster, "hab/km2", scenario.boundary_mode)

        self.tables = scenario.parameter_tables()
        for name, names in parameter_layers.items():
            self.tables[name].layers = names
            self.warnings.extend(_unused_keys(self.tables[name], self.units))
        self.density_unit = scenario.density_unit
        if from_roofs and population:
            self.p0 = self._population_from_roofs(scenario, calibration, crs, study, strata_groups, strata_census)
        for name in ("growth_rate", "dmax"):
            try:
                unit_values(self.tables[name], self.units, scenario.time.base_year)
            except KeyError as error:
                raise ScenarioError([message("scenario_parameter_missing", parameter=name, detail=str(error))]) from None

        if self.free and not (scenario.projections and scenario.projections.recalibrate):
            ranked = [name for name, rules in scenario.strata.classes.items() if rules.rank is not None]
            try:
                rates = {(self.tables["growth_rate"].for_key(name).years, self.tables["growth_rate"].for_key(name).values)
                         for name in ranked}
            except KeyError:
                rates = set()
            if len(rates) > 1:
                self.warnings.append(message("strata_reclassification"))
        self.indicators: List[Indicator] = [
            create_indicator(spec.type, scenario.indicator_tables(spec)) for spec in scenario.indicators
        ]
        self.roads = None
        if scenario.strata.roads_active() and population:
            self._load_roads(scenario)
        for (index, name), names in indicator_layers.items():
            table = self.indicators[index].parameters[name]
            table.layers = names
            self.warnings.extend(_unused_keys(table, self.units))
        for indicator in self.indicators:
            for name, table in indicator.parameters.items():
                try:
                    unit_values(table, self.units, scenario.time.base_year)
                except KeyError as error:
                    raise ScenarioError([message("scenario_parameter_missing", parameter=name,
                                                 detail=str(error))]) from None
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
        _check_file(roof_source.source, "roofs")
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

    # --- attraction of the roads (plan_demande_et_routes.md, B) ------------------------------------

    def _load_roads(self, scenario: Scenario) -> None:
        from .roads import RoadLayerError, road_attraction

        settings = scenario.strata.roads
        try:
            self.roads = road_attraction(self.units, settings, scenario.path(settings.source))
        except (RoadLayerError, RuntimeError, OSError) as error:
            raise ScenarioError([message("roads_unreadable", source=settings.source, detail=str(error))]) from None
        self.road_settings = settings
        if self.roads.lines == 0:
            self.warnings.append(message("roads_none", source=settings.source))
        lengths = ", ".join(f"{name} {km:g} km" for name, km in self.roads.length_km.items()) or "0 km"
        self.warnings.append(message("roads_used", lines=self.roads.lines, lengths=lengths,
                                     reach=f"{settings.reach_m:g}",
                                     actions=", ".join(a for a, on in (("migration", settings.migration),
                                                                        ("colonisation", settings.colonization
                                                                         and self.free)) if on) or "-"))
        if self.roads.unknown_classes:
            self.warnings.append(message("roads_unknown_classes", classes=", ".join(self.roads.unknown_classes)))

    def migration_attraction(self) -> Optional[np.ndarray]:
        if self.roads is None or not self.road_settings.migration:
            return None
        return self.roads.unit

    def near_road(self) -> Optional[np.ndarray]:
        """Cells where colonisation needs fewer neighbours (attractiveness >= 1 + threshold)."""
        if self.roads is None or not self.road_settings.colonization:
            return None
        cell = np.nan_to_num(self.roads.cell, nan=1.0).ravel()
        return cell >= 1.0 + self.road_settings.threshold - 1e-12

    # --- free strata mode (plan_polygones_libres.md) ---------------------------------------------

    def _start_polygons(self, scenario: Scenario, zones: List[Zone]) -> None:
        strata = scenario.strata
        rules = {name: Stratum(NO_RANK if r.rank is None else int(r.rank), r.colonizable)
                 for name, r in strata.classes.items()}
        start = scenario.time.start_year if scenario.time.start_mode == PROJECTION else scenario.time.base_year
        self.polygon_id, self.polygons = initial_polygons(self.units, zones, rules, float(start))
        self.strata = strata
        self.settings_tolerance = scenario.migration.tolerance
        labels = self.units.labels["class"]
        codes = self.units.codes["class"]
        known = self.polygon_id >= 0
        codes[known] = [labels.index(self.polygons.stratum[p]) for p in self.polygon_id[known]]
        self.initial_class = codes.copy()
        self.warnings.append(message("strata_free_mode", polygons=len(self.polygons), neighbors=strata.min_neighbors))
        self.stratum_rules = rules
        self.nucleus_rules = NucleusRules(**strata.new_nuclei)
        self.urban_rank = polygon_outputs.urban_rank(self.polygons, strata.urban_rank)
        if self.nucleus_rules.enabled:
            self.warnings.append(message("strata_nuclei_on", stratum=self.nucleus_rules.stratum,
                                         cells=self.nucleus_rules.min_cells))
        else:
            self.warnings.append(message("strata_nuclei_off"))
        if abs(scenario.cell_size - 250.0) > 1e-6:
            self.warnings.append(message("strata_cell_size", size=f"{scenario.cell_size:g}"))

    def start_history(self, year: float) -> PolygonHistory:
        history = PolygonHistory(self.units, self.polygons, self.polygon_id.copy(), self.polygon_id.copy(),
                                 reclassification=np.zeros(len(self.units)), start_year=int(round(year)))
        if self.roads is not None:
            settings = self.road_settings
            history.roads = {"main_distance": self.roads.main_distance, "reach_m": settings.reach_m,
                             "migration": settings.migration, "colonization": settings.colonization,
                             "min_neighbors": settings.min_neighbors, "threshold": settings.threshold,
                             "near_road": self.near_road()}
        return history

    def colonization_values(self, year: float) -> Tuple[np.ndarray, np.ndarray]:
        """Minimum inflow and saturation share of each polygon, from its stratum."""
        values = []
        for name, default in COLONIZATION_PARAMETERS.items():
            table = self.tables.get(name)
            values.append(np.array([default if table is None else table.for_keys([stratum]).value_at(year)
                                    for stratum in self.polygons.stratum], dtype=np.float64))
        return values[0], values[1]

    def colonise(self, history: PolygonHistory, population, capacity, protected, inflow, year: float) -> int:
        """One colonisation pass after the migration of a step; the new polygons count from the next step."""
        if inflow is None:
            return 0
        min_inflow, saturation_share = self.colonization_values(year)
        rules = ColonisationRules(self.strata.min_neighbors, self.strata.cell_membership_share,
                                  float(self.settings_tolerance), self.strata.min_inflow_unit, self.near_road(),
                                  self.road_settings.min_neighbors if self.roads is not None else 2)
        result = colonise(self.units, self.polygon_id, self.polygons, population, capacity, protected, inflow,
                          min_inflow, saturation_share, rules)
        before = self.polygon_id
        ncols = self.units.grid.ncols
        cell_population = np.bincount(self.units.cell_id, weights=np.where(result.changed, population, 0.0),
                                      minlength=self.units.grid.ncells)
        for cell, polygon, exported in zip(result.cells, result.winners, result.exported):
            history.events.append({"year": float(year), "cell": int(cell), "row": int(cell // ncols),
                                   "col": int(cell % ncols), "polygon": int(polygon), "event": "extension",
                                   "exported": float(exported), "population": float(cell_population[cell])})
        pid, nuclei = new_nuclei(self.units, result.polygon_id, self.polygons, population, capacity, protected,
                                 inflow, self.nucleus_rules, self.stratum_rules, year, float(self.settings_tolerance),
                                 self.strata.cell_membership_share)
        for nucleus in nuclei:
            for cell in nucleus.cells:
                cell = int(cell)
                history.events.append({"year": float(year), "cell": cell, "row": cell // ncols, "col": cell % ncols,
                                       "polygon": nucleus.polygon, "event": "nouveau_noyau",
                                       "population": float(population[self.units.cell_id == cell].sum()),
                                       "flags": nucleus.flags})
        changed = np.flatnonzero(pid != before)
        if len(changed) == 0:
            return 0
        self.polygon_id = pid
        labels = self.units.labels["class"]
        self.units.codes["class"][changed] = [labels.index(self.polygons.stratum[p]) for p in pid[changed]]
        self.units.__dict__.pop("_combination_cache", None)        # parameters follow the new strata
        return len(result.cells) + sum(len(n.cells) for n in nuclei)

    def measure_reclassification(self, history: PolygonHistory, population, rates, step) -> None:
        """Population that the change of growth rate of colonised units adds in this step (S1)."""
        changed = self.units.codes["class"] != self.initial_class
        if not changed.any():
            return
        initial_view = replace(self.units, codes={**self.units.codes, "class": self.initial_class})
        initial_rates = unit_means(self.tables["growth_rate"], initial_view, step.start, step.end)
        effect = population * (growth_factor(rates, step.duration) - growth_factor(initial_rates, step.duration))
        history.reclassification += np.where(changed, effect, 0.0)

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


def _missing(path: str) -> bool:
    """True when neither the system nor GDAL can reach the file (network shares included)."""
    if "://" in path or path.upper().startswith(("PG:", "WFS:")) or os.path.exists(path):
        return False
    if os.path.exists(os.path.normpath(path)):
        return False
    gdal.PushErrorHandler("CPLQuietErrorHandler")  # GDAL sometimes reaches what os.path cannot (UNC, /vsi)
    try:
        return gdal.OpenEx(path) is None
    except RuntimeError:  # when exceptions are enabled (by QGIS or another plugin)
        return True
    finally:
        gdal.PopErrorHandler()
        gdal.ErrorReset()


def _check_file(path: str, what: str = "layer", **values) -> None:
    """Stop with a message that names the setting (and its tab) whose file cannot be found."""
    if _missing(path):
        messages = [message(f"file_not_found_{what}", path=path, **values)]
        if path.startswith(("//", "\\\\")):
            messages.append(message("file_on_network", path=path))
        raise ScenarioError(messages)


def _read(scenario: Scenario, spec, crs: str):
    path = scenario.path(spec.source)
    _check_file(path)
    features = read_features(path, spec.layer, spec.where, target_crs_wkt=crs)
    if spec.field and features and spec.field not in features[0].attributes:
        raise ScenarioError([message("scenario_field_missing", field=spec.field, path=path)])
    return features


def _read_exclusion(scenario: Scenario, exclusion, crs: str):
    path = scenario.path(exclusion.source)
    _check_file(path, "exclusion", name=exclusion.name or "")
    try:
        features = read_features(path, exclusion.layer, exclusion.where, crs, exclusion.buffer_m)
    except BufferRequired:
        raise ScenarioError([message("exclusion_needs_buffer", name=exclusion.name or path)]) from None
    return [f.geometry for f in features]


def _load_projections(scenario: Scenario) -> Dict[str, TimeSeries]:
    """Projections by administrative unit (CSV or spreadsheet, long or wide layout; see engine.tables)."""
    spec = scenario.projections
    path = scenario.path(spec.file)
    _check_file(path, "projections")
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
