"""Attraction of the roads (plan_demande_et_routes.md, B; P14: fronts that are not rings).

A place near a road attracts migrants and is urbanised first. Its attractiveness is

    a = 1 + max over the road classes of  weight × exp(− distance / reach)

with the distance to the nearest road of each class (decision B-d: national 1, provincial 0.6, other 0.3,
reach 500 m). It is 1 far from any road, 2 on a national road of weight 1. It acts on:

1. the migration: the distance a migrant « feels » is the real distance divided by the attractiveness
   of the arrival unit (:func:`engine.migration.migrate`, ``attraction``);
2. the colonisation: a cell whose attractiveness reaches ``1 + threshold`` needs fewer neighbouring cells
   of the colonising polygon (``min_neighbors`` of the road settings, 2 instead of 3).

Distances are measured from points every :data:`STEP_M` metres along the lines (error under half a step).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from osgeo import ogr, osr
from scipy.spatial import cKDTree

from ._gdal import gdal_exceptions, srs_from_wkt

STEP_M = 20.0
MAIN_WEIGHT = 0.5
"""Roads of at least this weight are « main roads » for the plausibility indicators."""


class RoadLayerError(ValueError):
    """The road layer cannot be read, or holds no line."""


@dataclass
class RoadAttraction:
    unit: np.ndarray
    """Attractiveness of each calculation unit (at its centroid)."""
    cell: np.ndarray
    """Attractiveness of each cell (at its centre), as a (rows, cols) raster; NaN outside the grid's units."""
    main_distance: np.ndarray
    """Distance of each cell centre to the nearest main road (weight >= MAIN_WEIGHT), (rows, cols); inf if none."""
    lines: int
    length_km: Dict[str, float]
    """Length of road read per class (inside the extent used)."""
    unknown_classes: List[str]
    """Values of the class field that have no weight (they count for the weight of ``*``, 0 by default)."""


def weight_of(value, weights: Dict[str, float], has_field: bool) -> float:
    if not has_field:
        return float(weights.get("*", 1.0))
    key = "" if value is None else str(value)
    return float(weights.get(key, weights.get("*", 0.0)))


def read_road_points(source: str, layer: Optional[str], where: Optional[str], field: Optional[str],
                     weights: Dict[str, float], crs_wkt: str, extent: Tuple[float, float, float, float],
                     step: float = STEP_M):
    """Points along the roads (in ``crs_wkt``) grouped by weight, with the lengths and unknown classes."""
    xmin, ymin, xmax, ymax = extent
    window = ogr.CreateGeometryFromWkt(
        f"POLYGON(({xmin} {ymin},{xmax} {ymin},{xmax} {ymax},{xmin} {ymax},{xmin} {ymin}))")
    by_weight: Dict[float, List[np.ndarray]] = {}
    lengths: Dict[str, float] = {}
    unknown = set()
    count = 0
    with gdal_exceptions():
        datasource = ogr.Open(source)
        if datasource is None:
            raise RoadLayerError(source)
        ogr_layer = datasource.GetLayerByName(layer) if layer else datasource.GetLayer(0)
        if ogr_layer is None:
            raise RoadLayerError(f"{source}: no layer {layer!r}")
        if where:
            ogr_layer.SetAttributeFilter(where)
        definition = ogr_layer.GetLayerDefn()
        names = [definition.GetFieldDefn(i).GetName() for i in range(definition.GetFieldCount())]
        if field and field not in names:
            raise RoadLayerError(f"{source}: no field {field!r}")
        transform = None
        source_srs = ogr_layer.GetSpatialRef()
        if source_srs is not None:
            source_srs = source_srs.Clone()
            source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            target = srs_from_wkt(crs_wkt)
            if not source_srs.IsSame(target):
                transform = osr.CoordinateTransformation(source_srs, target)
        for feature in ogr_layer:
            geometry = feature.GetGeometryRef()
            if geometry is None or geometry.IsEmpty() or geometry.GetDimension() != 1:
                continue
            value = feature.GetField(field) if field else None
            weight = weight_of(value, weights, bool(field))
            if field and str(value if value is not None else "") not in weights and "*" not in weights:
                unknown.add(str(value))
            geometry = geometry.Clone()
            if transform is not None:
                geometry.Transform(transform)
            geometry = geometry.Intersection(window)
            if geometry is None or geometry.IsEmpty():
                continue
            count += 1
            label = str(value) if field else "*"
            lengths[label] = lengths.get(label, 0.0) + geometry.Length() / 1000
            if weight <= 0:
                continue
            geometry.Segmentize(step)
            points = _vertices(geometry)
            if len(points):
                by_weight.setdefault(weight, []).append(points)
    return ({w: np.concatenate(p) for w, p in by_weight.items()}, count,
            {k: round(v, 2) for k, v in sorted(lengths.items())}, sorted(unknown))


