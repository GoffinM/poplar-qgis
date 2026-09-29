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
    groups = [g for g in QgsProject.instance().layerTreeRoot().findGroups()
              if g.name().startswith("Poplar – Muramvya – exemple – ")]
    assert len(groups) == 1 and len(groups[0].findLayers()) == 2
    assert os.path.dirname(dialog.results_directory()) == dialog.output_directory()  # one folder per run
    dialog.page("report").refresh()
    assert "2030" in dialog.page("report").text.toPlainText()
    QgsProject.instance().clear()


def _run_in_dialog(dialog):
    from poplar.task import RunTask

    task = RunTask(dialog.scenario(), "test")
    task.done.connect(dialog._finished)
    assert task.run()
    task.finished(True)
    return dialog.selected_run


def test_runs_are_kept_apart_and_cleaned_up(iface, scenario_copy, monkeypatch):
    from poplar.engine import runs
    from poplar.ui.cleanup_dialog import CleanupDialog
    from poplar.ui.main_dialog import MainDialog

    dialog = MainDialog(iface, lambda page: None)
    dialog.load_file(scenario_copy)
    first = _run_in_dialog(dialog)
    second = _run_in_dialog(dialog)          # rewriting while the layers of the first run are open
    assert first != second and os.path.isdir(first) and os.path.isdir(second)
    assert dialog.session_runs == [first, second]

    page = dialog.page("results")
    page.refresh()
    assert page.run_list.count() == 2 and page.run_list.currentData() == second
    page.run_list.setCurrentIndex(1)
    page._run_chosen(1)
    assert dialog.results_directory() == first
    page.kept.setChecked(True)               # « à conserver »
    assert runs.read_run(first).kept

    cleanup = CleanupDialog(dialog.output_directory(), dialog)
    assert cleanup.selected() == [second]    # the kept run is spared
    cleanup.table.item(1, 5).setCheckState(cleanup.table.item(0, 5).checkState())  # untick « à conserver »
    assert not runs.read_run(first).kept
    cleanup.all.setChecked(False)
    cleanup.all.setChecked(True)
    assert set(cleanup.selected()) == {first}  # nothing kept: the latest success is spared
    layers = QgsProject.instance().mapLayers()
    assert any(l.source().startswith(first) for l in layers.values())
    cleanup.delete_selected()
    assert cleanup.deleted == [first] and not os.path.exists(first) and os.path.isdir(second)
    assert not any(l.source().startswith(first) for l in QgsProject.instance().mapLayers().values())

    offered = []
    monkeypatch.setattr(dialog, "clean_up", lambda key="": offered.append(key))
    dialog.session_runs = [second]
    runs.set_kept(second, False)
    _run_in_dialog(dialog)
    dialog.end_session()                     # end of session: clean-up offered once
    dialog.end_session()
    assert offered == ["cleanup.intro_end"]
    QgsProject.instance().clear()


def test_exclusion_made_of_lines_needs_a_buffer(iface, scenario_copy, tmp_path):
    from osgeo import ogr, osr
    from qgis.core import QgsVectorLayer
    from poplar.ui.main_dialog import MainDialog

    # A road crossing Muramvya, as a line layer
    path = str(tmp_path / "route.gpkg")
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    datasource = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    layer = datasource.CreateLayer("route", srs, ogr.wkbLineString)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(ogr.CreateGeometryFromWkt("LINESTRING (29.55 -3.30, 29.70 -3.22)"))
    layer.CreateFeature(feature)
    feature = layer = datasource = None
    road = QgsVectorLayer(path, "route", "ogr")
    assert road.isValid()
    QgsProject.instance().addMapLayer(road)

    dialog = MainDialog(iface, lambda page: None)
    dialog.load_file(scenario_copy)
    data = dialog.page("data")
    data._add_exclusion({"name": "RN7"})
    row = data.exclusions.rowCount() - 1
    data.exclusions.cellWidget(row, 1).setLayer(road)
    data.exclusions.cellWidget(row, 2).setCurrentIndex(1)  # relocate
    data.exclusions.item(row, 3).setText("2027")
    assert not dialog.check()
    assert any("RN7" in dialog.page("run").checks.item(i).text() for i in range(dialog.page("run").checks.count()))
    data.exclusions.item(row, 4).setText("50")
    assert dialog.check()
    assert dialog.collect()["exclusions"][-1]["buffer_m"] == 50
    directory = _run_in_dialog(dialog)
    with open(os.path.join(directory, "report.json"), encoding="utf-8") as handle:
        events = json.load(handle)["events"]
    assert any(e["code"] == "exclusion_relocated" and "RN7" in e["text"] for e in events)
    QgsProject.instance().clear()


def test_clean_up_is_offered_when_qgis_closes(iface):
    import poplar
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    plugin = poplar.classFactory(iface)
    plugin.initGui()
    calls = []

    class Dialog:
        def end_session(self):
            calls.append(True)

    plugin.dialog = Dialog()
    QCoreApplication.sendEvent(iface.mainWindow(), QEvent(QEvent.Type.Close))
    assert calls == [True]
    plugin.dialog = None
    plugin.unload()


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
