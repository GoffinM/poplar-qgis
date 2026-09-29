"""Output files of a run (spec §8): rasters per year and summary table.

File names are fixed and in English whatever the language (decision P5);
the table headers follow the language of the run.
"""

from __future__ import annotations

import csv
import os
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np
from osgeo import gdal

from .i18n import NUMBER_FORMATS, translate
from .parameters import from_hab_per_km2
from .raster_io import write_raster
from .rounding import round_preserving_total
from .units import Units

POPULATION_NODATA = -1
FLOAT_NODATA = -9999.0


def year_label(year: float) -> str:
    return f"{int(round(year))}" if abs(year - round(year)) < 1e-9 else f"{year:g}"


def write_year_rasters(
    directory: str,
    year: float,
    units: Units,
    population: np.ndarray,
    unallocated: np.ndarray,
    capacity: np.ndarray,
    density_unit: str,
    indicators: Optional[Mapping[str, np.ndarray]] = None,
) -> List[str]:
    """Write the rasters of one output year and return their paths.

    Populations are rounded per cell with a preserved total (decision P2);
    densities are computed from the rounded populations and the useful area
    of each cell.
    """
    grid = units.grid
    label = year_label(year)
    area = units.per_cell(units.area_km2)
    valid = area > 0
    paths = []

    def path(name: str) -> str:
        return os.path.join(directory, f"{name}_{label}.tif")

    cell_population = units.per_cell(population)
    rounded = np.full(area.shape, POPULATION_NODATA, dtype=np.int64)
    rounded[valid] = round_preserving_total(np.maximum(cell_population[valid], 0))
    write_raster(path("population"), rounded.astype(np.float64), grid.geotransform, grid.crs_wkt,
                 nodata=POPULATION_NODATA, dtype=gdal.GDT_Int32)
    paths.append(path("population"))

    density = np.full(area.shape, np.nan)
    density[valid] = from_hab_per_km2(rounded[valid] / area[valid], density_unit)
    for name, values in (
        ("density", density),
        ("unallocated", _masked(units.per_cell(unallocated), valid)),
        ("capacity", _masked(units.per_cell(capacity), valid)),
    ):
        write_raster(path(name), values, grid.geotransform, grid.crs_wkt, nodata=FLOAT_NODATA)
        paths.append(path(name))
    for key, values in (indicators or {}).items():
        write_raster(path(key), _masked(units.per_cell(values), valid), grid.geotransform, grid.crs_wkt,
                     nodata=FLOAT_NODATA)
        paths.append(path(key))
    return paths


def _masked(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    return np.where(valid, values, np.nan)


def summary_rows(
    year: float,
    units: Units,
    population: np.ndarray,
    unallocated: np.ndarray,
    density_unit: str,
    indicators: Optional[Mapping[str, np.ndarray]] = None,
    admin_layer: str = "admin",
) -> List[Dict[str, object]]:
    """One row per administrative unit (or a single row for the whole area)."""
    if admin_layer in units.codes:
        keys = np.array([v if v is not None else "" for v in units.values(admin_layer)], dtype=object)
    else:
        keys = np.full(len(units), "", dtype=object)
    rows = []
    for key in sorted(set(keys)):
        members = keys == key
        area = float(units.area_km2[members].sum())
        pop = float(population[members].sum())
        row = {
            "year": year_label(year),
            "admin_unit": key,
            "population": int(round(pop)),
            "area_km2": round(area, 4),
            "density": round(float(from_hab_per_km2(pop / area, density_unit)), 2) if area > 0 else 0.0,
            "unallocated": int(round(float(unallocated[members].sum()))),
        }
        for name, values in (indicators or {}).items():
            row[name] = round(float(values[members].sum()), 3)
        rows.append(row)
    return rows


def write_summary(path: str, rows: Sequence[Dict[str, object]], language: str, units_by_column: Mapping[str, str]) -> None:
    """CSV with headers in the language of the run (units in brackets)."""
    if not rows:
        return
    columns = list(rows[0].keys())
    headers = []
    for column in columns:
        label = translate(f"summary_{column}", language)
        unit = units_by_column.get(column)
        headers.append(f"{label} ({translate('unit_' + unit, language)})" if unit else label)
    # Spreadsheets expect ';' as separator where the decimal mark is a comma.
    decimal = NUMBER_FORMATS.get(language, NUMBER_FORMATS["en"])[1]
    delimiter = ";" if decimal == "," else ","
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([str(row[c]).replace(".", decimal) if isinstance(row[c], float) else row[c]
                             for c in columns])
