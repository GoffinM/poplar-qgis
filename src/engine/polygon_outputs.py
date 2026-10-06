"""Outputs of the free strata mode (plan_polygones_libres.md §5): rasters, smoothed polygons, genealogy.

At each output year:

- ``polygon_id_AAAA.tif``: polygon of each cell (the one covering at least half of it), with a QGIS style;
- ``statut_AAAA.tif``: 0 not urban, 1 urban from the start, 2 extension, 3 new nucleus, 9 exclusion
  (fiche §3.4, "urban" = rank at least ``urban_rank``).

Once, at the end of the run:

- ``annee_colonisation.tif``: year a cell (or its residue) last changed polygon, 0 if never;
- ``polygones.gpkg``: layer ``polygones`` (one feature per polygon and output year, smoothed for display
  only: the figures come from the calculation units, never from the outline), layer ``extensions`` (cells
  gained between two output years) and table ``genealogie``;
- ``polygones_legende.csv``: identifier, stratum, rank, parent and year of creation of each polygon.
"""

from __future__ import annotations

import csv
import os
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from osgeo import gdal, ogr

from ._gdal import gdal_exceptions, srs_from_wkt
from .outputs import year_label
from .polygons import NO_CELL, NO_POLYGON, NO_RANK, PolygonHistory, at_capacity, cell_membership
from .raster_io import write_raster
from .units import Units

NOT_URBAN, URBAN_START, EXTENSION, NEW_NUCLEUS, EXCLUSION = 0, 1, 2, 3, 9
STATUS_NODATA = 255.0
YEAR_NODATA = -1.0
GPKG = "polygones.gpkg"
LEGEND = "polygones_legende.csv"
PALETTE = ["#c8c8c8", "#f2d16b", "#e8945a", "#c9503c", "#8c2d3c", "#5a1e46", "#2f1a40", "#141026"]


def urban_rank(table, strata_urban_rank: Optional[int]) -> int:
    """Rank from which a polygon counts as urban: given, or the lowest rank above the lowest one."""
    if strata_urban_rank is not None:
        return int(strata_urban_rank)
    ranks = sorted({r for r in table.rank if r != NO_RANK})
    return ranks[1] if len(ranks) > 1 else (ranks[0] + 1 if ranks else 1)


# --- per output year ---------------------------------------------------------------------------


def polygon_stats(history: PolygonHistory, year: float, population: np.ndarray, capacity: np.ndarray,
                  protected: np.ndarray, polygon_id: np.ndarray, tolerance: float) -> List[dict]:
    """Area, population, density and share at capacity of each polygon (from the units)."""
    units = history.units
    pid = np.asarray(polygon_id)
    n = len(history.table)
    known = pid >= 0
    area = np.bincount(pid[known], weights=units.area_km2[known], minlength=n)
    people = np.bincount(pid[known], weights=population[known], minlength=n)
    habitable = known & ~protected
    full = at_capacity(population, capacity, tolerance)
    habitable_area = np.bincount(pid[habitable], weights=units.area_km2[habitable], minlength=n)
    full_area = np.bincount(pid[habitable & full], weights=units.area_km2[habitable & full], minlength=n)
    membership = history.membership[int(round(year))].ravel()
    cells = np.bincount(membership[membership >= 0], minlength=n)
    rows = []
    for polygon in np.flatnonzero(area > 0):
        rows.append({
            "year": float(year), "id": int(polygon), "area_km2": float(area[polygon]),
            "population": float(people[polygon]),
            "density": float(people[polygon] / area[polygon]),
            "saturated_share": float(full_area[polygon] / habitable_area[polygon]) if habitable_area[polygon] else None,
            "cells": int(cells[polygon]),
        })
    return rows


