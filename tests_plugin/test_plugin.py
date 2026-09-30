import csv
import json
import os
import re
import shutil

import numpy as np
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
    assert all(a.isEnabled() for a in plugin.actions)
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
    nodes = groups[0].findLayers() if len(groups) == 1 else []
    assert sorted(n.name() for n in nodes) == ["density 2025", "density 2030", "population 2025", "population 2030"]
    assert sorted(n.name() for n in nodes if n.itemVisibilityChecked()) == ["density 2030", "population 2030"]
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
    data.exclusions.cellWidget(row, 1).combo.setLayer(road)
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
    assert any("Urbain2" in str(m) for m in iface.bar.messages)          # shown in the message bar too
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


def _two_layer_geopackage(path):
    from osgeo import ogr, osr

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32735)
    datasource = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    for name, geometry_type, wkt in (("provinces", ogr.wkbPolygon, "POLYGON ((781000 9626000, 809000 9626000, "
                                      "809000 9651000, 781000 9651000, 781000 9626000))"),
                                     ("forages", ogr.wkbPoint, "POINT (795000 9638000)")):
        layer = datasource.CreateLayer(name, srs, geometry_type)
        layer.CreateField(ogr.FieldDefn("nom", ogr.OFTString))
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
        feature.SetField("nom", name)
        layer.CreateFeature(feature)
    datasource = None
    return path


def test_layers_are_chosen_from_files(iface, scenario_copy, tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog, QInputDialog, QMessageBox
    from poplar.ui import widgets
    from poplar.ui.main_dialog import MainDialog

    path = _two_layer_geopackage(str(tmp_path / "zonage.gpkg"))
    dialog = MainDialog(iface, lambda page: None)
    dialog.load_file(scenario_copy)
    growth = dialog.page("parameters").tables["growth_rate"]
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (path, ""))

    # A GeoPackage with two layers: the user picks one
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: ("provinces", True))
    layer = widgets.pick_file(growth.layer)
    assert layer is not None and growth.layer.currentLayer() is layer and not warnings
    assert widgets.source_of(layer) == {"source": path, "layer": "provinces"}
    assert widgets.pick_file(growth.layer) is layer                      # chosen twice: added once
    growth.field.setField("nom")
    assert list(growth.values()) == ["provinces", "*"]

    # Points in a list of polygons: explained, not selected
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: ("forages", True))
    assert widgets.pick_file(growth.layer) is None and "polygones" in warnings[-1]
    assert growth.layer.currentLayer() is layer
    QgsProject.instance().clear()


def test_layer_filters_and_other_sources(iface, scenario_copy, tmp_path, monkeypatch):
    import qgis.gui
    from qgis.core import QgsVectorLayer
    from poplar.compat import SECRETS, engine_source, postgres_layer
    from poplar.ui import widgets
    from poplar.ui.main_dialog import MainDialog

    # A filter set in QGIS is passed to the engine
    path = _two_layer_geopackage(str(tmp_path / "zonage.gpkg"))
    filtered = QgsVectorLayer(f"{path}|layername=provinces", "provinces", "ogr")
    filtered.setSubsetString("\"nom\" = 'provinces'")
    assert engine_source(filtered) == {"source": path, "layer": "provinces", "where": "\"nom\" = 'provinces'"}
    QgsProject.instance().addMapLayer(filtered)
    assert widgets.find_or_add_layer(path, "provinces", where="\"nom\" = 'provinces'") is filtered

    # PostGIS: connection string without the password, which is added for the run only
    uri = ("dbname='sig' host='srv.sher.be' port=5432 user='analyste' password='s3cret' sslmode=require "
           "key='id' srid=32735 type=MultiPolygon table=\"burundi\".\"communes\" (geom) sql=\"province\" = 'Muramvya'")
    postgis = QgsVectorLayer(uri, "communes", "postgres")
    spec = engine_source(postgis)
    assert spec == {"source": "PG:dbname='sig' host='srv.sher.be' port='5432' user='analyste' sslmode='require'",
                    "layer": "burundi.communes(geom)", "where": "\"province\" = 'Muramvya'"}
    assert SECRETS[spec["source"]] == "s3cret"
    again = postgres_layer(spec, "communes")
    assert engine_source(again) == spec                                  # a scenario reopens the same table

    dialog = MainDialog(iface, lambda page: None)
    dialog.load_file(scenario_copy)
    data = dialog.collect()
    data["admin_units"] = dict(spec, field="COMMUNE")
    dialog.data = data
    from poplar.ui.main_dialog import _with_passwords
    assert "password='s3cret'" in _with_passwords(data)["admin_units"]["source"]
    assert "s3cret" not in json.dumps(data)

    # A memory layer cannot be read by the engine: refused when chosen, reported by the check
    memory = QgsVectorLayer("Polygon?crs=EPSG:32735", "brouillon", "memory")
    warnings = []
    from qgis.PyQt.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    growth = dialog.page("parameters").tables["growth_rate"]
    assert widgets.set_new_layer(growth.layer, memory) is None and "GeoPackage" in warnings[-1]
    QgsProject.instance().addMapLayer(memory)
    growth.layer.setLayer(memory)
    assert not dialog.check()
    assert any("brouillon" in dialog.page("run").checks.item(i).text() for i in range(dialog.page("run").checks.count()))

    # « Database or other source… »: the QGIS source browser
    class Uri:
        uri, name, providerKey = f"{path}|layername=provinces", "provinces (base)", "ogr"

        def isValid(self):
            return True

    class Browser:
        def __init__(self, *args):
            pass

        def setWindowTitle(self, title):
            pass

        def exec(self):
            return True

        def uri(self):
            return Uri()

    monkeypatch.setattr(qgis.gui, "QgsDataSourceSelectDialog", Browser)
    growth.layer.setLayer(None)
    chosen = widgets.pick_source(growth.layer)
    assert chosen is not filtered and chosen.name() == "provinces (base)"   # no filter: another layer
    assert growth.layer.currentLayer() is chosen
    QgsProject.instance().clear()


