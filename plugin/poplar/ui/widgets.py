"""Small widget helpers shared by the dialogs."""

import os

from qgis.core import QgsProject, QgsRasterLayer, QgsSettings, QgsVectorLayer
from qgis.gui import QgsFieldComboBox, QgsMapLayerComboBox
from qgis.PyQt.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QToolButton, QWidget,
)

from ..compat import RASTER_TYPE, VECTOR_TYPE, UnsupportedSource, engine_source, postgres_layer
from ..engine.scenario import is_connection
from ..i18n import tip, tr


def label(key: str, with_tip: bool = True) -> QLabel:
    """Form label; its tooltip explains the field (spec §14.2)."""
    widget = QLabel(tr(key))
    if with_tip:
        widget.setToolTip(tip(key))
    return widget


def add_row(form: QFormLayout, key: str, field: QWidget) -> None:
    lbl = label(key)
    field.setToolTip(lbl.toolTip())
    form.addRow(lbl, field)


def choice_combo(pairs, current=None) -> QComboBox:
    """Combo box of (value, text) pairs; ``currentData()`` gives the value."""
    combo = QComboBox()
    for value, text in pairs:
        combo.addItem(text, value)
    if current is not None:
        set_combo_value(combo, current)
    return combo


def set_combo_value(combo: QComboBox, value) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def layer_combo(filters, allow_empty=False, raster=False):
    """A layer combo with a « … » button to add a file or a database layer to the project."""
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    combo = QgsMapLayerComboBox()
    combo.setFilters(filters)
    combo.setAllowEmptyLayer(allow_empty)
    if allow_empty:
        combo.setLayer(None)
    button = QToolButton()
    button.setText("…")
    button.setObjectName("browse")
    button.setToolTip(tip("layers.browse"))
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    menu = QMenu(button)
    menu.addAction(tr("layers.file"), lambda: pick_file(combo, raster))
    menu.addAction(tr("layers.sources"), lambda: pick_source(combo, raster))
    button.setMenu(menu)
    row.addWidget(combo, 1)
    row.addWidget(button)
    container.combo = combo
    container.button = button
    return container, combo


def layer_with_field(filters, allow_empty=False):
    """A layer combo (with its « … » button) and, next to it, the combo of its fields."""
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    picker, layers = layer_combo(filters, allow_empty)
    fields = QgsFieldComboBox()
    fields.setLayer(layers.currentLayer())
    layers.layerChanged.connect(fields.setLayer)
    row.addWidget(picker, 2)
    row.addWidget(fields, 1)
    return container, layers, fields


VECTOR_FILES = "*.shp *.gpkg *.sqlite *.geojson *.json *.fgb *.kml *.kmz *.gml *.tab *.mif *.gdb *.zip"
RASTER_FILES = "*.tif *.tiff *.vrt *.img *.asc *.nc *.jp2"


def pick_file(combo, raster=False):
    """Choose a file; a GeoPackage with several layers asks which one. Returns the layer set in the combo."""
    pattern = RASTER_FILES if raster else VECTOR_FILES
    path, _ = QFileDialog.getOpenFileName(combo, tr("layers.file"), last_folder(),
                                          f"{tr('layers.raster_files' if raster else 'layers.vector_files')} "
                                          f"({pattern});;{tr('layers.all_files')} (*)")
    if not path:
        return None
    QgsSettings().setValue(FOLDER_SETTING, os.path.dirname(path))
    return set_new_layer(combo, open_file_layer(path, raster, combo))


def open_file_layer(path, raster=False, parent=None):
    """Layer read from a file; for a file holding several layers, the user picks one."""
    name = os.path.splitext(os.path.basename(path))[0]
    if raster:
        return QgsRasterLayer(path, name)
    try:
        from qgis.core import QgsProviderRegistry

        details = [d for d in QgsProviderRegistry.instance().querySublayers(path)
                   if d.type() == VECTOR_TYPE]
    except (ImportError, AttributeError):  # pragma: no cover - QGIS < 3.22
        details = []
    if len(details) > 1:
        names = [d.name() for d in details]
        chosen, ok = QInputDialog.getItem(parent, tr("layers.sublayer"), tr("layers.sublayer_label"), names, 0, False)
        if not ok:
            return None
        detail = details[names.index(chosen)]
        return QgsVectorLayer(f"{path}|layername={detail.name()}", detail.name(), "ogr")
    return QgsVectorLayer(path, name, "ogr")


