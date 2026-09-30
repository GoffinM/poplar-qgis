"""Overture Maps buildings: roofs of a zone read from the GeoParquet files of the latest release.

Overture merges Google Open Buildings, Microsoft ML Buildings and OpenStreetMap
into one layer, with duplicates already removed, and publishes it every month
as about 500 GeoParquet files of 500 MB each (public, no account). Nothing is
downloaded in full: GDAL reads the files over HTTP and skips the blocks of rows
outside the zone. The files are sorted in space, so a province is usually in
one or two of them:

1. the file list of the release is read (and kept in the cache);
2. every file is asked, in parallel, how many buildings it has in the zone
   (a few kilobytes each: about 20 s for the whole world);
3. the files that have some are read, block by block, for the zone only.

Each building keeps its source (Google, Microsoft, OpenStreetMap), the year of
that source, its confidence when the source gives one (Google), and the class
and height when OpenStreetMap has them. The roof area is measured on the
outline, in the calculation CRS. It needs the Parquet driver of GDAL (QGIS 3.40
has it on Windows).
"""

from __future__ import annotations

import collections
import concurrent.futures
import datetime
import json
import os
import re
import xml.etree.ElementTree as ElementTree
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from osgeo import gdal, ogr, osr

from .._gdal import gdal_exceptions, srs_from_epsg, srs_from_wkt
from .fetch import Cancelled, DownloadCancelled, UrllibFetcher
from .open_buildings import LAYER, _remove_gpkg, report_path
from .zone import DownloadZone

DATASET = "Overture Maps – buildings"
BUCKET = "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com"
PREFIX = "theme=buildings/type=building/"
LICENCE = "ODbL v1.0 – https://docs.overturemaps.org/attribution/ (sources : Google Open Buildings, " \
          "Microsoft ML Buildings, OpenStreetMap)"
ATTRIBUTION = "© Overture Maps Foundation, © OpenStreetMap contributors, Google Open Buildings, Microsoft"
SOURCES = {"Google Open Buildings": "google", "Microsoft ML Buildings": "microsoft", "OpenStreetMap": "osm"}
KEPT_FIELDS = {"sources", "class", "subtype", "height", "num_floors"}
PARALLEL = 16

Progress = Callable[[float], None]


class ParquetMissing(RuntimeError):
    """The GDAL of this QGIS cannot read GeoParquet (no Parquet driver)."""


def available() -> bool:
    return ogr.GetDriverByName("Parquet") is not None


def _listing(fetcher, prefix: str, delimiter: bool) -> Tuple[List[str], List[Tuple[str, int]]]:
    """Common prefixes and (key, size) of an S3 listing, all pages."""
    prefixes, keys, token = [], [], None
    namespace = "{http://s3.amazonaws.com/doc/2006-03-01/}"
    while True:
        url = f"{BUCKET}/?list-type=2&prefix={prefix}" + ("&delimiter=/" if delimiter else "")
        if token:
            from urllib.parse import quote

            url += f"&continuation-token={quote(token, safe='')}"
        root = ElementTree.fromstring(fetcher.text(url))
        prefixes += [e.text for e in root.iter(f"{namespace}Prefix") if e.text and e.text != prefix]
        for item in root.iter(f"{namespace}Contents"):
            keys.append((item.find(f"{namespace}Key").text, int(item.find(f"{namespace}Size").text)))
        token_element = root.find(f"{namespace}NextContinuationToken")
        if token_element is None or not token_element.text:
            return prefixes, keys
        token = token_element.text


def latest_release(fetcher) -> str:
    """Name of the latest release (for example ``2026-09-23.1``)."""
    prefixes, _ = _listing(fetcher, "release/", delimiter=True)
    names = sorted(p.split("/")[1] for p in prefixes if re.match(r"release/\d{4}-\d{2}-\d{2}", p))
    if not names:
        raise IOError("no Overture release found")
    return names[-1]


def release_files(fetcher, release: str, cache_folder: Optional[str] = None) -> List[Tuple[str, int]]:
    """(key, size) of the building files of a release; the list is kept in the cache (it never changes)."""
    path = os.path.join(cache_folder, "overture", f"{release}.json") if cache_folder else None
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            return [tuple(item) for item in json.load(handle)]
    _, keys = _listing(fetcher, f"release/{release}/{PREFIX}", delimiter=False)
    keys = [(k, s) for k, s in keys if k.endswith(".parquet")]
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(keys, handle)
    return keys


