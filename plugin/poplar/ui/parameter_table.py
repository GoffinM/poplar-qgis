"""One parameter (growth rate, maximum density) linked to its own zones (decision of 29/09/2026).

The user picks a polygon layer and its field; the table then shows one row
per value found in that field, plus the default row (« * », used outside the
zones). A second layer can be crossed with the first one: rows are then the
pairs of values. Each row holds a constant or values at pivot years.
"""

import itertools
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont
from qgis.PyQt.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..compat import POLYGON_FILTER
from ..engine.parameters import DEFAULT_KEY, KEY_SEPARATOR
from ..engine.tables import TableError, parameter_sheet, parameter_values, read_table, sheets, write_table
from ..i18n import tip, tr
from .widgets import find_or_add_layer, layer_with_field, source_of

VALUE = Qt.ItemDataRole.UserRole
MISSING = QColor("#c98a36")


def field_values(layer, field):
    """Distinct values of a field, as the engine reads them (text), sorted."""
    if layer is None or not field:
        return []
    index = layer.fields().indexOf(field)
    if index < 0:
        return []
    values = set()
    for value in layer.uniqueValues(index):
        if value is None or (hasattr(value, "isNull") and value.isNull()):
            continue
        values.add(str(value))
    return sorted(values, key=lambda v: (v.lower(), v))


def _number(text):
    text = (text or "").strip().replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
    return float(text) if text else None


