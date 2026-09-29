"""One folder per run, kept runs and clean-up (decision of 29/09/2026)."""

import datetime as dt
import json
import os

import numpy as np
import pytest

from engine import runs
from engine.scenario import load_scenario
from engine.simulation import run
from world import make_world


def _run_folder(root, when, status="success", kept=False):
    directory = runs.new_run_directory(str(root), dt.datetime.fromisoformat(when))
    runs.finish_run(directory, "test", status, ["2025", "2030"])
    if kept:
        runs.set_kept(directory, True)
    return directory


def test_run_folders_are_time_stamped_and_unique(tmp_path):
    when = dt.datetime(2026, 9, 29, 14, 2, 5)
    first = runs.new_run_directory(str(tmp_path), when)
    second = runs.new_run_directory(str(tmp_path), when)
    assert os.path.basename(first) == "2026-09-29_140205"
    assert os.path.basename(second) == "2026-09-29_140205_2"
    assert runs.read_run(first).status == runs.RUNNING


def test_list_and_mark_runs(tmp_path):
    a = _run_folder(tmp_path, "2026-09-29T14:02:00", status="failed")
    b = _run_folder(tmp_path, "2026-09-29T14:15:00")
    (tmp_path / "not_a_run").mkdir()
    listed = runs.list_runs(str(tmp_path))
    assert [r.directory for r in listed] == [a, b]
    runs.set_kept(a, True, label="référence")
    kept = runs.read_run(a)
    assert kept.kept and kept.label == "référence" and kept.status == "failed"
    runs.finish_run(a, "test", "success", ["2030"])  # a new outcome keeps the flag and the label
    assert runs.read_run(a).kept and runs.read_run(a).label == "référence"


def test_default_deletion_spares_kept_runs_or_the_latest_success(tmp_path):
    a = _run_folder(tmp_path, "2026-09-29T14:02:00", status="failed")
    b = _run_folder(tmp_path, "2026-09-29T14:15:00")
    c = _run_folder(tmp_path, "2026-09-29T14:31:00")
    d = _run_folder(tmp_path, "2026-09-29T14:48:00", status="failed")
    listed = runs.list_runs(str(tmp_path))
    assert runs.default_deletion(listed) == {a, b, d}          # no run kept: the latest success is spared
    assert runs.default_deletion(listed[::-1]) == {a, b, d}    # whatever the order of the list
    runs.set_kept(b, True)
    assert runs.default_deletion(runs.list_runs(str(tmp_path))) == {a, c, d}


def test_delete_run_only_deletes_run_folders(tmp_path):
    directory = _run_folder(tmp_path, "2026-09-29T14:02:00")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "precious.shp").write_text("x")
    with pytest.raises(ValueError):
        runs.delete_run(str(tmp_path / "data"))
    assert (tmp_path / "data" / "precious.shp").exists()
    with open(os.path.join(directory, "population_2025.tif"), "wb") as handle:
        handle.write(b"\0" * 1000)
    assert runs.folder_size(directory) > 1000
    assert runs.delete_run(directory) == []
    assert not os.path.exists(directory)


def test_simulation_writes_each_run_in_its_own_folder(tmp_path):
    path = make_world(str(tmp_path), np.full((10, 10), 1000.0))
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data["output"]["per_run"] = True
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    scenario = load_scenario(path)
    first = run(scenario)
    second = run(scenario)
    root = scenario.path(scenario.output_directory)
    assert first.directory != second.directory
    assert os.path.dirname(first.directory) == root
    listed = runs.list_runs(root)
    assert [r.directory for r in listed] == [first.directory, second.directory]
    assert listed[0].status == "success" and listed[0].years[0] == "2024" and listed[0].years[-1] == "2030"
    assert os.path.exists(os.path.join(first.directory, "population_2030.tif"))
    assert load_scenario(os.path.join(first.directory, "scenario_used.json")).output_per_run
