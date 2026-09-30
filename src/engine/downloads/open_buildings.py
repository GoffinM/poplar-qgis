"""Google Open Buildings v3: roofs of a zone, downloaded tile by tile and written to a GeoPackage.

The dataset is public (Google Cloud Storage, no account). Files are split by
S2 cells of level 6 (about 100 km) and come in two kinds, without header row:

- ``points``: latitude, longitude, area in m², confidence, plus code;
- ``polygons``: the same with the outline (WKT) before the plus code, about
  four times heavier.

Only the rows whose centroid falls in the zone are kept (decision T4), then
written in the calculation CRS with the fields ``area_m2``, ``confidence`` and
``plus_code``. A report (``<name>.download.json``) says what was downloaded,
from where, when, what was kept and under which licence.
"""

from __future__ import annotations

import csv
import datetime
import gzip
import io
import json
import os
import zlib
from typing import Callable, Dict, List, Optional

import numpy as np
from osgeo import ogr, osr

from .._gdal import gdal_exceptions, srs_from_epsg, srs_from_wkt
from .fetch import Cancelled, DownloadCancelled, FileCache, RemoteMissing
from .s2 import covering_tokens
from .zone import DownloadZone

DATASET = "Google Open Buildings v3"
BASE_URL = "https://storage.googleapis.com/open-buildings-data/v3"
FOLDERS = {"points": "points_s2_level_6_gzip_no_header", "polygons": "polygons_s2_level_6_gzip_no_header"}
LEVEL = 6
IMAGERY_YEAR = 2023
"""Year given to the roofs by default: v3 was published in May 2023 from the imagery available then.
The files carry no date per building, so it is an upper bound, to be corrected when known."""
LICENCE = "CC BY 4.0 ou ODbL v1.0 (au choix) – https://sites.research.google/open-buildings/"
ATTRIBUTION = "Google Open Buildings (Sirko et al., 2021), v3"
LAYER = "roofs"
BATCH = 100_000

Progress = Callable[[float], None]


def tile_url(tile: str, kind: str = "points") -> str:
    return f"{BASE_URL}/{FOLDERS[kind]}/{tile}_buildings.csv.gz"


def tiles_for(zone: DownloadZone) -> List[str]:
    return covering_tokens(zone.lonlat_bounds(), LEVEL)


def report_path(output: str) -> str:
    return os.path.splitext(output)[0] + ".download.json"


def estimate(zone: DownloadZone, cache: FileCache, kind: str = "points") -> Dict[str, object]:
    """Tiles of the zone and the bytes still to download (tiles already in the cache cost nothing)."""
    tiles, to_download, missing = [], 0, []
    for tile in tiles_for(zone):
        key = _cache_key(tile, kind)
        if cache.has(key):
            tiles.append({"tile": tile, "cached": True})
            continue
        try:
            size = cache.fetcher.size(tile_url(tile, kind))
        except RemoteMissing:
            missing.append(tile)
            continue
        tiles.append({"tile": tile, "cached": False, "bytes": size})
        to_download += size or 0
    return {"tiles": tiles, "missing": missing, "bytes_to_download": to_download}


def _cache_key(tile: str, kind: str) -> str:
    return f"google_open_buildings_v3/{kind}/{tile}_buildings.csv.gz"


