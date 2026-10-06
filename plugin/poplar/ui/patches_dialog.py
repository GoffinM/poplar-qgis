"""Window « Prepare the built-up patches » (decision D1, docs/maquette_strates.html).

The starting population is computed once, in the background (the grid is cut as for a run); the patches
are then found again at each change of the settings, at once, and drawn on a small map. « Use these
patches » writes ``typologie_taches.gpkg`` next to the scenario (or in the results folder while the scenario
has not been saved) and switches the scenario to it, after confirmation; the Strata tab can go back.
"""

import json
import os
from dataclasses import asdict

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QImage, QPixmap
from qgis.PyQt.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..engine.i18n import format_number
from ..engine.patches import GPKG, REPORT, PatchRules, apply_patches, find_patches, write_typology
from ..i18n import current_language, tip, tr
from .style import stylesheet, tokens
from .widgets import add_row, choice_combo

COLOURS = {"light": {"": None, "Rural": "#e5ece9", "Transition": "#f1dfbd", "Urbain2": "#c98a36", "urban": "#1f6f6a"},
           "dark": {"": None, "Rural": "#2e3b38", "Transition": "#6b5634", "Urbain2": "#e0a85a", "urban": "#4fa9a1"}}


class StartingPopulationTask(QgsTask):
    """Cuts the grid and computes the starting population of the scenario (the slow part)."""

    done = pyqtSignal(object, object)

    def __init__(self, scenario, description):
        super().__init__(description, QgsTask.Flag.CanCancel)
        self.scenario = scenario
        self.model = None
        self.error = None

    def run(self):
        from ..engine.simulation import _Model

        try:
            self.model = _Model.load(self.scenario)
        except Exception as error:  # reported in the window
            self.error = error.with_traceback(None)
        return self.error is None

    def finished(self, ok):
        self.done.emit(self.model, self.error)


