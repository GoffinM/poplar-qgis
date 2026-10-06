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

from ..compat import with_password
from ..engine import runs
from ..engine.demand import latest_demand
from ..engine.scenario import ScenarioError, is_connection, scenario_from_dict
from ..i18n import current_language, tip, tr
from ..results import QUANTITIES, is_demand, load_grid_layer, load_polygon_layers, load_rasters, release_grid_layer
from ..task import RunTask
from .cleanup_dialog import CleanupDialog, run_title
from .nonconvergence_dialog import NonConvergenceDialog
from .style import state_icon, stylesheet, tokens
from .pages import (
    CalibrationPage, DataPage, IndicatorsPage, ParametersPage, ReportPage, ResultsPage, RunPage, ScenarioPage,
)
from .strata_page import StrataPage

INFORMATION = {"crs_used", "raster_reprojected", "start_from_projection", "roofs_calibrated", "strata_free_mode",
               "strata_nuclei_off", "strata_nuclei_on"}
"""Report lines that describe the run; every other warning is shown in the message bar."""
ICONS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icons")
HELP_PAGES = {"scenario": "parametres_et_scenario", "data": "parametres_et_scenario", "strata": "strates",
              "parameters": "parametres_et_scenario", "indicators": "resultats_et_indicateurs",
              "calibration": "calage", "run": "non_convergence", "results": "resultats_et_indicateurs",
              "report": "resultats_et_indicateurs"}


def _sources(value):
    """Every layer input of a scenario dict ({"source": …})."""
    if isinstance(value, dict):
        if isinstance(value.get("source"), str):
            yield value
        for item in value.values():
            yield from _sources(item)
    elif isinstance(value, list):
        for item in value:
            yield from _sources(item)


def _with_passwords(data):
    data = copy.deepcopy(data)
    for spec in _sources(data):
        spec["source"] = with_password(spec["source"])
    return data


def default_scenario() -> dict:
    return {
        "name": "", "language": current_language(), "cell_size": 250, "density_unit": "hab/km2",
        "time": {"base_year": 2024, "end_year": 2060, "time_step": 5, "migration_frequency": "annual",
                 "first_migration_year": 2025},
        "parameters": {"growth_rate": 2.0, "dmax": 2500},
        "migration": {"k": 3, "tolerance": 1, "policy": "stop"},
        "output": {"directory": "", "per_run": True},
    }


