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


def layer_source(layer):
    """(path, layer name) of a file-based layer, as the engine expects them."""
    from qgis.core import QgsProviderRegistry

    parts = QgsProviderRegistry.instance().decodeUri(layer.providerType(), layer.source())
    path = parts.get("path") or layer.source()
    return path, parts.get("layerName") or None