def _with_calibration(scenario_copy):
    with open(scenario_copy, encoding="utf-8") as handle:
        data = json.load(handle)
    data["calibration"] = {
        "buildings": {"source": os.path.join(MURAMVYA, "buildings_muramvya.gpkg"), "area_field": "area_m2"},
        "strata": {"source": data["typology"]["source"], "field": "COMMUNES", "group_field": "Type"},
        "census": {"MURAMVYA  RURAL": 136_759, "MURAMVYA URBAIN": 34_251}, "census_year": 2024,
    }
    with open(scenario_copy, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return scenario_copy


def test_calibration_tab(iface, scenario_copy, tmp_path):
    from poplar.ui.main_dialog import MainDialog

    dialog = MainDialog(iface, lambda page: None)
    dialog.load_file(_with_calibration(scenario_copy))
    page = dialog.page("calibration")
    assert page.census.rowCount() == 2 and page.census_values()["MURAMVYA URBAIN"] == 34_251
    roofs = page.roof_layer.currentLayer()
    page.roof_layer.setLayer(None)
    page.roof_layer.setLayer(roofs)                                 # choosing the layer again, by hand
    assert page.area_field.currentField() == "area_m2"              # guessed from its name
    assert page.usage_field.currentField() == ""                    # never the first field by default
    strata = page.strata_layer.currentLayer()
    page.strata_layer.setLayer(None)
    page.strata_layer.setLayer(strata)
    page.strata_field.setField("COMMUNES")
    assert page.group_field.currentField() == "" and page.census_field.currentField() == ""
    page.group_field.setField("Type")
    page.census_field.setField("COMMUNES")                          # text: not offered for a population
    assert page.census_field.currentField() == ""
    assert page.compute(background=False)
    assert page.group_table.rowCount() == 2 and "38 942" in page.status.text()
    page.group_table.selectRow(0)                                   # Rural
    assert page.current == "Rural" and page.editor.isEnabled()
    assert page.classes.rowCount() == 8 and len(page.chart.edges) == 9
    assert "écart +0,05" in page.totals.text() or "gap +0.05" in page.totals.text()

    from poplar.ui.widgets import set_combo_value
    shown = tuple(page.chart.edges)
    set_combo_value(page.cut, "manual")                             # chosen in the list: no error, limits kept
    assert page.settings["Rural"].cut == "manual" and page.settings["Rural"].edges == shown
    probe = np.array([15.0, 35.0, 60.0, 100.0])
    drawn = {}
    for method in ("steps", "segments", "polynomial"):              # the chart draws the curve of the method
        set_combo_value(page.method, method)
        assert page.chart.curve.method == method
        drawn[method] = tuple(np.round(page.chart.curve.population(probe), 3))
        page.chart.grab()
    assert len(set(drawn.values())) == 3
    set_combo_value(page.method, "steps")
    set_combo_value(page.cut, "breaks")

    page.n_classes.setValue(6)                                      # recut and refit at once
    assert page.classes.rowCount() == 6 and page.settings["Rural"].n_classes == 6
    page.chart.move_edge(2, 45)                                     # a limit dragged: manual cut
    assert page.settings["Rural"].cut == "manual" and 45 in page.settings["Rural"].edges
    value = float(page.classes.item(5, 6).text()) + 1
    page.classes.item(5, 6).setText(f"{value:g}")                  # one value changed by hand
    assert page.settings["Rural"].overrides == {5: value}
    assert page.classes.item(5, 6).text() == f"{value:g}"
    page._set_view("cumulative")
    page.chart.grab()                                               # both views draw without error
    page._set_view("distribution")
    page.chart.grab()

    page.use_roofs.setChecked(True)
    data = dialog.collect()
    assert data["base_population"]["source"] == "buildings"
    groups = data["calibration"]["groups"]
    assert groups["Rural"]["classes"]["method"] == "manual" and groups["Rural"]["overrides"] == {"5": value}
    assert groups["Urbain1"]["area_per_person"] > 0
    path = page.export_calibration(str(tmp_path / "calage.json"))
    page.settings = {}
    page.import_calibration(path)
    assert page.settings["Rural"].overrides == {5: value}

    directory = _run_in_dialog(dialog)
    with open(os.path.join(directory, "calibration.json"), encoding="utf-8") as handle:
        report = json.load(handle)
    assert report["groups"]["Rural"]["overridden"] == [5]
    assert dialog.page("report").refresh() is None
    QgsProject.instance().clear()


class _FakeTiles:
    """Serves 2 000 roofs of the workbooks as the Google tile 19c1; the other tiles have no buildings."""

    def __init__(self):
        from osgeo import ogr, osr

        from poplar.engine.downloads.fetch import RemoteMissing

        self.missing = RemoteMissing
        datasource = ogr.Open(os.path.join(MURAMVYA, "buildings_muramvya.gpkg"))
        layer = datasource.GetLayer(0)
        wgs84 = osr.SpatialReference()
        wgs84.ImportFromEPSG(4326)
        wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        source = layer.GetSpatialRef().Clone()
        source.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        transform = osr.CoordinateTransformation(source, wgs84)
        rows = []
        for index, feature in enumerate(layer):
            if index % 19:
                continue
            point = feature.GetGeometryRef().Centroid()
            lon, lat = transform.TransformPoint(point.GetX(), point.GetY())[:2]
            rows.append(f"{lat:.8f},{lon:.8f},{feature.GetField('area_m2'):.4f},0.8,6G8GXM9W+MR9C")
        self.rows = rows
        self.calls = []

    def size(self, url):
        if "/19c1_" not in url:
            raise self.missing(url)
        return 1000

    def fetch(self, url, path, progress=None, cancelled=None):
        import gzip

        self.calls.append(url)
        if "/19c1_" not in url:
            raise self.missing(url)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write("\n".join(self.rows) + "\n")


def test_roofs_downloaded_from_the_calibration_tab(iface, scenario_copy, tmp_path, monkeypatch):
    from poplar.ui.main_dialog import MainDialog

    dialog = MainDialog(iface, lambda page: None)
    dialog.load_file(_with_calibration(scenario_copy))
    page = dialog.page("calibration")
    window = page.download_roofs(show=False)
    assert window.zone_layer.currentLayer() == page.strata_layer.currentLayer()
    assert window.output.filePath().endswith(os.path.join("toits", "google_open_buildings_commune_muramvya.gpkg"))
    window.fetcher = _FakeTiles()
    window.cache_dir.setFilePath(str(tmp_path / "cache"))
    estimate = window.estimate()
    assert [t["tile"] for t in estimate["tiles"]] == ["19c1"] and "19c1" not in estimate["missing"]
    assert window.start(background=False)
    counts = window.report["counts"]
    assert counts["kept"] == len(window.fetcher.rows)
    raw_key = re.compile(r"^[a-z_]+(\.[a-z_]+)+$")
    texts = [w.text() for w in window.findChildren(QLabel)] + [w.toolTip() for w in window.findChildren(QWidget)]
    assert not [t for t in texts if raw_key.match(t)]                  # every text of the window is translated
    assert page.roof_layer.currentLayer() is window.layer and page.area_field.currentField() == "area_m2"
    assert page.confidence_field.currentField() == "confidence"
    assert os.path.exists(window.report["output"].replace(".gpkg", ".download.json"))

    kept = f"{counts['kept']:,}".replace(",", " ")
    assert window.info.text().startswith("✔") and kept in window.info.text()          # done, said plainly
    from poplar.i18n import tr

    assert window.start_button.text() == tr("download.again") and window.close_button.objectName() == "primary"
    assert page.roof_origin.isVisible() or not page.isVisible()
    assert kept in page.roof_origin.text() and any(kept in str(m) for m in iface.bar.messages)

    from qgis.PyQt.QtWidgets import QMessageBox

    again = page.download_roofs(show=False)                          # opened again: the download is announced
    assert again.info.text().startswith("✔") and again.start_button.text() == tr("download.again")
    assert again.close_button.objectName() == "primary" and again.start_button.objectName() == ""
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    assert not again.start(background=False)                         # a second click is confirmed first

    assert page.compute(background=False)
    assert page.report["roofs"]["download"]["dataset"] == "Google Open Buildings v3"
    window.fetcher.calls.clear()
    assert window.estimate()["bytes_to_download"] == 0 and window.fetcher.calls == []     # tile in the cache
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
    assert help_dialog.toc.count() == 6
    help_dialog.show_page("non_convergence")
    assert "Non-convergence" in help_dialog.browser.toPlainText()
    help_dialog.search.setText("rendement")
    visible = [help_dialog.toc.item(i).text() for i in range(help_dialog.toc.count())
               if not help_dialog.toc.item(i).isHidden()]
    assert visible and len(visible) < 6
    assert version() == "0.3.6"
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


def test_a_shapefile_opened_through_its_shx_is_read_from_its_shp(iface):
    from qgis.core import QgsVectorLayer
    from poplar.compat import engine_source

    layer = QgsVectorLayer(os.path.join(MURAMVYA, "commune_muramvya.shx"), "communes", "ogr")
    assert engine_source(layer)["source"].endswith("commune_muramvya.shp")
