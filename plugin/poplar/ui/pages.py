"""Tabs of the main window. Each page reads and writes its part of the scenario (a dict).

The dict follows the scenario file format of the engine (see engine/scenario.py),
so the window, the Processing algorithm and the command line share one format.
"""

import os

from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.gui import QgsFileWidget, QgsMapLayerComboBox, QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from ..compat import POLYGON_FILTER, RASTER_FILTER, VECTOR_FILTER, needs_buffer
from ..engine.crs import AUTO_EQUAL_AREA, AUTO_UTM, is_metric_projected
from ..engine.i18n import available_languages
from ..i18n import tip, tr
from ..engine import runs
from ..results import QUANTITIES, available_outputs
from .widgets import (
    add_row, choice_combo, find_or_add_layer, format_series, layer_with_field, parse_series, set_combo_value,
    source_of,
)


class Page(QWidget):
    key = ""

    def load(self, data: dict) -> None:
        """Show the values of the scenario."""

    def store(self, data: dict) -> None:
        """Write the values shown into the scenario."""

    def refresh(self) -> None:
        """Called each time the page is shown."""


def _box(title_key: str) -> tuple:
    box = QGroupBox(tr(title_key))
    form = QFormLayout(box)
    return box, form


def _spin(minimum, maximum, value=0, decimals=None, step=1.0):
    spin = QDoubleSpinBox() if decimals is not None else QSpinBox()
    if decimals is not None:
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    return spin


# --- Scenario -----------------------------------------------------------------------

class ScenarioPage(Page):
    key = "scenario"

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        layout = QVBoxLayout(self)
        box, form = _box("scenario.box")
        self.name = QLineEdit()
        add_row(form, "scenario.name", self.name)
        self.language = choice_combo([(code, tr(f"language.{code}")) for code in available_languages()])
        add_row(form, "scenario.language", self.language)
        self.output = QgsFileWidget()
        self.output.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        add_row(form, "scenario.output", self.output)
        layout.addWidget(box)

        box, form = _box("grid.box")
        self.cell = _spin(10, 100_000, 250, decimals=1, step=50)
        self.cell.setSuffix(" m")
        add_row(form, "grid.cell_size", self.cell)
        self.unit = choice_combo([("hab/km2", "hab/km²"), ("hab/ha", "hab/ha")])
        add_row(form, "grid.density_unit", self.unit)
        self.crs_mode = choice_combo([
            ("project", tr("crs.project")), (AUTO_UTM, tr("crs.auto_utm")),
            (AUTO_EQUAL_AREA, tr("crs.auto_equal_area")), ("custom", tr("crs.custom")),
        ])
        add_row(form, "grid.crs", self.crs_mode)
        self.crs = QgsProjectionSelectionWidget()
        self.crs.setEnabled(False)
        self.crs_mode.currentIndexChanged.connect(lambda: self.crs.setEnabled(self.crs_mode.currentData() == "custom"))
        form.addRow("", self.crs)
        self.crs_note = QLabel()
        self.crs_note.setWordWrap(True)
        form.addRow("", self.crs_note)
        layout.addWidget(box)
        layout.addStretch(1)

    def load(self, data):
        self.name.setText(data.get("name", ""))
        set_combo_value(self.language, data.get("language", "fr"))
        self.output.setFilePath(self.dialog.absolute(data.get("output", {}).get("directory", "")))
        self.cell.setValue(float(data.get("cell_size", 250)))
        set_combo_value(self.unit, data.get("density_unit", "hab/km2"))
        crs = data.get("crs")
        if crs in (AUTO_UTM, AUTO_EQUAL_AREA):
            set_combo_value(self.crs_mode, crs)
        elif crs:
            set_combo_value(self.crs_mode, "custom")
            self.crs.setCrs(QgsCoordinateReferenceSystem(crs))
        else:
            set_combo_value(self.crs_mode, "project")

    def store(self, data):
        data["name"] = self.name.text().strip()
        data["language"] = self.language.currentData()
        output = data.setdefault("output", {})
        output["directory"] = self.output.filePath()
        output["per_run"] = True  # one time-stamped folder per run: nothing is overwritten (29/09/2026)
        data["cell_size"] = self.cell.value()
        data["density_unit"] = self.unit.currentData()
        mode = self.crs_mode.currentData()
        if mode == "project":
            project_crs = QgsProject.instance().crs()
            if project_crs.isValid() and is_metric_projected(project_crs.toWkt()):
                data["crs"] = project_crs.authid() or project_crs.toWkt()
            else:
                data.pop("crs", None)  # the engine chooses: raster CRS if metric, else UTM
        elif mode == "custom":
            data["crs"] = self.crs.crs().authid() or self.crs.crs().toWkt()
        else:
            data["crs"] = mode

    def refresh(self):
        project_crs = QgsProject.instance().crs()
        if project_crs.isValid() and is_metric_projected(project_crs.toWkt()):
            self.crs_note.setText(tr("crs.project_note", crs=project_crs.authid()))
        else:
            self.crs_note.setText(tr("crs.project_not_metric"))


