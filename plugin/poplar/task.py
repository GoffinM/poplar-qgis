"""Run a scenario in the background with QgsTask: QGIS stays usable."""

from qgis.core import QgsTask
from qgis.PyQt.QtCore import pyqtSignal

from .engine.scenario import ScenarioError
from .engine.simulation import run


class RunTask(QgsTask):
    """Background run of the engine. ``done`` is emitted in the main thread."""

    done = pyqtSignal(object, object)  # (RunResult or None, error or None)

    def __init__(self, scenario, description):
        super().__init__(description, QgsTask.CanCancel)
        self.scenario = scenario
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = run(
                self.scenario,
                progress=lambda fraction: self.setProgress(100.0 * fraction),
                is_canceled=self.isCanceled,
            )
        except ScenarioError as error:
            self.error = error
        except Exception as error:  # reported to the user, never lost silently
            self.error = error
        return self.error is None

    def finished(self, ok):
        self.done.emit(self.result, self.error)
