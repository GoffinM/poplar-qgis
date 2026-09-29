import csv
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
    for spec in data["parameters"].values():
        for zone in spec.get("zones", []) if isinstance(spec, dict) else []:
            zone["source"] = os.path.join(MURAMVYA, zone["source"])
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
    assert data["parameters"]["dmax"]["values"]["Urbain1"] == 10000
    assert data["parameters"]["dmax"]["zones"][0]["field"] == "Type"
    assert len(data["parameters"]["growth_rate"]["values"]["*"]) == 8
    assert "zones" not in data["parameters"]["growth_rate"]
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


def _set_cell(widget, key, column, text):
    from poplar.ui.parameter_table import VALUE

    for row in range(widget.table.rowCount()):
        if widget.table.item(row, 0).data(VALUE) == key:
            widget.table.item(row, column).setText(text)
            return
    raise KeyError(key)


def test_parameters_linked_to_layers(iface, scenario_copy, tmp_path):
    from poplar.engine.scenario import scenario_from_dict
    from poplar.ui.main_dialog import MainDialog

    dialog = MainDialog(iface, lambda page: None)
    dialog.load_file(scenario_copy)
    page = dialog.page("parameters")
    dmax, growth = page.tables["dmax"], page.tables["growth_rate"]
    assert set(dmax.values()) == {"Rural", "Urbain1", "Urbain2", "*"}
    assert dmax.unused_keys() == ["Urbain2"] and "Urbain2" in dmax.status.text()
    assert list(growth.values()) == ["*"] and growth.layer.currentLayer() is None

    # TCAM per commune: the rows come from the field
    communes = dmax.layer.currentLayer()
    growth.layer.setLayer(communes)
    growth.field.setField("COMMUNES")
    rural, urban, default = growth.values()                             # « MURAMVYA  RURAL » (two spaces)
    assert "RURAL" in rural and "URBAIN" in urban and default == "*"
    assert isinstance(growth.values()["*"], dict)  # the former default series is kept
    _set_cell(growth, urban, 1, "3,5")
    spec = dialog.collect()["parameters"]["growth_rate"]
    assert spec["zones"][0]["field"] == "COMMUNES" and spec["values"][urban] == 3.5
    assert rural not in spec["values"]                                  # no value: the default applies
    scenario_from_dict(dialog.collect(), dialog.base_dir())

    # Crossing: communes × type
    growth.cross.setChecked(True)
    growth.layer2.setLayer(communes)
    growth.field2.setField("Type")
    keys = list(growth.values())
    assert f"{urban}|Urbain1" in keys and keys[-1] == "*" and len(keys) == 5
    _set_cell(growth, f"{urban}|Urbain1", 2, "4")
    spec = dialog.collect()["parameters"]["growth_rate"]
    assert len(spec["zones"]) == 2 and spec["values"][f"{urban}|Urbain1"] == 4

    # Spreadsheet round trip
    path = dmax.export_file(str(tmp_path / "dmax.xlsx"))
    _set_cell(dmax, "Rural", 1, "1")
    dmax.import_file(path)
    assert dmax.values()["Rural"] == 2500
    directory = _run_in_dialog(dialog)
    with open(os.path.join(directory, "report.json"), encoding="utf-8") as handle:
        codes = [w["code"] for w in json.load(handle)["warnings"]]
    assert "parameter_key_unused" in codes                              # Urbain2
    QgsProject.instance().clear()


