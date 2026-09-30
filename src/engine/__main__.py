"""Command line: ``python -m engine run scenario.json [--language en]``, ``report`` and ``download-roofs``."""

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
