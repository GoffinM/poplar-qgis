"""Calibration tab: roofs → inhabitants per roof → starting population (validated mock-up v5, 29/09/2026).

The roofs, strata and census are set at the top; « Calibrate » reads the
roofs once (in the background) and keeps the roof areas of every regression
group, so that everything below reacts instantly: number of classes, cut,
floor and ceiling, roof area per inhabitant, inhabitants retained per class.
Every setting is written into the ``calibration`` section of the scenario.
"""

import json

import numpy as np
from qgis.core import QgsTask
from qgis.core import QgsFieldProxyModel
from qgis.gui import QgsFieldComboBox, QgsFileWidget
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..compat import POLYGON_FILTER, VECTOR_FILTER
from ..engine.calibration import BREAKS, EQUAL, MANUAL_CUT, QUANTILE, SEGMENTS, STEPS, POLYNOMIAL
from ..engine.roof_population import ALERT_PERCENT, AREA_PER_PERSON, GroupSettings, WHOLE_AREA
from ..i18n import current_language, tip, tr
from .calibration_chart import CUMULATIVE, DISTRIBUTION, CalibrationChart
from .parameter_table import field_values
from .widgets import add_row, choice_combo, find_or_add_layer, layer_combo, layer_with_field, set_combo_value, source_of

LIMIT_MODES = ("percentile", "value", "none")


def _fmt(value, decimals=0):
    if value is None:
        return "–"
    text = f"{value:,.{decimals}f}".replace(",", " ")
    return text.replace(".", ",") if current_language() == "fr" else text


class CalibrationTask(QgsTask):
    """Reads the roofs and calibrates every group in the background."""

    done = pyqtSignal(object, object, object)  # report, groups, error

    def __init__(self, scenario):
        super().__init__(tr("calibration.task"), QgsTask.CanCancel)
        self.scenario = scenario
        self.report = self.groups = self.error = None

    def run(self):
        from ..engine.simulation import calibrate

        try:
            self.report, self.groups = calibrate(self.scenario)
        except Exception as error:  # shown to the user
            self.error = error
        return self.error is None

    def finished(self, ok):
        self.done.emit(self.report, self.groups, self.error)


