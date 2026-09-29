"""Building footprints: reading at scale and assignment to units (spec §3 bis).

A building is reduced to a point (its centroid, or a point on its surface)
and its roof area; polygons are never kept in memory. Sources are read in
batches with a spatial filter on the study extent.
"""

from __future__ import annotations

import csv
import gzip
import io
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple, Union

import numpy as np
from osgeo import ogr, osr

from ._gdal import gdal_exceptions, srs_from_epsg, srs_from_wkt
from .grid import Extent
from .units import Units

OPEN_BUILDINGS_COLUMNS = ("latitude", "longitude", "area_in_meters", "confidence")


@dataclass
class Buildings:
    x: np.ndarray
    y: np.ndarray
    area_m2: np.ndarray
    confidence: Optional[np.ndarray] = None

    def __len__(self) -> int:
        return len(self.x)

    @classmethod
    def concatenate(cls, parts: Sequence["Buildings"]) -> "Buildings":
        if not parts:
            return cls(np.empty(0), np.empty(0), np.empty(0))
        confidence = None
        if all(p.confidence is not None for p in parts):
            confidence = np.concatenate([p.confidence for p in parts])
        return cls(
            np.concatenate([p.x for p in parts]),
            np.concatenate([p.y for p in parts]),
            np.concatenate([p.area_m2 for p in parts]),
            confidence,
        )

    def subset(self, mask: np.ndarray) -> "Buildings":
        return Buildings(
            self.x[mask], self.y[mask], self.area_m2[mask],
            None if self.confidence is None else self.confidence[mask],
        )


def read_footprints(
    source: str,
    target_crs_wkt: str,
    layer: Optional[str] = None,
    extent: Optional[Extent] = None,
    area_field: Optional[str] = None,
    point_on_surface: bool = False,
    where: Optional[str] = None,
    batch_size: int = 100_000,
) -> Buildings:
    """Read footprints from any OGR source (GeoPackage, shapefile, PostGIS, WFS...).

    Polygons are reprojected to the grid CRS before their area is measured.
    For a layer of points, ``area_field`` gives the roof area in m2.
    ``extent`` (in the grid CRS) is applied as a spatial filter at the source.
    """
    with gdal_exceptions():
        datasource = ogr.Open(source)
        ogr_layer = datasource.GetLayerByName(layer) if layer else datasource.GetLayer(0)
        if where:
            ogr_layer.SetAttributeFilter(where)
        target_srs = srs_from_wkt(target_crs_wkt)
        source_srs = ogr_layer.GetSpatialRef()
        transform = None
        if source_srs is not None:
            source_srs = source_srs.Clone()
            source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            if not source_srs.IsSame(target_srs):
                transform = osr.CoordinateTransformation(source_srs, target_srs)
        if extent is not None:
            bounds = extent
            if transform is not None:
                back = osr.CoordinateTransformation(target_srs, source_srs)
                bounds = back.TransformBounds(*extent, 21)
            ogr_layer.SetSpatialFilterRect(*bounds)

        parts: List[Buildings] = []
        xs: List[float] = []
        ys: List[float] = []
        areas: List[float] = []
        for feature in ogr_layer:
            geometry = feature.GetGeometryRef()
            if geometry is None or geometry.IsEmpty():
                continue
            if transform is not None:
                geometry = geometry.Clone()
                geometry.Transform(transform)
            if geometry.GetDimension() == 2:
                point = geometry.PointOnSurface() if point_on_surface else geometry.Centroid()
                area = feature.GetFieldAsDouble(area_field) if area_field else geometry.GetArea()
            else:
                if not area_field:
                    raise ValueError(f"{source}: a layer of points needs an area field")
                point = geometry
                area = feature.GetFieldAsDouble(area_field)
            xs.append(point.GetX())
            ys.append(point.GetY())
            areas.append(area)
            if len(xs) >= batch_size:
                parts.append(Buildings(np.array(xs), np.array(ys), np.array(areas)))
                xs, ys, areas = [], [], []
        if xs:
            parts.append(Buildings(np.array(xs), np.array(ys), np.array(areas)))
    buildings = Buildings.concatenate(parts)
    return _clip(buildings, extent)