# --- Data ---------------------------------------------------------------------------

BEHAVIOURS = ["no_inflow", "relocate", "outside"]


class DataPage(Page):
    key = "data"

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        layout = QVBoxLayout(self)

        box, form = _box("data.territory")
        self.study = QgsMapLayerComboBox()
        self.study.setFilters(POLYGON_FILTER)
        add_row(form, "data.study_area", self.study)
        widget, self.typology, self.typology_field = layer_with_field(POLYGON_FILTER)
        add_row(form, "data.typology", widget)
        widget, self.admin, self.admin_field = layer_with_field(POLYGON_FILTER, allow_empty=True)
        add_row(form, "data.admin_units", widget)
        widget, self.zones, self.zones_field = layer_with_field(POLYGON_FILTER, allow_empty=True)
        add_row(form, "data.parameter_zones", widget)
        layout.addWidget(box)

        box, form = _box("data.population")
        self.raster = QgsMapLayerComboBox()
        self.raster.setFilters(RASTER_FILTER)
        add_row(form, "data.raster", self.raster)
        self.value_type = choice_combo([("density", tr("data.value_type.density")),
                                        ("count", tr("data.value_type.count"))])
        add_row(form, "data.value_type", self.value_type)
        self.boundary = choice_combo([("area_weighted", tr("data.boundary.area_weighted")),
                                      ("renormalized", tr("data.boundary.renormalized"))])
        add_row(form, "data.boundary", self.boundary)
        roofs = QLabel(tr("data.roofs_phase6"))
        roofs.setEnabled(False)
        add_row(form, "data.roofs", roofs)
        layout.addWidget(box)

        box = QGroupBox(tr("data.exclusions"))
        box.setToolTip(tip("data.exclusions"))
        inner = QVBoxLayout(box)
        self.exclusions = QTableWidget(0, 5)
        self.exclusions.setHorizontalHeaderLabels([tr("data.exclusions.name"), tr("data.exclusions.layer"),
                                                   tr("data.exclusions.behaviour"), tr("data.exclusions.year"),
                                                   tr("data.exclusions.buffer")])
        self.exclusions.horizontalHeaderItem(2).setToolTip(tip("data.exclusions.behaviour"))
        self.exclusions.horizontalHeaderItem(4).setToolTip(tip("data.exclusions.buffer"))
        header = self.exclusions.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.exclusions.setMinimumHeight(110)
        inner.addWidget(self.exclusions)
        buttons = QHBoxLayout()
        add = QPushButton(tr("common.add"))
        add.clicked.connect(lambda: self._add_exclusion({}))
        remove = QPushButton(tr("common.remove"))
        remove.clicked.connect(lambda: self.exclusions.removeRow(self.exclusions.currentRow()))
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        inner.addLayout(buttons)
        layout.addWidget(box)

        box, form = _box("data.projections")
        self.projections = QgsFileWidget()
        self.projections.setFilter("CSV (*.csv)")
        add_row(form, "data.projections.file", self.projections)
        self.projection_use = choice_combo([("compare", tr("data.projections.compare")),
                                            ("recalibrate", tr("data.projections.recalibrate")),
                                            ("start", tr("data.projections.start"))])
        add_row(form, "data.projections.use", self.projection_use)
        self.start_year = _spin(1900, 2200, 2026)
        add_row(form, "data.projections.start_year", self.start_year)
        layout.addWidget(box)

    def _add_exclusion(self, item):
        row = self.exclusions.rowCount()
        self.exclusions.insertRow(row)
        self.exclusions.setItem(row, 0, QTableWidgetItem(item.get("name", "")))
        layers = QgsMapLayerComboBox()
        layers.setFilters(VECTOR_FILTER)
        layer = find_or_add_layer(self.dialog.absolute(item.get("source")), item.get("layer"))
        if layer is not None:
            layers.setLayer(layer)
        self.exclusions.setCellWidget(row, 1, layers)
        behaviour = choice_combo([(b, tr(f"behaviour.{b}")) for b in BEHAVIOURS], item.get("behaviour", "no_inflow"))
        behaviour.setToolTip(tip("data.exclusions.behaviour"))
        self.exclusions.setCellWidget(row, 2, behaviour)
        year = item.get("year")
        self.exclusions.setItem(row, 3, QTableWidgetItem("" if year is None else f"{year:g}"))
        buffer = item.get("buffer_m")
        self.exclusions.setItem(row, 4, QTableWidgetItem("" if buffer is None else f"{buffer:g}"))

    def exclusions_without_buffer(self):
        """Names of the exclusion layers made of lines or points that have no buffer width."""
        names = []
        for row in range(self.exclusions.rowCount()):
            layer = self.exclusions.cellWidget(row, 1).currentLayer()
            buffer = self.exclusions.item(row, 4).text().strip() if self.exclusions.item(row, 4) else ""
            if layer is not None and needs_buffer(layer) and not buffer:
                name = self.exclusions.item(row, 0).text() if self.exclusions.item(row, 0) else ""
                names.append(name or layer.name())
        return names

    def load(self, data):
        def select(combo, spec, raster=False):
            if spec:
                layer = find_or_add_layer(self.dialog.absolute(spec.get("source")), spec.get("layer"), raster)
                if layer is not None:
                    combo.setLayer(layer)

        select(self.study, data.get("study_area"))
        select(self.typology, data.get("typology"))
        self.typology_field.setField((data.get("typology") or {}).get("field", ""))
        select(self.admin, data.get("admin_units"))
        self.admin_field.setField((data.get("admin_units") or {}).get("field", ""))
        select(self.zones, data.get("parameter_zones"))
        self.zones_field.setField((data.get("parameter_zones") or {}).get("field", ""))
        population = data.get("base_population") or {}
        if population.get("raster"):
            layer = find_or_add_layer(self.dialog.absolute(population["raster"]), raster=True)
            if layer is not None:
                self.raster.setLayer(layer)
        set_combo_value(self.value_type, population.get("value_type", "density"))
        set_combo_value(self.boundary, population.get("boundary_mode", "area_weighted"))
        self.exclusions.setRowCount(0)
        for item in data.get("exclusions", []):
            self._add_exclusion(item)
        projections = data.get("projections") or {}
        self.projections.setFilePath(self.dialog.absolute(projections.get("csv", "")))
        time = data.get("time", {})
        if time.get("start_mode") == "projection":
            set_combo_value(self.projection_use, "start")
            self.start_year.setValue(int(time.get("start_year") or 2026))
        elif projections.get("recalibrate"):
            set_combo_value(self.projection_use, "recalibrate")

    def store(self, data):
        data["study_area"] = source_of(self.study.currentLayer())
        typology = source_of(self.typology.currentLayer())
        if typology:
            typology["field"] = self.typology_field.currentField()
        data["typology"] = typology
        for key, combo, field in (("admin_units", self.admin, self.admin_field),
                                  ("parameter_zones", self.zones, self.zones_field)):
            spec = source_of(combo.currentLayer())
            if spec:
                spec["field"] = field.currentField()
                data[key] = spec
            else:
                data.pop(key, None)
        raster = self.raster.currentLayer()
        data["base_population"] = {
            "raster": source_of(raster)["source"] if raster else "",
            "value_type": self.value_type.currentData(),
            "boundary_mode": self.boundary.currentData(),
        }
        exclusions = []
        for row in range(self.exclusions.rowCount()):
            spec = source_of(self.exclusions.cellWidget(row, 1).currentLayer())
            if not spec:
                continue
            spec["name"] = self.exclusions.item(row, 0).text() if self.exclusions.item(row, 0) else ""
            spec["behaviour"] = self.exclusions.cellWidget(row, 2).currentData()
            year = (self.exclusions.item(row, 3).text() if self.exclusions.item(row, 3) else "").strip()
            buffer = (self.exclusions.item(row, 4).text() if self.exclusions.item(row, 4) else "").strip()
            if year:
                spec["year"] = float(year)
            if buffer:
                spec["buffer_m"] = float(buffer.replace(",", "."))
            exclusions.append(spec)
        data["exclusions"] = exclusions
        time = data.setdefault("time", {})
        path = self.projections.filePath()
        use = self.projection_use.currentData()
        if path:
            data["projections"] = {"csv": path, "recalibrate": use == "recalibrate"}
        else:
            data.pop("projections", None)
        if path and use == "start":
            time["start_mode"] = "projection"
            time["start_year"] = self.start_year.value()
        else:
            time["start_mode"] = "census"
            time.pop("start_year", None)


