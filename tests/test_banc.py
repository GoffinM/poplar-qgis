"""The non-regression bench (tools/banc.py) runs with the tests: every key figure within its tolerance."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import banc  # noqa: E402


def test_every_case_is_within_tolerance(tmp_path):
    results = banc.run_bench(str(tmp_path), network=bool(os.environ.get("POPLAR_NET_TEST")))
    assert {"muramvya_raster", "muramvya_toits_classeurs", "muramvya_toits"} <= set(results)
    out = [(name, row[5], row[1], row[2]) for name, result in results.items() for row in result["rows"] if not row[4]]
    assert out == []
    text, failures = banc.summary(results)
    assert failures == 0 and "Tout est conforme" in text


def test_a_figure_out_of_tolerance_is_reported():
    rows = banc.check("x", {"a": 10.5, "b": "failed"}, {"a": {"value": 10, "tolerance": 0.1},
                                                         "b": {"value": "success"}})
    assert [row[4] for row in rows] == [False, False]
    assert banc._fmt(139099.6545) == "139 099,6545" and banc._fmt(-1e-9) == "0"


@pytest.mark.parametrize("name", sorted(banc.CASES))
def test_every_case_has_expected_values(name):
    import json

    with open(banc.EXPECTED, encoding="utf-8") as handle:
        assert json.load(handle)[name]["figures"]