class ParameterTableWidget(QGroupBox):
    def __init__(self, name, dialog, parent=None, tip_key=None):
        super().__init__(parent)
        self.name = name
        self.dialog = dialog
        self.years = []
        self.setToolTip(tip(tip_key or f"parameters.{name}"))
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("parameters.zones")))
        widget, self.layer, self.field = layer_with_field(POLYGON_FILTER, allow_empty=True)
        widget.setToolTip(tip("parameters.zones"))
        row.addWidget(widget, 1)
        layout.addLayout(row)
        self.cross = QCheckBox(tr("parameters.cross"))
        self.cross.setToolTip(tip("parameters.cross"))
        layout.addWidget(self.cross)
        self.second_row = QWidget()
        row = QHBoxLayout(self.second_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(tr("parameters.zones_2")))
        widget, self.layer2, self.field2 = layer_with_field(POLYGON_FILTER, allow_empty=True)
        row.addWidget(widget, 1)
        self.second_row.setVisible(False)
        layout.addWidget(self.second_row)

        self.table = QTableWidget(0, 2)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(150)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        for key, slot in (("parameters.add_year", self._add_year), ("parameters.remove_year", self._remove_year),
                          ("parameters.import", self.import_file), ("parameters.export", self.export_file)):
            button = QPushButton(tr(key))
            button.setToolTip(tip(key))
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        row = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("chip")
        row.addWidget(self.status)
        row.addStretch(1)
        layout.addLayout(row)

        self.cross.toggled.connect(self._cross_toggled)
        for combo in (self.layer, self.layer2):
            combo.layerChanged.connect(lambda *args: self.sync_rows())
        for combo in (self.field, self.field2):
            combo.fieldChanged.connect(lambda *args: self.sync_rows())
        self.set_values({DEFAULT_KEY: None})

    # --- layout of the table ------------------------------------------------------

    @property
    def crossed(self):
        return self.cross.isChecked()

    def _zone_columns(self):
        return 2 if self.crossed else 1

    def _headers(self):
        zones = [tr("parameters.zone")] + ([tr("parameters.zone_2")] if self.crossed else [])
        return zones + [tr("parameters.constant")] + [f"{y:g}" for y in self.years]

    def _cross_toggled(self, checked):
        values = self.values()
        self.second_row.setVisible(checked)
        if not checked:
            values = {k: v for k, v in values.items() if KEY_SEPARATOR not in k}
        self.set_values(values)
        self.sync_rows()

    def zone_values(self):
        """Values of the first layer (and of the second one when crossed)."""
        first = field_values(self.layer.currentLayer(), self.field.currentField())
        if not self.crossed:
            return first, None
        return first, field_values(self.layer2.currentLayer(), self.field2.currentField())

    def expected_keys(self):
        first, second = self.zone_values()
        if second is None:
            return list(first)
        return [f"{a}{KEY_SEPARATOR}{b}" for a, b in itertools.product(first, second)]

    # --- values -------------------------------------------------------------------

    def values(self):
        """{key: None | number | {year: value}} for every row shown."""
        result = {}
        start = self._zone_columns()
        for row in range(self.table.rowCount()):
            key = self.table.item(row, 0).data(VALUE)
            constant = _number(self.table.item(row, start).text() if self.table.item(row, start) else "")
            if constant is not None:
                result[key] = constant
                continue
            series = {}
            for i, year in enumerate(self.years):
                item = self.table.item(row, start + 1 + i)
                value = _number(item.text() if item else "")
                if value is not None:
                    series[f"{year:g}"] = value
            result[key] = series or None
        return result

    def set_values(self, values):
        years = {float(y) for v in values.values() if isinstance(v, dict) for y in v}
        self.years = sorted(set(self.years) | years)
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setColumnCount(len(self._headers()))
        self.table.setHorizontalHeaderLabels(self._headers())
        keys = [k for k in values if k != DEFAULT_KEY] + [DEFAULT_KEY]
        for key in keys:
            self._append_row(key, values.get(key))
        self.table.blockSignals(False)
        self._update_status()

    def _append_row(self, key, value):
        row = self.table.rowCount()
        self.table.insertRow(row)
        if key == DEFAULT_KEY:
            parts = [tr("parameters.default_row")] + ([""] if self.crossed else [])
        elif self.crossed:
            first, _, second = key.partition(KEY_SEPARATOR) if KEY_SEPARATOR in key else (key, "", DEFAULT_KEY)
            parts = [tr("parameters.all") if p == DEFAULT_KEY else p for p in (first, second)]
        else:
            parts = [key]
        for column, text in enumerate(parts):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setData(VALUE, key)
            if key == DEFAULT_KEY:
                font = QFont(item.font())
                font.setItalic(True)
                item.setFont(font)
                item.setToolTip(tip("parameters.default_row"))
            self.table.setItem(row, column, item)
        start = self._zone_columns()
        cells = [""] * (1 + len(self.years))
        if isinstance(value, dict):
            by_year = {float(y): v for y, v in value.items()}
            for i, year in enumerate(self.years):
                if year in by_year:
                    cells[1 + i] = f"{by_year[year]:g}"
        elif value is not None:
            cells[0] = f"{value:g}"
        for i, text in enumerate(cells):
            self.table.setItem(row, start + i, QTableWidgetItem(text))

    def sync_rows(self):
        """One row per zone of the layer(s); rows with a value but no zone stay, marked."""
        values = self.values()
        expected = self.expected_keys()
        if not self.layer.currentLayer():
            merged = {DEFAULT_KEY: values.get(DEFAULT_KEY)}
        else:
            merged = {key: values.get(key) for key in expected}
            for key, value in values.items():
                if key not in merged and value is not None:
                    merged[key] = value
            merged[DEFAULT_KEY] = values.get(DEFAULT_KEY)
        self.set_values(merged)

    def unused_keys(self):
        """Keys holding a value that match no zone of the layer(s)."""
        first, second = self.zone_values()
        unused = []
        for key, value in self.values().items():
            if key == DEFAULT_KEY or value is None:
                continue
            if second is None:
                ok = key in first
            else:
                a, _, b = key.partition(KEY_SEPARATOR)
                ok = (a == DEFAULT_KEY or a in first) and (b == DEFAULT_KEY or b in second)
            if not ok:
                unused.append(key)
        return unused

    def _update_status(self):
        unused = set(self.unused_keys()) if self.layer.currentLayer() else set()
        for row in range(self.table.rowCount()):
            key = self.table.item(row, 0).data(VALUE)
            for column in range(self._zone_columns()):
                item = self.table.item(row, column)
                if key in unused:
                    item.setForeground(QBrush(MISSING))
                    item.setToolTip(tr("parameters.absent"))
        self.status.setProperty("state", "warn" if unused else "ok")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        if unused:
            keys = sorted(unused)
            self.status.setText(tr("parameters.status_absent",
                                   keys=", ".join(keys[:4]) + (f" (+{len(keys) - 4})" if len(keys) > 4 else "")))
        elif self.layer.currentLayer():
            self.status.setText(tr("parameters.status_zones", count=self.table.rowCount() - 1))
        else:
            self.status.setText(tr("parameters.status_uniform"))

    def _add_year(self):
        year, ok = QInputDialog.getDouble(self, tr("parameters.add_year"), tr("parameters.year"), 2040, 1900, 2300, 1)
        if ok and year not in self.years:
            values = self.values()
            self.years = sorted(self.years + [year])
            self.set_values(values)

    def _remove_year(self):
        if not self.years:
            return
        labels = [f"{y:g}" for y in self.years]
        label, ok = QInputDialog.getItem(self, tr("parameters.remove_year"), tr("parameters.year"), labels, 0, False)
        if ok:
            year = self.years[labels.index(label)]
            values = self.values()
            for key, value in values.items():
                if isinstance(value, dict):
                    value.pop(label, None)
                    values[key] = value or None
            self.years.remove(year)
            self.set_values(values)

    # --- scenario -----------------------------------------------------------------

    def load(self, spec, typology=None, parameter_zones=None):
        """Show a parameter of the scenario; older formats (typology classes, parameter zones) are converted."""
        self.years = []
        for combo in (self.layer, self.layer2):
            combo.blockSignals(True)
        self.layer.setLayer(None)
        self.layer2.setLayer(None)
        self.cross.blockSignals(True)
        self.cross.setChecked(False)
        self.second_row.setVisible(False)
        self.cross.blockSignals(False)

        zones, values = [], {}
        if isinstance(spec, (int, float)):
            values = {DEFAULT_KEY: float(spec)}
        elif isinstance(spec, dict) and "values" in spec:
            zones = spec.get("zones") or []
            zones = [zones] if isinstance(zones, dict) else list(zones)
            values = dict(spec["values"])
        elif isinstance(spec, dict):
            values = dict(spec)
            if set(values) - {DEFAULT_KEY}:
                zones = [typology] if typology else []
                if parameter_zones and typology:  # zone before class before default: crossed layers
                    zones = [parameter_zones, typology]
                    layer = self._layer(parameter_zones)
                    known = set(field_values(layer, parameter_zones.get("field")))
                    values = {(f"{k}{KEY_SEPARATOR}{DEFAULT_KEY}" if k in known else
                               f"{DEFAULT_KEY}{KEY_SEPARATOR}{k}") if k != DEFAULT_KEY else k: v
                              for k, v in values.items()}
        for i, (combo, field) in enumerate(((self.layer, self.field), (self.layer2, self.field2))):
            if i < len(zones) and zones[i]:
                layer = self._layer(zones[i])
                if layer is not None:
                    combo.setLayer(layer)
                    field.setLayer(layer)
                    field.setField(zones[i].get("field", ""))
        if len(zones) > 1:
            self.cross.blockSignals(True)
            self.cross.setChecked(True)
            self.second_row.setVisible(True)
            self.cross.blockSignals(False)
        for combo in (self.layer, self.layer2):
            combo.blockSignals(False)
        values.setdefault(DEFAULT_KEY, None)
        self.set_values(values)
        self.sync_rows()

    def _layer(self, zone):
        return find_or_add_layer(self.dialog.absolute(zone.get("source")), zone.get("layer"), where=zone.get("where"))

    def store(self):
        """The parameter in the scenario format (None if no value at all)."""
        values = {k: v for k, v in self.values().items() if v is not None}
        if not values:
            return None
        zones = []
        for combo, field in ((self.layer, self.field),) + (((self.layer2, self.field2),) if self.crossed else ()):
            spec = source_of(combo.currentLayer())
            if spec:
                spec["field"] = field.currentField()
                zones.append(spec)
        if not zones:
            return {"values": {DEFAULT_KEY: values[DEFAULT_KEY]}} if DEFAULT_KEY in values else {"values": values}
        return {"zones": zones, "values": values}

    # --- spreadsheets ---------------------------------------------------------------

    def import_file(self, path=None, sheet=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("parameters.import"), "", tr("parameters.table_filter"))
            if not path:
                return
        try:
            names = sheets(path)
            if sheet is None and len(names) > 1:
                sheet, ok = QInputDialog.getItem(self, tr("parameters.import"), tr("parameters.sheet"), names, 0, False)
                if not ok:
                    return
            values = parameter_values(read_table(path, sheet), self.crossed)
        except (TableError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, tr("parameters.import"), tr("parameters.import_error", error=str(error)))
            return
        current = self.values()
        current.update(values)
        self.set_values(current)
        self._update_status()

    def export_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, tr("parameters.export"), f"{self.name}.xlsx",
                                                  tr("parameters.export_filter"))
            if not path:
                return
        if not os.path.splitext(path)[1]:
            path += ".xlsx"
        values = {k: v for k, v in self.values().items() if v is not None}
        write_table(path, *parameter_sheet(values, self.crossed))
        return path
