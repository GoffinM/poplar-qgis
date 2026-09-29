"""Command line: ``python -m engine run scenario.json [--language en]``."""

from __future__ import annotations

import argparse
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
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    sys.exit(main())