def _vertices(geometry: ogr.Geometry) -> np.ndarray:
    if geometry.GetGeometryCount() > 0 and geometry.GetGeometryType() not in (ogr.wkbLineString,
                                                                                 ogr.wkbLineString25D):
        parts = [_vertices(geometry.GetGeometryRef(i)) for i in range(geometry.GetGeometryCount())]
        parts = [p for p in parts if len(p)]
        return np.concatenate(parts) if parts else np.empty((0, 2))
    if geometry.GetDimension() != 1:
        return np.empty((0, 2))
    return np.array([geometry.GetPoint_2D(i) for i in range(geometry.GetPointCount())], dtype=np.float64)


def attractiveness(x: np.ndarray, y: np.ndarray, points: Dict[float, np.ndarray], reach: float) -> np.ndarray:
    """``1 + max(weight × exp(−d / reach))`` at the given places."""
    result = np.ones(len(x))
    xy = np.column_stack([x, y])
    for weight, where in points.items():
        distance, _ = cKDTree(where).query(xy, distance_upper_bound=reach * 30)
        result = np.maximum(result, 1.0 + weight * np.exp(-distance / reach))
    return result


def nearest_distance(x: np.ndarray, y: np.ndarray, points: Dict[float, np.ndarray], min_weight: float) -> np.ndarray:
    chosen = [p for w, p in points.items() if w >= min_weight - 1e-12]
    if not chosen:
        return np.full(len(x), np.inf)
    distance, _ = cKDTree(np.concatenate(chosen)).query(np.column_stack([x, y]))
    return distance


def road_attraction(units, settings, path: str) -> RoadAttraction:
    """Attractiveness of the units and of the cells of a run, from the road settings of its scenario."""
    grid = units.grid
    margin = settings.reach_m * 10
    extent = (grid.x0 - margin, grid.y0 - grid.nrows * grid.cell_size - margin,
              grid.x0 + grid.ncols * grid.cell_size + margin, grid.y0 + margin)
    points, count, lengths, unknown = read_road_points(path, settings.layer, settings.where, settings.field,
                                                       settings.weights, grid.crs_wkt, extent)
    unit = attractiveness(units.cx, units.cy, points, settings.reach_m)
    rows, cols = np.divmod(np.arange(grid.ncells), grid.ncols)
    cx = grid.x0 + (cols + 0.5) * grid.cell_size
    cy = grid.y0 - (rows + 0.5) * grid.cell_size
    cell = attractiveness(cx, cy, points, settings.reach_m).reshape(grid.nrows, grid.ncols)
    present = np.zeros(grid.ncells, dtype=bool)
    present[units.cell_id] = True
    cell = np.where(present.reshape(cell.shape), cell, np.nan)
    main = nearest_distance(cx, cy, points, MAIN_WEIGHT).reshape(grid.nrows, grid.ncols)
    return RoadAttraction(unit, cell, main, count, lengths, unknown)
