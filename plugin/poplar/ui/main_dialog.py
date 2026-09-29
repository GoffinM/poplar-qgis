"""Main window of the plugin: one dialog, one tab per toolbar button (decision of 29/09/2026)."""

import copy
import json
import os

from qgis.core import Qgis, QgsApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QScrollArea, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QStackedWidget, QToolButton, QVBoxLayout,
)

from ..engine.scenario import ScenarioError, scenario_from_dict
from ..i18n import current_language, tip, tr
from ..results import load_rasters
from ..task import RunTask
from .nonconvergence_dialog import NonConvergenceDialog
from .pages import (
    CalibrationPage, DataPage, IndicatorsPage, ParametersPage, ReportPage, ResultsPage, RunPage, ScenarioPage,
)

ICONS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icons")
PAGE_ICONS = {"scenario": "scenario", "data": "data", "parameters": "parameters", "indicators": "results",
              "calibration": "calibration", "run": "run", "results": "results", "report": "report"}
HELP_PAGES = {"scenario": "parametres_et_scenario", "data": "parametres_et_scenario",
              "parameters": "parametres_et_scenario", "indicators": "resultats_et_indicateurs",
              "calibration": "prise_en_main", "run": "non_convergence", "results": "resultats_et_indicateurs",
              "report": "resultats_et_indicateurs"}


def default_scenario() -> dict:
    return {
        "name": "", "language": current_language(), "cell_size": 250, "density_unit": "hab/km2",
        "time": {"base_year": 2024, "end_year": 2060, "time_step": 5, "migration_frequency": "annual",
                 "first_migration_year": 2025},
        "parameters": {"growth_rate": 2.0, "dmax": 2500},
        "migration": {"k": 3, "tolerance": 1, "policy": "stop"},
        "output": {"directory": ""},
    }


