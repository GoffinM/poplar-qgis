"""Built-up patches as the starting polygons of the free strata mode (decision D1, plan §15).

The typology often gives administrative limits (a whole urban commune), not the built-up area: in free
mode the town then fills its commune and never spills over. This step finds the dense patches of the
starting population and writes a new typology layer:

1. density of each 250 m cell = starting population of the scenario / useful area;
2. dense cells: density at least ``density_threshold`` (1 500 hab/km², "urban centre" of the Degree of
   Urbanisation, UN and Eurostat);
3. smoothing, two passes at most: holes surrounded by dense cells are filled, and a cell with at least
   5 dense neighbours out of 8 becomes dense (Eurostat's majority rule);
4. patches: dense cells touching by a side; a patch is kept if it has ``min_population`` inhabitants
   (5 000); with ``secondary_min_population``, smaller patches above that size are kept as a second level;
5. classes: patches mostly inside the urban limits take the urban class, the others the secondary urban
   class (decision Q-b: a dense village outside the urban commune is urban de facto); the rest of the
   urban limits becomes ``Transition``; everything else keeps its class.

Written once (decision Q-d), so that it can be looked at, edited in QGIS and shared by the two modes:
``typologie_taches.gpkg``, a copy of the scenario that uses it (ranks, parameters of the new classes,
decision Q-c: Transition takes the maximum density of the rural class and the other parameters of the
urban class) and ``typologie_taches.json`` (what was found).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from osgeo import ogr
from scipy import ndimage

from ._gdal import gdal_exceptions, srs_from_wkt
from .scenario import load_scenario
from .vector_io import polygonal_part, union_all

LAYER = "typologie"
GPKG = "typologie_taches.gpkg"
REPORT = "typologie_taches.json"
TRANSITION = "Transition"
EIGHT = np.ones((3, 3), dtype=bool)
FOUR = ndimage.generate_binary_structure(2, 1)


@dataclass
class PatchRules:
    density_threshold: float = 1500.0
    """hab/km² (decision Q-a)."""
    min_population: float = 5000.0
    secondary_min_population: Optional[float] = None
    """Second level of smaller patches (for example 2 000 inhabitants); off by default (Q-a)."""
    urban_classes: Optional[List[str]] = None
    """Classes of the typology that are urban limits; by default the class with the highest starting density."""
    secondary_class: str = "Urbain2"
    transition_class: str = TRANSITION
    inside_only: bool = False
    """Keep only the patches inside the urban limits (the other choice of Q-b)."""
    smoothing_passes: int = 2


@dataclass
class Patch:
    id: int
    stratum: str
    cells: int
    area_km2: float
    population: float
    inside_share: float
    """Share of its population inside the urban limits."""


@dataclass
class PatchResult:
    classes: np.ndarray
    """Class of each cell (raster of strings, '' outside the study area)."""
    patch_class: Optional[np.ndarray] = None
    """Class of the patch cells only ('' elsewhere): what is drawn as patches."""
    patches: List[Patch] = field(default_factory=list)
    urban_classes: List[str] = field(default_factory=list)
    density: Optional[np.ndarray] = None


def find_patches(units, population: np.ndarray, rules: PatchRules) -> PatchResult:
    """Dense patches of the starting population and the class of each cell (pure numpy: no file)."""
    area = units.per_cell(units.area_km2)
    people = units.per_cell(population)
    inside = area > 0
    density = np.where(inside, people / np.where(inside, area, 1.0), 0.0)
    classes = np.array(units.values("class"), dtype=object)
    names = sorted({c for c in classes if c is not None})
    urban = rules.urban_classes or [_densest(units, population, classes, names)]
    urban_area = units.per_cell(np.where(np.isin(classes, urban), units.area_km2, 0.0))
    urban_cells = inside & (urban_area >= 0.5 * np.where(inside, area, 1.0))

    dense = inside & (density >= rules.density_threshold)
    for _ in range(max(0, rules.smoothing_passes)):
        before = dense.copy()
        dense = ndimage.binary_fill_holes(dense) & inside
        neighbours = ndimage.convolve(dense.astype(int), EIGHT.astype(int), mode="constant") - dense
        dense |= inside & (neighbours >= 5)
        if np.array_equal(before, dense):
            break

    labels, count = ndimage.label(dense, structure=FOUR)
    index = np.arange(1, count + 1)
    populations = ndimage.sum(people, labels, index) if count else np.zeros(0)
    inside_people = ndimage.sum(np.where(urban_cells, people, 0.0), labels, index) if count else np.zeros(0)
    cell_class = np.full(area.shape, "", dtype=object)
    majority = _majority_class(units, classes)
    cell_class[inside] = majority[inside]
    cell_class[urban_cells] = rules.transition_class
    patch_class = np.full(area.shape, "", dtype=object)
    patches = []
    floor = rules.secondary_min_population if rules.secondary_min_population is not None else rules.min_population
    for label, total, within in zip(index, populations, inside_people):
        if total < floor:
            continue
        share = float(within / total) if total > 0 else 0.0
        if rules.inside_only and share < 0.5:
            continue
        cells = labels == label
        if rules.inside_only:
            cells &= urban_cells
        stratum = urban[0] if total >= rules.min_population and share >= 0.5 else rules.secondary_class
        cell_class[cells] = stratum
        patch_class[cells] = stratum
        patches.append(Patch(len(patches), stratum, int(cells.sum()), float(area[cells].sum()),
                             float(people[cells].sum()), share))
    return PatchResult(cell_class, patch_class, patches, list(urban), density)


def _densest(units, population, classes, names) -> str:
    best, value = names[0], -1.0
    for name in names:
        members = classes == name
        surface = units.area_km2[members].sum()
        density = population[members].sum() / surface if surface > 0 else 0.0
        if density > value:
            best, value = name, density
    return best


def _majority_class(units, classes) -> np.ndarray:
    """Class covering the largest area of each cell, its pieces added up."""
    names = sorted({c for c in classes if c is not None})
    best = np.full(units.grid.ncells, "", dtype=object)
    best_area = np.zeros(units.grid.ncells)
    for name in names:
        area = np.bincount(units.cell_id, weights=np.where(classes == name, units.area_km2, 0.0),
                           minlength=units.grid.ncells)
        better = area > best_area
        best[better] = name
        best_area[better] = area[better]
    return best.reshape(units.grid.nrows, units.grid.ncols)


# --- files ---------------------------------------------------------------------------------------


def prepare(scenario_path: str, rules: PatchRules = PatchRules(), output: Optional[str] = None) -> Dict[str, str]:
    """Write the patch typology, the scenario copy and the report next to the scenario (or in ``output``)."""
    from .simulation import _Model

    scenario = load_scenario(scenario_path)
    model = _Model.load(scenario)
    units = model.units
    result = find_patches(units, model.p0, rules)
    folder = output or os.path.dirname(os.path.abspath(scenario_path))
    os.makedirs(folder, exist_ok=True)
    gpkg = os.path.join(folder, GPKG)
    crs = units.grid.crs_wkt
    study = union_all(f.geometry for f in _features(scenario, scenario.study_area, crs))
    typology = _features(scenario, scenario.typology, crs)
    _write_typology(gpkg, units.grid, study, typology, scenario.typology.field, result, rules)
    with open(scenario_path, encoding="utf-8") as handle:
        data = json.load(handle)
    copy = scenario_copy(data, os.path.relpath(gpkg, os.path.dirname(os.path.abspath(scenario_path)))
                         if output is None else gpkg, scenario, result, rules)
    base, _ = os.path.splitext(os.path.basename(scenario_path))
    copy_path = os.path.join(os.path.dirname(os.path.abspath(scenario_path)) if output is None else folder,
                             f"{base}_taches.json")
    if output is not None:                        # paths of the copy stay valid from its new folder
        copy = _absolute_paths(copy, os.path.dirname(os.path.abspath(scenario_path)))
    with open(copy_path, "w", encoding="utf-8") as handle:
        json.dump(copy, handle, ensure_ascii=False, indent=2)
    report_path = os.path.join(folder, REPORT)
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump({"rules": asdict(rules), "urban_classes": result.urban_classes,
                   "patches": [asdict(p) for p in result.patches],
                   "outside_urban_limits": [p.id for p in result.patches if p.inside_share < 0.5]},
                  handle, ensure_ascii=False, indent=2)
    return {"typology": gpkg, "scenario": copy_path, "report": report_path}


def _features(scenario, spec, crs):
    from .vector_io import read_features

    return read_features(scenario.path(spec.source), spec.layer, spec.where, target_crs_wkt=crs)


def _write_typology(path, grid, study, typology, field_name, result: PatchResult, rules: PatchRules) -> None:
    """Patches as cell outlines (inside the study area); the original polygons, minus the patches, keep
    their class, or become Transition when they were urban limits."""
    from .polygon_outputs import _vectorise

    stratum_codes = {name: i for i, name in enumerate(sorted({p.stratum for p in result.patches}))}
    raster = np.full(result.classes.shape, -1, dtype=np.int64)
    for name, code in stratum_codes.items():
        raster[result.patch_class == name] = code
    # Not cut by the study area: the cells are cut anyway when the scenario runs, and cutting here could split
    # one patch into pieces touching by a corner, hence two polygons at the start (P2).
    patch_shapes = {code: polygonal_part(geometry) for code, geometry in _vectorise(raster, grid).items()}
    patches_union = union_all([g for g in patch_shapes.values() if g is not None])
    with gdal_exceptions():
        driver = ogr.GetDriverByName("GPKG")
        if os.path.exists(path):
            driver.DeleteDataSource(path)
        datasource = driver.CreateDataSource(path)
        layer = datasource.CreateLayer(LAYER, srs_from_wkt(grid.crs_wkt), ogr.wkbMultiPolygon)
        layer.CreateField(ogr.FieldDefn(field_name, ogr.OFTString))
        layer.CreateField(ogr.FieldDefn("origine", ogr.OFTString))

        def add(geometry, value, origin):
            geometry = polygonal_part(geometry)
            if geometry is None:
                return
            feature = ogr.Feature(layer.GetLayerDefn())
            feature.SetGeometry(geometry)
            feature.SetField(field_name, value)
            feature.SetField("origine", origin)
            layer.CreateFeature(feature)

        for name, code in stratum_codes.items():
            if patch_shapes.get(code) is not None:
                add(patch_shapes[code], name, "tache")
        for feature in typology:
            value = str(feature.attributes[field_name])
            geometry = feature.geometry
            if patches_union is not None:
                geometry = geometry.Difference(patches_union)
            if value in result.urban_classes:
                add(geometry, rules.transition_class, "transition")
            else:
                add(geometry, value, "typologie")
        datasource = None


def scenario_copy(data: Dict[str, Any], typology_source: str, scenario, result: PatchResult,
                  rules: PatchRules) -> Dict[str, Any]:
    """The scenario on the patch typology, in free mode, with ranks and the parameters of the new classes."""
    copy = json.loads(json.dumps(data))
    old = (scenario.path(scenario.typology.source), scenario.typology.layer, scenario.typology.where,
           scenario.typology.field)
    copy["typology"] = {"source": typology_source, "layer": LAYER, "field": scenario.typology.field}
    copy["name"] = f"{data.get('name', '')} – taches bâties".strip(" –")
    output = dict(copy.get("output") or {})
    output["directory"] = (output.get("directory") or "outputs") + "_taches"
    copy["output"] = output
    urban = result.urban_classes[0]
    classes = sorted({c for c in np.unique(result.classes) if c})
    rural = [c for c in classes if c not in (urban, rules.secondary_class, rules.transition_class)]
    strata = dict(copy.get("strata") or {})
    ranks = dict(strata.get("classes") or {})
    for name in rural:                                  # rural classes stay below the transition
        rules_of = dict(ranks.get(name) or {})
        rank = rules_of.get("rank")
        rules_of["rank"] = 1 if rank is None or rank >= 2 else rank
        ranks[name] = rules_of
    for name, rank in ((rules.transition_class, 2), (rules.secondary_class, 3), (urban, 4)):
        ranks[name] = {**dict(ranks.get(name) or {}), "rank": rank}
    strata.update({"mode": "free", "classes": ranks, "urban_rank": 3})   # the patches are urban, not the transition
    copy["strata"] = strata

    def fill(values: Dict[str, Any], name: str) -> None:
        """Values of the new classes, copied from the existing ones (Q-c)."""
        if not isinstance(values, dict) or not any(k in values for k in [urban, *rural]):
            return                                      # a single value or "*": nothing to add
        source_rural = next((values[r] for r in rural if r in values), values.get("*"))
        source_urban = values.get(urban, values.get("*"))
        if rules.transition_class not in values:
            values[rules.transition_class] = source_rural if name == "dmax" else source_urban
        if rules.secondary_class not in values and source_urban is not None:
            values[rules.secondary_class] = source_urban

    def repoint(spec: Dict[str, Any]) -> None:
        zones = spec.get("zones")
        zones = zones if isinstance(zones, list) else [zones] if isinstance(zones, dict) else []
        for zone in zones:
            key = (scenario.path(zone.get("source", "")), zone.get("layer"), zone.get("where"), zone.get("field"))
            if key == old:                              # linked to the typology: now the patch typology
                zone.update({"source": typology_source, "layer": LAYER})
                zone.pop("where", None)

    for name, spec in (copy.get("parameters") or {}).items():
        if isinstance(spec, dict) and "values" in spec:
            repoint(spec)
            fill(spec["values"], name)
        else:
            fill(spec, name)
    for indicator in copy.get("indicators") or []:
        for name, spec in (indicator.get("parameters") or {}).items():
            if isinstance(spec, dict) and "values" in spec:
                repoint(spec)
                fill(spec["values"], name)
            else:
                fill(spec, name)
    return copy


def _absolute_paths(value: Any, base: str) -> Any:
    keys = ("source", "raster", "file", "csv")
    if isinstance(value, dict):
        return {k: (os.path.normpath(os.path.join(base, v)) if k in keys and isinstance(v, str) and v
                    and not os.path.isabs(v) and ":" not in v[:3] else _absolute_paths(v, base))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_absolute_paths(v, base) for v in value]
    return value