def _gdal_options(proxy: Optional[str]) -> Dict[str, str]:
    options = {"GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES", "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
               "GDAL_HTTP_MAX_RETRY": "3", "GDAL_HTTP_RETRY_DELAY": "2"}
    if proxy:
        from urllib.parse import unquote, urlsplit

        parts = urlsplit(proxy)
        options["GDAL_HTTP_PROXY"] = f"{parts.hostname}:{parts.port}" if parts.port else parts.hostname
        if parts.username:
            options["GDAL_HTTP_PROXYUSERPWD"] = f"{unquote(parts.username)}:{unquote(parts.password or '')}"
    return options


class _Options:
    """GDAL settings for the current thread only (QGIS and the other threads keep theirs)."""

    def __init__(self, options: Dict[str, str]):
        self.options = options

    def __enter__(self):
        self.previous = {k: gdal.GetThreadLocalConfigOption(k, None) for k in self.options}
        for key, value in self.options.items():
            gdal.SetThreadLocalConfigOption(key, value)

    def __exit__(self, *exc):
        for key, value in self.previous.items():
            gdal.SetThreadLocalConfigOption(key, value)


def _open(key: str):
    local = os.path.isabs(key) or key.startswith("/vsi")           # a local copy (tests, offline work)
    datasource = ogr.Open(key if local else f"/vsicurl/{BUCKET}/{key}")
    return datasource, datasource.GetLayer(0)


def files_in_zone(keys: Sequence[str], lonlat_bounds, options, cancelled: Optional[Cancelled] = None,
                  progress: Optional[Progress] = None) -> Dict[str, int]:
    """{file: buildings in the box} for the files that have some (asked in parallel)."""
    def count(key):
        if cancelled is not None and cancelled():
            return key, 0
        with _Options(options), gdal_exceptions():
            datasource, layer = _open(key)
            layer.SetSpatialFilterRect(*lonlat_bounds)
            number = layer.GetFeatureCount()
            layer = datasource = None
            return key, number

    found, done = {}, 0
    with concurrent.futures.ThreadPoolExecutor(PARALLEL) as pool:
        for key, number in pool.map(count, keys):
            done += 1
            if number:
                found[key] = number
            if progress is not None:
                progress(done / max(1, len(keys)))
    if cancelled is not None and cancelled():
        raise DownloadCancelled("overture")
    return found


