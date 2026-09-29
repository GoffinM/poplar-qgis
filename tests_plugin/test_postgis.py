"""Roofs read from a real PostGIS database (runs only when POPLAR_PG_TEST gives a connection).

Set up once (see docs/verification_poste.md, « Toits dans une base PostGIS »):
    ogr2ogr -f PostgreSQL "PG:host=localhost dbname=sig user=sher" data/test/muramvya/buildings_muramvya.gpkg \\
        -nln burundi.batiments -lco SPATIAL_INDEX=GIST
    POPLAR_PG_TEST="dbname='sig' host=localhost port=5432 user='sher' password='…'"
"""

import json
import os

import pytest
from qgis.core import QgsProject, QgsVectorLayer

from test_plugin import scenario_copy  # noqa: F401  (fixture)

CONNECTION = os.environ.get("POPLAR_PG_TEST")
pytestmark = pytest.mark.skipif(not CONNECTION, reason="no PostGIS test database (POPLAR_PG_TEST)")


def test_calibration_and_run_from_postgis(iface, scenario_copy):
    from poplar.task import RunTask
    from poplar.ui.main_dialog import MainDialog

    layer = QgsVectorLayer(f"{CONNECTION} key='fid' srid=32735 table=\"burundi\".\"batiments\" (geom)", "toits",
                           "postgres")
    assert layer.isValid() and layer.featureCount() == 38_942
    QgsProject.instance().addMapLayer(layer)
    dialog = MainDialog(iface, lambda page: None)
    dialog.load_file(scenario_copy)
    page = dialog.page("calibration")
    page.roof_layer.setLayer(layer)
    page.area_field.setLayer(layer)
    page.area_field.setField("area_m2")
    page.strata_layer.setLayer(dialog.page("data").typology.currentLayer())
    page.strata_field.setField("COMMUNES")
    page.group_field.setField("Type")
    page._fill_census()
    for row in range(page.census.rowCount()):
        key = page.census.item(row, 0).data(256)
        page.census.item(row, 1).setText("136759" if "RURAL" in key else "34251")
    page.census_year.setValue(2024)
    assert page.compute(background=False)
    assert "38 942" in page.status.text() and page.group_table.rowCount() == 2
    page.use_roofs.setChecked(True)
    data = dialog.collect()
    assert data["calibration"]["buildings"]["source"].startswith("PG:")
    password = dict(p.split("=", 1) for p in CONNECTION.split() if "=" in p).get("password", "").strip("'")
    assert not password or password not in json.dumps(data)
    task = RunTask(dialog.scenario(), "postgis")
    task.done.connect(dialog._finished)
    assert task.run()
    task.finished(True)
    with open(os.path.join(dialog.selected_run, "scenario_used.json"), encoding="utf-8") as handle:
        assert not password or password not in handle.read()
    QgsProject.instance().clear()
