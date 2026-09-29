"""Spreadsheets: CSV, Excel (xlsx, xls) and OpenDocument (ods) through GDAL/OGR.

No new dependency: GDAL, shipped with QGIS, reads Excel files (the XLS
driver needs FreeXL, present in the usual QGIS builds). A table is read as
a header row and data rows; cells are numbers, text or None.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from osgeo import ogr

from ._gdal import gdal_exceptions

SPREADSHEETS = {".xlsx": "XLSX", ".xls": "XLS", ".ods": "ODS"}
EXTENSIONS = (".csv", ".txt") + tuple(SPREADSHEETS)


class TableError(ValueError):
    """The file cannot be read as a table (format, missing sheet, empty)."""


@dataclass
class Table:
    headers: List[str]
    rows: List[List[Any]]

    def column(self, name: str) -> int:
        """Index of a column, ignoring case and surrounding spaces."""
        wanted = name.strip().lower()
        for i, header in enumerate(self.headers):
            if header.strip().lower() == wanted:
                return i
        raise TableError(f"column {name!r} not found (columns: {', '.join(self.headers)})")


def sheets(path: str) -> List[str]:
    """Sheet names of a spreadsheet (a CSV file has a single unnamed sheet)."""
    if _extension(path) not in SPREADSHEETS:
        return []
    with gdal_exceptions():
        datasource = _open(path)
        return [datasource.GetLayer(i).GetName() for i in range(datasource.GetLayerCount())]


def read_table(path: str, sheet: Optional[str] = None) -> Table:
    extension = _extension(path)
    if extension in (".csv", ".txt"):
        return _read_csv(path)
    if extension not in SPREADSHEETS:
        raise TableError(f"{path}: unsupported table format (expected {', '.join(EXTENSIONS)})")
    with gdal_exceptions():
        datasource = _open(path)
        layer = datasource.GetLayerByName(sheet) if sheet else datasource.GetLayer(0)
        if layer is None:
            raise TableError(f"{path}: sheet {sheet!r} not found")
        definition = layer.GetLayerDefn()
        headers = [definition.GetFieldDefn(i).GetName() for i in range(definition.GetFieldCount())]
        rows = []
        for feature in layer:
            row = [_cell(feature, i) for i in range(len(headers))]
            if any(v not in (None, "") for v in row):
                rows.append(row)
    if not headers:
        raise TableError(f"{path}: empty sheet")
    return Table(headers, rows)


def write_table(path: str, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    """Write a CSV (UTF-8, ';' separated, readable by Excel) or an xlsx/ods file."""
    extension = _extension(path)
    if extension in (".csv", ".txt"):
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(headers)
            writer.writerows([["" if v is None else v for v in row] for row in rows])
        return
    if extension not in (".xlsx", ".ods"):
        raise TableError(f"{path}: cannot write this format (use .csv, .xlsx or .ods)")
    if os.path.exists(path):
        os.remove(path)
    with gdal_exceptions():
        datasource = ogr.GetDriverByName(SPREADSHEETS[extension]).CreateDataSource(path)
        layer = datasource.CreateLayer("parameters", geom_type=ogr.wkbNone)
        numeric = [all(isinstance(r[i], (int, float)) or r[i] in (None, "") for r in rows) and
                   any(isinstance(r[i], (int, float)) for r in rows) for i in range(len(headers))]
        for header, is_number in zip(headers, numeric):
            layer.CreateField(ogr.FieldDefn(str(header), ogr.OFTReal if is_number else ogr.OFTString))
        for row in rows:
            feature = ogr.Feature(layer.GetLayerDefn())
            for i, value in enumerate(row):
                if value not in (None, ""):
                    feature.SetField(i, float(value) if numeric[i] else str(value))
            layer.CreateFeature(feature)
        datasource = None


def number(value: Any) -> Optional[float]:
    """A cell as a number ("2,5" and "2 500" accepted); None if empty."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    return float(text)


