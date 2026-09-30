"""Vector reading helpers (any OGR source: shapefile, GeoPackage, PostGIS, WFS...)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from osgeo import gdal, ogr, osr

from ._gdal import gdal_exceptions, srs_from_wkt


@dataclass
class Feature:
    geometry: ogr.Geometry
    attributes: Dict[str, Any] = field(default_factory=dict)


def memory_datasource() -> ogr.DataSource:
    """In-memory vector datasource, across GDAL versions."""
    mem = gdal.GetDriverByName("MEM")
    if mem is not None and mem.GetMetadataItem("DCAP_VECTOR") == "YES":      # GDAL 3.11+: « Memory » deprecated
        return mem.Create("", 0, 0, 0, gdal.GDT_Unknown)
    return ogr.GetDriverByName("Memory").CreateDataSource("")


def read_features(
    source: str,
    layer: Optional[str] = None,
    where: Optional[str] = None,
    target_crs_wkt: Optional[str] = None,
    buffer_m: Optional[float] = None,
) -> List[Feature]:
    """Read all features of a layer, reprojected to ``target_crs_wkt`` if given.

    Lines and points are turned into polygons with ``buffer_m`` (for example
    roads or rivers given as lines, boreholes given as points); without it
    they are rejected, because every input layer of the engine describes
    areas. Polygons are widened by ``buffer_m`` too when it is given. The
    buffer is applied after reprojection, so it is in metres of the
    calculation CRS.
    """
    with gdal_exceptions():
        datasource = ogr.Open(source)
        ogr_layer = datasource.GetLayerByName(layer) if layer else datasource.GetLayer(0)
        if where:
            ogr_layer.SetAttributeFilter(where)
        transform = None
        source_srs = ogr_layer.GetSpatialRef()
        if target_crs_wkt and source_srs is not None:
            source_srs = source_srs.Clone()
            source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            target_srs = srs_from_wkt(target_crs_wkt)
            if not source_srs.IsSame(target_srs):
                transform = osr.CoordinateTransformation(source_srs, target_srs)
        definition = ogr_layer.GetLayerDefn()
        names = [definition.GetFieldDefn(i).GetName() for i in range(definition.GetFieldCount())]
        features = []
        for ogr_feature in ogr_layer:
            geometry = ogr_feature.GetGeometryRef()
            if geometry is None or geometry.IsEmpty():
                continue
            geometry = geometry.Clone()
            if transform is not None:
                geometry.Transform(transform)
            geometry = _as_polygonal(geometry, buffer_m, source)
            if geometry is None:
                continue
            attributes = {name: ogr_feature.GetField(name) for name in names}
            features.append(Feature(geometry, attributes))
        return features


class BufferRequired(ValueError):
    """Lines or points were read without a buffer width."""


def _as_polygonal(geometry: ogr.Geometry, buffer_m: Optional[float], source: str) -> Optional[ogr.Geometry]:
    widen = buffer_m is not None and buffer_m > 0
    if geometry.GetDimension() < 2:
        if not widen:
            raise BufferRequired(f"{source}: line or point geometries need a buffer width")
        return polygonal_part(geometry.Buffer(buffer_m))
    if not geometry.IsValid():
        geometry = geometry.MakeValid()
    if widen:
        geometry = geometry.Buffer(buffer_m)
    return polygonal_part(geometry)


def polygonal_part(geometry: Optional[ogr.Geometry]) -> Optional[ogr.Geometry]:
    """Polygonal content of a geometry as a MultiPolygon, or None if it has no area.

    Intersections can return collections mixing polygons with lines or points
    (shared edges, touching corners); only the polygons carry an area.
    """
    if geometry is None or geometry.IsEmpty():
        return None
    flat_type = ogr.GT_Flatten(geometry.GetGeometryType())
    result = ogr.Geometry(ogr.wkbMultiPolygon)
    if flat_type == ogr.wkbPolygon:
        result.AddGeometry(geometry)
    elif flat_type == ogr.wkbMultiPolygon:
        for i in range(geometry.GetGeometryCount()):
            result.AddGeometry(geometry.GetGeometryRef(i))
    elif flat_type == ogr.wkbGeometryCollection:
        for i in range(geometry.GetGeometryCount()):
            part = polygonal_part(geometry.GetGeometryRef(i))
            if part is not None:
                for j in range(part.GetGeometryCount()):
                    result.AddGeometry(part.GetGeometryRef(j))
    else:
        return None
    if result.GetGeometryCount() == 0 or result.GetArea() <= 0:
        return None
    return result


def union_all(geometries: Iterable[ogr.Geometry]) -> Optional[ogr.Geometry]:
    """Union of polygonal geometries, as a MultiPolygon (None if empty)."""
    multi = ogr.Geometry(ogr.wkbMultiPolygon)
    for geometry in geometries:
        part = polygonal_part(geometry)
        if part is None:
            continue
        for i in range(part.GetGeometryCount()):
            multi.AddGeometry(part.GetGeometryRef(i))
    if multi.GetGeometryCount() == 0:
        return None
    with gdal_exceptions():
        return polygonal_part(multi.UnionCascaded())
