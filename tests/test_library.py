"""Library of scenarios."""

import json
import os

from engine.library import list_library, save_to_library, slug
from engine.scenario import load_scenario
from paths import MURAMVYA


def test_save_and_list(tmp_path):
    with open(os.path.join(MURAMVYA, "scenario_muramvya.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    first = save_to_library(str(tmp_path), data, "Muramvya – dmax +20 %", "Variante haute")
    second = save_to_library(str(tmp_path), data, "Muramvya – dmax +20 %")
    assert os.path.basename(first) == "muramvya_dmax_20.json"
    assert os.path.basename(second) == "muramvya_dmax_20_2.json"
    (tmp_path / "notes.json").write_text('{"not": "a scenario"}', encoding="utf-8")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    (tmp_path / "burundi").mkdir()
    save_to_library(str(tmp_path / "burundi"), data, "Bujumbura")
    entries = list_library(str(tmp_path))
    assert [e.name for e in entries] == ["Bujumbura", "Muramvya – dmax +20 %", "Muramvya – dmax +20 %"]
    assert entries[1].description == "Variante haute"
    assert load_scenario(first).description == "Variante haute"
    assert slug("   ") == "scenario"