def _extension(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def _open(path: str):
    driver = SPREADSHEETS[_extension(path)]
    if driver == "XLS" and ogr.GetDriverByName("XLS") is None:
        raise TableError(f"{path}: this GDAL cannot read .xls files; save the file as .xlsx")
    from osgeo import gdal

    dataset = gdal.OpenEx(path, gdal.OF_VECTOR, allowed_drivers=[driver], open_options=["HEADERS=FORCE"])
    if dataset is None:
        raise TableError(f"{path}: cannot be opened")
    return dataset


def _cell(feature, index: int) -> Any:
    if not feature.IsFieldSetAndNotNull(index):
        return None
    kind = feature.GetFieldDefnRef(index).GetType()
    if kind in (ogr.OFTInteger, ogr.OFTInteger64):
        return feature.GetFieldAsInteger64(index)
    if kind == ogr.OFTReal:
        return feature.GetFieldAsDouble(index)
    return feature.GetFieldAsString(index)


def _read_csv(path: str) -> Table:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            with open(path, newline="", encoding=encoding) as handle:
                text = handle.read()
            break
        except UnicodeDecodeError:
            continue
    first = text.splitlines()[0] if text.strip() else ""
    delimiter = max((";", ",", "\t"), key=first.count)
    lines = [row for row in csv.reader(text.splitlines(), delimiter=delimiter) if any(c.strip() for c in row)]
    if not lines:
        raise TableError(f"{path}: empty file")
    headers = [h.strip() for h in lines[0]]
    rows = [[c.strip() if c.strip() else None for c in row] + [None] * (len(headers) - len(row)) for row in lines[1:]]
    return Table(headers, rows)


# --- parameter tables (TCAM, maximum densities…) ------------------------------------

CONSTANT_HEADERS = ("constant", "constante", "constante (toutes années)")
ZONE_HEADERS = ("zone", "zone_1", "zone_2")


def parameter_sheet(values: dict, crossed: bool = False):
    """Headers and rows of a parameter given as ``{key: number | {year: value}}``.

    Columns: ``zone`` (and ``zone_2`` for crossed layers), ``constant``, then
    one column per pivot year. ``*`` is the default row.
    """
    years = sorted({float(y) for v in values.values() if isinstance(v, dict) for y in v})
    headers = ["zone"] + (["zone_2"] if crossed else []) + ["constant"] + [_year_label(y) for y in years]
    rows = []
    for key, value in values.items():
        zones = key.split("|", 1) if crossed and "|" in key else [key] + (["*"] if crossed else [])
        cells: List[Any] = list(zones)
        if isinstance(value, dict):
            by_year = {float(y): v for y, v in value.items()}
            cells += [None] + [by_year.get(y) for y in years]
        else:
            cells += [value] + [None] * len(years)
        rows.append(cells)
    return headers, rows


def parameter_values(table: Table, crossed: bool = False) -> dict:
    """``{key: number | {year: value}}`` read from a sheet written by :func:`parameter_sheet` or by hand."""
    lower = [h.strip().lower() for h in table.headers]
    zone_columns = [0, 1] if crossed else [0]
    constant = next((i for i, h in enumerate(lower) if h in CONSTANT_HEADERS), None)
    years = []
    for i, header in enumerate(table.headers):
        if i in zone_columns or i == constant:
            continue
        try:
            years.append((i, float(str(header).replace(",", "."))))
        except ValueError:
            raise TableError(f"column {header!r}: a year is expected") from None
    values = {}
    for row in table.rows:
        zones = [("*" if row[i] in (None, "") else str(row[i]).strip()) for i in zone_columns]
        key = zones[0] if len(zones) == 1 else ("*" if zones == ["*", "*"] else "|".join(zones))
        fixed = number(row[constant]) if constant is not None else None
        if fixed is not None:
            values[key] = fixed
            continue
        series = {_year_label(y): number(row[i]) for i, y in years if number(row[i]) is not None}
        if series:
            values[key] = series
    return values


def _year_label(year: float) -> str:
    return f"{year:g}"


# --- population projections -----------------------------------------------------------

UNIT_NAMES = ("admin", "unit", "unité", "unite", "admin_unit", "commune", "communes", "zone", "name", "nom")
YEAR_NAMES = ("year", "année", "annee", "an")
VALUE_NAMES = ("population", "pop", "value", "valeur", "habitants")
LONG, WIDE = "long", "wide"


@dataclass
class ProjectionTable:
    series: dict
    """{unit: [(year, population), …]}"""
    layout: str
    unit_column: str

    def years(self) -> List[float]:
        return sorted({y for points in self.series.values() for y, _ in points})


def read_projections(path: str, sheet: Optional[str] = None, unit_column: Optional[str] = None,
                     year_column: Optional[str] = None, value_column: Optional[str] = None) -> ProjectionTable:
    """Projections by administrative unit, from a CSV or a spreadsheet.

    Long layout: one row per unit and year (columns unit, year, population).
    Wide layout: one row per unit and one column per year, as statistics
    offices usually publish them. The layout is detected from the headers.
    """
    table = read_table(path, sheet)
    unit = table.column(unit_column) if unit_column else _find(table, UNIT_NAMES, 0)
    year_columns = [(i, _as_year(h)) for i, h in enumerate(table.headers) if i != unit and _as_year(h) is not None]
    series: dict = {}
    if year_columns and not year_column and not value_column:
        layout = WIDE
        for row in table.rows:
            key = _key(row[unit])
            for i, year in year_columns:
                value = number(row[i])
                if key and value is not None:
                    series.setdefault(key, []).append((year, value))
    else:
        layout = LONG
        year = table.column(year_column) if year_column else _find(table, YEAR_NAMES)
        value = table.column(value_column) if value_column else _find(table, VALUE_NAMES)
        for row in table.rows:
            key, when, amount = _key(row[unit]), number(row[year]), number(row[value])
            if key and when is not None and amount is not None:
                series.setdefault(key, []).append((when, amount))
    if not series:
        raise TableError(f"{path}: no projection found")
    for key, points in series.items():
        years = [y for y, _ in points]
        if len(set(years)) != len(years):
            raise TableError(f"{path}: unit {key!r} has the same year twice")
    return ProjectionTable(series, layout, table.headers[unit])


def _find(table: Table, names: Sequence[str], default: Optional[int] = None) -> int:
    lower = [h.strip().lower() for h in table.headers]
    for name in names:
        if name in lower:
            return lower.index(name)
    if default is not None:
        return default
    raise TableError(f"no column among {', '.join(names)} (columns: {', '.join(table.headers)})")


def _as_year(header: Any) -> Optional[float]:
    try:
        year = float(str(header).strip().replace(",", "."))
    except ValueError:
        return None
    return year if 1800 <= year <= 2300 else None


def _key(value: Any) -> str:
    """Unit names as the engine reads them from the layer (1.0 read by a spreadsheet is « 1 »)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()
