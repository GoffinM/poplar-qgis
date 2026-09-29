"""Processing provider of the plugin."""

import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .run_scenario import RunScenarioAlgorithm

ICON = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icons", "poplar.svg")


class PoplarProvider(QgsProcessingProvider):
    def loadAlgorithms(self):  # noqa: N802
        self.addAlgorithm(RunScenarioAlgorithm())

    def id(self):
        return "poplar"

    def name(self):
        return "Poplar"

    def icon(self):
        return QIcon(ICON)
