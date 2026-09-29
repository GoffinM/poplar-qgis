"""Scenario file (JSON): every input and setting of a run (spec §2).

Paths are relative to the scenario file. Parameters are given as a single
value, per key (typology class or parameter zone, ``*`` for the default),
and optionally per pivot year::

    "growth_rate": {"*": {"2026": 3.0, "2040": 2.0}, "Urbain1": 4.0}

Loading checks the whole file and reports every problem at once, as
translatable messages (:class:`ScenarioError`).
"""

from __future__ import annotations

import json
import os
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
    csv: str
    recalibrate: bool = False


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
    language: str = DEFAULT_LANGUAGE
    cell_size: float = 250.0
    density_unit: str = "hab/km2"
    boundary_mode: str = "area_weighted"
    population_value_type: str = "density"
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
    extrapolation: str = CONSTANT
    base_dir: str = ""

    # --- paths --------------------------------------------------------------------

    def path(self, value: str) -> str:
        return value if os.path.isabs(value) else os.path.normpath(os.path.join(self.base_dir, value))

    # --- parameters ---------------------------------------------------------------

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
                                   "value_type": data.pop("population_value_type")}
        data["output"] = {"directory": data.pop("output_directory")}
        return _drop_none(data)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)


def parse_parameter(name: str, spec: Any, extrapolation: str = CONSTANT) -> ParameterTable:
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
        projections = Projections(required(data["projections"], "csv", "projections.") or "",
                                  bool(data["projections"].get("recalibrate", False)))
    indicators = [IndicatorSpec(item.get("type", ""), item.get("parameters", {})) for item in data.get("indicators", [])]

    if errors or time is None or study_area is None or typology is None:
        raise ScenarioError(errors or [message("scenario_missing_key", key="time")])

    scenario = Scenario(
        study_area=study_area, typology=typology, base_population_raster=raster, time=time,
        parameters=parameters, name=data.get("name", ""), language=data.get("language", DEFAULT_LANGUAGE),
        cell_size=float(data.get("cell_size", 250.0)), density_unit=data.get("density_unit", "hab/km2"),
        boundary_mode=base_population.get("boundary_mode", "area_weighted"),
        population_value_type=base_population.get("value_type", "density"), crs=data.get("crs"),
        parameter_zones=vector(data.get("parameter_zones"), "parameter_zones", needs_field=True),
        admin_units=vector(data.get("admin_units"), "admin_units", needs_field=True),
        exclusions=exclusions, projections=projections, migration=migration, indicators=indicators,
        output_directory=(data.get("output") or {}).get("directory", "outputs"),
        extrapolation=data.get("extrapolation", CONSTANT), base_dir=base_dir,
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
    for spec in scenario.indicators:
        from .indicators import REGISTRY

        if spec.type not in REGISTRY:
            invalid("indicators.type", spec.type, " | ".join(sorted(REGISTRY)))
    return errors


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(v) for v in value]
    return value
