"""Toolbar, « Population » menu and Processing provider."""

import os

from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu

from .i18n import tip, tr

ICONS = os.path.join(os.path.dirname(__file__), "icons")
# (page or command, icon, available)
BUTTONS = [
    ("scenario", "scenario", True), ("data", "data", True), ("parameters", "parameters", True),
    ("calibration", "calibration", False), ("run", "run", True), ("results", "results", True),
    ("report", "report", True), (None, None, None), ("help", "help", True), ("about", "about", True),
]


class PoplarPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.actions = []
        self.toolbar = None
        self.menu = None
        self.provider = None
        self.dialog = None
        self.help = None

    def initProcessing(self):  # noqa: N802
        from .processing.provider import PoplarProvider

        self.provider = PoplarProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):  # noqa: N802
        self.initProcessing()
        self.toolbar = self.iface.addToolBar(tr("plugin.toolbar"))
        self.toolbar.setObjectName("PoplarToolbar")
        self.menu = QMenu(tr("plugin.menu"), self.iface.mainWindow().menuBar())
        self.menu.setToolTip(tip("plugin.menu"))
        for key, icon, available in BUTTONS:
            if key is None:
                self.toolbar.addSeparator()
                self.menu.addSeparator()
                continue
            action = QAction(QIcon(os.path.join(ICONS, f"{icon}.svg")), tr(f"button.{key}"), self.iface.mainWindow())
            action.setToolTip(tip(f"button.{key}"))
            action.setEnabled(bool(available))
            action.triggered.connect(lambda checked=False, k=key: self.open(k))
            self.toolbar.addAction(action)
            self.menu.addAction(action)
            self.actions.append(action)
        menubar = self.iface.mainWindow().menuBar()
        menubar.insertMenu(self.iface.firstRightStandardMenu().menuAction(), self.menu)

    def unload(self):
        for action in self.actions:
            self.iface.removeToolBarIcon(action)
        if self.toolbar is not None:
            self.toolbar.deleteLater()
        if self.menu is not None:
            self.menu.deleteLater()
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
        for window in (self.dialog, self.help):
            if window is not None:
                window.close()

    def open(self, key):
        if key == "help":
            self.open_help("prise_en_main")
        elif key == "about":
            from .ui.about_dialog import AboutDialog

            AboutDialog(self.iface.mainWindow()).exec()
        else:
            self.main_dialog().show_page(key)

    def main_dialog(self):
        if self.dialog is None:
            from .ui.main_dialog import MainDialog

            self.dialog = MainDialog(self.iface, self.open_help, self.iface.mainWindow())
        return self.dialog

    def open_help(self, page):
        from .ui.help_dialog import HelpDialog

        if self.help is None:
            self.help = HelpDialog(self.iface.mainWindow())
        self.help.show_page(page)