def status_raster(history: PolygonHistory, year: float, urban_from: int) -> np.ndarray:
    """Status of each cell (fiche §3.4) at ``year``, as floats with NaN outside the study area."""
    units = history.units
    table = history.table
    ranks = np.array(table.rank + [NO_RANK], dtype=np.int64)        # index -1 (no majority) -> NO_RANK
    start = history.membership[history.start_year]
    now = history.membership[int(round(year))]
    urban_now = (now >= 0) & (ranks[np.where(now >= 0, now, -1)] >= urban_from)
    urban_start = (start >= 0) & (ranks[np.where(start >= 0, start, -1)] >= urban_from)
    created = np.array([c is not None and c > history.start_year + 1e-9 for c in table.created] + [False])
    nucleus = urban_now & created[np.where(now >= 0, now, -1)]
    status = np.full(now.shape, float(NOT_URBAN))
    status[urban_now & ~urban_start] = EXTENSION
    status[nucleus & ~urban_start] = NEW_NUCLEUS
    status[urban_start & urban_now] = URBAN_START
    excluded = units.per_cell(np.where(units.no_inflow, units.area_km2, 0.0))
    area = units.per_cell(units.area_km2)
    with np.errstate(invalid="ignore", divide="ignore"):
        status[(area > 0) & (excluded / np.where(area > 0, area, 1.0) >= 0.5)] = EXCLUSION
    status[now == NO_CELL] = np.nan
    return status


def write_year(directory: str, history: PolygonHistory, year: float, urban_from: int) -> List[str]:
    """``polygon_id_AAAA.tif`` (with its QGIS style) and ``statut_AAAA.tif``."""
    grid = history.units.grid
    label = year_label(year)
    membership = history.membership[int(round(year))].astype(np.float64)
    membership[membership == NO_CELL] = np.nan
    ids_path = os.path.join(directory, f"polygon_id_{label}.tif")
    write_raster(ids_path, membership, grid.geotransform, grid.crs_wkt, nodata=float(NO_CELL), dtype=gdal.GDT_Int32)
    _write_style(os.path.splitext(ids_path)[0] + ".qml", history.table)
    status_path = os.path.join(directory, f"statut_{label}.tif")
    write_raster(status_path, status_raster(history, year, urban_from), grid.geotransform, grid.crs_wkt,
                 nodata=STATUS_NODATA, dtype=gdal.GDT_Byte)
    return [ids_path, status_path]


# --- end of the run ----------------------------------------------------------------------------


def write_final(directory: str, history: PolygonHistory, cell_size: float, min_patch_km2: Optional[float] = None,
                passes: int = 2) -> List[str]:
    """``annee_colonisation.tif``, ``polygones.gpkg`` and the legend."""
    units = history.units
    grid = units.grid
    years = np.zeros(grid.ncells)
    for event in history.events:
        years[event["cell"]] = event["year"]
    years = years.reshape(grid.nrows, grid.ncols)
    years[history.membership[history.start_year] == NO_CELL] = np.nan
    year_path = os.path.join(directory, "annee_colonisation.tif")
    write_raster(year_path, years, grid.geotransform, grid.crs_wkt, nodata=YEAR_NODATA, dtype=gdal.GDT_Int16)
    legend = _write_legend(directory, history.table)
    gpkg = os.path.join(directory, GPKG)
    min_area = min_patch_km2 if min_patch_km2 is not None else grid.cell_area_km2
    with gdal_exceptions():
        driver = ogr.GetDriverByName("GPKG")
        if os.path.exists(gpkg):
            driver.DeleteDataSource(gpkg)
        datasource = driver.CreateDataSource(gpkg)
        srs = srs_from_wkt(grid.crs_wkt)
        _polygons_layer(datasource, srs, history, min_area, passes)
        _extensions_layer(datasource, srs, history)
        _genealogy_table(datasource, history)
        datasource = None
    return [year_path, gpkg, legend]


