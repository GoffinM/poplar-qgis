"""Download of the OpenStreetMap roads of the study zone (Overpass API), from the Data tab.

The zone is a polygon layer (the study area by default), widened by a margin and kept inside an optional
limit. The download runs in the background; the GeoPackage is then added to the project, styled by class
(national, provincial, other). The roads are not used by the model yet (plan_demande_et_routes.md, B).
"""

import os

from qgis.core import (
    QgsApplication, QgsCategorizedSymbolRenderer, QgsLineSymbol, QgsRendererCategory, QgsTask,
)
from qgis.gui import QgsFileWidget
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QMessageBox, QProgressBar, QVBoxLayout,
)

from ..compat import POLYGON_FILTER
from ..engine.downloads import osm_roads
from ..engine.downloads.fetch import DownloadCancelled, UrllibFetcher
from ..engine.downloads.zone import DownloadZone, EmptyZone
from ..engine.library import slug
from ..engine.roofs import download_origin
from ..i18n import tr
from .download_dialog import _engine_layer, _release, calculation_crs, qgis_proxy
from .widgets import add_row, find_or_add_layer, layer_combo

STYLE = [("nationale", "#a4452a", 1.2), ("provinciale", "#c98a36", 0.8), ("autre", "#8a8f8d", 0.3)]


class RoadsTask(QgsTask):
    done = pyqtSignal(object, object)  # report, error (None and None when cancelled)

    def __init__(self, zone, limit, crs_wkt, margin_m, output, fetcher):
        super().__init__(tr("roads.task"), QgsTask.Flag.CanCancel)
        self.zone, self.limit, self.crs_wkt, self.margin_m = zone, limit, crs_wkt, margin_m
        self.output, self.fetcher = output, fetcher
        self.report = self.error = None

    def run(self):
        try:
            zone = DownloadZone.from_layers(self.zone, self.crs_wkt, self.margin_m, self.limit)
            self.report = osm_roads.download_osm_roads(zone, self.output, self.fetcher,
                                                       progress=lambda fraction: self.setProgress(100 * fraction),
                                                       cancelled=self.isCanceled)
        except DownloadCancelled:
            return False
        except Exception as error:  # shown to the user; no traceback kept, it would hold the file open
            self.error = error.with_traceback(None)
        return self.error is None

    def finished(self, ok):
        self.done.emit(self.report, self.error)


def style_roads(layer):
    categories = []
    for name, colour, width in STYLE:
        symbol = QgsLineSymbol.createSimple({"line_color": colour, "line_width": str(width)})
        categories.append(QgsRendererCategory(name, symbol, tr(f"roads.class.{name}")))
    layer.setRenderer(QgsCategorizedSymbolRenderer("classe", categories))
    layer.triggerRepaint()


def _summary(report):
    counts = report.get("counts") or {}
    lengths = counts.get("length_km") or {}
    return {"date": (report.get("date") or "")[:16].replace("T", " "), "count": counts.get("kept", 0),
            "national": f"{lengths.get('nationale', 0):g}", "provincial": f"{lengths.get('provinciale', 0):g}",
            "other": f"{lengths.get('autre', 0):g}", "file": os.path.basename(report.get("output") or "")}