def _sources(value) -> List[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return [v for v in (value or []) if isinstance(v, dict)]


def download_overture(zone: DownloadZone, output: str, cache_folder: Optional[str] = None, fetcher=None,
                      kind: str = "points", min_confidence: Optional[float] = None,
                      datasets: Optional[Sequence[str]] = None, release: Optional[str] = None,
                      progress: Optional[Progress] = None, cancelled: Optional[Cancelled] = None) -> Dict[str, object]:
    """Read the buildings of the zone from Overture and write them like the Google download (same fields)."""
    if not available():
        raise ParquetMissing("the GDAL of this QGIS has no Parquet driver")
    if kind not in ("points", "polygons"):
        raise ValueError(f"unknown kind {kind!r} (expected points or polygons)")
    fetcher = fetcher or UrllibFetcher()
    progress = progress or (lambda fraction: None)
    options = _gdal_options(getattr(fetcher, "proxy", None))
    release = release or latest_release(fetcher)
    keys = [k for k, _ in release_files(fetcher, release, cache_folder)]
    bounds = zone.lonlat_bounds()
    found = files_in_zone(keys, bounds, options, cancelled, lambda f: progress(0.3 * f))
    wanted = {SOURCES.get(d, d) for d in datasets} if datasets else None

    partial = os.path.splitext(output)[0] + ".part.gpkg"
    try:
        counts, by_source, years = _write(found, zone, partial, kind, min_confidence, wanted, options,
                                          lambda f: progress(0.3 + 0.7 * f), cancelled)
    except BaseException:
        _remove_gpkg(partial)
        raise
    if os.path.exists(report_path(output)):
        os.remove(report_path(output))
    _remove_gpkg(output)
    os.replace(partial, output)
    report = {
        "dataset": DATASET,
        "release": release,
        "kind": kind,
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "output": os.path.abspath(output),
        "layer": LAYER,
        "fields": {"area": "area_m2", "confidence": "confidence", "source": "source", "year": "year"},
        "crs_wkt": zone.crs_wkt,
        "zone": {"area_km2": round(zone.area_km2(), 1), "margin_m": zone.margin_m, "limited": zone.limited,
                 "lonlat_bounds": [round(v, 5) for v in bounds]},
        "filters": {"min_confidence": min_confidence, "sources": sorted(wanted) if wanted else None},
        "files": [{"file": f"{BUCKET}/{k}", "buildings_in_box": n} for k, n in sorted(found.items())],
        "counts": counts,
        "by_source": dict(by_source),
        "imagery_year": years.most_common(1)[0][0] if years else None,
        "years": dict(sorted(years.items())),
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
    }
    with open(report_path(output), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    progress(1.0)
    return report


def _write(found, zone, output, kind, min_confidence, wanted, options, progress, cancelled):
    counts = {"read": 0, "outside_zone": 0, "other_source": 0, "low_confidence": 0, "kept": 0}
    by_source: Dict[str, int] = collections.Counter()
    years: Dict[int, int] = collections.Counter()
    bounds = zone.lonlat_bounds()
    mask = zone.mask()
    polygons = kind == "polygons"
    total = max(1, sum(found.values()))
    with gdal_exceptions(), _Options(options):
        target = srs_from_wkt(zone.crs_wkt)
        transform = osr.CoordinateTransformation(srs_from_epsg(4326), target)
        _remove_gpkg(output)
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        datasource = ogr.GetDriverByName("GPKG").CreateDataSource(output)
        out = definition = source_layer = source = None
        try:
            out = datasource.CreateLayer(LAYER, target, ogr.wkbMultiPolygon if polygons else ogr.wkbPoint,
                                         ["SPATIAL_INDEX=YES"])
            for name, field_type in (("area_m2", ogr.OFTReal), ("confidence", ogr.OFTReal),
                                     ("source", ogr.OFTString), ("year", ogr.OFTInteger),
                                     ("class", ogr.OFTString), ("height", ogr.OFTReal),
                                     ("num_floors", ogr.OFTInteger)):
                out.CreateField(ogr.FieldDefn(name, field_type))
            out.SetMetadataItem("DESCRIPTION", f"{DATASET} ({kind}) – {LICENCE}")
            definition = out.GetLayerDefn()
            for key in sorted(found):
                source, source_layer = _open(key)
                names = [source_layer.GetLayerDefn().GetFieldDefn(i).GetName()
                         for i in range(source_layer.GetLayerDefn().GetFieldCount())]
                source_layer.SetIgnoredFields([n for n in names if n not in KEPT_FIELDS])
                source_layer.SetSpatialFilterRect(*bounds)
                out.StartTransaction()
                for feature in source_layer:
                    counts["read"] += 1
                    if counts["read"] % 5000 == 0:
                        if cancelled is not None and cancelled():
                            raise DownloadCancelled(key)
                        progress(min(1.0, counts["read"] / total))
                    _one(feature, out, definition, transform, mask, polygons, min_confidence, wanted,
                         counts, by_source, years)
                out.CommitTransaction()
                source_layer = source = None
        finally:
            out = definition = source_layer = source = datasource = None   # nothing keeps a file open
    counts["outside_zone"] = counts["read"] - counts["kept"] - counts["low_confidence"] - counts["other_source"]
    return counts, by_source, years


def _one(feature, out, definition, transform, mask, polygons, min_confidence, wanted, counts, by_source, years):
    geometry = feature.GetGeometryRef()
    if geometry is None or geometry.IsEmpty():
        return
    geometry = geometry.Clone()
    geometry.Transform(transform)
    centroid = geometry.Centroid()
    if not mask.contains(np.array([centroid.GetX()]), np.array([centroid.GetY()]))[0]:
        return
    sources = _sources(feature.GetField("sources"))
    main = sources[0] if sources else {}
    name = SOURCES.get(main.get("dataset"), main.get("dataset") or "unknown")
    if wanted is not None and name not in wanted:
        counts["other_source"] += 1
        return
    confidence = main.get("confidence")
    if min_confidence is not None and confidence is not None and confidence < min_confidence:
        counts["low_confidence"] += 1              # the threshold applies to the sources that give a confidence
        return
    result = ogr.Feature(definition)
    if polygons:
        result.SetGeometry(ogr.ForceToMultiPolygon(geometry))
    else:
        result.SetGeometry(centroid)
    result.SetField("area_m2", geometry.GetArea())
    if confidence is not None:
        result.SetField("confidence", float(confidence))
    result.SetField("source", name)
    year = str(main.get("update_time") or "")[:4]
    if year.isdigit():
        result.SetField("year", int(year))
        years[int(year)] += 1
    for field in ("class", "height", "num_floors"):
        index = feature.GetFieldIndex(field)
        if index >= 0 and feature.IsFieldSetAndNotNull(index):
            result.SetField(field, feature.GetField(index))
    out.CreateFeature(result)
    counts["kept"] += 1
    by_source[name] += 1
