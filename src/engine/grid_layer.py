"""One vector layer of the grid cells with every result of a run: ``mailles.gpkg`` (and ``mailles.shp`` on request).

One square per cell of the study area, empty cells included, with:

- ``cell_id``, ``row``, ``col``: the place of the cell in the calculation grid (the one of the rasters);
- ``area_km2``: the useful area of the cell (inside the study area, outside the areas left out);
- ``class`` and ``admin``: the typology class and the administrative unit of the largest part of the cell;
- for each output year and each result: population, density, capacity, population not relocated and the
  indicators (water…), read back from the rasters written by the run.

GeoPackage fields are named ``population_2030``, ``density_2030``…; Shapefile names are cut to 10
characters (``pop2030``, ``den2030``…), and ``mailles_champs.csv`` gives the full name and the unit of each.
"""

from __future__ import annotations

import csv
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from osgeo import ogr

from ._gdal import gdal_exceptions, srs_from_wkt
from .raster_io import read_raster
from .units import Units

GPKG, SHP, BOTH, NONE = "gpkg", "shp", "both", "none"
FORMATS = (GPKG, SHP, BOTH, NONE)
NAME = "mailles"
LAYER = "mailles"
SHORT = {
    "population": "pop", "density": "den", "capacity": "cap", "unallocated": "nrl",
    "water_domestic": "wdom", "water_consumption_mean": "wcon", "water_production_mean": "wpro",
    "water_production_peak_day": "wpjr", "water_peak_hour": "wphr",
}
ORDER = list(SHORT)
_RASTER = re.compile(r"^(?P<quantity>[a-z_]+)_(?P<year>\d{4}(?:\.\d+)?)\.tif$")
BATCH = 20_000


def outputs_in(directory: str) -> Dict[str, List[str]]:
    """{quantity: [year labels]} of the rasters written in a run folder, in a stable order."""
    found: Dict[str, List[str]] = {}
    for name in os.listdir(directory):
        match = _RASTER.match(name)
        if match:
            found.setdefault(match.group("quantity"), []).append(match.group("year"))
    ordered = sorted(found, key=lambda q: (ORDER.index(q) if q in ORDER else len(ORDER), q))
    return {q: sorted(found[q], key=float) for q in ordered}


def _largest_part(units: Units, layer: str) -> Dict[int, str]:
    """Label of ``layer`` for the largest part of each cell (cells split between several zones)."""
    if layer not in units.codes:
        return {}
    order = np.lexsort((-units.area_km2, units.cell_id))            # by cell, largest part first
    cells, first = np.unique(units.cell_id[order], return_index=True)
    codes = units.codes[layer][order][first]
    labels = units.labels[layer]
    return {int(c): str(labels[k]) for c, k in zip(cells, codes) if k >= 0}


def _short_name(quantity: str, year: str) -> str:
    return (SHORT.get(quantity, quantity[:4]) + year.replace(".", "_"))[:10]