def read_open_buildings_csv(
    paths: Union[str, Sequence[str]],
    target_crs_wkt: str,
    extent: Optional[Extent] = None,
    min_confidence: Optional[float] = None,
    columns: Tuple[str, str, str, str] = OPEN_BUILDINGS_COLUMNS,
    batch_size: int = 200_000,
) -> Buildings:
    """Read Google Open Buildings tiles (CSV, optionally gzip-compressed).

    Only the centroid coordinates, the area and the confidence are read, so
    the polygons themselves are never decoded. Coordinates are WGS 84
    longitude/latitude and are projected to the grid CRS in batches.
    """
    if isinstance(paths, str):
        paths = [paths]
    lat_col, lon_col, area_col, conf_col = columns
    with gdal_exceptions():
        wgs84 = srs_from_epsg(4326)
        target_srs = srs_from_wkt(target_crs_wkt)
        transform = osr.CoordinateTransformation(wgs84, target_srs)
        lonlat_bounds = None
        if extent is not None:
            back = osr.CoordinateTransformation(target_srs, wgs84)
            lonlat_bounds = back.TransformBounds(*extent, 21)

    parts: List[Buildings] = []
    for path in paths:
        with _open_text(path) as handle:
            reader = csv.reader(handle)
            header = next(reader)
            i_lat, i_lon, i_area = header.index(lat_col), header.index(lon_col), header.index(area_col)
            i_conf = header.index(conf_col) if conf_col in header else None
            batch: List[Tuple[float, float, float, float]] = []
            for row in reader:
                lon, lat = float(row[i_lon]), float(row[i_lat])
                if lonlat_bounds is not None and not (
                    lonlat_bounds[0] <= lon <= lonlat_bounds[2] and lonlat_bounds[1] <= lat <= lonlat_bounds[3]
                ):
                    continue
                conf = float(row[i_conf]) if i_conf is not None else np.nan
                if min_confidence is not None and conf < min_confidence:
                    continue
                batch.append((lon, lat, float(row[i_area]), conf))
                if len(batch) >= batch_size:
                    parts.append(_project_batch(batch, transform))
                    batch = []
            if batch:
                parts.append(_project_batch(batch, transform))
    return _clip(Buildings.concatenate(parts), extent)


def _project_batch(batch, transform) -> Buildings:
    data = np.array(batch, dtype=np.float64)
    with gdal_exceptions():
        projected = np.array(transform.TransformPoints(data[:, :2].tolist()))
    return Buildings(projected[:, 0], projected[:, 1], data[:, 2], data[:, 3].astype(np.float32))


def _open_text(path: str) -> io.TextIOBase:
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", newline="")
    return open(path, encoding="utf-8", newline="")


def _clip(buildings: Buildings, extent: Optional[Extent]) -> Buildings:
    if extent is None or len(buildings) == 0:
        return buildings
    xmin, ymin, xmax, ymax = extent
    mask = (buildings.x >= xmin) & (buildings.x <= xmax) & (buildings.y >= ymin) & (buildings.y <= ymax)
    return buildings.subset(mask)


def assign_to_units(buildings: Buildings, units: Units) -> np.ndarray:
    """Index of the unit that contains each building point (-1 if none).

    Points in a whole cell are assigned by index arithmetic alone; only the
    points that fall in a split cell need a point-in-polygon test.
    """
    grid = units.grid
    row, col, inside = grid.locate(buildings.x, buildings.y)
    result = np.full(len(buildings), -1, dtype=np.int64)
    cell = np.where(inside, row * grid.ncols + col, -1)
    first = np.searchsorted(units.cell_id, cell, side="left")
    last = np.searchsorted(units.cell_id, cell, side="right")
    count = np.where(inside, last - first, 0)

    first_safe = np.minimum(first, len(units) - 1)
    simple = (count == 1) & units.whole_cell[first_safe]
    result[simple] = first[simple]

    to_test = np.flatnonzero((count >= 1) & ~simple)
    with gdal_exceptions():
        point = ogr.Geometry(ogr.wkbPoint)
        for i in to_test:
            point.SetPoint_2D(0, float(buildings.x[i]), float(buildings.y[i]))
            for k in range(first[i], last[i]):
                if units.geometry(k).Intersects(point):
                    result[i] = k
                    break
    return result


def per_unit_totals(unit_index: np.ndarray, values: np.ndarray, n_units: int) -> np.ndarray:
    """Sum ``values`` per unit, ignoring unassigned buildings."""
    mask = unit_index >= 0
    return np.bincount(unit_index[mask], weights=values[mask], minlength=n_units)
