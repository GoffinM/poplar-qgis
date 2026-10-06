"""Command line: ``python -m engine run scenario.json [--language en]``, ``report``, ``grid``, ``excel``,
``compare``, ``patches`` and ``download-roofs``."""

from __future__ import annotations

import argparse
import os
import sys

from .i18n import available_languages
from .nonconvergence import NonConvergenceError
from .scenario import ScenarioError, load_scenario
from .simulation import run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine", description="Population growth and migration engine")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run a scenario file")
    run_parser.add_argument("scenario")
    run_parser.add_argument("--language", choices=available_languages())
    report_parser = commands.add_parser("report", help="write report.html for a run folder")
    report_parser.add_argument("folder")
    report_parser.add_argument("--language", choices=available_languages())
    grid_parser = commands.add_parser("grid", help="write the cell layer (mailles) of a run folder again")
    grid_parser.add_argument("folder")
    grid_parser.add_argument("--format", choices=("gpkg", "shp", "both"), default="gpkg")
    grid_parser.add_argument("--scenario-folder", help="folder of the scenario (runs written before 0.7.1)")
    excel_parser = commands.add_parser("excel", help="write calage.xlsx from the calibration.json of a run folder")
    excel_parser.add_argument("folder")
    excel_parser.add_argument("--language", choices=available_languages(), default="fr")
    compare_parser = commands.add_parser("compare", help="compare a run in planned mode with one in free mode")
    compare_parser.add_argument("planned", help="run folder in planned mode")
    compare_parser.add_argument("free", help="run folder in free mode (same scenario)")
    compare_parser.add_argument("--output", help="folder of the comparison (the free run by default)")
    patches_parser = commands.add_parser("patches", help="built-up patches as the starting polygons (free mode)")
    patches_parser.add_argument("scenario")
    patches_parser.add_argument("--density", type=float, default=1500.0, help="dense cells, hab/km2 (1500)")
    patches_parser.add_argument("--min-population", type=float, default=5000.0, help="smallest patch (5000)")
    patches_parser.add_argument("--secondary-population", type=float,
                                help="smaller patches kept as a second level (for example 2000)")
    patches_parser.add_argument("--urban-class", action="append", help="urban limits class (repeatable)")
    patches_parser.add_argument("--inside-only", action="store_true", help="only patches inside the urban limits")
    patches_parser.add_argument("--output", help="folder of the files (next to the scenario by default)")
    download_parser = commands.add_parser("download-roofs", help="download Google Open Buildings roofs of a zone")
    download_parser.add_argument("zone", help="polygons of the zone (the strata layer, for example)")
    download_parser.add_argument("output", help="GeoPackage to write")
    download_parser.add_argument("--crs", required=True, help="calculation CRS, for example EPSG:32735")
    download_parser.add_argument("--margin", type=float, default=0.0, help="margin around the zone, in metres")
    download_parser.add_argument("--limit", help="polygons the zone must stay in (a national boundary)")
    download_parser.add_argument("--polygons", action="store_true", help="outlines instead of points")
    download_parser.add_argument("--min-confidence", type=float)
    download_parser.add_argument("--cache", default=os.path.join(os.path.expanduser("~"), ".poplar", "cache"))
    args = parser.parse_args(argv)
    if args.command == "grid":
        from .grid_layer import rebuild

        for path in rebuild(args.folder, args.format, args.scenario_folder):
            print(path)
        return 0
    if args.command == "excel":
        return _excel(args)
    if args.command == "patches":
        from .patches import PatchRules, prepare

        rules = PatchRules(args.density, args.min_population, args.secondary_population, args.urban_class,
                           inside_only=args.inside_only)
        try:
            for path in prepare(args.scenario, rules, args.output).values():
                print(path)
        except ScenarioError as error:
            print(str(error), file=sys.stderr)
            return 1
        return 0
    if args.command == "compare":
        from .comparison import NotComparable, write as write_comparison

        try:
            for path in write_comparison(args.planned, args.free, args.output):
                print(path)
        except (NotComparable, OSError) as error:
            print(str(error), file=sys.stderr)
            return 1
        return 0
    if args.command == "download-roofs":
        return _download_roofs(args)
    if args.command == "report":
        from .html_report import write_html_report

        try:
            print(write_html_report(args.folder, args.language))
        except FileNotFoundError as error:
            print(f"no report.json in this folder: {error}", file=sys.stderr)
            return 1
        return 0

    try:
        scenario = load_scenario(args.scenario)
    except ScenarioError as error:
        print(str(error), file=sys.stderr)
        return 1
    if args.language:
        scenario.language = args.language

    def show(fraction: float) -> None:
        print(f"\r{fraction:6.1%}", end="", flush=True)

    try:
        result = run(scenario, progress=show)
    except (ScenarioError, NonConvergenceError) as error:
        print(f"\n{error}", file=sys.stderr)
        return 1
    print()
    with open(f"{result.directory}/report.txt", encoding="utf-8") as handle:
        print(handle.read())
    return 2 if result.status == "failed" else 0


def _excel(args) -> int:
    import json

    from .calibration_excel import write_calibration_workbook

    report_path = os.path.join(args.folder, "calibration.json")
    if not os.path.isfile(report_path):
        print(f"no calibration.json in {args.folder}", file=sys.stderr)
        return 1
    with open(report_path, encoding="utf-8") as handle:
        report = json.load(handle)
    calibration, name = {}, ""
    used = os.path.join(args.folder, "scenario_used.json")
    if os.path.isfile(used):
        with open(used, encoding="utf-8") as handle:
            scenario = json.load(handle)
        calibration, name = scenario.get("calibration") or {}, scenario.get("name") or ""
    print(write_calibration_workbook(report, os.path.join(args.folder, "calage.xlsx"), args.language, calibration,
                                     name))
    return 0


def _download_roofs(args) -> int:
    from osgeo import osr

    from .downloads.fetch import FileCache
    from .downloads.open_buildings import download_open_buildings
    from .downloads.zone import DownloadZone, EmptyZone, ZoneLayer

    srs = osr.SpatialReference()
    srs.SetFromUserInput(args.crs)
    try:
        zone = DownloadZone.from_layers(ZoneLayer(args.zone), srs.ExportToWkt(), args.margin,
                                        ZoneLayer(args.limit) if args.limit else None)
    except EmptyZone:
        print("the zone is empty (no polygon, or nothing inside the limit)", file=sys.stderr)
        return 1
    report = download_open_buildings(zone, args.output, FileCache(args.cache),
                                     "polygons" if args.polygons else "points", args.min_confidence,
                                     lambda fraction: print(f"\r{fraction:6.1%}", end="", flush=True))
    print(f"\n{report['counts']['kept']} roofs written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