def test_projections_from_a_spreadsheet(iface, scenario_copy, tmp_path):
    from poplar.engine.tables import write_table
    from poplar.ui.main_dialog import MainDialog
    from poplar.ui.parameter_table import field_values

    dialog = MainDialog(iface, lambda page: None)
    dialog.load_file(scenario_copy)
    data = dialog.page("data")
    communes = field_values(data.admin.currentLayer(), "COMMUNES")
    path = str(tmp_path / "projections_isteebu.xlsx")
    write_table(path, ["Commune", "2024", "2030"], [[communes[0], 70000.0, 80000.0], [communes[1], 30000.0, 36000.0]])
    data.projections.setFilePath(path)
    assert data.projection_preview.property("state") == "ok"
    assert "2 " in data.projection_preview.text() and "2024–2030" in data.projection_preview.text()
    data.projection_use.setCurrentIndex(1)  # recalibrate
    projections = dialog.collect()["projections"]
    assert projections == {"file": path, "recalibrate": True}
    directory = _run_in_dialog(dialog)
    with open(os.path.join(directory, "summary.csv"), encoding="utf-8-sig") as handle:
        totals = {row[1]: int(row[2]) for row in csv.reader(handle, delimiter=";") if row[0] == "2030"}
    # Recalibrated on the projections, then migration may cross the commune limits (spec §5.2)
    assert sum(totals.values()) == 116000
    assert totals[communes[1]] == pytest.approx(36000, rel=2e-3)

    data.projection_columns["year"].setCurrentIndex(1)  # a wrong column: the error is shown before running
    data._update_projection_preview()
    assert data.projection_preview.property("state") == "warn"
    QgsProject.instance().clear()


def test_scenario_library(iface, scenario_copy, tmp_path):
    from poplar.ui.library_dialog import LibraryDialog, library_folder, set_library_folder
    from poplar.ui.main_dialog import MainDialog

    previous = library_folder()
    set_library_folder(str(tmp_path / "library"))
    try:
        dialog = MainDialog(iface, lambda page: None)
        dialog.load_file(scenario_copy)
        library = LibraryDialog(dialog)
        assert library.empty.isVisibleTo(library) and not library.open_button.isEnabled()
        path = library.add_current("Muramvya – référence", "TCAM ISTEEBU, dmax 2 500 / 10 000")
        assert os.path.dirname(path) == str(tmp_path / "library")
        assert [e.name for e in library.entries] == ["Muramvya – référence"]
        library.table.selectRow(0)
        library.open_selected()
        assert library.chosen == path

        other = MainDialog(iface, lambda page: None)
        other.load_template(library.chosen)
        assert other.path is None                                   # « Save » asks for a new file
        data = other.collect()
        assert data["name"] == "Muramvya – référence" and data["description"].startswith("TCAM")
        assert os.path.isabs(data["study_area"]["source"]) and os.path.exists(data["study_area"]["source"])
        assert other.check()
    finally:
        set_library_folder(previous)
    QgsProject.instance().clear()


def test_older_scenarios_are_converted(iface, scenario_copy):
    from poplar.ui.main_dialog import MainDialog

    with open(scenario_copy, encoding="utf-8") as handle:
        data = json.load(handle)
    typology = data["typology"]
    data["parameters"]["dmax"] = {"Rural": 2500, "Urbain1": 10000}
    data["parameters"]["growth_rate"] = {"MURAMVYA URBAIN": 3.0, "Rural": 2.5, "*": 2.0}
    data["parameter_zones"] = {"source": typology["source"], "field": "COMMUNES"}
    with open(scenario_copy, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    dialog = MainDialog(iface, lambda page: None)
    dialog.load_file(scenario_copy)
    page = dialog.page("parameters")
    growth = page.tables["growth_rate"]
    assert growth.crossed and growth.field.currentField() == "COMMUNES" and growth.field2.currentField() == "Type"
    values = {k: v for k, v in growth.values().items() if v is not None}
    assert values == {"MURAMVYA URBAIN|*": 3.0, "*|Rural": 2.5, "*": 2.0}  # zone, then class, then default
    dmax = page.tables["dmax"]
    assert dmax.crossed and {k for k, v in dmax.values().items() if v} == {"*|Rural", "*|Urbain1"}
    assert "parameter_zones" not in dialog.collect()
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
    assert version() == "0.2.0"
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