def download_open_buildings(zone: DownloadZone, output: str, cache: FileCache, kind: str = "points",
                            min_confidence: Optional[float] = None, progress: Optional[Progress] = None,
                            cancelled: Optional[Cancelled] = None) -> Dict[str, object]:
    """Download the tiles of the zone (or take them from the cache) and write the roofs of the zone."""
    if kind not in FOLDERS:
        raise ValueError(f"unknown kind {kind!r} (expected points or polygons)")
    progress = progress or (lambda fraction: None)
    tiles = tiles_for(zone)
    share = 1.0 / max(1, len(tiles))
    files, tile_report = [], []
    for index, tile in enumerate(tiles):
        url, key = tile_url(tile, kind), _cache_key(tile, kind)
        cached = cache.has(key)

        def step(received, total, index=index):
            if total:
                progress(0.6 * share * (index + min(1.0, received / total)))

        try:
            path = cache.get(key, url, step, cancelled)
        except RemoteMissing:
            tile_report.append({"tile": tile, "url": url, "status": "no_buildings"})
            continue
        files.append(path)
        tile_report.append({"tile": tile, "url": url, "status": "cached" if cached else "downloaded",
                            "bytes": os.path.getsize(path)})
        progress(0.6 * share * (index + 1))

    # Written beside, then swapped: a failed or cancelled download never spoils the roofs already there.
    partial = os.path.splitext(output)[0] + ".part.gpkg"
    try:
        counts = _write_roofs(files, zone, partial, kind, min_confidence,
                              lambda fraction: progress(0.6 + 0.4 * fraction), cancelled)
    except BaseException:
        _remove_gpkg(partial)
        raise
    if os.path.exists(report_path(output)):
        os.remove(report_path(output))
    _remove_gpkg(output)
    os.replace(partial, output)
    report = {
        "dataset": DATASET,
        "kind": kind,
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "output": os.path.abspath(output),
        "layer": LAYER,
        "fields": {"area": "area_m2", "confidence": "confidence"},
        "crs_wkt": zone.crs_wkt,
        "zone": {"area_km2": round(zone.area_km2(), 1), "margin_m": zone.margin_m, "limited": zone.limited,
                 "lonlat_bounds": [round(v, 5) for v in zone.lonlat_bounds()]},
        "filters": {"min_confidence": min_confidence},
        "tiles": tile_report,
        "counts": counts,
        "imagery_year": IMAGERY_YEAR,
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
    }
    with open(report_path(output), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    progress(1.0)
    return report


def _remove_gpkg(path: str) -> None:
    for name in (path, path + "-wal", path + "-shm", path + "-journal"):
        if os.path.exists(name):
            os.remove(name)


class DamagedTile(IOError):
    """A tile in the cache cannot be read to the end (interrupted download): it was removed from the cache."""


def _write_roofs(files, zone, output, kind, min_confidence, progress, cancelled) -> Dict[str, int]:
    west, south, east, north = zone.lonlat_bounds()
    mask = zone.mask()
    counts = {"read": 0, "outside_zone": 0, "low_confidence": 0, "kept": 0}
    with gdal_exceptions():
        target = srs_from_wkt(zone.crs_wkt)
        transform = osr.CoordinateTransformation(srs_from_epsg(4326), target)
        _remove_gpkg(output)
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        datasource = ogr.GetDriverByName("GPKG").CreateDataSource(output)
        try:
            _fill(datasource, files, target, transform, west, south, east, north, mask, kind, min_confidence,
                  counts, progress, cancelled)
        finally:
            datasource = None                     # always closed: Windows cannot delete an open file
    counts["outside_zone"] = counts["read"] - counts["kept"] - counts["low_confidence"]
    return counts


def _fill(datasource, files, target, transform, west, south, east, north, mask, kind, min_confidence,
          counts, progress, cancelled) -> None:
    polygons = kind == "polygons"
    layer = definition = None
    try:
        layer = datasource.CreateLayer(LAYER, target, ogr.wkbMultiPolygon if polygons else ogr.wkbPoint,
                                       ["SPATIAL_INDEX=YES"])
        for name, kind_ in (("area_m2", ogr.OFTReal), ("confidence", ogr.OFTReal), ("plus_code", ogr.OFTString)):
            layer.CreateField(ogr.FieldDefn(name, kind_))
        layer.SetMetadataItem("DESCRIPTION", f"{DATASET} ({kind}) – {LICENCE}")
        definition = layer.GetLayerDefn()

        sizes = [os.path.getsize(f) for f in files]
        done = 0
        for path, size in zip(files, sizes):
            rows: List[list] = []
            try:
                with gzip.open(path, "rb") as raw:
                    reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
                    for row in reader:
                        counts["read"] += 1
                        lat, lon = float(row[0]), float(row[1])
                        if not (west <= lon <= east and south <= lat <= north):
                            continue
                        rows.append(row)
                        if len(rows) >= BATCH:
                            _flush(rows, layer, definition, transform, mask, polygons, min_confidence, counts)
                            rows = []
                            if cancelled is not None and cancelled():
                                raise DownloadCancelled(path)
                            progress((done + raw.fileobj.tell() / max(1, size)) / max(1, len(files)))
            except (EOFError, OSError, zlib.error, UnicodeDecodeError, IndexError, ValueError) as error:
                os.remove(path)                   # a damaged tile is downloaded again next time
                raise DamagedTile(f"{os.path.basename(path)}: {error}") from None
            if rows:
                _flush(rows, layer, definition, transform, mask, polygons, min_confidence, counts)
            done += 1
            progress(done / max(1, len(files)))
    finally:
        layer = definition = datasource = None     # nothing keeps the file open, even from a traceback


def _flush(rows, layer, definition, transform, mask, polygons, min_confidence, counts) -> None:
    lat = np.array([float(r[0]) for r in rows])
    lon = np.array([float(r[1]) for r in rows])
    projected = np.array(transform.TransformPoints(np.column_stack([lon, lat]).tolist()))
    inside = mask.contains(projected[:, 0], projected[:, 1])
    confidence = np.array([float(r[3]) for r in rows])
    if min_confidence is not None:
        low = inside & (confidence < min_confidence)
        counts["low_confidence"] += int(low.sum())
        inside &= ~low
    layer.StartTransaction()
    for i in np.flatnonzero(inside):
        row = rows[i]
        feature = ogr.Feature(definition)
        if polygons:
            geometry = ogr.CreateGeometryFromWkt(row[4])
            geometry.AssignSpatialReference(None)
            geometry.Transform(transform)
            geometry = ogr.ForceToMultiPolygon(geometry)
        else:
            geometry = ogr.Geometry(ogr.wkbPoint)
            geometry.AddPoint_2D(float(projected[i, 0]), float(projected[i, 1]))
        feature.SetGeometry(geometry)
        feature.SetField("area_m2", float(row[2]))
        feature.SetField("confidence", float(row[3]))
        feature.SetField("plus_code", row[-1])
        layer.CreateFeature(feature)
    layer.CommitTransaction()
    counts["kept"] += int(inside.sum())
