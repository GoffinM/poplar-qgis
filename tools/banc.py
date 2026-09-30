"""Non-regression bench: the reference cases, their key figures, compared with the expected values.

    python tools/banc.py                 # cases without network
    python tools/banc.py --reseau        # also the Google Open Buildings download (129 MB the first time)
    python tools/banc.py --sortie DIR    # folder for the runs and the summary (temporary folder by default)

Each case gives a few figures; ``tools/banc_reference.json`` holds the expected value and the tolerance
of each. The summary (``banc.md``) lists them with the gap, and the command fails if one is out of
tolerance. To run before every new version (the tests run the same cases, without the network).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

MURAMVYA = os.path.join(ROOT, "data", "test", "muramvya")
REFERENCE_OUTPUTS = os.path.join(ROOT, "reference_outputs", "muramvya")
EXPECTED = os.path.join(HERE, "banc_reference.json")
RURAL, URBAN = "MURAMVYA  RURAL", "MURAMVYA URBAIN"
CENSUS = {RURAL: 136_759, URBAN: 34_251}


def _load(name, folder, **changes):
    from engine.scenario import scenario_from_dict

    with open(os.path.join(MURAMVYA, name), encoding="utf-8") as handle:
        data = json.load(handle)
    for key, value in changes.items():
        data[key] = value
    data["output"] = {"directory": folder}
    return scenario_from_dict(data, MURAMVYA)


def _raster_sum(directory, name):
    import numpy as np

    from engine.raster_io import read_raster

    return float(np.nansum(read_raster(os.path.join(directory, name)).values))


def _pattern(directory):
    """Correlation, cell by cell, of the 2060 population with the legacy final output (pentree_final)."""
    import numpy as np
    from osgeo import ogr

    from engine.raster_io import read_raster

    raster = read_raster(os.path.join(directory, "population_2060.tif"))
    ours = np.nan_to_num(raster.values)
    x0, y0 = raster.geotransform[0], raster.geotransform[3]
    reference = np.zeros_like(ours)
    datasource = ogr.Open(os.path.join(REFERENCE_OUTPUTS, "pentree_final.shp"))
    for feature in datasource.GetLayer(0):
        geometry = feature.GetGeometryRef()
        if geometry is None or geometry.GetArea() == 0:
            continue
        point = geometry.PointOnSurface()
        row, col = int((y0 - point.GetY()) // 250), int((point.GetX() - x0) // 250)
        reference[row, col] += feature.GetField("Pop2060") or 0
    compared = reference > 0
    return float(np.corrcoef(ours[compared], reference[compared])[0, 1])


def case_raster(folder):
    """The example scenario, 2024 → 2060, from the population raster (the former tool's chain)."""
    from engine.simulation import run

    start = time.perf_counter()
    result = run(_load("scenario_muramvya.json", folder))
    seconds = time.perf_counter() - start
    return {
        "status": result.status,
        "population_2024": result.initial_population,
        "population_2060": result.final_population,
        "growth_vs_legacy": (result.final_population / result.initial_population) / (309_642 / 164_805),
        "pattern_correlation": _pattern(result.directory),
        "water_domestic_2060": _raster_sum(result.directory, "water_domestic_2060.tif"),
        "balance_error_max": max(abs(s.balance_error) for s in result.steps),
        **_grid_layer(result.directory),
    }, seconds


def _grid_layer(directory):
    """Cells of mailles.gpkg and their 2060 population (the same total as the rasters)."""
    from osgeo import ogr

    datasource = ogr.Open(os.path.join(directory, "mailles.gpkg"))
    layer = datasource.GetLayer(0)
    total = sum(f.GetField("population_2060") or 0 for f in layer)
    return {"grid_cells": layer.GetFeatureCount(), "grid_population_2060": float(total)}


def case_legacy_roofs(folder):
    """Roofs → inhabitants with the curves of Lionel's workbooks (legacy mode)."""
    from engine.calibration import legacy_curve
    from engine.simulation import _Model

    calibration = {
        "buildings": {"source": "buildings_muramvya.gpkg", "area_field": "area_m2"},
        "strata": {"source": "commune_muramvya.shp", "field": "COMMUNES", "group_field": "Type"},
        "groups": {"Rural": legacy_curve("Rural").to_dict(), "Urbain1": legacy_curve("Urbain").to_dict()},
        "recalibrate": False,
    }
    start = time.perf_counter()
    model = _Model.load(_load("scenario_muramvya.json", folder, calibration=calibration,
                              base_population={"source": "buildings", "raster": "pop2023_muramvya.tif"}))
    strata = model.calibration_report["strata"]
    return {"rural": strata[RURAL]["population"], "urban": strata[URBAN]["population"],
            "total": float(model.p0.sum())}, time.perf_counter() - start


def case_roofs(folder):
    """The roofs scenario (current model: whole inhabitants per class, roof area per inhabitant), run to 2060."""
    from engine.simulation import run

    start = time.perf_counter()
    result = run(_load("scenario_muramvya_toits.json", folder))
    seconds = time.perf_counter() - start
    with open(os.path.join(result.directory, "calibration.json"), encoding="utf-8") as handle:
        report = json.load(handle)
    rural, urban = report["groups"]["Rural"], report["groups"]["Urbain1"]
    return {
        "status": result.status,
        "roofs_read": report["roofs"]["read"],
        "rural_m2_per_inhabitant": rural["area_per_person"],
        "urban_m2_per_inhabitant": urban["area_per_person"],
        "rural_gap_percent": rural["gap_percent"],
        "urban_gap_percent": urban["gap_percent"],
        "population_start": result.initial_population,
        "population_2060": result.final_population,
    }, seconds


def case_download(folder):
    """Google Open Buildings v3 on the two communes, compared with the roofs of the workbooks."""
    import numpy as np
    from osgeo import ogr
    from scipy.spatial import cKDTree

    from engine._gdal import srs_from_epsg
    from engine.downloads.fetch import FileCache
    from engine.downloads.open_buildings import download_open_buildings
    from engine.downloads.zone import DownloadZone, ZoneLayer

    cache = os.environ.get("POPLAR_CACHE") or os.path.join(os.path.expanduser("~"), ".poplar", "cache")
    zone = DownloadZone.from_layers(ZoneLayer(os.path.join(MURAMVYA, "commune_muramvya.shp")),
                                    srs_from_epsg(32735).ExportToWkt())
    output = os.path.join(folder, "google.gpkg")
    start = time.perf_counter()
    report = download_open_buildings(zone, output, FileCache(cache))
    seconds = time.perf_counter() - start

    def points(path):
        datasource = ogr.Open(path)
        return np.array([(f.GetGeometryRef().GetX(), f.GetGeometryRef().GetY()) for f in datasource.GetLayer(0)])

    distance, _ = cKDTree(points(output)).query(points(os.path.join(MURAMVYA, "buildings_muramvya.gpkg")))
    return {"roofs_kept": report["counts"]["kept"], "workbook_roofs_found": int((distance < 1).sum())}, seconds


def case_overture(folder):
    """Overture Maps (latest release) on the two communes: count, sources, calibration with these roofs."""
    import copy

    from engine._gdal import srs_from_epsg
    from engine.downloads import overture
    from engine.downloads.zone import DownloadZone, ZoneLayer
    from engine.simulation import calibrate

    zone = DownloadZone.from_layers(ZoneLayer(os.path.join(MURAMVYA, "commune_muramvya.shp")),
                                    srs_from_epsg(32735).ExportToWkt())
    output = os.path.join(folder, "overture.gpkg")
    start = time.perf_counter()
    report = overture.download_overture(zone, output, cache_folder=folder)
    seconds = time.perf_counter() - start
    scenario = _load("scenario_muramvya_toits.json", folder)
    scenario.calibration = copy.deepcopy(scenario.calibration)
    scenario.calibration["buildings"]["source"] = output
    groups = calibrate(scenario)[0]["groups"]
    return {"roofs_kept": report["counts"]["kept"],
            "google_share": report["by_source"].get("google", 0) / max(1, report["counts"]["kept"]),
            "rural_m2_per_inhabitant": groups["Rural"]["area_per_person"],
            "urban_m2_per_inhabitant": groups["Urbain1"]["area_per_person"]}, seconds


CASES = {
    "muramvya_raster": case_raster,
    "muramvya_toits_classeurs": case_legacy_roofs,
    "muramvya_toits": case_roofs,
    "telechargement_google": case_download,
    "telechargement_overture": case_overture,
}
NETWORK = {"telechargement_google", "telechargement_overture"}


def check(name, figures, expected):
    """Rows (figure, expected, obtained, gap, ok) of one case."""
    rows = []
    for key, spec in expected.items():
        value = figures.get(key)
        target, tolerance = spec["value"], spec.get("tolerance", 0)
        if isinstance(target, str):
            ok, gap = value == target, ""
        else:
            gap = None if value is None else value - target
            ok = gap is not None and abs(gap) <= tolerance
        rows.append((key, target, value, gap, ok, spec.get("label", key)))
    return rows


def _fmt(value):
    """French writing: 139 099,6545 (four decimals at most, none when zero)."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return {None: "–"}.get(value, str(value))
    if abs(value) < 5e-5:
        return "0"
    text = f"{value:,.4f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"
    return text.replace(",", " ").replace(".", ",")


def run_bench(folder, network=False, only=None):
    with open(EXPECTED, encoding="utf-8") as handle:
        expected = json.load(handle)
    results = {}
    for name, function in CASES.items():
        if only and name not in only:
            continue
        if name in NETWORK and not network:
            continue
        if name == "telechargement_overture":
            from engine.downloads import overture

            if not overture.available():            # GDAL without the Parquet driver
                continue
        case_folder = os.path.join(folder, name)
        os.makedirs(case_folder, exist_ok=True)
        figures, seconds = function(case_folder)
        results[name] = {"rows": check(name, figures, expected[name]["figures"]), "seconds": seconds,
                         "title": expected[name]["title"]}
    return results


def summary(results):
    from engine import __version__

    lines = [f"# Banc de non-régression – Poplar {__version__}", "",
             f"{datetime.datetime.now():%d/%m/%Y %H:%M}", ""]
    failures = 0
    for name, result in results.items():
        lines += [f"## {result['title']}", "", f"Durée : {result['seconds']:.1f} s", "",
                  "| Grandeur | Attendu | Obtenu | Écart | |", "|---|---|---|---|---|"]
        for key, target, value, gap, ok, label in result["rows"]:
            failures += not ok
            lines.append(f"| {label} | {_fmt(target)} | {_fmt(value)} | {_fmt(gap) if gap != '' else ''} | "
                         f"{'✔' if ok else '✖'} |")
        lines.append("")
    lines.append("**Tout est conforme.**" if not failures else f"**{failures} écart(s) hors tolérance.**")
    return "\n".join(lines) + "\n", failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reseau", action="store_true", help="include the Google Open Buildings download")
    parser.add_argument("--sortie", help="folder for the runs and banc.md")
    parser.add_argument("--cas", nargs="*", help="only these cases")
    args = parser.parse_args(argv)
    folder = args.sortie or tempfile.mkdtemp(prefix="poplar_banc_")
    text, failures = summary(run_bench(folder, args.reseau, args.cas))
    with open(os.path.join(folder, "banc.md"), "w", encoding="utf-8") as handle:
        handle.write(text)
    print(text)
    print(f"Résumé écrit dans {os.path.join(folder, 'banc.md')}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
