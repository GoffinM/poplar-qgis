"""Download of the roofs of the study zone from Google Open Buildings (plan of 30/09/2026, step 3).

The zone is a polygon layer (the strata by default), widened by a margin and
kept inside an optional limit (a national boundary). The download runs in the
background; tiles are kept in a cache and reused. At the end, the GeoPackage
is added to the project and chosen as the roof layer of the Calibration tab.
"""

import os

from qgis.core import (
    Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsSettings, QgsTask,
)
from qgis.gui import QgsFileWidget
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from ..compat import POLYGON_FILTER, with_password
from ..engine.downloads.fetch import DownloadCancelled, FileCache, UrllibFetcher
from ..engine.downloads.open_buildings import download_open_buildings, estimate
from ..engine.downloads.zone import DownloadZone, EmptyZone, ZoneLayer
from ..engine.library import slug
from ..i18n import tr
from .widgets import add_row, choice_combo, find_or_add_layer, layer_combo, source_of

CACHE_SETTING = "poplar/download_cache"


def default_cache():
    return QgsSettings().value(CACHE_SETTING, "") or os.path.join(QgsApplication.qgisSettingsDirPath(),
                                                                   "poplar_cache")


def qgis_proxy():
    """Proxy set in the QGIS options (Settings › Options › Network), as a URL; None to use the system one."""
    settings = QgsSettings()
    enabled = str(settings.value("proxy/proxyEnabled", "false")).lower() == "true"
    host = settings.value("proxy/proxyHost", "")
    if not enabled or not host or settings.value("proxy/proxyType", "") == "DefaultProxy":
        return None
    user, password = settings.value("proxy/proxyUser", ""), settings.value("proxy/proxyPassword", "")
    port = settings.value("proxy/proxyPort", "")
    credentials = f"{user}:{password}@" if user else ""
    return f"http://{credentials}{host}{':' + str(port) if port else ''}"


def calculation_crs(layer):
    """WKT of a metric CRS for the zone: the layer's own when projected in metres, else the UTM zone of its centre."""
    from ..engine.crs import utm_wkt

    crs = layer.crs()
    if not crs.isGeographic() and crs.mapUnits() == Qgis.DistanceUnit.Meters:
        return crs.toWkt()
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    centre = QgsCoordinateTransform(crs, wgs84, QgsProject.instance()).transform(layer.extent().center())
    return utm_wkt(centre.x(), centre.y())


def _engine_layer(layer):
    spec = source_of(layer)
    if spec is None or spec.get("unsupported"):
        return None
    return ZoneLayer(with_password(spec["source"]), spec.get("layer"), spec.get("where"))


class DownloadTask(QgsTask):
    done = pyqtSignal(object, object)  # report, error (None and None when cancelled)

    def __init__(self, zone, limit, crs_wkt, margin_m, output, cache, kind, min_confidence):
        super().__init__(tr("download.task"), QgsTask.CanCancel)
        self.zone, self.limit, self.crs_wkt, self.margin_m = zone, limit, crs_wkt, margin_m
        self.output, self.cache, self.kind, self.min_confidence = output, cache, kind, min_confidence
        self.report = self.error = None

    def run(self):
        try:
            zone = DownloadZone.from_layers(self.zone, self.crs_wkt, self.margin_m, self.limit)
            self.report = download_open_buildings(zone, self.output, self.cache, self.kind, self.min_confidence,
                                                  lambda fraction: self.setProgress(100 * fraction),
                                                  self.isCanceled)
        except DownloadCancelled:
            return False
        except Exception as error:  # shown to the user
            self.error = error
        return self.error is None

    def finished(self, ok):
        self.done.emit(self.report, self.error)