class DownloadRoadsDialog(QDialog):
    downloaded = pyqtSignal(object)  # the road layer added to the project

    def __init__(self, zone_layer=None, base_dir="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("roads.title"))
        self.setMinimumWidth(540)
        self.base_dir = base_dir or os.getcwd()
        self.fetcher = None          # tests put a fake here; else urllib with the QGIS proxy
        self.task = None
        self.report = None
        self.layer = None
        layout = QVBoxLayout(self)
        intro = QLabel(tr("roads.intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        widget, self.zone_layer = layer_combo(POLYGON_FILTER)
        add_row(form, "download.zone", widget)
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 100)
        self.margin.setDecimals(1)
        self.margin.setSingleStep(0.5)
        self.margin.setSuffix(" km")
        self.margin.setValue(2.0)
        add_row(form, "download.margin", self.margin)
        widget, self.limit_layer = layer_combo(POLYGON_FILTER, allow_empty=True)
        add_row(form, "download.limit", widget)
        self.output = QgsFileWidget()
        self.output.setStorageMode(QgsFileWidget.StorageMode.SaveFile)
        self.output.setFilter("GeoPackage (*.gpkg)")
        add_row(form, "download.output", self.output)
        layout.addLayout(form)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("chip")
        layout.addWidget(self.info)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        licence = QLabel(tr("roads.licence"))
        licence.setWordWrap(True)
        licence.setObjectName("hint")
        layout.addWidget(licence)
        self.buttons = QDialogButtonBox()
        self.start_button = self.buttons.addButton(tr("download.start"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.start_button.setObjectName("primary")
        self.cancel_button = self.buttons.addButton(tr("download.cancel"), QDialogButtonBox.ButtonRole.ActionRole)
        self.cancel_button.setEnabled(False)
        self.close_button = self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.start_button.clicked.connect(lambda: self.start())
        self.cancel_button.clicked.connect(self.cancel)
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.buttons)
        self.zone_layer.layerChanged.connect(self._zone_changed)
        self.output.fileChanged.connect(lambda *args: self._show_existing())
        if zone_layer is not None:
            self.zone_layer.setLayer(zone_layer)
        self._zone_changed(self.zone_layer.currentLayer())

    def _zone_changed(self, layer):
        if layer is not None:
            name = slug(layer.name()) or "zone"
            self.output.setFilePath(os.path.join(self.base_dir, "routes", f"routes_osm_{name}.gpkg"))
        self._show_existing()

    def _say(self, text, state="ok"):
        self.info.setText(text)
        self.info.setProperty("state", state)
        self.info.style().unpolish(self.info)
        self.info.style().polish(self.info)

    def _show_existing(self):
        origin = download_origin(self.output.filePath())
        self._say(tr("roads.existing", **_summary(origin)) if origin else "")
        self.start_button.setText(tr("download.again" if origin else "download.start"))
        return origin

    def start(self, background=True, ask=True):
        layer = self.zone_layer.currentLayer()
        zone = _engine_layer(layer) if layer is not None else None
        output = self.output.filePath()
        if zone is None:
            self._say(tr("download.no_zone"), "warn")
            return False
        if not output:
            return False
        if not output.lower().endswith(".gpkg"):
            output += ".gpkg"
        origin = download_origin(output)
        if origin and ask and QMessageBox.question(self, tr("roads.title"), tr("roads.replace", **_summary(origin))) \
                != QMessageBox.StandardButton.Yes:
            return False
        limit_layer = self.limit_layer.currentLayer()
        limit = _engine_layer(limit_layer) if limit_layer is not None else None
        _release(output)                                  # QGIS must let go of the file before it is replaced
        fetcher = self.fetcher or UrllibFetcher(timeout=osm_roads.TIMEOUT_S + 60, proxy=qgis_proxy())
        self.task = RoadsTask(zone, limit, calculation_crs(layer), self.margin.value() * 1000, output, fetcher)
        self.task.progressChanged.connect(lambda value: self.progress.setValue(int(value)))
        self.task.done.connect(self._finished)
        self._running(True)
        if background:
            QgsApplication.taskManager().addTask(self.task)
        else:
            self.task.finished(self.task.run())
        return True

    def cancel(self):
        if self.task is not None:
            self.task.cancel()
            self._say(tr("download.cancelling"), "warn")

    def _running(self, running):
        self.progress.setVisible(running)
        self.progress.setValue(0)
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        if running:
            self._say(tr("roads.running"))

    def _finished(self, report, error):
        self.task = None
        self._running(False)
        if error is not None:
            if isinstance(error, EmptyZone):
                self._say(tr("download.empty_zone"), "warn")
            elif isinstance(error, osm_roads.OverpassError):
                self._say(tr("roads.no_server", error=error), "warn")
            else:
                self._say(tr("download.error", error=error), "warn")
        elif report is None:
            self._say(tr("download.cancelled"), "warn")
        if report is None:
            output = self.output.filePath()
            if output and os.path.exists(output):          # the roads downloaded before, untouched
                find_or_add_layer(output, osm_roads.LAYER)
            return
        self.report = report
        self.layer = find_or_add_layer(report["output"], report["layer"])
        if self.layer is not None:
            self.layer.setName(os.path.splitext(os.path.basename(report["output"]))[0])
            style_roads(self.layer)
        self._say(tr("roads.done", **_summary(report)))
        self.start_button.setText(tr("download.again"))
        self.close_button.setFocus()
        self.downloaded.emit(self.layer)