class PatchesDialog(QDialog):
    def __init__(self, main, background=True):
        super().__init__(main)
        self.main = main
        self.model = None
        self.scenario = None
        self.result = None
        self.rules = None
        self.setWindowTitle(tr("patches.title"))
        self.colours = tokens(self)
        self.setStyleSheet(stylesheet(self.colours))
        self.resize(920, 660)
        layout = QVBoxLayout(self)
        self.status = QLabel(tr("patches.loading"))
        self.status.setObjectName("chip")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        top = QHBoxLayout()
        box = QGroupBox(tr("patches.settings"))
        form = QFormLayout(box)
        self.density = QSpinBox()
        self.density.setRange(100, 100000)
        self.density.setSingleStep(100)
        self.density.setValue(1500)
        self.density.setSuffix(" hab/km²")
        add_row(form, "patches.density", self.density)
        self.population = QSpinBox()
        self.population.setRange(100, 10000000)
        self.population.setSingleStep(500)
        self.population.setValue(5000)
        add_row(form, "patches.min_population", self.population)
        self.second = QCheckBox(tr("patches.second"))
        self.second.setToolTip(tip("patches.second"))
        self.second_population = QSpinBox()
        self.second_population.setRange(100, 10000000)
        self.second_population.setSingleStep(500)
        self.second_population.setValue(2000)
        form.addRow(self.second, self.second_population)
        self.outside = choice_combo([(False, tr("patches.outside.urban")), (True, tr("patches.outside.ignored"))])
        add_row(form, "patches.outside", self.outside)
        self.urban = QLabel("—")
        add_row(form, "patches.urban_classes", self.urban)
        smoothing = QLabel(tr("patches.smoothing.value"))
        smoothing.setWordWrap(True)
        add_row(form, "patches.smoothing", smoothing)
        self.totals = QLabel()
        self.totals.setWordWrap(True)
        form.addRow(self.totals)
        top.addWidget(box, 1)
        right = QVBoxLayout()
        self.map = QLabel()
        self.map.setMinimumSize(320, 280)
        self.map.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(self.map, 1)
        self.key = QLabel()
        right.addWidget(self.key)
        top.addLayout(right, 1)
        layout.addLayout(top, 1)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([tr(f"patches.column.{c}") for c in
                                              ("number", "class", "cells", "area", "population", "inside")])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setMaximumHeight(170)
        layout.addWidget(self.table)
        hint = QLabel(tr("patches.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(tr("common.cancel"))
        cancel.clicked.connect(self.reject)
        self.use = QPushButton(tr("patches.use"))
        self.use.setObjectName("primary")
        self.use.setToolTip(tip("patches.use"))
        self.use.clicked.connect(self.apply)
        self.use.setEnabled(False)
        buttons.addWidget(cancel)
        buttons.addWidget(self.use)
        layout.addLayout(buttons)

        for widget in (self.density, self.population, self.second_population):
            widget.valueChanged.connect(lambda *args: self.update_preview())
        self.second.toggled.connect(lambda *args: self.update_preview())
        self.outside.currentIndexChanged.connect(lambda *args: self.update_preview())
        self._enable(False)
        self.start(background)

    # --- starting population ---------------------------------------------------------

    def start(self, background=True):
        try:
            self.scenario = self.main.scenario()
        except Exception as error:
            messages = getattr(error, "messages", None)
            text = "\n".join(m.render(current_language()) for m in messages) if messages else str(error)
            self.status.setProperty("state", "warn")
            self.status.setText(tr("patches.scenario_error", error=text))
            return
        self.task = StartingPopulationTask(self.scenario, tr("patches.task"))
        self.task.done.connect(self._loaded)
        if background:
            QgsApplication.taskManager().addTask(self.task)
        else:
            self.task.finished(self.task.run())

    def _loaded(self, model, error):
        self.task = None
        if error is not None:
            self.status.setProperty("state", "warn")
            self.status.setText(tr("patches.scenario_error", error=error))
            return
        self.model = model
        self.status.setText(tr("patches.ready", population=format_number(float(model.p0.sum()), current_language(), 0)))
        self._enable(True)
        self.update_preview()

    def _enable(self, on):
        for widget in (self.density, self.population, self.second, self.second_population, self.outside):
            widget.setEnabled(on)
        self.use.setEnabled(on and bool(self.result and self.result.patches))

    # --- preview ---------------------------------------------------------------------

    def current_rules(self) -> PatchRules:
        return PatchRules(float(self.density.value()), float(self.population.value()),
                          float(self.second_population.value()) if self.second.isChecked() else None,
                          inside_only=bool(self.outside.currentData()))

    def update_preview(self):
        if self.model is None:
            return
        self.rules = self.current_rules()
        self.result = find_patches(self.model.units, self.model.p0, self.rules)
        self.urban.setText(", ".join(self.result.urban_classes))
        self._draw()
        language = current_language()
        patches = sorted(self.result.patches, key=lambda p: -p.population)
        self.table.setRowCount(0)
        for i, patch in enumerate(patches):
            self.table.insertRow(i)
            inside = (f"{format_number(100 * patch.inside_share, language, 0)} %" if patch.inside_share >= 0.5
                      else tr("patches.outside_commune"))
            for j, value in enumerate((str(i + 1), patch.stratum, str(patch.cells),
                                       format_number(patch.area_km2, language, 2),
                                       format_number(patch.population, language, 0), inside)):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, j, item)
        area = sum(p.area_km2 for p in patches)
        people = sum(p.population for p in patches)
        total = float(self.model.p0.sum()) or 1.0
        self.totals.setText(tr("patches.totals", count=len(patches), area=format_number(area, language, 1),
                               population=format_number(people, language, 0),
                               share=format_number(100 * people / total, language, 0)))
        self.use.setEnabled(bool(patches))

    def _draw(self):
        classes = self.result.classes
        palette = COLOURS["dark" if self.colours.get("window") != "#ffffff" else "light"]
        urban = set(self.result.urban_classes)
        rows, cols = classes.shape
        inside = [(r, c) for r in range(rows) for c in range(cols) if classes[r, c]]
        if not inside:
            return
        r0, r1 = min(r for r, _ in inside), max(r for r, _ in inside) + 1
        c0, c1 = min(c for _, c in inside), max(c for _, c in inside) + 1
        image = QImage(c1 - c0, r1 - r0, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        for r in range(r0, r1):
            for c in range(c0, c1):
                name = classes[r, c]
                colour = palette["urban"] if name in urban else palette.get(name, palette["Rural"] if name else None)
                if colour:
                    image.setPixelColor(c - c0, r - r0, QColor(colour))
        pixmap = QPixmap.fromImage(image)
        self.map.setPixmap(pixmap.scaled(self.map.width(), self.map.height(), Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.FastTransformation))
        self.key.setText(" · ".join(
            f'<span style="color:{colour}">■</span> {label}' for label, colour in (
                (", ".join(sorted(urban)), palette["urban"]), ("Urbain2", palette["Urbain2"]),
                ("Transition", palette["Transition"]), ("Rural", palette["Rural"]))))

    # --- use -------------------------------------------------------------------------

    def target_folder(self):
        """Next to the saved scenario, else in the results folder."""
        if self.main.path:
            return os.path.dirname(self.main.path)
        return self.main.output_directory()

    def apply(self, confirm=True):
        folder = self.target_folder()
        if not folder:
            QMessageBox.warning(self, tr("patches.title"), tr("patches.no_folder"))
            return None
        if confirm and QMessageBox.question(self, tr("patches.title"), tr("patches.confirm")) \
                != QMessageBox.StandardButton.Yes:
            return None
        os.makedirs(folder, exist_ok=True)
        path = write_typology(os.path.join(folder, GPKG), self.scenario, self.model.units, self.result, self.rules)
        with open(os.path.join(folder, REPORT), "w", encoding="utf-8") as handle:
            json.dump({"rules": asdict(self.rules), "urban_classes": self.result.urban_classes,
                       "patches": [asdict(p) for p in self.result.patches]}, handle, ensure_ascii=False, indent=2)
        source = os.path.relpath(path, self.main.base_dir()) if self.main.path else path
        data = apply_patches(self.main.collect(), source, self.scenario, self.result, self.rules)
        self.main.reload(data)
        self.main.iface.messageBar().pushSuccess("Poplar", tr("patches.applied", count=len(self.result.patches),
                                                               path=path))
        self.accept()
        return path