# --- Parameters ---------------------------------------------------------------------

PARAMETERS = ["growth_rate", "dmax"]


class ParametersPage(Page):
    key = "parameters"

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        layout = QVBoxLayout(self)

        box, form = _box("time.box")
        self.base_year = _spin(1900, 2200, 2024)
        add_row(form, "time.base_year", self.base_year)
        self.end_year = _spin(1900, 2300, 2060)
        add_row(form, "time.end_year", self.end_year)
        self.step = _spin(0.1, 50, 5, decimals=1, step=1)
        self.step.setSuffix(tr("time.years_suffix"))
        add_row(form, "time.time_step", self.step)
        self.outputs = QLineEdit()
        self.outputs.setPlaceholderText(tr("time.output_years.placeholder"))
        add_row(form, "time.output_years", self.outputs)
        self.frequency = choice_combo([("annual", tr("time.frequency.annual")),
                                       ("time_step", tr("time.frequency.time_step"))])
        add_row(form, "time.frequency", self.frequency)
        self.first_migration = _spin(1900, 2300, 2025)
        add_row(form, "time.first_migration_year", self.first_migration)
        layout.addWidget(box)

        box = QGroupBox(tr("parameters.box"))
        box.setToolTip(tip("parameters.box"))
        inner = QVBoxLayout(box)
        self.table = QTableWidget(0, 3)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(170)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        inner.addWidget(self.table)
        buttons = QHBoxLayout()
        for key, slot in (("parameters.add_row", self._add_row_clicked), ("parameters.add_year", self._add_year),
                          ("common.remove", lambda: self.table.removeRow(self.table.currentRow()))):
            button = QPushButton(tr(key))
            button.clicked.connect(slot)
            buttons.addWidget(button)
        self.extrapolation = choice_combo([("constant", tr("parameters.extrapolation.constant")),
                                           ("linear", tr("parameters.extrapolation.linear"))])
        self.extrapolation.setToolTip(tip("parameters.extrapolation"))
        buttons.addStretch(1)
        buttons.addWidget(QLabel(tr("parameters.extrapolation")))
        buttons.addWidget(self.extrapolation)
        inner.addLayout(buttons)
        note = QLabel(tr("parameters.note"))
        note.setWordWrap(True)
        inner.addWidget(note)
        layout.addWidget(box)

        box, form = _box("migration.box")
        self.k = _spin(1, 50, 3)
        add_row(form, "migration.k", self.k)
        self.tolerance = _spin(1, 1000, 1)
        add_row(form, "migration.tolerance", self.tolerance)
        self.policy = choice_combo([(p, tr(f"policy.{p}")) for p in ("stop", "raise_dmax", "sink", "unallocated")])
        add_row(form, "migration.policy", self.policy)
        self.max_increase = _spin(0, 500, 0, decimals=0, step=5)
        self.max_increase.setSuffix(" %")
        add_row(form, "migration.max_auto_increase", self.max_increase)
        self.sink_width = _spin(1, 50, 4)
        add_row(form, "migration.sink_width_cells", self.sink_width)
        layout.addWidget(box)
        self.years = []
        self._set_headers()

    # Table: key | parameter | constant | pivot years...
    def _set_headers(self):
        self.table.setColumnCount(3 + len(self.years))
        headers = [tr("parameters.key"), tr("parameters.parameter"), tr("parameters.constant")] + \
                  [f"{y:g}" for y in self.years]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeaderItem(0).setToolTip(tip("parameters.key"))

    def _add_year(self):
        year, ok = QInputDialog.getInt(self, tr("parameters.add_year"), tr("parameters.year"), 2040, 1900, 2300)
        if ok and year not in self.years:
            self._insert_year(float(year))

    def _insert_year(self, year):
        values = self._read_rows()
        self.years = sorted(set(self.years) | {year})
        self._fill(values)

    def _add_row_clicked(self):
        self._append_row("*", "growth_rate", None)

    def _append_row(self, key, parameter, value):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(key))
        combo = choice_combo([(p, tr(f"parameter.{p}")) for p in PARAMETERS], parameter)
        self.table.setCellWidget(row, 1, combo)
        if isinstance(value, dict):
            for year, v in value.items():
                column = 3 + self.years.index(float(year))
                self.table.setItem(row, column, QTableWidgetItem(f"{v:g}"))
        elif value is not None:
            self.table.setItem(row, 2, QTableWidgetItem(f"{value:g}"))

    def _read_rows(self):
        rows = []
        for row in range(self.table.rowCount()):
            key = self.table.item(row, 0).text().strip() if self.table.item(row, 0) else "*"
            parameter = self.table.cellWidget(row, 1).currentData()
            cells = {}
            for column in range(2, self.table.columnCount()):
                item = self.table.item(row, column)
                if item and item.text().strip():
                    cells[column] = float(item.text().replace(",", ".").replace(" ", "").replace(" ", ""))
            if 2 in cells:
                value = cells[2]
            elif cells:
                value = {f"{self.years[c - 3]:g}": v for c, v in sorted(cells.items())}
            else:
                value = None
            rows.append((key or "*", parameter, value))
        return rows

    def _fill(self, rows):
        self.table.setRowCount(0)
        self._set_headers()
        for key, parameter, value in rows:
            self._append_row(key, parameter, value)

    def load(self, data):
        time = data.get("time", {})
        self.base_year.setValue(int(time.get("base_year", 2024)))
        self.end_year.setValue(int(time.get("end_year", 2060)))
        self.step.setValue(float(time.get("time_step", 5)))
        years = time.get("output_years")
        self.outputs.setText(", ".join(f"{y:g}" for y in years) if years else "")
        set_combo_value(self.frequency, time.get("migration_frequency", "annual"))
        self.first_migration.setValue(int(time.get("first_migration_year") or time.get("base_year", 2024) + 1))
        parameters = data.get("parameters", {})
        rows, years = [], set()
        for parameter in PARAMETERS:
            spec = parameters.get(parameter)
            if isinstance(spec, (int, float)):
                rows.append(("*", parameter, spec))
            elif isinstance(spec, dict):
                for key, value in spec.items():
                    if isinstance(value, dict):
                        years |= {float(y) for y in value}
                    rows.append((key, parameter, value))
        self.years = sorted(years)
        self._fill(rows)
        set_combo_value(self.extrapolation, data.get("extrapolation", "constant"))
        migration = data.get("migration", {})
        self.k.setValue(int(migration.get("k", 3)))
        self.tolerance.setValue(int(migration.get("tolerance", 1)))
        set_combo_value(self.policy, migration.get("policy", "stop"))
        self.max_increase.setValue(100 * float(migration.get("max_auto_increase", 0)))
        self.sink_width.setValue(int(migration.get("sink_width_cells", 4)))

    def store(self, data):
        time = data.setdefault("time", {})
        time.update({
            "base_year": self.base_year.value(), "end_year": self.end_year.value(), "time_step": self.step.value(),
            "migration_frequency": self.frequency.currentData(), "first_migration_year": self.first_migration.value(),
        })
        text = self.outputs.text().replace(";", ",").strip()
        if text:
            time["output_years"] = [float(y) for y in text.split(",") if y.strip()]
        else:
            time.pop("output_years", None)
        parameters = {k: v for k, v in data.get("parameters", {}).items() if k not in PARAMETERS}
        for key, parameter, value in self._read_rows():
            if value is not None:
                parameters.setdefault(parameter, {})[key] = value
        data["parameters"] = parameters
        data["extrapolation"] = self.extrapolation.currentData()
        data["migration"] = {
            "k": self.k.value(), "tolerance": self.tolerance.value(), "policy": self.policy.currentData(),
            "max_auto_increase": self.max_increase.value() / 100.0, "sink_width_cells": self.sink_width.value(),
        }


