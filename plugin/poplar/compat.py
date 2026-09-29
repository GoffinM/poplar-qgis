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


try:  # QGIS >= 3.30
    from qgis.core import Qgis

    VECTOR_TYPE, RASTER_TYPE = Qgis.LayerType.Vector, Qgis.LayerType.Raster
except AttributeError:  # pragma: no cover - older QGIS
    from qgis.core import QgsMapLayerType

    VECTOR_TYPE, RASTER_TYPE = QgsMapLayerType.VectorLayer, QgsMapLayerType.RasterLayer


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


FILE_PROVIDERS = ("ogr", "gdal", "spatialite")
SSL_MODES = {1: "disable", 2: "allow", 3: "require", 4: "verify-ca", 5: "verify-full"}

SECRETS = {}
"""Database passwords of this session, by engine source: never written to a scenario file."""


class UnsupportedSource(ValueError):
    """The engine (GDAL/OGR) cannot read this kind of layer (memory layer, web service…)."""


def engine_source(layer):
    """Engine input of a QGIS layer: {"source", "layer"?, "where"?}.

    Files (shapefile, GeoPackage, GeoTIFF, SpatiaLite…) give their path and
    sub-layer; a filter set in QGIS becomes ``where``. PostGIS layers give an
    OGR connection string (``PG:…``) without the password, which stays in
    memory for this session (:data:`SECRETS`).
    """
    from qgis.core import QgsProviderRegistry

    provider = layer.providerType()
    parts = QgsProviderRegistry.instance().decodeUri(provider, layer.source())
    if provider in FILE_PROVIDERS:
        spec = {"source": _main_file(parts.get("path") or layer.source())}
        if parts.get("layerName"):
            spec["layer"] = parts["layerName"]
        subset = parts.get("subset") or (layer.subsetString() if hasattr(layer, "subsetString") else "")
        if subset:
            spec["where"] = subset
        return spec
    if provider == "postgres":
        return _postgres_source(layer, parts)
    raise UnsupportedSource(provider)


SHAPEFILE_PARTS = (".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx")


def _main_file(path):
    """The file GDAL must open: the .shp of a shapefile opened through one of its other files.

    Paths are written the way the system writes them (on Windows, « //serveur/partage/… »
    becomes « \\\\serveur\\partage\\… »).
    """
    import os

    if "|" not in path and "://" not in path:
        path = os.path.normpath(path)
        stem, extension = os.path.splitext(path)
        if extension.lower() in SHAPEFILE_PARTS:
            for candidate in (stem + ".shp", stem + ".SHP"):
                if os.path.exists(candidate):
                    return candidate
    return path


def _postgres_source(layer, parts):
    from qgis.core import QgsApplication, QgsDataSourceUri

    uri = QgsDataSourceUri(layer.source())
    user, password = parts.get("username") or "", parts.get("password") or ""
    if uri.authConfigId():  # credentials kept in the QGIS authentication database
        try:
            ok, items = QgsApplication.authManager().updateDataSourceUriItems([], uri.authConfigId(), "postgres")
            for item in items if ok else []:
                key, _, value = item.partition("=")
                if key == "user":
                    user = value.strip("'")
                elif key == "password":
                    password = value.strip("'")
        except Exception:  # pragma: no cover - depends on the user's authentication database
            pass
    connection = []
    for key, value in (("service", parts.get("service")), ("dbname", parts.get("dbname")), ("host", parts.get("host")),
                       ("port", parts.get("port")), ("user", user), ("sslmode", _ssl_mode(parts.get("sslmode")))):
        if value:
            connection.append(f"{key}='{value}'")
    source = "PG:" + " ".join(connection)
    table = f"{parts.get('schema') or 'public'}.{parts.get('table')}"
    if parts.get("geometrycolumn"):
        table += f"({parts['geometrycolumn']})"
    spec = {"source": source, "layer": table}
    if parts.get("sql"):
        spec["where"] = parts["sql"]
    if password:
        SECRETS[source] = password
    return spec


def _ssl_mode(value):
    try:
        return SSL_MODES.get(int(getattr(value, "value", value)))
    except (TypeError, ValueError):
        return None


def with_password(source):
    """The connection string with the password of this session, for the run only."""
    password = SECRETS.get(source)
    return f"{source} password='{password}'" if password else source


def postgres_layer(spec, name):
    """QGIS layer for a ``PG:`` engine source (used when a scenario is opened)."""
    import re

    from qgis.core import QgsDataSourceUri, QgsVectorLayer

    values = dict(re.findall(r"(\w+)='([^']*)'", spec["source"]))
    uri = QgsDataSourceUri()
    if values.get("service"):
        uri.setConnection(values["service"], values.get("dbname", ""), values.get("user", ""),
                          SECRETS.get(spec["source"], ""))
    else:
        modes = {name: number for number, name in SSL_MODES.items()}
        uri.setConnection(values.get("host", ""), values.get("port", "5432"), values.get("dbname", ""),
                          values.get("user", ""), SECRETS.get(spec["source"], ""),
                          QgsDataSourceUri.SslMode(modes.get(values.get("sslmode"), 0)))
    match = re.match(r"^(?:([^.(]+)\.)?([^(]+)(?:\((.+)\))?$", spec.get("layer") or "")
    schema, table, geometry = (match.groups() if match else ("public", spec.get("layer", ""), None))
    uri.setDataSource(schema or "public", table, geometry or "geom", spec.get("where") or "")
    return QgsVectorLayer(uri.uri(False), name, "postgres")
