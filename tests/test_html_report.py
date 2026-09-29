"""Automatic HTML report outside QGIS (plan of phase 6, step 6.6)."""

import json
import os

import numpy as np
import pytest

from engine.__main__ import main
from engine.html_report import build_html_report
from engine.scenario import load_scenario
from engine.simulation import run
from world import make_world


def test_every_run_writes_a_self_contained_html_report(tmp_path):
    result = run(load_scenario(make_world(str(tmp_path), np.full((10, 10), 1000.0))))
    path = os.path.join(result.directory, "report.html")
    assert path in result.outputs
    with open(path, encoding="utf-8") as handle:
        page = handle.read()
    assert page.startswith("<!doctype html>") and "<svg" in page and "Évolution de la population" in page
    assert "http" not in page.replace("http-equiv", "")                  # nothing loaded from elsewhere
    assert "Calage" not in page                                           # no roofs: no calibration section


def test_report_command_and_calibration_section(tmp_path):
    from test_roof_population import CENSUS, _scenario

    result = run(_scenario(tmp_path, {"census": CENSUS, "census_year": 2024,
                                      "groups": {"Rural": {"overrides": {"2": 9}}}}))
    os.remove(os.path.join(result.directory, "report.html"))
    assert main(["report", result.directory, "--language", "en"]) == 0
    with open(os.path.join(result.directory, "report.html"), encoding="utf-8") as handle:
        page = handle.read()
    assert "Calibration: from roofs to population" in page and "Group Rural" in page
    assert page.count("<svg") >= 5                                        # population + 2 charts per group
    assert 'class="mod"' in page                                          # the value changed by hand
    assert main(["report", str(tmp_path / "nowhere")]) == 1
    french = build_html_report(result.directory)
    assert "Surface de toit par habitant" in french