def _polygons_layer(datasource, srs, history, min_area, passes) -> None:
    table = history.table
    layer = datasource.CreateLayer("polygones", srs, ogr.wkbMultiPolygon, ["SPATIAL_INDEX=YES"])
    for name, kind in (("id", ogr.OFTInteger), ("strate", ogr.OFTString), ("rang", ogr.OFTInteger),
                       ("parent", ogr.OFTInteger), ("annee", ogr.OFTInteger), ("surface_km2", ogr.OFTReal),
                       ("population", ogr.OFTInteger), ("densite_moyenne", ogr.OFTReal),
                       ("part_saturee", ogr.OFTReal), ("mailles", ogr.OFTInteger)):
        layer.CreateField(ogr.FieldDefn(name, kind))
    stats = {(int(round(row["year"])), row["id"]): row for row in history.stats}
    grid = history.units.grid
    layer.StartTransaction()
    for year in sorted(history.membership):
        membership = history.membership[year]
        for polygon, geometry in _vectorise(membership, grid).items():
            geometry = _smooth(geometry, membership, polygon, grid, passes, min_area)
            if geometry is None:
                continue
            row = stats.get((year, polygon), {})
            feature = ogr.Feature(layer.GetLayerDefn())
            feature.SetGeometry(geometry)
            feature.SetField("id", int(polygon))
            feature.SetField("strate", table.stratum[polygon])
            feature.SetField("rang", int(table.rank[polygon]))
            feature.SetField("parent", int(table.parent[polygon]))
            feature.SetField("annee", int(year))
            for field, key in (("surface_km2", "area_km2"), ("densite_moyenne", "density"),
                               ("part_saturee", "saturated_share")):
                if row.get(key) is not None:
                    feature.SetField(field, float(row[key]))
            if "population" in row:
                feature.SetField("population", int(round(row["population"])))
            if "cells" in row:
                feature.SetField("mailles", int(row["cells"]))
            layer.CreateFeature(feature)
    layer.CommitTransaction()


def _extensions_layer(datasource, srs, history) -> None:
    layer = datasource.CreateLayer("extensions", srs, ogr.wkbMultiPolygon, ["SPATIAL_INDEX=YES"])
    for name, kind in (("id", ogr.OFTInteger), ("strate", ogr.OFTString), ("annee_debut", ogr.OFTInteger),
                       ("annee_fin", ogr.OFTInteger), ("surface_km2", ogr.OFTReal), ("mailles", ogr.OFTInteger)):
        layer.CreateField(ogr.FieldDefn(name, kind))
    years = sorted(history.membership)
    grid = history.units.grid
    layer.StartTransaction()
    for before, after in zip(years[:-1], years[1:]):
        old, new = history.membership[before], history.membership[after]
        gained = np.where((new >= 0) & (new != old), new, NO_CELL)
        for polygon, geometry in _vectorise(gained, grid).items():
            feature = ogr.Feature(layer.GetLayerDefn())
            feature.SetGeometry(geometry)
            feature.SetField("id", int(polygon))
            feature.SetField("strate", history.table.stratum[polygon])
            feature.SetField("annee_debut", int(before))
            feature.SetField("annee_fin", int(after))
            feature.SetField("surface_km2", geometry.GetArea() / 1e6)
            feature.SetField("mailles", int((gained == polygon).sum()))
            layer.CreateFeature(feature)
    layer.CommitTransaction()


def genealogy_rows(history: PolygonHistory) -> List[dict]:
    """Initial polygons, extensions (grouped by year and polygon), new nuclei and contacts."""
    rows = []
    start = history.start_year
    for row in history.stats:
        if int(round(row["year"])) == start:
            rows.append({"id": row["id"], "annee": start, "evenement": "initial", "parent": NO_POLYGON,
                         "autre_id": None, "mailles": row["cells"], "population": row["population"]})
    grouped: Dict[Tuple[int, int, str], dict] = {}
    for event in history.events:
        key = (int(round(event["year"])), event["polygon"], event.get("event", "extension"))
        entry = grouped.setdefault(key, {"mailles": 0, "population": 0.0, "flags": set()})
        entry["mailles"] += 1
        entry["population"] += event.get("population", 0.0)
        entry["flags"].update(event.get("flags", []))
    for (year, polygon, kind), entry in sorted(grouped.items()):
        rows.append({"id": polygon, "annee": year, "evenement": kind,
                     "parent": history.table.parent[polygon] if kind == "nouveau_noyau" else polygon,
                     "autre_id": None, "mailles": entry["mailles"], "population": entry["population"],
                     "a_verifier": ", ".join(sorted(entry["flags"])) or None})
    rows.extend(_contacts(history))
    return rows


