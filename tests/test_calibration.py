"""Roofs → inhabitants calibration (spec §3 ter, plan of phase 6)."""

import os

import numpy as np
import pytest
from osgeo import ogr

from engine.calibration import (
    LEGACY, POLYNOMIAL, SEGMENTS, Curve, area_distribution, census_at, class_counts, hypothesis_values,
    legacy_curve, natural_breaks, recalibration_factors, regress_values,
)
from paths import MURAMVYA


@pytest.fixture(scope="module")
def muramvya_roofs():
    """The 38 942 roofs of the former workbooks, with the population each workbook gave them."""
    ogr.UseExceptions()
    datasource = ogr.Open(os.path.join(MURAMVYA, "buildings_muramvya.gpkg"))
    roofs = {}
    for feature in datasource.GetLayer(0):
        roofs.setdefault(feature.GetField("stratum"), []).append((feature.GetField("area_m2"),
                                                                   feature.GetField("legacy_pop")))
    return {k: np.array(v) for k, v in roofs.items()}


def test_legacy_mode_reproduces_the_workbooks(muramvya_roofs):
    for stratum, expected in (("Rural", 139_100), ("Urbain", 33_253)):
        areas, workbook = muramvya_roofs[stratum][:, 0], muramvya_roofs[stratum][:, 1]
        population = legacy_curve(stratum).population(areas)
        assert np.abs(population - workbook).max() < 1e-9            # roof by roof
        assert round(population.sum()) == expected                   # 139 100 and 33 253


def test_legacy_diagnostics_show_the_known_weaknesses(muramvya_roofs):
    areas = muramvya_roofs["Rural"][:, 0]
    diagnostics = legacy_curve("Rural").diagnostics(areas)
    assert not diagnostics["monotone"]                               # F21: maximum near 72 m², then decreasing
    # état des lieux §11.2: 16 526 rural roofs of 70 m² or more, 93 of them above 450 m² (excluded)
    assert (areas >= 70).sum() == 16_526
    assert diagnostics["share_capped"] == pytest.approx(16_433 / 32_881)


def test_full_precision_polynomial_changes_the_urban_total(muramvya_roofs):
    """F20: with the exact least-squares coefficients the urban population drops by about 9 %."""
    areas = muramvya_roofs["Urbain"][:, 0]
    exact = Curve(LEGACY, values=legacy_curve("Urbain").values)       # coefficients fitted, not rounded
    assert exact.population(areas).sum() == pytest.approx(30_341, abs=2)


def test_segments_are_monotone_and_flat_beyond_the_last_class():
    curve = Curve(SEGMENTS, edges=(10, 20, 40, 80), values=(1, 3, 5), node_areas=(15, 30, 60))
    assert curve.population([5, 15, 22.5, 30, 60, 200, 451]).tolist() == [0, 1, 2, 3, 5, 5, 0]
    wavy = Curve(SEGMENTS, edges=(10, 20, 40, 80), values=(1, 4, 3))
    assert wavy.diagnostics()["monotone"] and not wavy.diagnostics()["points_monotone"]


def test_points_at_the_mean_area_of_each_class():
    areas = np.array([11.0, 13.0, 25.0, 35.0, 70.0])
    curve = Curve(SEGMENTS, edges=(10, 20, 40, 80), values=(1, 3, 5)).with_data(areas)
    assert curve.node_areas == (12.0, 30.0, 70.0)
    assert class_counts(areas, curve.edges).tolist() == [2, 2, 1]


def test_polynomial_is_fitted_and_never_negative():
    curve = Curve(POLYNOMIAL, edges=LEGACY_EDGES_10(), values=(0, 0, 1, 2, 3, 3, 4, 5, 5, 5), min_area=0).fitted()
    assert len(curve.coefficients) == 4
    values = curve.population(np.arange(0, 450))
    assert values.min() >= 0 and values[300] == values[curve.nodes()[0][-1].astype(int) + 1]


def LEGACY_EDGES_10():
    from engine.calibration import LEGACY_EDGES

    return LEGACY_EDGES


def test_hypotheses_of_the_detailed_classes_sheet():
    assert hypothesis_values((0, 5, 13, 65, 100)) == (0.0, 1.0, 6.0, 10.0)


def test_natural_breaks_find_the_gaps_of_the_distribution():
    rng = np.random.default_rng(1)
    areas = np.concatenate([rng.normal(20, 2, 4000), rng.normal(45, 3, 3000), rng.normal(90, 5, 1000)])
    limits = natural_breaks(areas, 3, 10, 450)
    assert limits[0] == 10 and limits[-1] == 450 and len(limits) == 4
    assert 26 <= limits[1] <= 38 and 55 <= limits[2] <= 75
    distribution = area_distribution(areas)
    assert sum(distribution["count"]) >= 0.99 * len(areas)
    assert np.argmax(distribution["density"]) < 30


def test_multiple_regression_recovers_known_values():
    rng = np.random.default_rng(2)
    truth = np.array([0.5, 2.0, 3.5, 5.0])
    counts = rng.integers(50, 2000, size=(12, 4)).astype(float)
    census = counts @ truth
    result = regress_values(counts, census)
    assert np.allclose(result.values, truth, atol=1e-6) and result.r2 == pytest.approx(1.0) and result.determined
    few = regress_values(counts[:2], census[:2])
    assert not few.determined and np.all(np.diff(few.values) >= -1e-12) and min(few.values) >= 0


def test_census_gap_and_recalibration():
    assert census_at(136_759, 2024, 2023, 2.2) == pytest.approx(136_759 / 1.022)
    factors = recalibration_factors({"Rural": 139_100.0, "Urbain": 33_253.0, "Autre": 10.0},
                                     {"Rural": 136_759, "Urbain": 34_251})
    assert factors["Rural"] == pytest.approx(136_759 / 139_100) and factors["Autre"] == 1.0


def test_curves_round_trip_through_json():
    curve = Curve(POLYNOMIAL, edges=(10, 20, 40), values=(1, 2)).fitted()
    assert Curve.from_dict(curve.to_dict()) == curve
    with pytest.raises(ValueError):
        Curve(SEGMENTS, edges=(10, 5), values=(1,))
