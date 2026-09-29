"""Small helpers to run on QGIS 3.34+ (Qt5) and QGIS 4 (Qt6)."""

from qgis.core import QgsMapLayerProxyModel

try:  # QGIS >= 3.34
    from qgis.core import Qgis

    POLYGON_FILTER = Qgis.LayerFilter.PolygonLayer
    RASTER_FILTER = Qgis.LayerFilter.RasterLayer
    VECTOR_FILTER = Qgis.LayerFilter.VectorLayer
except AttributeError:  # pragma: no cover - older QGIS
    POLYGON_FILTER = QgsMapLayerProxyModel.PolygonLayer
    RASTER_FILTER = QgsMapLayerProxyModel.RasterLayer
    VECTOR_FILTER = QgsMapLayerProxyModel.VectorLayer


try:  # QGIS >= 3.30
    from qgis.core import Qgis

    LINEAR_GEOMETRIES = (Qgis.GeometryType.Point, Qgis.GeometryType.Line)
except AttributeError:  # pragma: no cover - older QGIS
    from qgis.core import QgsWkbTypes

    LINEAR_GEOMETRIES = (QgsWkbTypes.PointGeometry, QgsWkbTypes.LineGeometry)


def needs_buffer(layer):
    """True for a vector layer of points or lines: the engine needs a buffer width to make areas of it."""
    geometry_type = getattr(layer, "geometryType", None)
    return geometry_type is not None and geometry_type() in LINEAR_GEOMETRIES


def layer_source(layer):
    """(path, layer name) of a file-based layer, as the engine expects them."""
    from qgis.core import QgsProviderRegistry

    parts = QgsProviderRegistry.instance().decodeUri(layer.providerType(), layer.source())
    path = parts.get("path") or layer.source()
    return path, parts.get("layerName") or None