def _contacts(history: PolygonHistory) -> List[dict]:
    """First output year when two polygons of the same rank touch (8 neighbours): informative (P9)."""
    seen = set()
    rows = []
    ranks = history.table.rank
    for year in sorted(history.membership):
        membership = history.membership[year]
        padded = np.pad(membership, 1, constant_values=NO_CELL)
        centre = padded[1:-1, 1:-1]
        pairs = set()
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            other = padded[1 + dr:padded.shape[0] - 1 + dr, 1 + dc:padded.shape[1] - 1 + dc]
            touching = (centre >= 0) & (other >= 0) & (centre != other)
            for a, b in zip(centre[touching].tolist(), other[touching].tolist()):
                pairs.add((min(a, b), max(a, b)))
        for a, b in sorted(pairs):
            if (a, b) in seen or ranks[a] != ranks[b] or ranks[a] == NO_RANK:
                continue
            seen.add((a, b))
            if year != history.start_year:
                rows.append({"id": a, "annee": year, "evenement": "contact", "parent": None, "autre_id": b,
                             "mailles": None, "population": None})
    return rows


def _genealogy_table(datasource, history) -> None:
    layer = datasource.CreateLayer("genealogie", None, ogr.wkbNone)
    for name, kind in (("id", ogr.OFTInteger), ("annee", ogr.OFTInteger), ("evenement", ogr.OFTString),
                       ("parent", ogr.OFTInteger), ("autre_id", ogr.OFTInteger), ("mailles", ogr.OFTInteger),
                       ("population", ogr.OFTInteger), ("a_verifier", ogr.OFTString)):
        layer.CreateField(ogr.FieldDefn(name, kind))
    layer.StartTransaction()
    for row in genealogy_rows(history):
        feature = ogr.Feature(layer.GetLayerDefn())
        for key, value in row.items():
            if value is None:
                continue
            feature.SetField(key, int(round(value)) if key == "population" else value)
        layer.CreateFeature(feature)
    layer.CommitTransaction()


# --- geometry ------------------------------------------------------------------------------------


def _vectorise(values: np.ndarray, grid) -> Dict[int, ogr.Geometry]:
    """One multipolygon per value >= 0 of a cell raster (exact cell outlines)."""
    with gdal_exceptions():
        raster = gdal.GetDriverByName("MEM").Create("", grid.ncols, grid.nrows, 1, gdal.GDT_Int32)
        raster.SetGeoTransform(grid.geotransform)
        band = raster.GetRasterBand(1)
        band.WriteArray(values.astype(np.int32))
        mask = gdal.GetDriverByName("MEM").Create("", grid.ncols, grid.nrows, 1, gdal.GDT_Byte)
        mask.GetRasterBand(1).WriteArray((values >= 0).astype(np.uint8))
        from .vector_io import memory_datasource

        vectors = memory_datasource()
        layer = vectors.CreateLayer("cells", None, ogr.wkbPolygon)
        layer.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
        gdal.Polygonize(band, mask.GetRasterBand(1), layer, 0, [], callback=None)
        result: Dict[int, ogr.Geometry] = {}
        for feature in layer:
            polygon = feature.GetField(0)
            geometry = result.setdefault(polygon, ogr.Geometry(ogr.wkbMultiPolygon))
            geometry.AddGeometry(feature.GetGeometryRef())
        return result