class MainDialog(QDialog):
    def __init__(self, iface, help_opener, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.help_opener = help_opener
        self.path = None
        self.data = default_scenario()
        self.task = None
        self.setWindowTitle(tr("main.title"))
        self.resize(980, 720)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600; font-size: 14px")
        header.addWidget(self.title, 1)
        help_button = QToolButton()
        help_button.setText("?")
        help_button.setToolTip(tip("main.help"))
        help_button.clicked.connect(lambda: self.help_opener(HELP_PAGES.get(self.current_key(), "prise_en_main")))
        header.addWidget(help_button)
        layout.addLayout(header)

        body = QHBoxLayout()
        self.tabs = QListWidget()
        self.tabs.setFixedWidth(180)
        self.stack = QStackedWidget()
        self.pages = [ScenarioPage(self), DataPage(self), ParametersPage(self), IndicatorsPage(self),
                      CalibrationPage(self), RunPage(self), ResultsPage(self), ReportPage(self)]
        for page in self.pages:
            item = QListWidgetItem(QIcon(os.path.join(ICONS, f"{PAGE_ICONS[page.key]}.svg")), tr(f"tab.{page.key}"))
            item.setToolTip(tip(f"tab.{page.key}"))
            if page.key == "calibration":
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.tabs.addItem(item)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        self.tabs.currentRowChanged.connect(self._show_row)
        body.addWidget(self.tabs)
        body.addWidget(self.stack, 1)
        layout.addLayout(body, 1)

        footer = QHBoxLayout()
        for key, slot in (("main.open", self.open_scenario), ("main.save", self.save_scenario)):
            button = QPushButton(tr(key))
            button.setToolTip(tip(key))
            button.clicked.connect(slot)
            footer.addWidget(button)
        footer.addStretch(1)
        close = QPushButton(tr("common.close"))
        close.clicked.connect(self.close)
        run = QPushButton(tr("main.run"))
        run.setDefault(True)
        run.clicked.connect(lambda: (self.show_page("run"), self.run()))
        footer.addWidget(close)
        footer.addWidget(run)
        layout.addLayout(footer)

        for page in self.pages:
            page.load(self.data)
        self._update_title()
        self.tabs.setCurrentRow(0)

    # --- navigation ---------------------------------------------------------------

    def current_key(self) -> str:
        return self.pages[self.stack.currentIndex()].key

    def page(self, key):
        return next(p for p in self.pages if p.key == key)

    def show_page(self, key: str) -> None:
        self.tabs.setCurrentRow([p.key for p in self.pages].index(key))
        self.show()
        self.raise_()
        self.activateWindow()

    def _show_row(self, row):
        self.stack.setCurrentIndex(row)
        self.pages[row].refresh()

    def _update_title(self):
        name = self.data.get("name") or tr("main.untitled")
        self.title.setText(tr("main.heading", name=name))

    # --- scenario file ------------------------------------------------------------

    def base_dir(self) -> str:
        return os.path.dirname(self.path) if self.path else os.getcwd()

    def absolute(self, path):
        if not path:
            return path
        return path if os.path.isabs(path) else os.path.normpath(os.path.join(self.base_dir(), path))

    def collect(self) -> dict:
        data = copy.deepcopy(self.data)
        for page in self.pages:
            page.store(data)
        self.data = data
        self._update_title()
        return data

    def output_directory(self) -> str:
        return self.absolute((self.collect().get("output") or {}).get("directory", ""))

    def open_scenario(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("main.open"), "", tr("main.scenario_filter"))
        if path:
            self.load_file(path)

    def load_file(self, path):
        with open(path, encoding="utf-8") as handle:
            self.data = json.load(handle)
        self.path = path
        for page in self.pages:
            page.load(self.data)
        self._update_title()

    def save_scenario(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("main.save"), self.path or "", tr("main.scenario_filter"))
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        self.path = path
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.collect(), handle, ensure_ascii=False, indent=2)
        self.iface.messageBar().pushSuccess("Poplar", tr("main.saved", path=path))

    def scenario(self):
        """Engine scenario built from the window (raises ScenarioError with every problem)."""
        return scenario_from_dict(self.collect(), self.base_dir())

    # --- checks and run -----------------------------------------------------------

    def check(self) -> bool:
        page = self.page("run")
        language = current_language()
        try:
            scenario = self.scenario()
        except ScenarioError as error:
            page.show_checks([(False, m.render(language)) for m in error.messages])
            return False
        items = [(True, tr("check.scenario_ok"))]
        if not scenario.output_directory:
            items.append((False, tr("check.no_output")))
        page.show_checks(items)
        return all(ok for ok, _ in items)

    def run(self):
        if self.task is not None or not self.check():
            return
        scenario = self.scenario()
        page = self.page("run")
        page.running(True)
        page.log.setPlainText(tr("run.started"))
        self.task = RunTask(scenario, tr("run.task", name=scenario.name or "Poplar"))
        self.task.progressChanged.connect(lambda value: page.progress.setValue(int(value)))
        self.task.done.connect(self._finished)
        QgsApplication.taskManager().addTask(self.task)

    def cancel(self):
        if self.task is not None:
            self.task.cancel()

    def _finished(self, result, error):
        self.task = None
        page = self.page("run")
        page.running(False)
        language = current_language()
        if error is not None:
            messages = getattr(error, "messages", None)
            text = "\n".join(m.render(language) for m in messages) if messages else str(error)
            page.log.appendPlainText(text)
            self.iface.messageBar().pushCritical("Poplar", tr("run.error"))
            return
        page.progress.setValue(100)
        with open(os.path.join(result.directory, "report.txt"), encoding="utf-8") as handle:
            page.log.setPlainText(handle.read())
        if result.failure is not None:
            self._offer_solutions(result)
            return
        level = Qgis.Success if result.status in ("success", "success_with_adjustments") else Qgis.Warning
        self.iface.messageBar().pushMessage("Poplar", tr(f"run.status.{result.status}"), level)
        years = sorted({os.path.basename(p).split("_")[-1][:-4] for p in result.outputs
                        if os.path.basename(p).startswith("population_")}, key=float)
        self.load_results(["population", "density"], years[-1:])

    def _offer_solutions(self, result):
        """Lack of room: offer the solutions, then run again with the one chosen (spec §7.2)."""
        dialog = NonConvergenceDialog(result, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.iface.messageBar().pushWarning("Poplar", tr("run.status.failed"))
            return
        migration = self.data.setdefault("migration", {})
        choice = dialog.choice()
        migration["policy"] = choice["policy"]
        if "max_auto_increase" in choice:
            migration["max_auto_increase"] = choice["max_auto_increase"]
        self.page("parameters").load(self.data)
        self.run()

    def load_results(self, quantities, years):
        directory = self.output_directory()
        group = f"Poplar – {self.data.get('name') or tr('main.untitled')}"
        layers = load_rasters(directory, quantities, years, group)
        if layers:
            self.iface.messageBar().pushInfo("Poplar", tr("results.loaded", count=len(layers)))
