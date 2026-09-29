"""Small widget helpers shared by the dialogs."""

import os

from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.gui import QgsFieldComboBox, QgsMapLayerComboBox
from qgis.PyQt.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QWidget

from ..compat import layer_source
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


def layer_with_field(filters, allow_empty=False):
    """A layer combo and, next to it, the combo of its fields."""
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    layers = QgsMapLayerComboBox()
    layers.setFilters(filters)
    layers.setAllowEmptyLayer(allow_empty)
    if allow_empty:
        layers.setLayer(None)
    fields = QgsFieldComboBox()
    fields.setLayer(layers.currentLayer())
    layers.layerChanged.connect(fields.setLayer)
    row.addWidget(layers, 2)
    row.addWidget(fields, 1)
    return container, layers, fields


def source_of(layer):
    """Engine input for a layer: {"source": path, "layer": name} (None if no layer)."""
    if layer is None:
        return None
    path, name = layer_source(layer)
    result = {"source": path}
    if name:
        result["layer"] = name
    return result


def find_or_add_layer(path, layer_name=None, raster=False):
    """Layer of the project that reads ``path`` (and ``layer_name``); added to the project if missing."""
    if not path:
        return None
    wanted = os.path.normcase(os.path.abspath(path))
    for layer in QgsProject.instance().mapLayers().values():
        try:
            source, name = layer_source(layer)
        except Exception:
            continue
        if os.path.normcase(os.path.abspath(source)) == wanted and (layer_name is None or name in (None, layer_name)):
            return layer
    if not os.path.exists(path):
        return None
    base = os.path.splitext(os.path.basename(path))[0]
    if raster:
        layer = QgsRasterLayer(path, base)
    else:
        uri = f"{path}|layername={layer_name}" if layer_name else path
        layer = QgsVectorLayer(uri, layer_name or base, "ogr")
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
