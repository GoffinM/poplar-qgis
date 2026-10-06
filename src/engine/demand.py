"""Demand computed again on a finished run, without running the population model (plan_demande_et_routes.md, A).

Each run keeps the population of each calculation unit at its output years (``populations.npz``: a few
tens of kilobytes), with the population not placed and the class of each unit (in free strata mode a
colonised unit takes the parameters of its new polygon, water allowance included).

:func:`recompute_demand` cuts the grid again from the layers of the scenario (it must give the grid of the
run, else :class:`~engine.grid_layer.GridMismatch`), computes the indicators (water…) with the parameters
of the scenario given, and writes them in a dated sub-folder of the run (decision A-a): nothing of the run
is overwritten, and several sets of parameters can be compared. Runs written before this version have no
populations per unit: the population of each cell is shared between its units pro rata of their area
(decision A-b, exact for whole cells), and the result says so.
"""

from __future__ import annotations

import datetime
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

FILE = "populations.npz"
PARAMETERS = "demande_parametres.json"
PREFIX = "demande_"


def save_populations(directory: str, units, by_year: Dict[str, Dict[str, np.ndarray]]) -> str:
    """Keep the population, the population not placed and the class of each unit, per output year."""
    arrays = {"years": np.array(list(by_year), dtype=str), "cell_id": units.cell_id.astype(np.int64),
              "area_km2": units.area_km2.astype(np.float64)}
    for label, values in by_year.items():
        arrays[f"population_{label}"] = values["population"].astype(np.float64)
        arrays[f"unallocated_{label}"] = values["unallocated"].astype(np.float64)
        arrays[f"classes_{label}"] = values["classes"].astype(np.int32)
    path = os.path.join(directory, FILE)
    np.savez_compressed(path, **arrays)
    return path


@dataclass
class DemandResult:
    directory: str
    """Dated sub-folder of the run with the demand rasters, summary.csv and the parameters used."""
    files: List[str] = field(default_factory=list)
    years: List[str] = field(default_factory=list)
    approximated: bool = False
    """True for a run without populations per unit (shared pro rata of the area, decision A-b)."""


def _scenario_of(run_directory: str, prepare=None):
    from .scenario import scenario_from_dict

    with open(os.path.join(run_directory, "scenario_used.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    base = data.pop("base_dir", None) or run_directory
    if prepare is not None:
        data = prepare(data)
    return scenario_from_dict(data, base)


def _new_folder(run_directory: str) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    folder = os.path.join(run_directory, PREFIX + stamp)
    suffix = 1
    while os.path.exists(folder):
        suffix += 1
        folder = os.path.join(run_directory, f"{PREFIX}{stamp}_{suffix}")
    os.makedirs(folder)
    return folder


def latest_demand(run_directory: str) -> Optional[str]:
    """The last demand sub-folder of a run (None if the demand was never computed again)."""
    if not run_directory or not os.path.isdir(run_directory):
        return None
    folders = sorted(name for name in os.listdir(run_directory)
                     if name.startswith(PREFIX) and os.path.isdir(os.path.join(run_directory, name)))
    return os.path.join(run_directory, folders[-1]) if folders else None


def recompute_demand(run_directory: str, scenario=None, prepare=None, progress=None) -> DemandResult:
    """Compute the indicators of a finished run again, with the parameters of ``scenario``.

    ``scenario``: the scenario whose indicator parameters apply (the window's, for the plugin); by default
    the one of the run. Its layers must give the grid of the run.
    """
    from .grid_layer import GridMismatch, load_cells, write_grid_layer
    from .i18n import message
    from .outputs import summary_rows, write_summary, write_year_rasters
    from .raster_io import read_raster
    from .simulation import _Model

    if scenario is None:
        scenario = _scenario_of(run_directory, prepare)
    if not scenario.indicators:
        raise ValueError("the scenario has no indicator (Indicators tab): nothing to compute")
    model = _Model.load(scenario, population=False)
    units = model.units
    path = os.path.join(run_directory, FILE)
    approximated = not os.path.isfile(path)
    if not approximated:
        with np.load(path, allow_pickle=False) as data:
            kept = {key: data[key] for key in data.files}
        if len(kept["cell_id"]) != len(units) or not np.array_equal(kept["cell_id"], units.cell_id) \
                or not np.allclose(kept["area_km2"], units.area_km2):
            raise GridMismatch(run_directory)
        years = [str(y) for y in kept["years"]]
    else:
        years = sorted((name[len("population_"):-4] for name in os.listdir(run_directory)
                        if name.startswith("population_") and name.endswith(".tif")), key=float)
        kept = {}
    folder = _new_folder(run_directory)
    files, rows = [], []
    cell_area = units.per_cell(units.area_km2).ravel()
    share = np.where(cell_area[units.cell_id] > 0, units.area_km2 / cell_area[units.cell_id], 0.0)
    initial_classes = units.codes["class"].copy()
    for index, label in enumerate(years):
        year = float(label)
        if not approximated:
            population = kept[f"population_{label}"]
            unallocated = kept[f"unallocated_{label}"]
            classes = kept.get(f"classes_{label}")
        else:
            raster = read_raster(os.path.join(run_directory, f"population_{label}.tif"))
            if raster.values.shape != (units.grid.nrows, units.grid.ncols) or \
                    not np.allclose(raster.geotransform, units.grid.geotransform):
                raise GridMismatch(run_directory)
            population = np.nan_to_num(raster.values).ravel()[units.cell_id] * share
            left_path = os.path.join(run_directory, f"unallocated_{label}.tif")
            left = np.nan_to_num(read_raster(left_path).values).ravel() if os.path.isfile(left_path) \
                else np.zeros(units.grid.ncells)
            unallocated = left[units.cell_id] * share
            classes = None
        units.codes["class"] = classes.astype(units.codes["class"].dtype) if classes is not None else initial_classes
        units.__dict__.pop("_combination_cache", None)         # parameters follow the class of that year
        values = model.indicator_values(population, year)
        written = write_year_rasters(folder, year, units, population, unallocated,
                                     np.zeros(len(units)), scenario.density_unit, values)
        for name in written:                                   # only the demand: population stays in the run
            base = os.path.basename(name)
            if base.split("_")[0] in ("population", "density", "unallocated", "capacity"):
                os.remove(name)
            else:
                files.append(name)
        rows.extend(summary_rows(year, units, population, unallocated, scenario.density_unit, values))
        if progress is not None:
            progress((index + 1) / max(1, len(years)))
    units.codes["class"] = initial_classes
    summary = os.path.join(folder, "summary.csv")
    write_summary(summary, rows, scenario.language, model.column_units(scenario))
    files.append(summary)
    cells = load_cells(run_directory)
    if cells is not None and scenario.output_grid_layer != "none":
        files.extend(write_grid_layer(folder, cells, scenario.output_grid_layer, scenario.density_unit,
                                      model.column_units(scenario)))
    record = {
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "run": os.path.abspath(run_directory),
        "years": years,
        "indicators": [{"type": spec.type, "parameters": spec.parameters} for spec in scenario.indicators],
        "approximated": approximated,
        "note": message("demand_approximated").render(scenario.language) if approximated else "",
    }
    with open(os.path.join(folder, PARAMETERS), "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    files.append(os.path.join(folder, PARAMETERS))
    return DemandResult(folder, files, years, approximated)