def pick_source(combo, raster=False):
    """Browse every source QGIS knows: files, GeoPackage, PostGIS and other databases."""
    from qgis.gui import QgsDataSourceSelectDialog

    dialog = QgsDataSourceSelectDialog(None, True, RASTER_TYPE if raster else VECTOR_TYPE, combo)
    dialog.setWindowTitle(tr("layers.sources"))
    if not dialog.exec():
        return None
    uri = dialog.uri()
    if not uri.isValid():
        return None
    if raster:
        layer = QgsRasterLayer(uri.uri, uri.name, uri.providerKey)
    else:
        layer = QgsVectorLayer(uri.uri, uri.name, uri.providerKey)
    return set_new_layer(combo, layer)


def set_new_layer(combo, layer):
    """Add the layer to the project and select it; explain when it cannot be used here."""
    if layer is None:
        return None
    if not layer.isValid():
        QMessageBox.warning(combo, tr("layers.file"), tr("layers.invalid", name=layer.name()))
        return None
    try:
        engine_source(layer)
    except UnsupportedSource as error:
        QMessageBox.warning(combo, tr("layers.file"), tr("layers.unsupported", name=layer.name(), provider=str(error)))
        return None
    if not _accepted(combo, layer):  # points in a list of polygons, for instance
        QMessageBox.warning(combo, tr("layers.file"), tr("layers.wrong_type", name=layer.name()))
        return None
    existing = _same_layer_in_project(layer)
    if existing is None:
        QgsProject.instance().addMapLayer(layer)
        existing = layer
    combo.setLayer(existing)
    return existing


def _accepted(combo, layer):
    """True if the combo would list the layer (geometry type, raster or vector)."""
    from qgis.core import QgsMapLayerProxyModel

    model = QgsMapLayerProxyModel()
    model.setFilters(combo.filters())
    return model.acceptsLayer(layer)


FOLDER_SETTING = "poplar/last_folder"


def last_folder():
    return QgsSettings().value(FOLDER_SETTING, "") or ""


def _same_layer_in_project(layer):
    try:
        wanted = engine_source(layer)
    except UnsupportedSource:
        return None
    return _find_layer(wanted)


def _normalised(spec):
    source = spec.get("source") or ""
    if not is_connection(source):
        source = os.path.normcase(os.path.abspath(source))
    return source, spec.get("layer"), spec.get("where") or None


def _find_layer(spec, raster=None):
    """Layer of the project that reads the same source, sub-layer and filter."""
    wanted = _normalised(spec)
    for layer in QgsProject.instance().mapLayers().values():
        if raster is not None and isinstance(layer, QgsRasterLayer) != raster:
            continue
        try:
            found = _normalised(engine_source(layer))
        except Exception:
            continue
        if found[0] == wanted[0] and (wanted[1] is None or found[1] in (None, wanted[1])) and \
                (found[2] == wanted[2] or wanted[2] is None and spec.get("layer") is None):
            return layer
    return None


def source_of(layer):
    """Engine input for a layer (None if no layer). An unreadable layer is marked ``unsupported``."""
    if layer is None:
        return None
    try:
        return engine_source(layer)
    except UnsupportedSource as error:
        return {"source": layer.source(), "unsupported": str(error), "name": layer.name()}


def find_or_add_layer(path, layer_name=None, raster=False, where=None):
    """Layer of the project that reads ``path`` (and ``layer_name``); added to the project if missing."""
    if not path:
        return None
    spec = {"source": path, "layer": layer_name, "where": where}
    layer = _find_layer(spec, raster)
    if layer is not None:
        return layer
    if path.startswith("PG:"):
        layer = postgres_layer(spec, (layer_name or "postgis").split("(")[0])
    elif not os.path.exists(path):
        return None
    else:
        base = os.path.splitext(os.path.basename(path))[0]
        if raster:
            layer = QgsRasterLayer(path, base)
        else:
            uri = f"{path}|layername={layer_name}" if layer_name else path
            layer = QgsVectorLayer(uri, layer_name or base, "ogr")
            if where and layer.isValid():
                layer.setSubsetString(where)
    if not layer.isValid():
        return None
    QgsProject.instance().addMapLayer(layer)
    return layer


def parse_series(text: str):
    """Parse ``20`` or ``2026: 20; 2040: 30`` into a number or a {year: value} mapping (None if empty)."""
    text = (text or "").strip()
    if not text:
        return None
    if ":" not in text:
        return float(text.replace(",", ".").replace(" ", "").replace(" ", ""))
    series = {}
    for part in text.split(";"):
        if part.strip():
            year, value = part.split(":")
            series[str(float(year.strip())).rstrip("0").rstrip(".")] = float(value.strip().replace(",", "."))
    return series


def format_series(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return "; ".join(f"{year}: {v:g}" for year, v in value.items())
    return f"{value:g}"
