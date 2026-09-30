"""Excel workbook of the calibration (calage.xlsx): written without any library, read by Excel and LibreOffice."""

import copy
import json
import os
import re
import zipfile
from xml.etree import ElementTree

import pytest

from engine.calibration_excel import write_calibration_workbook
from engine.roof_population import GroupSettings, refresh_report
from engine.scenario import scenario_from_dict
from engine.simulation import calibrate, run
from engine.xlsx import Chart, Series, Workbook, sheet_title
from paths import MURAMVYA

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _scenario(tmp_path, **changes):
    with open(os.path.join(MURAMVYA, "scenario_muramvya_toits.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    data["output"] = {"directory": str(tmp_path / "out")}
    data["time"].update({"end_year": 2026, "output_years": [2026]})
    data.update(changes)
    return scenario_from_dict(data, MURAMVYA), data


@pytest.fixture(scope="module")
def calibrated(tmp_path_factory):
    scenario, data = _scenario(tmp_path_factory.mktemp("calage"))
    report, groups = calibrate(scenario)
    return report, groups, data


def _parts(path):
    with zipfile.ZipFile(path) as package:
        return {name: package.read(name) for name in package.namelist()}


def _sheets(parts):
    workbook = ElementTree.fromstring(parts["xl/workbook.xml"])
    return [s.get("name") for s in workbook.iter(f"{MAIN}sheet")]


def _texts(xml):
    return [t.text for t in ElementTree.fromstring(xml).iter(f"{MAIN}t")]


def test_workbook_of_the_calibration(tmp_path, calibrated):
    report, _, data = calibrated
    calibration = copy.deepcopy(data["calibration"])
    calibration["strata"]["source"] = "PG:dbname=sig host=srv user=sher password='secret' table=communes"
    path = write_calibration_workbook(report, str(tmp_path / "calage.xlsx"), "fr", calibration, "Muramvya")
    parts = _parts(path)
    for name, content in parts.items():                              # every part is well-formed XML
        if name.endswith((".xml", ".rels")):
            ElementTree.fromstring(content)
    assert _sheets(parts) == ["Synthèse", "Classes – Rural", "Distribution – Rural", "Classes – Urbain1",
                              "Distribution – Urbain1", "Hypothèses", "Sources"]
    assert len([n for n in parts if n.startswith("xl/charts/chart")]) == 8
    summary = " ".join(t for t in _texts(parts["xl/worksheets/sheet1.xml"]) if t)
    assert "Calage des toits – Muramvya" in summary and "MURAMVYA URBAIN" in summary
    classes = parts["xl/worksheets/sheet2.xml"].decode()
    assert "<f>D5*G5</f>" in classes and "<f>SUM(H5:H12)</f>" in classes      # live formulas
    assert "16,9 m² de toit par habitant" in classes
    everything = b"".join(parts.values()).decode("utf-8", "replace")
    assert "secret" not in everything and "PG:dbname=sig" in everything  # the source, never the password
    chart = parts["xl/charts/chart1.xml"].decode()
    assert "'Classes – Rural'!$K$6:$K$" in chart and "<c:scatterChart>" in chart


def test_workbook_opens_with_openpyxl(tmp_path, calibrated):
    openpyxl = pytest.importorskip("openpyxl")
    report, _, data = calibrated
    path = write_calibration_workbook(report, str(tmp_path / "calage.xlsx"), "en", data["calibration"])
    book = openpyxl.load_workbook(path)
    assert book.sheetnames[0] == "Summary" and book["Classes – Rural"]["A4"].value == "Class"


def test_report_follows_the_settings_being_edited(calibrated):
    report, groups, _ = calibrated
    settings = {name: GroupSettings.from_dict(name, entry["settings"]) for name, entry in report["groups"].items()}
    settings["Rural"].n_classes = 5
    settings["Rural"].area_per_person = 20.0                          # fewer inhabitants per roof
    fresh = refresh_report(report, groups, settings)
    assert len(fresh["groups"]["Rural"]["class_counts"]) == 5 and len(report["groups"]["Rural"]["class_counts"]) == 8
    rural = fresh["strata"]["MURAMVYA  RURAL"]
    assert rural["computed"] < report["strata"]["MURAMVYA  RURAL"]["computed"]
    assert rural["gap_percent"] < 0 and rural["factor"] == 1.0
    assert fresh["total"] == pytest.approx(sum(s["population"] for s in fresh["strata"].values()))
    assert refresh_report(report, groups, settings, recalibrate=True)["total"] == pytest.approx(136_759 + 34_251)


def test_every_run_from_roofs_writes_the_workbook_and_the_command_rebuilds_it(tmp_path):
    from engine.__main__ import main

    scenario, _ = _scenario(tmp_path)
    result = run(scenario)
    path = os.path.join(result.directory, "calage.xlsx")
    assert path in result.outputs and os.path.getsize(path) > 10_000
    os.remove(path)
    assert main(["excel", result.directory, "--language", "en"]) == 0
    assert _sheets(_parts(path))[0] == "Summary"


def test_writer_basics(tmp_path):
    book = Workbook("t")
    sheet = book.sheet("a/b:c*")
    assert sheet.name == "a-b-c-" and sheet_title("a-b-c-", [sheet.name]) == "a-b-c- (2)"
    sheet.row(1, ["x", 1, 2.5, None, True, "=A1", "é<&>"])
    sheet.set(2, 1, float("nan"))
    chart = Chart("bar", "c", legend=False).add(Series("s", sheet.ref(2, 1, 1), sheet.ref(3, 1, 1)))
    sheet.add_chart(chart, 1, 3)
    parts = _parts(book.save(str(tmp_path / "t.xlsx")))
    xml = parts["xl/worksheets/sheet1.xml"].decode()
    assert '<c r="B1"><v>1</v></c>' in xml and "<f>A1</f>" in xml and "é&lt;&amp;&gt;" in xml
    assert re.search(r'<c r="A2"/>', xml)                             # NaN left empty
    assert "xl/charts/chart1.xml" in parts and "xl/drawings/drawing1.xml" in parts