class MainDialog(QDialog):
    def __init__(self, iface, help_opener, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.help_opener = help_opener
        self.path = None
        self.data = default_scenario()
        self.task = None
        self.demand_task = None
        self.selected_run = None
        """Run folder shown by the Results and Report tabs (None: the latest one)."""
        self.session_runs = []
        """Run folders written since the window opened; clean-up is offered at the end of the session."""
        self.setWindowTitle(tr("main.title"))
        self.resize(980, 720)

        self.colours = tokens(self)
        self.setStyleSheet(stylesheet(self.colours))
        self.last_check = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header_frame = QFrame()
        header_frame.setObjectName("header")
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(14, 10, 14, 10)
        logo = QLabel()
        logo.setPixmap(QIcon(os.path.join(ICONS, "poplar.svg")).pixmap(28, 28))
        header.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("subtitle")
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        help_button = QToolButton()
        help_button.setObjectName("help")
        help_button.setText("?")
        help_button.setToolTip(tip("main.help"))
        help_button.clicked.connect(lambda: self.help_opener(HELP_PAGES.get(self.current_key(), "prise_en_main")))
        header.addWidget(help_button)
        layout.addWidget(header_frame)

        body = QHBoxLayout()
        body.setSpacing(0)
        self.tabs = QListWidget()
        self.tabs.setObjectName("tabs")
        self.tabs.setFixedWidth(180)
        self.stack = QStackedWidget()
        self.pages = [ScenarioPage(self), DataPage(self), StrataPage(self), ParametersPage(self), IndicatorsPage(self),
                      CalibrationPage(self), RunPage(self), ResultsPage(self), ReportPage(self)]
        for page in self.pages:
            item = QListWidgetItem(state_icon("empty", self.colours), tr(f"tab.{page.key}"))
            item.setToolTip(tip(f"tab.{page.key}"))
            self.tabs.addItem(item)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        self.tabs.currentRowChanged.connect(self._show_row)
        body.addWidget(self.tabs)
        self.stack.setContentsMargins(8, 4, 8, 4)
        body.addWidget(self.stack, 1)
        layout.addLayout(body, 1)

        footer_frame = QFrame()
        footer_frame.setObjectName("footer")
        footer = QHBoxLayout(footer_frame)
        footer.setContentsMargins(12, 8, 12, 8)
        for key, slot in (("main.open", self.open_scenario), ("main.save", self.save_scenario),
                          ("main.library", self.open_library)):
            button = QPushButton(tr(key))
            button.setToolTip(tip(key))
            button.clicked.connect(slot)
            footer.addWidget(button)
        footer.addStretch(1)
        close = QPushButton(tr("common.close"))
        close.clicked.connect(self.close)
        run = QPushButton(tr("main.run"))
        run.setObjectName("primary")
        run.setDefault(True)
        run.clicked.connect(lambda: (self.show_page("run"), self.run()))
        footer.addWidget(close)
        footer.addWidget(run)
        layout.addWidget(footer_frame)

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
        data = self.data
        self.title.setText(data.get("name") or tr("main.untitled"))
        time = data.get("time") or {}
        if time.get("base_year") and time.get("end_year"):
            self.subtitle.setText(tr("main.period", start=f"{float(time['base_year']):g}",
                                     end=f"{float(time['end_year']):g}"))
        self._update_states(data)

    def _update_states(self, data):
        """Dot of each tab: complete, to check, or empty."""
        parameters = self.page("parameters").tables
        output = self.absolute((data.get("output") or {}).get("directory", ""))
        has_runs = bool(output) and bool(runs.list_runs(output) or os.path.exists(os.path.join(output, "report.txt")))
        states = {
            "scenario": "ok" if data.get("name") and output else "warn",
            "data": "ok" if data.get("study_area") and data.get("typology") and
                    ((data.get("base_population") or {}).get("raster")
                     or (data.get("base_population") or {}).get("source") == "buildings") else "warn",
            "parameters": "ok" if all(w.store() for w in parameters.values()) and
                          not any(w.unused_keys() for w in parameters.values()) else "warn",
            "strata": "ok" if (data.get("strata") or {}).get("mode") == "free" else "empty",
            "indicators": "ok" if data.get("indicators") else "empty",
            "calibration": ("ok" if (data.get("calibration") or {}).get("census") else "warn")
            if data.get("calibration") else "empty",
            "run": {None: "empty", True: "ok", False: "warn"}[self.last_check],
            "results": "ok" if has_runs else "empty",
            "report": "ok" if has_runs else "empty",
        }
        for row, page in enumerate(self.pages):
            item = self.tabs.item(row)
            if item.data(Qt.ItemDataRole.UserRole) != states[page.key]:
                item.setData(Qt.ItemDataRole.UserRole, states[page.key])
                item.setIcon(state_icon(states[page.key], self.colours))

    # --- scenario file ------------------------------------------------------------

    def base_dir(self) -> str:
        return os.path.dirname(self.path) if self.path else os.getcwd()

    def absolute(self, path):
        if not path or is_connection(path):
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

    def results_directory(self) -> str:
        """Folder of the run shown: the one selected, else the latest run, else the output folder itself."""
        root = self.output_directory()
        if self.selected_run and os.path.dirname(os.path.normpath(self.selected_run)) == os.path.normpath(root or ""):
            if os.path.isdir(self.selected_run):
                return self.selected_run
        latest = runs.latest_run(root)
        return latest.directory if latest else root

    def open_scenario(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("main.open"), "", tr("main.scenario_filter"))
        if path:
            self.load_file(path)

    def load_file(self, path):
        with open(path, encoding="utf-8") as handle:
            self.data = json.load(handle)
        self.path = path
        self.selected_run = None
        for page in self.pages:
            page.load(self.data)
        self._update_title()

    def reload(self, data):
        """Show a scenario changed outside the tabs (built-up patches applied or undone)."""
        self.data = data
        for page in self.pages:
            page.load(self.data)
        self._update_title()

    def open_library(self):
        from .library_dialog import LibraryDialog

        dialog = LibraryDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.chosen:
            self.load_template(dialog.chosen)

    def load_template(self, path):
        """New scenario from a library entry: the entry itself is never overwritten by « Save »."""
        self.load_file(path)
        self.data = self.collect()  # paths made absolute while the entry's folder is known
        self.path = None
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
        """Engine scenario built from the window (raises ScenarioError with every problem).

        Database passwords of this session are added here, for the run only:
        the scenario file and the copy written with the results never hold them.
        """
        return scenario_from_dict(_with_passwords(self.collect()), self.base_dir())

    # --- checks and run -----------------------------------------------------------

    def check(self) -> bool:
        page = self.page("run")
        language = current_language()
        layers = [(False, tr("layers.unsupported", name=spec.get("name", ""), provider=spec["unsupported"]))
                  for spec in _sources(self.collect()) if spec.get("unsupported")]
        layers += [(False, tr("check.buffer_missing", name=name))
                   for name in self.page("data").exclusions_without_buffer()]
        try:
            scenario = self.scenario()
        except ScenarioError as error:
            page.show_checks(layers + [(False, m.render(language)) for m in error.messages])
            self.last_check = False
            self._update_states(self.data)
            return False
        items = ([] if layers else [(True, tr("check.scenario_ok"))]) + layers
        if not scenario.output_directory:
            items.append((False, tr("check.no_output")))
        page.show_checks(items)
        self.last_check = all(ok for ok, _ in items)
        self._update_states(self.data)
        return self.last_check

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
        self.selected_run = result.directory
        if result.directory not in self.session_runs:
            self.session_runs.append(result.directory)
        with open(os.path.join(result.directory, "report.txt"), encoding="utf-8") as handle:
            page.log.setPlainText(handle.read())
        if result.failure is not None:
            self._offer_solutions(result)
            return
        level = (Qgis.MessageLevel.Success if result.status in ("success", "success_with_adjustments")
                 else Qgis.MessageLevel.Warning)
        self.iface.messageBar().pushMessage("Poplar", tr(f"run.status.{result.status}"), level)
        notable = [w for w in result.warnings if w.code not in INFORMATION]
        if notable:
            self.iface.messageBar().pushWarning(
                "Poplar", tr("run.warnings", count=len(notable), first=notable[0].render(language)))
        years = sorted({os.path.basename(p).split("_")[-1][:-4] for p in result.outputs
                        if os.path.basename(p).startswith("population_")}, key=float)
        wanted = {float(y) for y in (self.data.get("time") or {}).get("output_years") or []}
        if wanted:                                  # the years asked for in the parameters, not the base year
            years = [y for y in years if float(y) in wanted] or years
        self.load_results(["population", "density"], years, visible=years[-1:])   # the last one shown

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

    def _results_group(self, directory):
        group = f"Poplar – {self.data.get('name') or tr('main.untitled')}"
        run = runs.read_run(directory)
        if run is not None:
            group += f" – {run_title(run)}"
        return group

    def generate_grid_layer(self, fmt, background=True):
        """Cell layer of the run shown (Results tab, else the latest), written again without running the model."""
        from ..task import GridLayerTask

        directory = self.results_directory()
        if not directory or not os.path.isfile(os.path.join(directory, "scenario_used.json")):
            self.iface.messageBar().pushWarning("Poplar", tr("grid.no_run"))
            return None
        release_grid_layer(directory)                   # QGIS lets go of the former file first
        task = GridLayerTask(directory, fmt, self.base_dir(), _with_passwords, tr("grid.task"))
        task.done.connect(lambda paths, error: self._grid_layer_done(directory, paths, error))
        self.grid_task = task
        if background:
            QgsApplication.taskManager().addTask(task)
        else:
            task.finished(task.run())
        return task

    def _grid_layer_done(self, directory, paths, error):
        self.grid_task = None
        if error is not None:
            from ..engine.grid_layer import GridMismatch

            key = "grid.mismatch" if isinstance(error, GridMismatch) else "grid.failed"
            self.iface.messageBar().pushWarning("Poplar", tr(key, error=error))
            return
        prefer = "shp" if paths and not any(p.endswith(".gpkg") for p in paths) else "gpkg"
        layer = load_grid_layer(directory, self._results_group(directory), prefer)
        run = runs.read_run(directory)
        self.iface.messageBar().pushSuccess("Poplar", tr("grid.done", run=run_title(run) if run else directory,
                                                         count=layer.featureCount() if layer else 0))

    # --- demand computed again (plan_demande_et_routes.md, A) ------------------------

    def recompute_demand(self, background=True):
        """Indicators of the run shown, computed again with the parameters of the window (Indicators tab)."""
        from ..task import DemandTask

        directory = self.results_directory()
        bar = self.iface.messageBar()
        if not directory or not os.path.isfile(os.path.join(directory, "scenario_used.json")):
            bar.pushWarning("Poplar", tr("demand.no_run"))
            return None
        if self.demand_task is not None:
            return None
        try:
            scenario = self.scenario()                  # with this session's database passwords
        except ScenarioError as error:
            text = "\n".join(m.render(current_language()) for m in error.messages)
            bar.pushWarning("Poplar", tr("demand.scenario_error", error=text))
            return None
        if not scenario.indicators:
            bar.pushWarning("Poplar", tr("demand.no_indicator"))
            return None
        task = DemandTask(directory, scenario, tr("demand.task", run=self._run_name(directory)))
        task.done.connect(lambda result, error: self._demand_done(directory, result, error))
        self.demand_task = task
        if background:
            QgsApplication.taskManager().addTask(task)
        else:
            task.finished(task.run())
        return task

    def _run_name(self, directory):
        run = runs.read_run(directory)
        return run_title(run) if run else os.path.basename(directory)

    def _demand_done(self, directory, result, error):
        self.demand_task = None
        bar = self.iface.messageBar()
        if error is not None:
            from ..engine.grid_layer import GridMismatch

            key = "demand.mismatch" if isinstance(error, GridMismatch) else "demand.failed"
            bar.pushWarning("Poplar", tr(key, error=error))
            return
        names = os.listdir(result.directory)
        quantities = [q for q in QUANTITIES if is_demand(q) and f"{q}_{result.years[-1]}.tif" in names]
        layers = load_rasters(result.directory, quantities, result.years[-1:], self._results_group(directory), [],
                              suffix=f" · {os.path.basename(result.directory)}")
        if layers:                                     # the production to deliver shown, the others ticked off
            from qgis.core import QgsProject

            shown = next((l for l in layers if l.name().startswith("water_production_mean")), layers[0])
            QgsProject.instance().layerTreeRoot().findLayer(shown.id()).setItemVisibilityChecked(True)
        bar.pushSuccess("Poplar", tr("demand.done", run=self._run_name(directory),
                                     folder=os.path.basename(result.directory)))
        if result.approximated:
            bar.pushWarning("Poplar", tr("demand.approximated"))
        self.page("results").refresh()
        self.page("indicators").refresh()

    def load_results(self, quantities, years, visible=None):
        directory = self.results_directory()
        group = self._results_group(directory)
        demand = latest_demand(directory)               # the demand computed again last replaces the run's
        moved = [q for q in quantities if is_demand(q)] if demand else []
        layers = load_rasters(directory, [q for q in quantities if q not in moved], years, group, visible)
        if moved:
            layers += load_rasters(demand, moved, years, group, visible, suffix=f" · {os.path.basename(demand)}")
        if years and os.path.exists(os.path.join(directory, "polygones.gpkg")):    # free strata mode
            layers += load_rasters(directory, [q for q in ("statut", "polygon_id") if q not in quantities],
                                   years[-1:], group, [])
            layers += load_polygon_layers(directory, group, years[-1])
        grid = load_grid_layer(directory, group)
        if grid is not None and grid not in layers:
            layers.append(grid)
        if layers:
            self.iface.messageBar().pushInfo("Poplar", tr("results.loaded", count=len(layers)))

    # --- clean-up of the run folders ----------------------------------------------

    def clean_up(self, intro_key="cleanup.intro"):
        """Offer to delete the run folders; returns the dialog (after it closed)."""
        root = self.output_directory()
        dialog = CleanupDialog(root, self, intro_key)
        dialog.exec()
        if self.selected_run in dialog.deleted:
            self.selected_run = None
        return dialog

    def end_session(self):
        """At the end of the session, offer to delete the runs not kept (if this session wrote any)."""
        written = [d for d in self.session_runs if os.path.isdir(d)]
        self.session_runs = []
        if self.task is not None or not written:
            return
        if runs.default_deletion(runs.list_runs(self.output_directory())):
            self.clean_up("cleanup.intro_end")

    def closeEvent(self, event):  # noqa: N802
        self.end_session()
        super().closeEvent(event)

    def reject(self):
        self.end_session()
        super().reject()
