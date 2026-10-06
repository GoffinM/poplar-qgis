"""Scenario file (JSON): every input and setting of a run (spec §2).

Paths are relative to the scenario file. Parameters are given as a single
value, per key (typology class or parameter zone, ``*`` for the default),
and optionally per pivot year::

    "growth_rate": {"*": {"2026": 3.0, "2040": 2.0}, "Urbain1": 4.0}

or linked to their own zones, one layer or two crossed layers (spec §2.3 bis)::

    "dmax": {"zones": [{"source": "types.shp", "field": "Type"}],
             "values": {"Rural": 2500, "Urbain1": 10000, "*": 2500}}

Loading checks the whole file and reports every problem at once, as
translatable messages (:class:`ScenarioError`).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .i18n import DEFAULT_LANGUAGE, Message, available_languages, message
from .nonconvergence import POLICIES
from .parameters import CONSTANT, DEFAULT_KEY, DENSITY_FACTORS, LINEAR, ParameterTable, TimeSeries, load_parameters_csv
from .timeline import ANNUAL, PER_STEP

OUTSIDE = "outside"
NO_INFLOW = "no_inflow"
RELOCATE = "relocate"
BEHAVIOURS = (OUTSIDE, NO_INFLOW, RELOCATE)
CENSUS = "census"
PROJECTION = "projection"
PLANNED = "planned"
FREE = "free"
STRATA_MODES = (PLANNED, FREE)
COLONIZATION_PARAMETERS = {"colonization_min_inflow": 0.1, "saturation_share": 0.8}
"""Parameters of the colonising polygon in free mode, with their defaults (plan_polygones_libres.md §9)."""


class ScenarioError(ValueError):
    def __init__(self, messages: List[Message]):
        super().__init__("\n".join(m.render(DEFAULT_LANGUAGE) for m in messages))
        self.messages = messages


@dataclass
class VectorInput:
    source: str
    layer: Optional[str] = None
    where: Optional[str] = None
    field: Optional[str] = None


@dataclass
class Exclusion:
    source: str
    behaviour: str
    name: str = ""
    year: Optional[float] = None
    layer: Optional[str] = None
    where: Optional[str] = None
    buffer_m: Optional[float] = None


@dataclass
class TimeSettings:
    base_year: float
    end_year: float
    time_step: float = 1.0
    output_years: Optional[List[float]] = None
    migration_frequency: str = ANNUAL
    first_migration_year: Optional[float] = None
    start_mode: str = CENSUS
    start_year: Optional[float] = None


@dataclass
class MigrationOptions:
    k: int = 3
    tolerance: int = 1
    max_iterations: int = 10_000
    policy: str = "stop"
    max_auto_increase: float = 0.0
    sink_width_cells: int = 4
    sink_dmax: Optional[float] = None


@dataclass
class Projections:
    file: str
    """CSV or spreadsheet (xlsx, xls, ods); ``csv`` is accepted as the older name of this key."""
    recalibrate: bool = False
    sheet: Optional[str] = None
    unit_column: Optional[str] = None
    year_column: Optional[str] = None
    value_column: Optional[str] = None


@dataclass
class StratumSettings:
    rank: Optional[int] = None
    colonizable: bool = True


DEFAULT_ROAD_WEIGHTS = {"nationale": 2.0, "provinciale": 0.6, "autre": 0.3}


@dataclass
class RoadSettings:
    """Attraction of the roads (plan_demande_et_routes.md, B, validated on 06/10/2026).

    Attractiveness of a place: ``1 + weight × exp(−distance / reach_m)``, with the weight of the nearest
    road of each class (the largest term is kept). It acts on the migration (the distance a migrant
    « feels » is the real distance divided by the attractiveness of the arrival unit) and on the
    colonisation (a cell whose attractiveness reaches ``1 + threshold`` needs only ``min_neighbors``
    neighbouring cells of the colonising polygon). The speed of the fronts stays a result.
    """

    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_ROAD_WEIGHTS))
    source: str = ""
    layer: Optional[str] = None
    where: Optional[str] = None
    field: Optional[str] = None             # (after ``weights``: the name hides dataclasses.field below)
    """Field of the class of each road; without it, every road has the weight of ``*`` (1 by default)."""
    reach_m: float = 500.0
    migration: bool = True
    colonization: bool = True
    min_neighbors: int = 2
    threshold: float = 0.5
    in_planned_mode: bool = False
    """Planned mode: the migration follows the roads too (off by default: same results as the former tool)."""


@dataclass
class StrataSettings:
    """Strata that change in time (fiche §3.5, plan_polygones_libres.md).

    ``planned``: the polygons given as input never change (the default, same
    results as before). ``free``: polygons grow by colonisation.
    """

    mode: str = PLANNED
    min_neighbors: int = 3
    cell_membership_share: float = 0.5
    min_inflow_unit: str = "share_of_capacity"
    classes: Dict[str, StratumSettings] = field(default_factory=dict)
    urban_rank: Optional[int] = None
    """Rank from which a polygon is urban, for the status rasters (default: the second lowest rank)."""
    min_patch_area_km2: Optional[float] = None
    """Smallest part drawn in the smoothed polygons (default: one cell); display only (P18)."""
    smoothing_passes: int = 3
    new_nuclei: Dict[str, Any] = field(default_factory=dict)
    """Rule of the new nuclei (P8/P17), off by default: enabled, stratum, min_cells, enclave_km2, migration_share."""
    roads: Optional[RoadSettings] = None
    """Attraction of the roads (off without a road layer)."""

    def roads_active(self) -> bool:
        """The roads change something in this mode."""
        return self.roads is not None and bool(self.roads.source) and (self.free or self.roads.in_planned_mode)

    @property
    def free(self) -> bool:
        return self.mode == FREE


@dataclass
class IndicatorSpec:
    type: str
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Scenario:
    study_area: VectorInput
    typology: VectorInput
    base_population_raster: str
    time: TimeSettings
    parameters: Dict[str, Any]
    name: str = ""
    description: str = ""
    language: str = DEFAULT_LANGUAGE
    cell_size: float = 250.0
    density_unit: str = "hab/km2"
    boundary_mode: str = "area_weighted"
    population_value_type: str = "density"
    population_source: str = "raster"
    """``raster`` (population raster) or ``buildings`` (roofs calibrated on the census, section ``calibration``)."""
    calibration: Optional[Dict[str, Any]] = None
    """Content of the population raster: ``density`` (in ``density_unit``) or ``count`` per pixel."""
    crs: Optional[str] = None
    """Calculation CRS (EPSG code, WKT, ``auto-utm`` or ``auto-equal-area``); see engine.crs."""
    parameter_zones: Optional[VectorInput] = None
    admin_units: Optional[VectorInput] = None
    exclusions: List[Exclusion] = field(default_factory=list)
    projections: Optional[Projections] = None
    migration: MigrationOptions = field(default_factory=MigrationOptions)
    indicators: List[IndicatorSpec] = field(default_factory=list)
    output_directory: str = "outputs"
    output_per_run: bool = False
    """Write each run in its own time-stamped sub-folder of ``output_directory`` (see engine.runs)."""
    output_grid_layer: str = "gpkg"
    """Layer of the grid cells with every result: ``gpkg`` (default), ``shp``, ``both`` or ``none``."""
    strata: StrataSettings = field(default_factory=StrataSettings)
    extrapolation: str = CONSTANT
    base_dir: str = ""

    # --- paths --------------------------------------------------------------------

    def path(self, value: str) -> str:
        if is_connection(value) or os.path.isabs(value):
            return value
        return os.path.normpath(os.path.join(self.base_dir, value))

    # --- parameters ---------------------------------------------------------------

    def parameter_zones_of(self, name: str) -> List[VectorInput]:
        """Zone layers of a parameter linked to its own zones (empty for typology classes)."""
        return parameter_zone_inputs(self.parameters.get(name))

    def parameter_tables(self) -> Dict[str, ParameterTable]:
        """Growth rate and maximum density (and any other entry), as parameter tables."""
        tables: Dict[str, ParameterTable] = {}
        csv = self.parameters.get("csv")
        if csv:
            tables.update(load_parameters_csv(self.path(csv), self.extrapolation))
        for name, spec in self.parameters.items():
            if name == "csv":
                continue
            tables[name] = parse_parameter(name, spec, self.extrapolation)
        return tables

    def indicator_tables(self, spec: IndicatorSpec) -> Dict[str, ParameterTable]:
        return {name: parse_parameter(name, value, self.extrapolation) for name, value in spec.parameters.items()}

    # --- serialisation -----------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("base_dir")
        data["base_population"] = {"raster": data.pop("base_population_raster"), "boundary_mode": data.pop("boundary_mode"),
                                   "value_type": data.pop("population_value_type"),
                                   "source": data.pop("population_source")}
        data["output"] = {"directory": data.pop("output_directory"), "per_run": data.pop("output_per_run"),
                          "grid_layer": data.pop("output_grid_layer")}
        if self.strata == StrataSettings():
            data.pop("strata")                       # files of the planned mode stay as they were
        return _without_passwords(_drop_none(data))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)


def parameter_zone_inputs(spec: Any) -> List[VectorInput]:
    if not isinstance(spec, dict) or "values" not in spec:
        return []
    zones = spec.get("zones") or []
    if isinstance(zones, dict):
        zones = [zones]
    return [VectorInput(z.get("source", ""), z.get("layer"), z.get("where"), z.get("field")) for z in zones]


def parse_parameter(name: str, spec: Any, extrapolation: str = CONSTANT) -> ParameterTable:
    if isinstance(spec, dict) and "values" in spec:
        zones = spec.get("zones") or []
        count = 1 if isinstance(zones, dict) else len(zones)
        if count > 2:
            raise ValueError(f"parameter {name!r}: one or two zone layers are expected")
        return parse_parameter(name, spec["values"], extrapolation)
    if isinstance(spec, (int, float)):
        return ParameterTable(name, {DEFAULT_KEY: TimeSeries.constant(float(spec))})
    if not isinstance(spec, dict):
        raise ValueError(f"parameter {name!r}: a number or a mapping is expected")
    table = ParameterTable(name)
    for key, value in spec.items():
        if isinstance(value, (int, float)):
            table.series[str(key)] = TimeSeries.constant(float(value))
        elif isinstance(value, dict) and value:
            years = [float(y) for y in value]
            table.series[str(key)] = TimeSeries(tuple(years), tuple(float(v) for v in value.values()), extrapolation)
        else:
            raise ValueError(f"parameter {name!r}, key {key!r}: a number or a {{year: value}} mapping is expected")
    return table


def load_scenario(path: str) -> Scenario:
    with open(path, encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except json.JSONDecodeError as error:
            raise ScenarioError([message("scenario_invalid_json", path=path, detail=str(error))]) from None
    return scenario_from_dict(data, os.path.dirname(os.path.abspath(path)))


def scenario_from_dict(data: Dict[str, Any], base_dir: str = "") -> Scenario:
    errors: List[Message] = []

    def required(section: Dict[str, Any], key: str, where: str) -> Any:
        if key not in section or section[key] in (None, ""):
            errors.append(message("scenario_missing_key", key=f"{where}{key}"))
            return None
        return section[key]

    def vector(section: Any, where: str, needs_field: bool = False) -> Optional[VectorInput]:
        if section is None:
            return None
        if not isinstance(section, dict):
            errors.append(message("scenario_invalid_value", key=where, expected="{source, layer, where, field}"))
            return None
        source = required(section, "source", f"{where}.")
        if needs_field:
            required(section, "field", f"{where}.")
        return VectorInput(source or "", section.get("layer"), section.get("where"), section.get("field"))

    study_area = vector(required(data, "study_area", ""), "study_area")
    typology = vector(required(data, "typology", ""), "typology", needs_field=True)
    base_population = required(data, "base_population", "") or {}
    population_source = base_population.get("source", "raster") if base_population else "raster"
    if population_source == "buildings":
        raster = base_population.get("raster") or ""
    else:
        raster = required(base_population, "raster", "base_population.") if base_population else None
    time_data = required(data, "time", "") or {}
    parameters = required(data, "parameters", "") or {}

    time = None
    if time_data:
        base_year = required(time_data, "base_year", "time.")
        end_year = required(time_data, "end_year", "time.")
        if base_year is not None and end_year is not None:
            time = TimeSettings(
                base_year=float(base_year), end_year=float(end_year),
                time_step=float(time_data.get("time_step", 1.0)),
                output_years=time_data.get("output_years"),
                migration_frequency=time_data.get("migration_frequency", ANNUAL),
                first_migration_year=time_data.get("first_migration_year"),
                start_mode=time_data.get("start_mode", CENSUS),
                start_year=time_data.get("start_year"),
            )

    exclusions = []
    for i, item in enumerate(data.get("exclusions", []) or []):
        where = f"exclusions[{i}]."
        source = required(item, "source", where)
        behaviour = required(item, "behaviour", where)
        exclusions.append(Exclusion(source or "", behaviour or "", item.get("name", f"exclusion_{i + 1}"),
                                    item.get("year"), item.get("layer"), item.get("where"), item.get("buffer_m")))

    migration = MigrationOptions(**{k: v for k, v in (data.get("migration") or {}).items()
                                    if k in MigrationOptions.__dataclass_fields__})
    projections = None
    if data.get("projections"):
        spec = dict(data["projections"])
        if "file" not in spec and "csv" in spec:
            spec["file"] = spec.pop("csv")
        spec.pop("csv", None)
        projections = Projections(required(spec, "file", "projections.") or "",
                                  bool(spec.get("recalibrate", False)), spec.get("sheet"), spec.get("unit_column"),
                                  spec.get("year_column"), spec.get("value_column"))
    indicators = [IndicatorSpec(item.get("type", ""), item.get("parameters", {})) for item in data.get("indicators", [])]
    strata = StrataSettings()
    strata_data = data.get("strata")
    if strata_data is not None:
        if not isinstance(strata_data, dict):
            errors.append(message("scenario_invalid_value", key="strata", value=str(strata_data),
                                  expected="{mode, min_neighbors, cell_membership_share, min_inflow_unit, classes}"))
        else:
            classes = {}
            for name, rules in (strata_data.get("classes") or {}).items():
                rules = rules if isinstance(rules, dict) else {}
                classes[str(name)] = StratumSettings(rules.get("rank"), bool(rules.get("colonizable", True)))
            strata = StrataSettings(
                mode=str(strata_data.get("mode", PLANNED)), min_neighbors=strata_data.get("min_neighbors", 3),
                cell_membership_share=strata_data.get("cell_membership_share", 0.5),
                min_inflow_unit=str(strata_data.get("min_inflow_unit", "share_of_capacity")), classes=classes,
                urban_rank=strata_data.get("urban_rank"), min_patch_area_km2=strata_data.get("min_patch_area_km2"),
                smoothing_passes=strata_data.get("smoothing_passes", 3),
                new_nuclei=dict(strata_data.get("new_nuclei") or {}), roads=_roads(strata_data.get("roads"), errors))

    if errors or time is None or study_area is None or typology is None:
        raise ScenarioError(errors or [message("scenario_missing_key", key="time")])

    scenario = Scenario(
        study_area=study_area, typology=typology, base_population_raster=raster, time=time,
        parameters=parameters, name=data.get("name", ""), description=data.get("description", ""), language=data.get("language", DEFAULT_LANGUAGE),
        cell_size=float(data.get("cell_size", 250.0)), density_unit=data.get("density_unit", "hab/km2"),
        boundary_mode=base_population.get("boundary_mode", "area_weighted"),
        population_value_type=base_population.get("value_type", "density"), crs=data.get("crs"),
        population_source=population_source, calibration=data.get("calibration"),
        parameter_zones=vector(data.get("parameter_zones"), "parameter_zones", needs_field=True),
        admin_units=vector(data.get("admin_units"), "admin_units", needs_field=True),
        exclusions=exclusions, projections=projections, migration=migration, indicators=indicators,
        output_directory=(data.get("output") or {}).get("directory", "outputs"),
        output_per_run=bool((data.get("output") or {}).get("per_run", False)),
        output_grid_layer=str((data.get("output") or {}).get("grid_layer", "gpkg")),
        extrapolation=data.get("extrapolation", CONSTANT), base_dir=base_dir, strata=strata,
    )
    errors.extend(validate(scenario))
    if errors:
        raise ScenarioError(errors)
    return scenario


def validate(scenario: Scenario) -> List[Message]:
    """Consistency checks that do not need to open the data (files are checked at run time)."""
    errors: List[Message] = []

    def invalid(key: str, value: Any, expected: str) -> None:
        errors.append(message("scenario_invalid_value", key=key, value=str(value), expected=expected))

    t = scenario.time
    if t.end_year <= t.base_year:
        invalid("time.end_year", t.end_year, f"> {t.base_year:g}")
    if t.time_step <= 0:
        invalid("time.time_step", t.time_step, "> 0")
    if t.migration_frequency not in (ANNUAL, PER_STEP):
        invalid("time.migration_frequency", t.migration_frequency, f"{ANNUAL} | {PER_STEP}")
    if t.start_mode not in (CENSUS, PROJECTION):
        invalid("time.start_mode", t.start_mode, f"{CENSUS} | {PROJECTION}")
    if t.start_mode == PROJECTION:
        if t.start_year is None:
            errors.append(message("scenario_missing_key", key="time.start_year"))
        if scenario.projections is None or scenario.admin_units is None:
            errors.append(message("scenario_projection_needs_data"))
    if scenario.projections is not None and scenario.projections.recalibrate and scenario.admin_units is None:
        errors.append(message("scenario_projection_needs_data"))
    if scenario.cell_size <= 0:
        invalid("cell_size", scenario.cell_size, "> 0")
    if scenario.density_unit not in DENSITY_FACTORS:
        invalid("density_unit", scenario.density_unit, " | ".join(DENSITY_FACTORS))
    if scenario.boundary_mode not in ("area_weighted", "renormalized"):
        invalid("base_population.boundary_mode", scenario.boundary_mode, "area_weighted | renormalized")
    if scenario.population_source not in ("raster", "buildings"):
        invalid("base_population.source", scenario.population_source, "raster | buildings")
    if scenario.population_source == "buildings" or scenario.calibration:
        from .roof_population import parse_calibration

        try:
            parse_calibration(scenario.calibration or {})
        except ValueError as error:
            errors.append(message("scenario_invalid_parameter", detail=str(error)))
    if scenario.population_value_type not in ("density", "count"):
        invalid("base_population.value_type", scenario.population_value_type, "density | count")
    if scenario.extrapolation not in (CONSTANT, LINEAR):
        invalid("extrapolation", scenario.extrapolation, f"{CONSTANT} | {LINEAR}")
    if scenario.language not in available_languages():
        invalid("language", scenario.language, " | ".join(available_languages()))
    m = scenario.migration
    if m.policy not in POLICIES:
        invalid("migration.policy", m.policy, " | ".join(POLICIES))
    if int(m.tolerance) != m.tolerance or m.tolerance < 1:
        invalid("migration.tolerance", m.tolerance, "1, 2, 3…")
    if m.k < 1:
        invalid("migration.k", m.k, ">= 1")
    for i, exclusion in enumerate(scenario.exclusions):
        if exclusion.behaviour not in BEHAVIOURS:
            invalid(f"exclusions[{i}].behaviour", exclusion.behaviour, " | ".join(BEHAVIOURS))
        if exclusion.behaviour == OUTSIDE and exclusion.year is not None:
            errors.append(message("scenario_dated_outside", name=exclusion.name))
    for name in ("growth_rate", "dmax"):
        if name not in scenario.parameters and "csv" not in scenario.parameters:
            errors.append(message("scenario_missing_key", key=f"parameters.{name}"))
    try:
        scenario.parameter_tables() if "csv" not in scenario.parameters else None
    except ValueError as error:
        errors.append(message("scenario_invalid_parameter", detail=str(error)))
    for name, spec in scenario.parameters.items():
        for i, zone in enumerate(parameter_zone_inputs(spec)):
            if not zone.source or not zone.field:
                errors.append(message("scenario_missing_key", key=f"parameters.{name}.zones[{i}].source/field"))
    from .grid_layer import FORMATS

    if scenario.output_grid_layer not in FORMATS:
        invalid("output.grid_layer", scenario.output_grid_layer, " | ".join(FORMATS))
    errors.extend(_validate_strata(scenario.strata))
    for spec in scenario.indicators:
        from .indicators import REGISTRY

        if spec.type not in REGISTRY:
            invalid("indicators.type", spec.type, " | ".join(sorted(REGISTRY)))
        for name, value in spec.parameters.items():
            for i, zone in enumerate(parameter_zone_inputs(value)):
                if not zone.source or not zone.field:
                    errors.append(message("scenario_missing_key",
                                          key=f"indicators.{spec.type}.{name}.zones[{i}].source/field"))
        try:
            scenario.indicator_tables(spec)
        except ValueError as error:
            errors.append(message("scenario_invalid_parameter", detail=str(error)))
    return errors


ROAD_KEYS = ("source", "layer", "where", "field", "weights", "reach_m", "migration", "colonization", "min_neighbors",
             "threshold", "in_planned_mode")


def _roads(data: Any, errors: List[Message]) -> Optional[RoadSettings]:
    if data is None:
        return None
    if not isinstance(data, dict) or not data.get("source"):
        errors.append(message("scenario_missing_key", key="strata.roads.source"))
        return None
    unknown = set(data) - set(ROAD_KEYS)
    if unknown:
        errors.append(message("scenario_invalid_value", key="strata.roads", value=", ".join(sorted(unknown)),
                              expected=", ".join(ROAD_KEYS)))
    known = {k: v for k, v in data.items() if k in ROAD_KEYS}
    if "weights" in known:
        try:
            known["weights"] = {str(k): float(v) for k, v in (known["weights"] or {}).items()}
        except (TypeError, ValueError, AttributeError):
            errors.append(message("scenario_invalid_value", key="strata.roads.weights", value=str(known["weights"]),
                                  expected="{class: weight}"))
            known.pop("weights")
    return RoadSettings(**known)


def _validate_roads(roads: RoadSettings) -> List[Message]:
    errors: List[Message] = []

    def invalid(key: str, value: Any, expected: str) -> None:
        errors.append(message("scenario_invalid_value", key=f"strata.roads.{key}", value=str(value), expected=expected))

    if not isinstance(roads.reach_m, (int, float)) or roads.reach_m <= 0:
        invalid("reach_m", roads.reach_m, "> 0")
    if not isinstance(roads.min_neighbors, int) or not 0 <= roads.min_neighbors <= 8:
        invalid("min_neighbors", roads.min_neighbors, "0…8")
    if not isinstance(roads.threshold, (int, float)) or roads.threshold <= 0:
        invalid("threshold", roads.threshold, "> 0")
    for key, weight in roads.weights.items():
        if weight < 0:
            invalid(f"weights.{key}", weight, ">= 0")
    return errors


def _validate_strata(strata: StrataSettings) -> List[Message]:
    errors: List[Message] = []

    def invalid(key: str, value: Any, expected: str) -> None:
        errors.append(message("scenario_invalid_value", key=f"strata.{key}", value=str(value), expected=expected))

    if strata.mode not in STRATA_MODES:
        invalid("mode", strata.mode, " | ".join(STRATA_MODES))
    if not isinstance(strata.min_neighbors, int) or not 0 <= strata.min_neighbors <= 8:
        invalid("min_neighbors", strata.min_neighbors, "0…8")
    if not isinstance(strata.cell_membership_share, (int, float)) or not 0.5 <= strata.cell_membership_share <= 1:
        invalid("cell_membership_share", strata.cell_membership_share, "0.5…1")
    if strata.min_inflow_unit not in ("share_of_capacity", "inhabitants"):
        invalid("min_inflow_unit", strata.min_inflow_unit, "share_of_capacity | inhabitants")
    for name, rules in strata.classes.items():
        if rules.rank is not None and (not isinstance(rules.rank, int) or isinstance(rules.rank, bool)
                                       or rules.rank < 0):
            invalid(f"classes.{name}.rank", rules.rank, "0, 1, 2…")
    if not isinstance(strata.smoothing_passes, int) or not 0 <= strata.smoothing_passes <= 5:
        invalid("smoothing_passes", strata.smoothing_passes, "0…5")
    nuclei = strata.new_nuclei
    unknown = set(nuclei) - {"enabled", "stratum", "min_cells", "enclave_km2", "migration_share"}
    if unknown:
        invalid("new_nuclei", ", ".join(sorted(unknown)), "enabled, stratum, min_cells, enclave_km2, migration_share")
    if nuclei.get("enabled") and nuclei.get("stratum") not in strata.classes:
        invalid("new_nuclei.stratum", nuclei.get("stratum"), " | ".join(strata.classes) or "a class of strata.classes")
    if strata.free and not any(rules.rank is not None for rules in strata.classes.values()):
        errors.append(message("scenario_missing_key", key="strata.classes.<class>.rank"))
    if strata.roads is not None:
        errors.extend(_validate_roads(strata.roads))
    return errors


def is_connection(value: str) -> bool:
    """Database or service connection (``PG:…``, ``MSSQL:…``, ``https://…``) rather than a file path.

    A Windows drive (``C:\\…``) has a single letter before the colon.
    """
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]+:", value or ""))


PASSWORD = re.compile(r"\s*\bpassword\s*=\s*('[^']*'|\S+)", re.IGNORECASE)


def _without_passwords(value: Any) -> Any:
    """Scenario files never hold database passwords (they stay in QGIS or in ~/.pgpass)."""
    if isinstance(value, dict):
        return {k: _without_passwords(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_without_passwords(v) for v in value]
    if isinstance(value, str) and is_connection(value):
        return PASSWORD.sub("", value)
    return value


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(v) for v in value]
    return value