class DownloadRoofsDialog(QDialog):
    """Zone, source and destination; « Download » starts the task, the dialog shows its progress."""

    downloaded = pyqtSignal(object)  # the roof layer added to the project

    def __init__(self, zone_layer=None, base_dir="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("download.title"))
        self.setMinimumWidth(560)
        self.base_dir = base_dir or os.getcwd()
        self.fetcher = None          # tests put a fake here; else urllib with the QGIS proxy
        self.task = None
        self.report = None
        self.layer = None
        layout = QVBoxLayout(self)
        intro = QLabel(tr("download.intro"))
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
        self.margin.setValue(1.0)
        add_row(form, "download.margin", self.margin)
        widget, self.limit_layer = layer_combo(POLYGON_FILTER, allow_empty=True)
        add_row(form, "download.limit", widget)
        self.kind = choice_combo([("points", tr("download.kind.points")), ("polygons", tr("download.kind.polygons"))])
        add_row(form, "download.kind", self.kind)
        confidence = QWidget()
        row = QHBoxLayout(confidence)
        row.setContentsMargins(0, 0, 0, 0)
        self.confidence_on = QCheckBox(tr("calibration.confidence_on"))
        self.confidence = QDoubleSpinBox()
        self.confidence.setRange(0.65, 1)
        self.confidence.setSingleStep(0.05)
        self.confidence.setValue(0.75)
        self.confidence.setEnabled(False)
        self.confidence_on.toggled.connect(self.confidence.setEnabled)
        row.addWidget(self.confidence_on)
        row.addWidget(self.confidence)
        row.addStretch(1)
        add_row(form, "download.confidence", confidence)
        self.output = QgsFileWidget()
        self.output.setStorageMode(QgsFileWidget.StorageMode.SaveFile)
        self.output.setFilter("GeoPackage (*.gpkg)")
        add_row(form, "download.output", self.output)
        self.cache_dir = QgsFileWidget()
        self.cache_dir.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        self.cache_dir.setFilePath(default_cache())
        add_row(form, "download.cache", self.cache_dir)
        layout.addLayout(form)

        row = QHBoxLayout()
        self.estimate_button = QPushButton(tr("download.estimate"))
        self.estimate_button.clicked.connect(lambda: self.estimate())
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("chip")
        row.addWidget(self.estimate_button)
        row.addWidget(self.info, 1)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        source = QLabel(tr("download.licence"))
        source.setWordWrap(True)
        source.setObjectName("hint")
        layout.addWidget(source)

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
        if zone_layer is not None:
            self.zone_layer.setLayer(zone_layer)
        self._zone_changed(self.zone_layer.currentLayer())

    def _zone_changed(self, layer):
        self.info.setText("")
        if layer is not None:
            name = slug(layer.name()) or "zone"
            self.output.setFilePath(os.path.join(self.base_dir, "toits", f"google_open_buildings_{name}.gpkg"))

    def _cache(self):
        return FileCache(self.cache_dir.filePath() or default_cache(), self.fetcher or UrllibFetcher(proxy=qgis_proxy()))

    def _inputs(self):
        layer = self.zone_layer.currentLayer()
        zone = _engine_layer(layer) if layer is not None else None
        if zone is None:
            self.info.setText(tr("download.no_zone"))
            return None
        limit_layer = self.limit_layer.currentLayer()
        limit = _engine_layer(limit_layer) if limit_layer is not None else None
        return zone, limit, calculation_crs(layer), self.margin.value() * 1000

    def estimate(self):
        """Tiles and megabytes still to download (the cached tiles cost nothing)."""
        inputs = self._inputs()
        if inputs is None:
            return None
        zone, limit, crs_wkt, margin = inputs
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            area = DownloadZone.from_layers(zone, crs_wkt, margin, limit)
            result = estimate(area, self._cache(), self.kind.currentData())
        except EmptyZone:
            self.info.setText(tr("download.empty_zone"))
            return None
        except Exception as error:  # network, unreadable layer: shown as is
            self.info.setText(tr("download.error", error=error))
            return None
        finally:
            QApplication.restoreOverrideCursor()
        self.info.setText(tr("download.estimated", area=f"{area.area_km2():,.0f}".replace(",", " "),
                             tiles=len(result["tiles"]), cached=sum(t["cached"] for t in result["tiles"]),
                             mb=f"{result['bytes_to_download'] / 1e6:,.0f}".replace(",", " ")))
        return result

    def start(self, background=True):
        inputs = self._inputs()
        output = self.output.filePath()
        if inputs is None or not output:
            return False
        if not output.lower().endswith(".gpkg"):
            output += ".gpkg"
        zone, limit, crs_wkt, margin = inputs
        QgsSettings().setValue(CACHE_SETTING, self.cache_dir.filePath())
        min_confidence = self.confidence.value() if self.confidence_on.isChecked() else None
        self.task = DownloadTask(zone, limit, crs_wkt, margin, output, self._cache(), self.kind.currentData(),
                                 min_confidence)
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

    def _running(self, running):
        self.progress.setVisible(running)
        self.progress.setValue(0)
        self.start_button.setEnabled(not running)
        self.estimate_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.info.setText(tr("download.running") if running else self.info.text())

    def _finished(self, report, error):
        self.task = None
        self._running(False)
        if error is not None:
            key = "download.empty_zone" if isinstance(error, EmptyZone) else "download.error"
            self.info.setText(tr(key, error=error))
            return
        if report is None:
            self.info.setText(tr("download.cancelled"))
            return
        self.report = report
        self.layer = find_or_add_layer(report["output"], report["layer"])
        if self.layer is not None:
            self.layer.setName(os.path.splitext(os.path.basename(report["output"]))[0])
        counts = report["counts"]
        self.info.setText(tr("download.done", kept=f"{counts['kept']:,}".replace(",", " "),
                             read=f"{counts['read']:,}".replace(",", " ")))
        self.downloaded.emit(self.layer)