def _smooth(geometry: ogr.Geometry, membership: np.ndarray, polygon: int, grid, passes: int,
            min_area: float) -> Optional[ogr.Geometry]:
    """Chaikin smoothing for display; vertices shared with another polygon stay where they are, so that
    neighbouring polygons keep a common border. Parts under ``min_area`` (km2) are left out."""
    padded = np.pad(membership, 1, constant_values=NO_CELL)
    x0, size, _, y0, _, _ = grid.geotransform

    def fixed(x: float, y: float) -> bool:
        col, row = int(round((x - x0) / size)), int(round((y0 - y) / size))
        around = padded[row:row + 2, col:col + 2]
        return bool(((around >= 0) & (around != polygon)).any())

    result = ogr.Geometry(ogr.wkbMultiPolygon)
    for i in range(geometry.GetGeometryCount()):
        part = geometry.GetGeometryRef(i)
        if part.GetArea() / 1e6 < min_area - 1e-9:
            continue
        smoothed = ogr.Geometry(ogr.wkbPolygon)
        for j in range(part.GetGeometryCount()):
            ring = part.GetGeometryRef(j)
            points = [ring.GetPoint_2D(k) for k in range(ring.GetPointCount() - 1)]
            flags = [fixed(x, y) for x, y in points]
            for _ in range(passes):
                points, flags = _chaikin(points, flags)
            new_ring = ogr.Geometry(ogr.wkbLinearRing)
            for x, y in points + points[:1]:
                new_ring.AddPoint_2D(x, y)
            smoothed.AddGeometry(new_ring)
        result.AddGeometry(smoothed)
    return result if result.GetGeometryCount() else None


def _chaikin(points: Sequence[Tuple[float, float]], fixed: Sequence[bool]):
    """One pass of Chaikin's corner cutting on a closed ring, fixed vertices kept and edges between two
    fixed vertices left straight."""
    out, flags = [], []
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        fa, fb = fixed[i], fixed[(i + 1) % n]
        if fa:
            out.append(a)
            flags.append(True)
        if fa and fb:
            continue
        q = (0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1])
        r = (0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1])
        if not fa:
            out.append(q)
            flags.append(False)
        if not fb:
            out.append(r)
            flags.append(False)
    return out, flags


# --- legend and style ----------------------------------------------------------------------------


def _write_legend(directory: str, table) -> str:
    path = os.path.join(directory, LEGEND)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["id", "strate", "rang", "parent", "annee_creation"])
        for polygon in range(len(table)):
            created = table.created[polygon]
            writer.writerow([polygon, table.stratum[polygon], table.rank[polygon], table.parent[polygon],
                             "" if created is None else f"{created:g}"])
    return path


def _write_style(path: str, table) -> None:
    """QGIS paletted style: one colour per rank (the darker, the more urban), labelled with the stratum."""
    ranks = sorted({r for r in table.rank if r != NO_RANK})
    entries = []
    for polygon in range(len(table)):
        rank = table.rank[polygon]
        colour = PALETTE[min(ranks.index(rank) if rank in ranks else 0, len(PALETTE) - 1)]
        label = f"{polygon} – {table.stratum[polygon]}".replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
        entries.append(f'<paletteEntry value="{polygon}" color="{colour}" alpha="255" label="{label}"/>')
    entries.append(f'<paletteEntry value="{NO_POLYGON}" color="#ffffff" alpha="0" label="-"/>')
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('<!DOCTYPE qgis PUBLIC \'http://mrcc.com/qgis.dtd\' \'SYSTEM\'>\n<qgis version="3.40">\n'
                     '<pipe><rasterrenderer type="paletted" band="1" opacity="0.8"><colorPalette>\n'
                     + "\n".join(entries) + '\n</colorPalette></rasterrenderer></pipe>\n</qgis>\n')
