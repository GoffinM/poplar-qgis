"""Screenshots of the plugin window on the Muramvya example (docs/captures/).

Run headless: QT_QPA_PLATFORM=offscreen python3 tools/capture_plugin.py [--dark]
"""

import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tests_plugin"))

from qgis_env import MURAMVYA, FakeIface  # noqa: E402  (starts QGIS)


def main():
    from qgis.core import QgsProject
    from qgis.PyQt.QtGui import QColor, QPalette
    from qgis.PyQt.QtWidgets import QApplication

    dark = "--dark" in sys.argv
    if dark:
        palette = QPalette()
        for role, colour in ((QPalette.ColorRole.Window, "#2b3030"), (QPalette.ColorRole.Base, "#1f2424"),
                             (QPalette.ColorRole.WindowText, "#e4ecea"), (QPalette.ColorRole.Text, "#e4ecea"),
                             (QPalette.ColorRole.Button, "#333a3a"), (QPalette.ColorRole.ButtonText, "#e4ecea")):
            palette.setColor(role, QColor(colour))
        QApplication.instance().setPalette(palette)

    from poplar.task import RunTask
    from poplar.ui.main_dialog import MainDialog

    work = tempfile.mkdtemp()
    with open(os.path.join(MURAMVYA, "scenario_muramvya.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    for name in os.listdir(MURAMVYA):
        if not os.path.isdir(os.path.join(MURAMVYA, name)):
            shutil.copy(os.path.join(MURAMVYA, name), work)
    data["calibration"] = {
        "buildings": {"source": "buildings_muramvya.gpkg", "area_field": "area_m2"},
        "strata": {"source": "commune_muramvya.shp", "field": "COMMUNES", "group_field": "Type"},
        "census": {"MURAMVYA  RURAL": 136759, "MURAMVYA URBAIN": 34251}, "census_year": 2024,
    }
    data["time"]["end_year"] = 2030
    data["time"]["output_years"] = []
    path = os.path.join(work, "scenario.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)

    dialog = MainDialog(FakeIface(), lambda page: None)
    dialog.load_file(path)
    dialog.resize(1000, 760)
    for _ in range(2):
        task = RunTask(dialog.scenario(), "capture")
        task.done.connect(dialog._finished)
        task.run()
        task.finished(True)
    dialog.show()
    suffix = "_dark" if dark else ""
    out = os.path.join(REPO, "docs", "captures")
    for key in ("scenario", "data", "parameters", "indicators", "run", "results", "report"):
        dialog.show_page(key)
        QApplication.processEvents()
        dialog.grab().save(os.path.join(out, f"plugin_{key}{suffix}.png"))
    page = dialog.page("calibration")
    dialog.show_page("calibration")
    page.compute(background=False)
    page.group_table.selectRow(0)
    for view in ("distribution", "cumulative"):
        page._set_view(view)
        QApplication.processEvents()
        page.grab().save(os.path.join(out, f"plugin_calibration_{view}{suffix}.png"))
    from poplar.ui.cleanup_dialog import CleanupDialog

    cleanup = CleanupDialog(dialog.output_directory(), dialog)
    cleanup.show()
    QApplication.processEvents()
    cleanup.grab().save(os.path.join(out, f"plugin_cleanup{suffix}.png"))
    QgsProject.instance().clear()
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