class LimitEditor(QWidget):
    """Floor or ceiling: a percentile of the roof areas, a value in m², or no limit."""

    def __init__(self, default_percentile, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.mode = choice_combo([(m, tr(f"calibration.limit.{m}")) for m in LIMIT_MODES])
        self.value = QDoubleSpinBox()
        self.value.setRange(0, 10_000)
        self.value.setDecimals(1)
        self.value.setValue(default_percentile)
        row.addWidget(self.mode)
        row.addWidget(self.value)
        self.mode.currentIndexChanged.connect(lambda: self.value.setEnabled(self.mode.currentData() != "none"))

    def spec(self):
        mode = self.mode.currentData()
        if mode == "none":
            return None
        return {mode: self.value.value()}

    def set_spec(self, spec):
        for widget in (self.mode, self.value):
            widget.blockSignals(True)
        if spec is None:
            set_combo_value(self.mode, "none")
        elif isinstance(spec, (int, float)):
            set_combo_value(self.mode, "value")
            self.value.setValue(float(spec))
        else:
            key = "percentile" if "percentile" in spec else "value"
            set_combo_value(self.mode, key)
            self.value.setValue(float(spec[key]))
        self.value.setEnabled(self.mode.currentData() != "none")
        for widget in (self.mode, self.value):
            widget.blockSignals(False)


class UsageDialog(QDialog):
    """Coefficient of each usage category (housing = 1, mixed = 0.5, shop = 0…)."""

    def __init__(self, categories, coefficients, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("calibration.usage_coefficients"))
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([tr("calibration.usage_category"), tr("calibration.coefficient")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        keys = [c for c in categories if c != "*"] + ["*"]
        for key in keys:
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(tr("calibration.usage_other") if key == "*" else key)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(f"{coefficients.get(key, 1.0):g}"))
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def coefficients(self):
        result = {}
        for row in range(self.table.rowCount()):
            key = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            try:
                result[key] = float(self.table.item(row, 1).text().replace(",", "."))
            except ValueError:
                continue
        return result


class CalibrationPage(QWidget):
    key = "calibration"

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.report = None
        self.groups = {}             # group name → GroupData (roofs of the group), after « Calibrate »
        self.settings = {}           # group name → GroupSettings (what the scenario holds)
        self.current = None
        self.usage = {}
        self.census_memory = {}
        self.task = None
        self._building = False
        layout = QVBoxLayout(self)

        self.use_roofs = QCheckBox(tr("calibration.use_roofs"))
        self.use_roofs.setToolTip(tip("calibration.use_roofs"))
        layout.addWidget(self.use_roofs)

        top = QHBoxLayout()
        box = QGroupBox(tr("calibration.roofs"))
        form = QFormLayout(box)
        widget, self.roof_layer = layer_combo(VECTOR_FILTER, allow_empty=True)
        add_row(form, "calibration.roof_layer", widget)
        download = QPushButton(tr("calibration.download"))
        download.setToolTip(tip("calibration.download"))
        download.clicked.connect(lambda: self.download_roofs())
        form.addRow("", download)
        self.roof_origin = QLabel()
        self.roof_origin.setObjectName("chip")
        self.roof_origin.setWordWrap(True)
        self.roof_origin.setVisible(False)
        form.addRow("", self.roof_origin)
        self.roof_file = QgsFileWidget()
        self.roof_file.setFilter("Google Open Buildings (*.csv *.csv.gz *.gz)")
        add_row(form, "calibration.roof_file", self.roof_file)
        self.area_field = QgsFieldComboBox()
        self.area_field.setAllowEmptyFieldName(True)
        add_row(form, "calibration.area_field", self.area_field)
        usage = QWidget()
        row = QHBoxLayout(usage)
        row.setContentsMargins(0, 0, 0, 0)
        self.usage_field = QgsFieldComboBox()
        self.usage_field.setAllowEmptyFieldName(True)
        coefficients = QPushButton(tr("calibration.usage_coefficients"))
        coefficients.clicked.connect(self._edit_usage)
        row.addWidget(self.usage_field, 1)
        row.addWidget(coefficients)
        add_row(form, "calibration.usage_field", usage)
        confidence = QWidget()
        row = QHBoxLayout(confidence)
        row.setContentsMargins(0, 0, 0, 0)
        self.confidence_on = QCheckBox(tr("calibration.confidence_on"))
        self.confidence_field = QgsFieldComboBox()
        self.confidence_field.setAllowEmptyFieldName(True)
        self.confidence = QDoubleSpinBox()
        self.confidence.setRange(0, 1)
        self.confidence.setSingleStep(0.05)
        self.confidence.setValue(0.75)
        for w in (self.confidence_on, self.confidence_field, self.confidence):
            row.addWidget(w)
        add_row(form, "calibration.confidence", confidence)
        self.roof_year = QSpinBox()
        self.roof_year.setRange(1899, 2200)
        self.roof_year.setSpecialValueText("–")
        self.roof_year.setValue(1899)
        add_row(form, "calibration.roof_year", self.roof_year)
        for combo in (self.area_field, self.usage_field, self.confidence_field):
            combo.setLayer(self.roof_layer.currentLayer())
        self.roof_layer.layerChanged.connect(self._roof_layer_changed)
        top.addWidget(box, 1)

        box = QGroupBox(tr("calibration.strata"))
        form = QFormLayout(box)
        widget, self.strata_layer, self.strata_field = layer_with_field(POLYGON_FILTER, allow_empty=True)
        add_row(form, "calibration.strata_layer", widget)
        self.group_field = QgsFieldComboBox()
        self.group_field.setAllowEmptyFieldName(True)
        self.census_field = QgsFieldComboBox()
        self.census_field.setAllowEmptyFieldName(True)
        self.census_field.setFilters(QgsFieldProxyModel.Filter.Numeric if hasattr(QgsFieldProxyModel, "Filter")
                                     else QgsFieldProxyModel.Numeric)  # a population is a number
        self.strata_layer.layerChanged.connect(self._strata_layer_changed)
        add_row(form, "calibration.group_field", self.group_field)
        add_row(form, "calibration.census_field", self.census_field)
        self.census = QTableWidget(0, 2)
        self.census.setHorizontalHeaderLabels([tr("calibration.stratum"), tr("calibration.census")])
        self.census.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.census.setMinimumHeight(90)
        self.census.setMaximumHeight(140)
        add_row(form, "calibration.census_table", self.census)
        self.census_year = QSpinBox()
        self.census_year.setRange(1899, 2200)
        self.census_year.setSpecialValueText("–")
        self.census_year.setValue(1899)
        add_row(form, "calibration.census_year", self.census_year)
        self.target_year = QSpinBox()
        self.target_year.setRange(1899, 2200)
        self.target_year.setSpecialValueText(tr("calibration.target_year.start"))
        self.target_year.setValue(1899)
        add_row(form, "calibration.target_year", self.target_year)
        self.gap_rate = QLineEdit()
        self.gap_rate.setPlaceholderText(tr("calibration.gap_rate.placeholder"))
        add_row(form, "calibration.gap_rate", self.gap_rate)
        self.recalibrate = QCheckBox(tr("calibration.recalibrate"))
        self.recalibrate.setToolTip(tip("calibration.recalibrate"))
        form.addRow("", self.recalibrate)
        top.addWidget(box, 1)
        layout.addLayout(top)
        self.strata_layer.layerChanged.connect(lambda *a: self._fill_census())
        self.strata_field.fieldChanged.connect(lambda *a: self._fill_census())
        self.census_field.fieldChanged.connect(lambda *a: self._fill_census(from_field=True))

        row = QHBoxLayout()
        self.compute_button = QPushButton(tr("calibration.compute"))
        self.compute_button.setObjectName("primary")
        self.compute_button.setToolTip(tip("calibration.compute"))
        self.compute_button.clicked.connect(lambda: self.compute())
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("chip")
        export = QPushButton(tr("calibration.export"))
        export.clicked.connect(lambda: self.export_calibration())
        load = QPushButton(tr("calibration.import"))
        load.clicked.connect(lambda: self.import_calibration())
        row.addWidget(self.compute_button)
        row.addWidget(self.status, 1)
        row.addWidget(export)
        row.addWidget(load)
        layout.addLayout(row)

        box = QGroupBox(tr("calibration.groups"))
        inner = QVBoxLayout(box)
        self.group_table = QTableWidget(0, 8)
        self.group_table.setHorizontalHeaderLabels([tr(f"calibration.column.{c}") for c in (
            "group", "strata", "roofs", "area_per_person", "computed", "census", "gap", "factor")])
        self.group_table.verticalHeader().setVisible(False)
        self.group_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.group_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.group_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.group_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.group_table.setMaximumHeight(130)
        self.group_table.itemSelectionChanged.connect(self._group_selected)
        inner.addWidget(self.group_table)
        layout.addWidget(box)

        self.editor = QGroupBox(tr("calibration.group"))
        inner = QVBoxLayout(self.editor)
        row = QHBoxLayout()
        self.method = choice_combo([(m, tr(f"calibration.method.{m}")) for m in (STEPS, SEGMENTS, POLYNOMIAL)])
        self.cut = choice_combo([(c, tr(f"calibration.cut.{c}")) for c in (BREAKS, EQUAL, QUANTILE, MANUAL_CUT)])
        self.n_classes = QSpinBox()
        self.n_classes.setRange(1, 20)
        self.n_classes.setValue(8)
        for key, widget in (("calibration.method", self.method), ("calibration.cut", self.cut),
                            ("calibration.n_classes", self.n_classes)):
            label = QLabel(tr(key))
            label.setToolTip(tip(key))
            widget.setToolTip(tip(key))
            row.addWidget(label)
            row.addWidget(widget)
        row.addStretch(1)
        inner.addLayout(row)
        row = QHBoxLayout()
        self.floor = LimitEditor(1)
        self.ceiling = LimitEditor(90)
        self.exclude_on = QCheckBox(tr("calibration.exclude_above"))
        self.exclude_on.setToolTip(tip("calibration.exclude_above"))
        self.exclude = QDoubleSpinBox()
        self.exclude.setRange(1, 100_000)
        self.exclude.setValue(450)
        for key, widget in (("calibration.floor", self.floor), ("calibration.ceiling", self.ceiling)):
            label = QLabel(tr(key))
            label.setToolTip(tip(key))
            row.addWidget(label)
            row.addWidget(widget)
        row.addWidget(self.exclude_on)
        row.addWidget(self.exclude)
        row.addStretch(1)
        inner.addLayout(row)
        row = QHBoxLayout()
        self.area_per_person = QDoubleSpinBox()
        self.area_per_person.setRange(0.5, 500)
        self.area_per_person.setDecimals(2)
        self.area_per_person.setSuffix(" m²")
        fit = QPushButton(tr("calibration.fit"))
        fit.setObjectName("primary")
        fit.setToolTip(tip("calibration.fit"))
        fit.clicked.connect(self.fit)
        self.min_per_roof = QSpinBox()
        self.min_per_roof.setRange(0, 100)
        self.max_per_roof = QSpinBox()
        self.max_per_roof.setRange(1, 500)
        for key, widget in (("calibration.area_per_person", self.area_per_person), (None, fit),
                            ("calibration.min_per_roof", self.min_per_roof),
                            ("calibration.max_per_roof", self.max_per_roof)):
            if key:
                label = QLabel(tr(key))
                label.setToolTip(tip(key))
                row.addWidget(label)
            row.addWidget(widget)
        row.addStretch(1)
        inner.addLayout(row)
        row = QHBoxLayout()
        self.view_distribution = QPushButton(tr("calibration.view.distribution"))
        self.view_cumulative = QPushButton(tr("calibration.view.cumulative"))
        for button, view in ((self.view_distribution, DISTRIBUTION), (self.view_cumulative, CUMULATIVE)):
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, v=view: self._set_view(v))
            row.addWidget(button)
        self.view_distribution.setChecked(True)
        row.addStretch(1)
        inner.addLayout(row)
        self.chart = CalibrationChart()
        self.chart.labels = {"area": tr("calibration.chart.area"), "people": tr("calibration.chart.people")}
        self.chart.edgesChanged.connect(self._edges_dragged)
        inner.addWidget(self.chart)
        self.classes = QTableWidget(0, 6)
        self.classes.setHorizontalHeaderLabels([tr(f"calibration.class.{c}") for c in (
            "number", "from", "to", "roofs", "mean", "proposed")] )
        self.classes.setColumnCount(7)
        self.classes.setHorizontalHeaderItem(6, QTableWidgetItem(tr("calibration.class.retained")))
        self.classes.verticalHeader().setVisible(False)
        self.classes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.classes.horizontalHeader().setStretchLastSection(True)
        self.classes.setMinimumHeight(290)
        self.classes.itemChanged.connect(self._value_edited)
        inner.addWidget(self.classes)
        self.totals = QLabel()
        self.totals.setWordWrap(True)
        self.totals.setObjectName("chip")
        inner.addWidget(self.totals)
        row = QHBoxLayout()
        self.reference = QLineEdit()
        self.reference.setPlaceholderText(tr("calibration.reference.placeholder"))
        self.reference.setToolTip(tip("calibration.reference"))
        self.reference.textChanged.connect(lambda *a: self._update_tcam())
        label = QLabel(tr("calibration.reference"))
        label.setToolTip(tip("calibration.reference"))
        row.addWidget(label)
        row.addWidget(self.reference)
        self.tcam = QLabel()
        self.tcam.setWordWrap(True)
        row.addWidget(self.tcam, 1)
        inner.addLayout(row)
        layout.addWidget(self.editor)
        self.editor.setEnabled(False)

        for widget in (self.method, self.cut):
            widget.currentIndexChanged.connect(lambda *a: self._settings_changed(recut=True))
        self.n_classes.valueChanged.connect(lambda *a: self._settings_changed(recut=True))
        for editor in (self.floor, self.ceiling):
            editor.mode.currentIndexChanged.connect(lambda *a: self._settings_changed(recut=True))
            editor.value.editingFinished.connect(lambda: self._settings_changed(recut=True))
        self.exclude_on.toggled.connect(lambda *a: self._settings_changed(recut=True))
        self.exclude.editingFinished.connect(lambda: self._settings_changed(recut=True))
        self.area_per_person.editingFinished.connect(lambda: self._settings_changed(recut=False))
        for spin in (self.min_per_roof, self.max_per_roof):
            spin.valueChanged.connect(lambda *a: self._settings_changed(recut=False))

    AREA_NAMES = ("area_m2", "area_in_meters", "area", "surface", "superficie", "surf_m2", "shape_area")

    def _roof_layer_changed(self, layer):
        """New roof layer: area field guessed from its name, no usage nor confidence field until chosen."""
        for combo in (self.area_field, self.usage_field, self.confidence_field):
            combo.setLayer(layer)
            combo.setField("")
        self._show_roof_origin(layer)
        if layer is not None and not self._building:
            names = {f.name().lower(): f.name() for f in layer.fields()}
            for candidate in self.AREA_NAMES:
                if candidate in names:
                    self.area_field.setField(names[candidate])
                    break
            if "confidence" in names:
                self.confidence_field.setField(names["confidence"])

    def download_roofs(self, show=True):
        """Open the download window on the strata zone; the roofs downloaded become the roof layer."""
        from .download_dialog import DownloadRoofsDialog

        dialog = DownloadRoofsDialog(self.strata_layer.currentLayer(), self.dialog.base_dir(), self)
        dialog.downloaded.connect(self._roofs_downloaded)
        if show:
            dialog.exec()
        return dialog

    def _roofs_downloaded(self, layer):
        if layer is None:
            return
        self.roof_file.setFilePath("")
        self.roof_layer.setLayer(layer)            # area and confidence fields are found by their names
        origin = self._show_roof_origin(layer)
        if origin and origin.get("imagery_year"):
            self.roof_year.setValue(int(origin["imagery_year"]))      # from the dataset, fresh download
        if origin:
            from .download_dialog import _summary

            self.dialog.iface.messageBar().pushSuccess("Poplar", tr("calibration.downloaded", **_summary(origin)))

    def _show_roof_origin(self, layer):
        """Roofs downloaded by Poplar: date, number and source shown under the layer."""
        from ..engine.roofs import download_origin

        spec = source_of(layer) if layer is not None else None
        origin = download_origin(spec["source"]) if spec and not spec.get("unsupported") else None
        if origin and origin.get("imagery_year") and self.roof_year.value() <= 1899 and not self._building:
            self.roof_year.setValue(int(origin["imagery_year"]))      # year of the images, when not set yet
        if origin:
            from .download_dialog import _summary

            self.roof_origin.setText(tr("calibration.roof_origin", dataset=origin.get("dataset", ""),
                                        **_summary(origin)))
        self.roof_origin.setVisible(bool(origin))
        return origin

    def _strata_layer_changed(self, layer):
        """New strata layer: no group nor census field until chosen (never the first field by default)."""
        for combo in (self.group_field, self.census_field):
            combo.setLayer(layer)
            combo.setField("")

    def _show_status(self, text, warn=False):
        self.status.setText(text)
        self.status.setProperty("state", "warn" if warn else "ok")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    # --- census table -----------------------------------------------------------------

    def _fill_census(self, from_field=False):
        """One row per stratum (or « whole area »), kept values, or values of the census field."""
        self.census_memory.update(self.census_values())       # typed values survive a change of layer or field
        current = self.census_memory
        layer, field = self.strata_layer.currentLayer(), self.strata_field.currentField()
        keys = field_values(layer, field) if layer is not None and field else [WHOLE_AREA]
        from_layer = {}
        census_field = self.census_field.currentField()
        if from_field and layer is not None and field and census_field:
            for feature in layer.getFeatures():
                value = feature[census_field]
                if value not in (None, "") and not (hasattr(value, "isNull") and value.isNull()):
                    key = str(feature[field])
                    from_layer[key] = from_layer.get(key, 0.0) + float(value)
        self.census.setRowCount(0)
        for key in keys:
            row = self.census.rowCount()
            self.census.insertRow(row)
            item = QTableWidgetItem(tr("calibration.whole_area") if key == WHOLE_AREA else key)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.census.setItem(row, 0, item)
            value = from_layer.get(key, current.get(key))
            self.census.setItem(row, 1, QTableWidgetItem("" if value is None else f"{value:g}"))

    def census_values(self):
        values = {}
        for row in range(self.census.rowCount()):
            key = self.census.item(row, 0).data(Qt.ItemDataRole.UserRole)
            item = self.census.item(row, 1)
            text = (item.text() if item else "").replace(" ", "").replace(" ", "").replace(",", ".")
            if text:
                try:
                    values[key] = float(text)
                except ValueError:
                    pass
        return values

    def _edit_usage(self):
        layer, field = self.roof_layer.currentLayer(), self.usage_field.currentField()
        categories = field_values(layer, field) if layer is not None and field else []
        dialog = UsageDialog(categories, self.usage, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.usage = dialog.coefficients()

    # --- scenario ---------------------------------------------------------------------

    def load(self, data):
        self._building = True
        calibration = data.get("calibration") or {}
        self.use_roofs.setChecked((data.get("base_population") or {}).get("source") == "buildings")
        buildings = calibration.get("buildings") or {}
        source = buildings.get("source") or ""
        self.roof_file.setFilePath("")
        self.roof_layer.setLayer(None)
        if source.lower().endswith((".csv", ".gz")):
            self.roof_file.setFilePath(self.dialog.absolute(source))
        elif source:
            layer = find_or_add_layer(self.dialog.absolute(source), buildings.get("layer"), where=buildings.get("where"))
            if layer is not None:
                self.roof_layer.setLayer(layer)
        for combo in (self.area_field, self.usage_field, self.confidence_field):
            combo.setLayer(self.roof_layer.currentLayer())
        self.area_field.setField(buildings.get("area_field") or "")
        self.usage_field.setField(buildings.get("usage_field") or "")
        self.usage = dict(buildings.get("usage_coefficients") or {})
        self.confidence_on.setChecked(buildings.get("min_confidence") is not None)
        self.confidence_field.setField(buildings.get("confidence_field") or "")
        self.confidence.setValue(float(buildings.get("min_confidence") or 0.75))
        self.roof_year.setValue(int(buildings.get("year") or 1899))
        strata = calibration.get("strata") or {}
        self.strata_layer.setLayer(None)
        if strata.get("source"):
            layer = find_or_add_layer(self.dialog.absolute(strata["source"]), strata.get("layer"), where=strata.get("where"))
            if layer is not None:
                self.strata_layer.setLayer(layer)
                self.strata_field.setLayer(layer)
                self.strata_field.setField(strata.get("field") or "")
        for combo in (self.group_field, self.census_field):
            combo.setLayer(self.strata_layer.currentLayer())
        self.group_field.setField(strata.get("group_field") or "")
        self.census_field.setField(strata.get("census_field") or "")
        self.census.setRowCount(0)
        self.census_memory = {}
        self._fill_census()
        for row in range(self.census.rowCount()):
            key = self.census.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if key in (calibration.get("census") or {}):
                self.census.item(row, 1).setText(f"{calibration['census'][key]:g}")
        self.census_year.setValue(int(calibration.get("census_year") or 1899))
        self.target_year.setValue(int(calibration.get("target_year") or 1899))
        rate = calibration.get("gap_growth_rate")
        self.gap_rate.setText("" if rate is None or isinstance(rate, dict) else f"{rate:g}")
        self.recalibrate.setChecked(bool(calibration.get("recalibrate", False)))
        self.settings = {}
        for name, spec in (calibration.get("groups") or {}).items():
            try:
                self.settings[name] = GroupSettings.from_dict(name, spec)
            except ValueError:
                continue
        self.report, self.groups, self.current = None, {}, None
        self.group_table.setRowCount(0)
        self.editor.setEnabled(False)
        self.status.setText(tr("calibration.not_computed") if source else "")
        self._building = False

    def store(self, data):
        buildings = {}
        path = self.roof_file.filePath()
        if path:
            buildings = {"source": path}
        elif self.roof_layer.currentLayer() is not None:
            buildings = source_of(self.roof_layer.currentLayer())
        if not buildings:
            data.pop("calibration", None)
            if (data.get("base_population") or {}).get("source") == "buildings":
                data["base_population"]["source"] = "raster"
            return
        for key, combo in (("area_field", self.area_field), ("usage_field", self.usage_field)):
            if combo.currentField():
                buildings[key] = combo.currentField()
        if self.usage:
            buildings["usage_coefficients"] = self.usage
        if self.confidence_on.isChecked():
            buildings["min_confidence"] = self.confidence.value()
            if self.confidence_field.currentField():
                buildings["confidence_field"] = self.confidence_field.currentField()
        if self.roof_year.value() > 1899:
            buildings["year"] = self.roof_year.value()
        calibration = {"buildings": buildings, "recalibrate": self.recalibrate.isChecked()}
        strata = source_of(self.strata_layer.currentLayer())
        if strata and self.strata_field.currentField():
            strata["field"] = self.strata_field.currentField()
            for key, combo in (("group_field", self.group_field), ("census_field", self.census_field)):
                if combo.currentField():
                    strata[key] = combo.currentField()
            calibration["strata"] = strata
        census = self.census_values()
        if census:
            calibration["census"] = census
        if self.census_year.value() > 1899:
            calibration["census_year"] = self.census_year.value()
        if self.target_year.value() > 1899:
            calibration["target_year"] = self.target_year.value()
        if self.gap_rate.text().strip():
            try:
                calibration["gap_growth_rate"] = float(self.gap_rate.text().replace(",", "."))
            except ValueError:
                pass
        if self.settings:
            calibration["groups"] = {name: group.to_dict() for name, group in self.settings.items()}
        data["calibration"] = calibration
        data.setdefault("base_population", {})["source"] = "buildings" if self.use_roofs.isChecked() else "raster"

    def refresh(self):
        pass

    # --- calibration ------------------------------------------------------------------

    def compute(self, background=True):
        """Read the roofs and calibrate every group (background task in QGIS; direct in the tests)."""
        from ..engine.scenario import ScenarioError

        try:
            scenario = self.dialog.scenario()
        except ScenarioError as error:
            self._show_status("\n".join(m.render(current_language()) for m in error.messages), warn=True)
            return False
        if scenario.calibration is None:
            self._show_status(tr("calibration.no_roofs"), warn=True)
            return False
        self._show_status(tr("calibration.running"))
        self.compute_button.setEnabled(False)
        if not background:
            from ..engine.simulation import calibrate

            try:
                report, groups = calibrate(scenario)
            except Exception as error:
                self._computed(None, None, error)
                return False
            self._computed(report, groups, None)
            return True
        from qgis.core import QgsApplication

        self.task = CalibrationTask(scenario)
        self.task.done.connect(self._computed)
        QgsApplication.taskManager().addTask(self.task)
        return True

    def _computed(self, report, groups, error):
        self.task = None
        self.compute_button.setEnabled(True)
        if error is not None:
            messages = getattr(error, "messages", None)
            self._show_status("\n".join(m.render(current_language()) for m in messages) if messages else str(error),
                              warn=True)
            return
        self.report, self.groups = report, groups
        for name, entry in report["groups"].items():
            group = self.settings.get(name) or GroupSettings.from_dict(name, entry["settings"])
            if group.values_from == AREA_PER_PERSON and group.area_per_person is None:
                group.area_per_person = entry.get("area_per_person")
            self.settings[name] = group
        roofs = report["roofs"]
        self._show_status(tr("calibration.done", read=_fmt(roofs["read"]), kept=_fmt(roofs["kept"]),
                             outside=_fmt(roofs.get("outside_study_area", 0))))
        self._fill_groups()
        if self.group_table.rowCount():
            self.group_table.selectRow(0)

    def _fill_groups(self):
        names = sorted(self.groups)
        self.group_table.blockSignals(True)
        self.group_table.setRowCount(len(names))
        for row, name in enumerate(names):
            curve, entry = self.groups[name].curve(self.settings[name])
            target = self.groups[name].target
            computed = entry["population_before_recalibration"]
            cells = [tr("calibration.whole_area") if name == WHOLE_AREA else name, ", ".join(self.groups[name].strata),
                     _fmt(len(self.groups[name].areas)), _fmt(entry.get("area_per_person"), 2), _fmt(computed),
                     _fmt(target), "–" if not target else f"{entry['gap_percent']:+.2f} %".replace(".", ","),
                     "–" if not target else f"1 ({_fmt(target / computed, 3)})"]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.group_table.setItem(row, column, item)
        self.group_table.blockSignals(False)

    def _group_selected(self):
        rows = self.group_table.selectionModel().selectedRows()
        if not rows:
            return
        self.current = self.group_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        self.editor.setTitle(tr("calibration.group_title", name=self.group_table.item(rows[0].row(), 0).text()))
        self.editor.setEnabled(True)
        self._show_settings(self.settings[self.current])
        self._redraw()

    def _show_settings(self, group):
        self._building = True
        set_combo_value(self.method, group.method)
        set_combo_value(self.cut, group.cut)
        self.n_classes.setValue(group.n_classes if group.cut != MANUAL_CUT or not group.edges else len(group.edges) - 1)
        self.floor.set_spec(group.floor)
        self.ceiling.set_spec(group.ceiling)
        self.exclude_on.setChecked(group.exclude_above is not None)
        self.exclude.setValue(group.exclude_above or 450)
        self.area_per_person.setValue(group.area_per_person or 10)
        self.min_per_roof.setValue(group.min_per_roof)
        self.max_per_roof.setValue(group.max_per_roof)
        self._building = False

    def _settings_changed(self, recut):
        """A setting of the group changed: rebuild the classes (and refit) or only the values."""
        if self._building or self.current is None:
            return
        group = self.settings[self.current]
        group.method = self.method.currentData()
        group.cut = self.cut.currentData()
        group.n_classes = self.n_classes.value()
        group.floor = self.floor.spec()
        group.ceiling = self.ceiling.spec()
        group.exclude_above = self.exclude.value() if self.exclude_on.isChecked() else None
        group.min_per_roof = self.min_per_roof.value()
        group.max_per_roof = max(self.max_per_roof.value(), group.min_per_roof)
        if group.cut != MANUAL_CUT:
            group.edges = None
        elif not group.edges:                                # « manual » chosen in the list: keep the limits shown
            group.edges = tuple(self.chart.edges)
        if recut:
            group.overrides = {}
            if group.values_from == AREA_PER_PERSON and self.groups[self.current].target:
                group.area_per_person = None                 # refitted on the census, as in the mock-up
        else:
            group.area_per_person = self.area_per_person.value()
        self._redraw()

    def fit(self):
        """« Fit to the census »: the roof area per inhabitant giving the census best."""
        if self.current is None:
            return
        group = self.settings[self.current]
        group.values_from = AREA_PER_PERSON
        group.area_per_person = None
        group.overrides = {}
        self._redraw()

    def _edges_dragged(self, edges):
        if self.current is None:
            return
        group = self.settings[self.current]
        group.cut = MANUAL_CUT
        group.edges = tuple(edges)
        group.overrides = {}
        self._building = True
        set_combo_value(self.cut, MANUAL_CUT)
        self._building = False
        self._redraw()

    def _value_edited(self, item):
        if self._building or self.current is None or item.column() != 6:
            return
        group = self.settings[self.current]
        proposed = float(self.classes.item(item.row(), 5).text())
        try:
            value = float(item.text().replace(",", "."))
        except ValueError:
            return
        if value == proposed:
            group.overrides.pop(item.row(), None)
        else:
            group.overrides[item.row()] = value
        self._redraw()

    def _redraw(self):
        """Curve of the current group with its settings: chart, table of classes, totals."""
        group, data = self.settings[self.current], self.groups[self.current]
        try:
            curve, entry = data.curve(group)
        except ValueError as error:
            self.totals.setText(str(error))
            return
        if group.values_from == AREA_PER_PERSON and entry.get("area_per_person") is not None:
            group.area_per_person = entry["area_per_person"]
        self._building = True
        self.area_per_person.setValue(group.area_per_person or self.area_per_person.value())
        if group.cut != MANUAL_CUT:
            self.n_classes.setValue(len(curve.edges) - 1)
        self._building = False
        retained = entry.get("retained_values", list(curve.values))
        proposed = entry.get("proposed_values", retained)
        self.chart.set_data(data.areas, data.weights, curve.edges, retained, curve=curve)
        counts = entry.get("class_counts", [])
        means = entry.get("class_means", [])
        self._building = True
        self.classes.setRowCount(len(retained))
        for k in range(len(retained)):
            cells = [str(k + 1), _fmt(curve.edges[k], 1), _fmt(curve.edges[k + 1], 1),
                     _fmt(counts[k] if k < len(counts) else None), _fmt(means[k] if k < len(means) else None, 1),
                     f"{proposed[k]:g}", f"{retained[k]:g}"]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column != 6:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                elif k in group.overrides:
                    item.setBackground(self.palette().highlight().color().lighter(170))
                    item.setToolTip(tr("calibration.overridden"))
                self.classes.setItem(k, column, item)
        self._building = False
        population, target = entry["population_before_recalibration"], data.target
        if target:
            gap = entry["gap_percent"]
            key = "calibration.totals_alert" if abs(gap) > ALERT_PERCENT else "calibration.totals"
            self.totals.setText(tr(key, population=_fmt(population), census=_fmt(target),
                                   gap=f"{gap:+.2f}".replace(".", ","), factor=_fmt(target / population, 3),
                                   alert=_fmt(ALERT_PERCENT)))
            self.totals.setProperty("state", "warn" if abs(gap) > ALERT_PERCENT else "ok")
        else:
            self.totals.setText(tr("calibration.totals_no_census", population=_fmt(population)))
            self.totals.setProperty("state", "warn")
        self.totals.style().unpolish(self.totals)
        self.totals.style().polish(self.totals)
        self._fill_groups()
        self._update_tcam()

    def _set_view(self, view):
        self.view_distribution.setChecked(view == DISTRIBUTION)
        self.view_cumulative.setChecked(view == CUMULATIVE)
        self.chart.set_view(view)

    def _update_tcam(self):
        """TCAM suggested by a reference roof area per inhabitant (another source) over the gap of years."""
        text = self.reference.text().strip().replace(",", ".")
        roof_year, census_year = self.roof_year.value(), self.census_year.value()
        if self.current is None or not text or roof_year <= 1899 or census_year <= 1899 or roof_year == census_year:
            self.tcam.setText(tr("calibration.tcam_none"))
            return
        try:
            reference = float(text)
        except ValueError:
            return
        group, data = self.settings[self.current], self.groups[self.current]
        if not data.target:
            return
        probe = GroupSettings.from_dict(self.current, dict(group.to_dict(), area_per_person=reference, overrides={}))
        _, entry = data.curve(probe)
        rate = ((data.target / entry["population_before_recalibration"]) ** (1 / (census_year - roof_year)) - 1) * 100
        self.tcam.setText(tr("calibration.tcam", rate=f"{rate:.1f}".replace(".", ","), reference=_fmt(reference, 1)))

    # --- export / import of a calibration ------------------------------------------------

    def export_calibration(self, path=None):
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, tr("calibration.export"), "calibration.json", "JSON (*.json)")
            if not path:
                return None
        data = {name: group.to_dict() for name, group in self.settings.items()}
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"groups": data}, handle, ensure_ascii=False, indent=2)
        return path

    def import_calibration(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("calibration.import"), "", "JSON (*.json)")
            if not path:
                return
        try:
            with open(path, encoding="utf-8") as handle:
                groups = json.load(handle).get("groups", {})
            self.settings.update({name: GroupSettings.from_dict(name, spec) for name, spec in groups.items()})
        except (OSError, ValueError, AttributeError) as error:
            QMessageBox.warning(self, tr("calibration.import"), str(error))
            return
        if self.current in self.settings and self.current in self.groups:
            self._show_settings(self.settings[self.current])
            self._redraw()
