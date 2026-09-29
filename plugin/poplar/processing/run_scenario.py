"""Processing algorithm: run a scenario file (batch processing, Model Builder)."""

import os

from qgis.core import (
    QgsProcessingAlgorithm, QgsProcessingContext, QgsProcessingException, QgsProcessingOutputFile, QgsProcessingOutputFolder,
    QgsProcessingOutputString, QgsProcessingParameterBoolean, QgsProcessingParameterEnum, QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
)

from ..engine.i18n import available_languages
from ..engine.scenario import ScenarioError, load_scenario
from ..engine.simulation import run
from ..i18n import tr


class RunScenarioAlgorithm(QgsProcessingAlgorithm):
    SCENARIO = "SCENARIO"
    OUTPUT = "OUTPUT"
    LANGUAGE = "LANGUAGE"
    LOAD = "LOAD"

    def name(self):
        return "run_scenario"

    def displayName(self):  # noqa: N802
        return tr("processing.run.name")

    def group(self):
        return ""

    def groupId(self):  # noqa: N802
        return ""

    def shortHelpString(self):  # noqa: N802
        return tr("processing.run.help")

    def createInstance(self):  # noqa: N802
        return RunScenarioAlgorithm()

    def initAlgorithm(self, config=None):  # noqa: N802
        self.languages = ["(scenario)"] + available_languages()
        self.addParameter(QgsProcessingParameterFile(self.SCENARIO, tr("processing.run.scenario"), extension="json"))
        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT, tr("processing.run.output"), optional=True, createByDefault=False))
        self.addParameter(QgsProcessingParameterEnum(
            self.LANGUAGE, tr("processing.run.language"), options=self.languages, defaultValue=0))
        self.addParameter(QgsProcessingParameterBoolean(self.LOAD, tr("processing.run.load"), defaultValue=False))
        self.addOutput(QgsProcessingOutputFolder("OUTPUT_FOLDER", tr("processing.run.output_folder")))
        self.addOutput(QgsProcessingOutputString("STATUS", tr("processing.run.status")))
        self.addOutput(QgsProcessingOutputFile("REPORT", tr("processing.run.report")))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        path = self.parameterAsFile(parameters, self.SCENARIO, context)
        try:
            scenario = load_scenario(path)
        except ScenarioError as error:
            raise QgsProcessingException(str(error))
        output = self.parameterAsString(parameters, self.OUTPUT, context)
        if output:
            scenario.output_directory = output
        language = self.languages[self.parameterAsEnum(parameters, self.LANGUAGE, context)]
        if language != "(scenario)":
            scenario.language = language
        try:
            result = run(scenario, progress=lambda f: feedback.setProgress(100.0 * f), is_canceled=feedback.isCanceled)
        except ScenarioError as error:
            raise QgsProcessingException(str(error))
        report = os.path.join(result.directory, "report.txt")
        with open(report, encoding="utf-8") as handle:
            for line in handle:
                feedback.pushInfo(line.rstrip())
        if self.parameterAsBoolean(parameters, self.LOAD, context):
            # Layers are added by QGIS once the algorithm ends (never from the worker thread).
            from ..results import available_outputs

            years = available_outputs(result.directory).get("population", [])[-1:]
            for quantity in ("population", "density"):
                for year in years:
                    layer_path = os.path.join(result.directory, f"{quantity}_{year}.tif")
                    details = QgsProcessingContext.LayerDetails(f"{quantity} {year}", context.project(), quantity)
                    context.addLayerToLoadOnCompletion(layer_path, details)
        return {"OUTPUT_FOLDER": result.directory, "STATUS": result.status, "REPORT": report}