# --- Indicators ---------------------------------------------------------------------

WATER_PARAMETERS = ["water_per_capita", "non_domestic_share", "non_domestic_volume", "network_efficiency",
                    "peak_day_factor", "peak_hour_factor"]


class IndicatorsPage(Page):
    key = "indicators"

    def __init__(self, dialog):
        super().__init__()
        layout = QVBoxLayout(self)
        box = QGroupBox(tr("water.box"))
        inner = QVBoxLayout(box)
        self.enabled = QCheckBox(tr("water.enabled"))
        self.enabled.setToolTip(tip("water.enabled"))
        inner.addWidget(self.enabled)
        self.table = QTableWidget(0, 1 + len(WATER_PARAMETERS))
        self.table.setMinimumHeight(120)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setHorizontalHeaderLabels([tr("parameters.key")] + [tr(f"water.{p}") for p in WATER_PARAMETERS])
        for i, p in enumerate(WATER_PARAMETERS, start=1):
            self.table.horizontalHeaderItem(i).setToolTip(tip(f"water.{p}"))
        inner.addWidget(self.table)
        buttons = QHBoxLayout()
        add = QPushButton(tr("common.add"))
        add.clicked.connect(lambda: self._row("*", {}))
        remove = QPushButton(tr("common.remove"))
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        inner.addLayout(buttons)
        note = QLabel(tr("water.note"))
        note.setWordWrap(True)
        inner.addWidget(note)
        layout.addWidget(box)
        other = QLabel(tr("indicators.other"))
        other.setWordWrap(True)
        other.setEnabled(False)
        layout.addWidget(other)
        layout.addStretch(1)

    def _row(self, key, values):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(key))
        for i, p in enumerate(WATER_PARAMETERS, start=1):
            self.table.setItem(row, i, QTableWidgetItem(format_series(values.get(p))))

    def load(self, data):
        self.table.setRowCount(0)
        water = next((i for i in data.get("indicators", []) if i.get("type") == "water"), None)
        self.enabled.setChecked(water is not None)
        if water is None:
            self._row("*", {"water_per_capita": 20.0})
            return
        # Same format as the other parameters: a number, or {class or zone: number or {year: value}}.
        by_key = {}
        for p, spec in water.get("parameters", {}).items():
            if isinstance(spec, dict):
                for key, value in spec.items():
                    by_key.setdefault(key, {})[p] = value
            else:
                by_key.setdefault("*", {})[p] = spec
        for key, values in by_key.items():
            self._row(key, values)

    def store(self, data):
        indicators = [i for i in data.get("indicators", []) if i.get("type") != "water"]
        if self.enabled.isChecked():
            parameters = {}
            for row in range(self.table.rowCount()):
                key = self.table.item(row, 0).text().strip() or "*"
                for i, p in enumerate(WATER_PARAMETERS, start=1):
                    value = parse_series(self.table.item(row, i).text() if self.table.item(row, i) else "")
                    if value is not None:
                        parameters.setdefault(p, {})[key] = value
            indicators.append({"type": "water", "parameters": parameters})
        data["indicators"] = indicators


