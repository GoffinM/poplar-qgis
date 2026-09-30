"""Zone of a download: the strata (or any polygons), widened by a margin, kept inside an optional limit.

The margin reaches a little beyond the study area (areas that could be seen as
room for extension may already be densely built); the limit (a national
boundary, for example) stops it at a border.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from osgeo import gdal, ogr, osr

from .._gdal import gdal_exceptions, srs_from_epsg, srs_from_wkt
from ..vector_io import memory_datasource, polygonal_part, read_features, union_all

MAX_MASK_CELLS = 40_000_000


class EmptyZone(ValueError):
    """The zone has no area (no polygon, or nothing left inside the limit)."""


@dataclass
class ZoneLayer:
    source: str
    layer: Optional[str] = None
    where: Optional[str] = None


@dataclass
class DownloadZone:
    geometry: ogr.Geometry
    """MultiPolygon in ``crs_wkt`` (metres)."""
    crs_wkt: str
    margin_m: float = 0.0
    limited: bool = False

    @classmethod
    def from_layers(cls, area: ZoneLayer, crs_wkt: str, margin_m: float = 0.0,
                    limit: Optional[ZoneLayer] = None) -> "DownloadZone":
        geometry = union_all(f.geometry for f in read_features(area.source, area.layer, area.where, crs_wkt))
        if geometry is None:
            raise EmptyZone(area.source)
        with gdal_exceptions():
            if margin_m > 0:
                geometry = polygonal_part(geometry.Buffer(margin_m))
            if limit is not None:
                border = union_all(f.geometry for f in read_features(limit.source, limit.layer, limit.where, crs_wkt))
                geometry = polygonal_part(geometry.Intersection(border)) if border is not None else None
        if geometry is None:
            raise EmptyZone(area.source)
        return cls(geometry, crs_wkt, margin_m, limit is not None)

    def area_km2(self) -> float:
        return self.geometry.GetArea() / 1e6

    def lonlat_bounds(self) -> Tuple[float, float, float, float]:
        with gdal_exceptions():
            transform = osr.CoordinateTransformation(srs_from_wkt(self.crs_wkt), srs_from_epsg(4326))
            xmin, xmax, ymin, ymax = self.geometry.GetEnvelope()
            return transform.TransformBounds(xmin, ymin, xmax, ymax, 21)

    def mask(self) -> "ZoneMask":
        return ZoneMask(self)


class ZoneMask:
    """The zone burnt into a grid, to test millions of points at numpy speed.

    Points in cells crossed by the outline of the zone are tested exactly
    against the polygons; the others are decided by their cell alone.
    """

    def __init__(self, zone: DownloadZone):
        xmin, xmax, ymin, ymax = zone.geometry.GetEnvelope()
        pixel = max(25.0, float(np.sqrt((xmax - xmin) * (ymax - ymin) / MAX_MASK_CELLS)))
        self.xmin, self.ymax, self.pixel = xmin - pixel, ymax + pixel, pixel
        width = int(np.ceil((xmax - xmin) / pixel)) + 2
        height = int(np.ceil((ymax - ymin) / pixel)) + 2
        with gdal_exceptions():
            raster = gdal.GetDriverByName("MEM").Create("", width, height, 1, gdal.GDT_Byte)
            raster.SetGeoTransform((self.xmin, pixel, 0, self.ymax, 0, -pixel))
            raster.SetProjection(zone.crs_wkt)
            vectors = memory_datasource()
            layer = vectors.CreateLayer("zone", srs_from_wkt(zone.crs_wkt), ogr.wkbMultiPolygon)
            feature = ogr.Feature(layer.GetLayerDefn())
            feature.SetGeometry(zone.geometry)
            layer.CreateFeature(feature)
            gdal.RasterizeLayer(raster, [1], layer, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
            self.cells = raster.GetRasterBand(1).ReadAsArray().astype(bool)
            outline = zone.geometry.GetBoundary()
            edge_layer = vectors.CreateLayer("outline", srs_from_wkt(zone.crs_wkt), ogr.wkbMultiLineString)
            edge_feature = ogr.Feature(edge_layer.GetLayerDefn())
            edge_feature.SetGeometry(outline)
            edge_layer.CreateFeature(edge_feature)
            raster.GetRasterBand(1).Fill(0)
            gdal.RasterizeLayer(raster, [1], edge_layer, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
            self.edges = raster.GetRasterBand(1).ReadAsArray().astype(bool)
        self.geometry = zone.geometry

    def contains(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        col = np.floor((x - self.xmin) / self.pixel).astype(np.int64)
        row = np.floor((self.ymax - y) / self.pixel).astype(np.int64)
        inside = (col >= 0) & (row >= 0) & (col < self.cells.shape[1]) & (row < self.cells.shape[0])
        result = np.zeros(len(x), dtype=bool)
        result[inside] = self.cells[row[inside], col[inside]]
        edge = np.zeros(len(x), dtype=bool)
        edge[inside] = self.edges[row[inside], col[inside]]
        with gdal_exceptions():
            point = ogr.Geometry(ogr.wkbPoint)
            for i in np.flatnonzero(edge):
                point.SetPoint_2D(0, float(x[i]), float(y[i]))
                result[i] = self.geometry.Intersects(point)
        return result
