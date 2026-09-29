"""QGIS environment for the plugin tests (headless), shared by conftest and the tests."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "plugin"))
for path in ("/usr/share/qgis/python/plugins", "/usr/share/qgis/python"):
    if os.path.isdir(path) and path not in sys.path:
        sys.path.append(path)

from qgis.core import QgsApplication  # noqa: E402

_APP = QgsApplication([], True)
_APP.initQgis()

MURAMVYA = os.path.join(REPO, "data", "test", "muramvya")


class MessageBar:
    def __init__(self):
        self.messages = []

    def _push(self, *args, **kwargs):
        self.messages.append(args)

    pushSuccess = pushInfo = pushWarning = pushCritical = pushMessage = _push


class FakeIface:
    """The few QgisInterface methods the plugin uses."""

    def __init__(self):
        from qgis.PyQt.QtWidgets import QMainWindow, QMenu

        self.window = QMainWindow()
        self.right_menu = QMenu("Help", self.window)
        self.window.menuBar().addMenu(self.right_menu)
        self.bar = MessageBar()
        self.toolbars = []

    def mainWindow(self):  # noqa: N802
        return self.window

    def addToolBar(self, name):  # noqa: N802
        toolbar = self.window.addToolBar(name)
        self.toolbars.append(toolbar)
        return toolbar

    def firstRightStandardMenu(self):  # noqa: N802
        return self.right_menu

    def removeToolBarIcon(self, action):  # noqa: N802
        for toolbar in self.toolbars:
            toolbar.removeAction(action)

    def messageBar(self):  # noqa: N802
        return self.bar