# --- Calibration (phase 6) ----------------------------------------------------------

class CalibrationPage(Page):
    key = "calibration"

    def __init__(self, dialog):
        super().__init__()
        layout = QVBoxLayout(self)
        text = QLabel(tr("calibration.phase6"))
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addStretch(1)


# --- Run ----------------------------------------------------------------------------

class RunPage(Page):
    key = "run"

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        layout = QVBoxLayout(self)
        box = QGroupBox(tr("run.checks"))
        inner = QVBoxLayout(box)
        self.checks = QListWidget()
        inner.addWidget(self.checks)
        check = QPushButton(tr("run.check_button"))
        check.clicked.connect(dialog.check)
        inner.addWidget(check, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(box)

        box = QGroupBox(tr("run.box"))
        inner = QVBoxLayout(box)
        buttons = QHBoxLayout()
        self.run_button = QPushButton(tr("run.run"))
        self.run_button.setToolTip(tip("run.run"))
        self.run_button.clicked.connect(dialog.run)
        self.cancel_button = QPushButton(tr("run.cancel"))
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(dialog.cancel)
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        inner.addLayout(buttons)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        inner.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        inner.addWidget(self.log)
        layout.addWidget(box)

    def show_checks(self, items):
        self.checks.clear()
        for ok, text in items:
            item = QListWidgetItem(("✔ " if ok else "✖ ") + text)
            self.checks.addItem(item)

    def running(self, active: bool):
        self.run_button.setEnabled(not active)
        self.cancel_button.setEnabled(active)
        if active:
            self.progress.setValue(0)


# --- Results ------------------------------------------------------------------------

class ResultsPage(Page):
    key = "results"

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        layout = QVBoxLayout(self)
        box = QGroupBox(tr("results.runs"))
        inner = QVBoxLayout(box)
        self.run_list = QComboBox()
        self.run_list.setToolTip(tip("results.run"))
        self.run_list.activated.connect(self._run_chosen)
        inner.addWidget(self.run_list)
        row = QHBoxLayout()
        self.kept = QCheckBox(tr("results.kept"))
        self.kept.setToolTip(tip("results.kept"))
        self.kept.toggled.connect(self._keep)
        self.label = QLineEdit()
        self.label.setPlaceholderText(tr("results.label.placeholder"))
        self.label.setToolTip(tip("results.label"))
        self.label.editingFinished.connect(self._keep)
        clean = QPushButton(tr("results.clean"))
        clean.setToolTip(tip("results.clean"))
        clean.clicked.connect(self._clean)
        row.addWidget(self.kept)
        row.addWidget(self.label, 1)
        row.addWidget(clean)
        inner.addLayout(row)
        self.folder = QLabel()
        self.folder.setWordWrap(True)
        inner.addWidget(self.folder)
        layout.addWidget(box)

        lists = QHBoxLayout()
        self.quantities = QListWidget()
        self.years = QListWidget()
        lists.addWidget(self.quantities)
        lists.addWidget(self.years)
        layout.addLayout(lists)
        buttons = QHBoxLayout()
        load = QPushButton(tr("results.load"))
        load.setToolTip(tip("results.load"))
        load.clicked.connect(self._load)
        table = QPushButton(tr("results.open_table"))
        table.clicked.connect(lambda: self._open("summary.csv"))
        folder = QPushButton(tr("results.open_folder"))
        folder.clicked.connect(lambda: self._open(""))
        for button in (load, table, folder):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def refresh(self):
        from .cleanup_dialog import run_title

        directory = self.dialog.results_directory()
        self.run_list.clear()
        for run in reversed(runs.list_runs(self.dialog.output_directory())):
            text = f"{run_title(run)} · {tr(f'cleanup.status.{run.status}')}" + (" ★" if run.kept else "")
            self.run_list.addItem(text, run.directory)
        set_combo_value(self.run_list, directory)
        run = runs.read_run(directory) if directory else None
        for widget in (self.kept, self.label):
            widget.blockSignals(True)
            widget.setEnabled(run is not None)
        self.kept.setChecked(bool(run and run.kept))
        self.label.setText(run.label if run else "")
        for widget in (self.kept, self.label):
            widget.blockSignals(False)
        self.folder.setText(tr("results.folder", folder=directory or "—"))
        outputs = available_outputs(directory)
        self.quantities.clear()
        self.years.clear()
        for quantity in QUANTITIES:
            if quantity in outputs:
                item = QListWidgetItem(tr(f"quantity.{quantity}"))
                item.setData(Qt.ItemDataRole.UserRole, quantity)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if quantity in ("population", "density")
                                   else Qt.CheckState.Unchecked)
                self.quantities.addItem(item)
        years = outputs.get("population", [])
        for i, year in enumerate(years):
            item = QListWidgetItem(year)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if i in (0, len(years) - 1) else Qt.CheckState.Unchecked)
            self.years.addItem(item)

    def _run_chosen(self, index):
        self.dialog.selected_run = self.run_list.itemData(index)
        self.refresh()

    def _keep(self, *args):
        directory = self.dialog.results_directory()
        if runs.read_run(directory) is None:
            return
        runs.set_kept(directory, self.kept.isChecked(), self.label.text().strip())
        index = self.run_list.currentIndex()
        self.refresh()
        self.run_list.setCurrentIndex(index)

    def _clean(self):
        self.dialog.clean_up()
        self.refresh()

    def _checked(self, widget, role=None):
        values = []
        for i in range(widget.count()):
            item = widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                values.append(item.data(role) if role is not None else item.text())
        return values

    def _load(self):
        quantities = self._checked(self.quantities, Qt.ItemDataRole.UserRole)
        years = self._checked(self.years)
        self.dialog.load_results(quantities, years)

    def _open(self, name):
        path = os.path.join(self.dialog.results_directory() or "", name)
        if os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))


# --- Report -------------------------------------------------------------------------

class ReportPage(Page):
    key = "report"

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        layout = QVBoxLayout(self)
        self.text = QTextBrowser()
        layout.addWidget(self.text)

    def refresh(self):
        path = os.path.join(self.dialog.results_directory() or "", "report.txt")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                self.text.setPlainText(handle.read())
        else:
            self.text.setPlainText(tr("report.none"))
