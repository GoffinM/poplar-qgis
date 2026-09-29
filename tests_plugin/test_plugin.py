import json
import os
import re
import shutil

import pytest
from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtWidgets import QLabel, QWidget

from qgis_env import MURAMVYA, REPO


@pytest.fixture
def scenario_copy(tmp_path):
    """The Muramvya example scenario, with absolute paths and results in a temporary folder."""
    with open(os.path.join(MURAMVYA, "scenario_muramvya.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    for key in ("study_area", "typology", "admin_units"):
        data[key]["source"] = os.path.join(MURAMVYA, data[key]["source"])
    data["base_population"]["raster"] = os.path.join(MURAMVYA, data["base_population"]["raster"])
    for exclusion in data["exclusions"]:
        exclusion["source"] = os.path.join(MURAMVYA, exclusion["source"])
    data["time"]["end_year"] = 2030
    data["time"]["output_years"] = [2025, 2030]
    data["output"]["directory"] = str(tmp_path / "out")
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_plugin_loads_and_unloads(iface):
    import poplar

    plugin = poplar.classFactory(iface)
    plugin.initGui()
    assert len(plugin.actions) == 9
    assert [a.isEnabled() for a in plugin.actions].count(False) == 1  # calibration: phase 6
    assert QgsApplication.processingRegistry().algorithmById("poplar:run_scenario") is not None
    assert all(a.toolTip() for a in plugin.actions)
    plugin.unload()
    assert QgsApplication.processingRegistry().providerById("poplar") is None


def test_processing_algorithm_runs_a_scenario(processing_ready, scenario_copy, iface):
    import poplar
    from qgis import processing

    plugin = poplar.classFactory(iface)
    plugin.initProcessing()
    try:
        result = processing.run("poplar:run_scenario", {"SCENARIO": scenario_copy, "LANGUAGE": 0, "LOAD": False})
    finally:
        QgsApplication.processingRegistry().removeProvider(plugin.provider)
    assert result["STATUS"] == "success"
    assert os.path.exists(result["REPORT"])
    assert os.path.exists(os.path.join(result["OUTPUT_FOLDER"], "population_2030.tif"))


def test_dialog_reads_and_writes_the_scenario(iface, scenario_copy):
    from poplar.engine.scenario import scenario_from_dict
    from poplar.ui.main_dialog import MainDialog

    dialog = MainDialog(iface, lambda page: None)
    dialog.load_file(scenario_copy)
    data = dialog.collect()
    assert data["name"] == "Muramvya – exemple"
    assert data["typology"]["field"] == "Type"
    assert data["exclusions"][0]["behaviour"] == "no_inflow"
    assert data["parameters"]["dmax"]["Urbain1"] == 10000
    assert len(data["parameters"]["growth_rate"]["*"]) == 8
    water = data["indicators"][0]["parameters"]
    assert water["water_per_capita"]["*"] == 20 and water["network_efficiency"]["*"] == 75
    scenario = scenario_from_dict(data, dialog.base_dir())
    assert scenario.time.end_year == 2030
    QgsProject.instance().clear()


def test_dialog_run_loads_the_results(iface, scenario_copy):
    from poplar.task import RunTask
    from poplar.ui.main_dialog import MainDialog

    dialog = MainDialog(iface, lambda page: None)
    dialog.load_file(scenario_copy)
    assert dialog.check()
    task = RunTask(dialog.scenario(), "test")
    task.done.connect(dialog._finished)
    assert task.run()
    task.finished(True)
    group = QgsProject.instance().layerTreeRoot().findGroup("Poplar – Muramvya – exemple")
    assert group is not None and len(group.findLayers()) == 2
    dialog.page("report").refresh()
    assert "2030" in dialog.page("report").text.toPlainText()
    QgsProject.instance().clear()


def test_every_widget_text_and_tooltip_is_translated(iface):
    from poplar.ui.main_dialog import MainDialog

    dialog = MainDialog(iface, lambda page: None)
    raw_key = re.compile(r"^[a-z_]+(\.[a-z_]+)+$")
    for widget in dialog.findChildren(QWidget):
        assert ".tip" not in widget.toolTip(), widget.toolTip()
        if isinstance(widget, QLabel):
            assert not raw_key.match(widget.text()), widget.text()


def test_catalogs_are_complete():
    catalogs = {}
    for language in ("fr", "en"):
        with open(os.path.join(REPO, "plugin", "poplar", "i18n", f"{language}.json"), encoding="utf-8") as handle:
            catalogs[language] = json.load(handle)
    assert set(catalogs["fr"]) == set(catalogs["en"])


def test_help_and_about(iface):
    from poplar.ui.about_dialog import AboutDialog, version
    from poplar.ui.help_dialog import HelpDialog

    help_dialog = HelpDialog()
    assert help_dialog.toc.count() == 5
    help_dialog.show_page("non_convergence")
    assert "Non-convergence" in help_dialog.browser.toPlainText()
    help_dialog.search.setText("rendement")
    visible = [help_dialog.toc.item(i).text() for i in range(help_dialog.toc.count())
               if not help_dialog.toc.item(i).isHidden()]
    assert visible and len(visible) < 5
    assert version() == "0.1.0"
    AboutDialog()


def test_help_html_is_up_to_date(tmp_path):
    import subprocess
    import sys

    before = {n: open(os.path.join(REPO, "plugin/poplar/help/fr", n), encoding="utf-8").read()
              for n in os.listdir(os.path.join(REPO, "plugin/poplar/help/fr"))}
    subprocess.run([sys.executable, os.path.join(REPO, "tools", "build_help.py")], check=True, capture_output=True)
    after = {n: open(os.path.join(REPO, "plugin/poplar/help/fr", n), encoding="utf-8").read()
             for n in os.listdir(os.path.join(REPO, "plugin/poplar/help/fr"))}
    assert before == after, "run tools/build_help.py after editing docs/aide"