def write_grid_layer(directory: str, units: Units, fmt: str = GPKG, density_unit: str = "hab/km2",
                     units_of: Optional[Dict[str, str]] = None) -> List[str]:
    """Write the cell layer of a run folder; returns the files written (none with ``fmt="none"``)."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r} (expected {', '.join(FORMATS)})")
    if fmt == NONE:
        return []
    grid = units.grid
    area = units.per_cell(units.area_km2)
    rows, cols = np.nonzero(area > 0)                            # every cell of the study area, even empty
    outputs = outputs_in(directory)
    columns: List[Tuple[str, str, str, np.ndarray]] = []            # (quantity, year, unit, values of the cells)
    for quantity, years in outputs.items():
        for year in years:
            values = read_raster(os.path.join(directory, f"{quantity}_{year}.tif")).values[rows, cols]
            unit = density_unit if quantity == "density" else (units_of or {}).get(quantity, "")
            columns.append((quantity, year, unit, values))
    classes, admins = _largest_part(units, "class"), _largest_part(units, "admin")
    written = []
    formats = [GPKG, SHP] if fmt == BOTH else [fmt]
    for kind in formats:
        path = os.path.join(directory, f"{NAME}.{kind}")
        _write(path, kind, grid, rows, cols, area[rows, cols], classes, admins, columns)
        written.append(path)
        if kind == SHP:
            written.append(_write_field_table(directory, columns))
    return written


def _write(path, kind, grid, rows, cols, area, classes, admins, columns) -> None:
    driver = ogr.GetDriverByName("GPKG" if kind == GPKG else "ESRI Shapefile")
    with gdal_exceptions():
        if os.path.exists(path):
            driver.DeleteDataSource(path)
        datasource = driver.CreateDataSource(path)
        layer = datasource.CreateLayer(LAYER, srs_from_wkt(grid.crs_wkt), ogr.wkbPolygon,
                                       ["SPATIAL_INDEX=YES"] if kind == GPKG else ["ENCODING=UTF-8"])
        fields = [("cell_id", ogr.OFTInteger64), ("row", ogr.OFTInteger), ("col", ogr.OFTInteger),
                  ("area_km2", ogr.OFTReal), ("class", ogr.OFTString), ("admin", ogr.OFTString)]
        names = []
        for quantity, year, _, _ in columns:
            name = f"{quantity}_{year}" if kind == GPKG else _short_name(quantity, year)
            names.append(name)
            fields.append((name, ogr.OFTInteger if quantity == "population" else ogr.OFTReal))
        for name, field_type in fields:
            definition = ogr.FieldDefn(name, field_type)
            if field_type == ogr.OFTString:
                definition.SetWidth(80)
            layer.CreateField(definition)
        feature_definition = layer.GetLayerDefn()
        x0, size, _, y0, _, _ = grid.geotransform
        # plain Python lists and field numbers: one call per value, no numpy scalar, no field name look-up
        index = {name: feature_definition.GetFieldIndex(name) for name, _ in fields}
        data = []
        for name, (quantity, _, _, values) in zip(names, columns):
            as_list = values.tolist()
            if quantity == "population":
                as_list = [None if v != v else int(round(v)) for v in as_list]
            data.append((index[name], as_list))
        row_list, col_list, area_list = rows.tolist(), cols.tolist(), area.tolist()
        i_cell, i_row, i_col, i_area = index["cell_id"], index["row"], index["col"], index["area_km2"]
        i_class, i_admin = index["class"], index["admin"]
        layer.StartTransaction()
        for i, (row, col) in enumerate(zip(row_list, col_list)):
            if i and i % BATCH == 0:
                layer.CommitTransaction()
                layer.StartTransaction()
            left, top = x0 + col * size, y0 - row * size
            right, bottom = left + size, top - size
            feature = ogr.Feature(feature_definition)
            feature.SetGeometryDirectly(ogr.CreateGeometryFromWkt(
                f"POLYGON(({left} {top},{right} {top},{right} {bottom},{left} {bottom},{left} {top}))"))
            cell = row * grid.ncols + col
            feature.SetField(i_cell, cell)
            feature.SetField(i_row, row)
            feature.SetField(i_col, col)
            feature.SetField(i_area, area_list[i])
            label = classes.get(cell)
            if label is not None:
                feature.SetField(i_class, label)
            label = admins.get(cell)
            if label is not None:
                feature.SetField(i_admin, label)
            for field, values in data:
                value = values[i]
                if value is not None and value == value:          # None and NaN: left empty
                    feature.SetField(field, value)
            layer.CreateFeature(feature)
        layer.CommitTransaction()
        layer = datasource = None


def _write_field_table(directory: str, columns: Sequence[Tuple[str, str, str, np.ndarray]]) -> str:
    """Short Shapefile names → full names and units (a Shapefile field name has 10 characters at most)."""
    path = os.path.join(directory, f"{NAME}_champs.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["champ_shp", "grandeur", "annee", "unite"])
        for name, meaning in (("cell_id", "cell id"), ("row", "row"), ("col", "column"),
                              ("area_km2", "useful area"), ("class", "typology class"), ("admin", "admin unit")):
            writer.writerow([name, meaning, "", "km2" if name == "area_km2" else ""])
        for quantity, year, unit, _ in columns:
            writer.writerow([_short_name(quantity, year), quantity, year, unit])
    return path
