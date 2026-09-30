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
    releases = online_releases(fetcher)
    if not releases:
        raise IOError("no Overture release found")
    return releases[-1]


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


INDEX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overture_index")
INDEX_URLS = [  # the index of each release, published with the plugin (tools/overture_index.py)
    "https://raw.githubusercontent.com/GoffinM/poplar-qgis/main/src/engine/downloads/overture_index/{release}.json",
    "https://raw.githubusercontent.com/GoffinM/poplar-qgis/claude/legacy-code-assessment-frf66q/src/engine/"
    "downloads/overture_index/{release}.json",
]


def online_releases(fetcher) -> List[str]:
    """Releases still published, oldest first (Overture keeps the last two or three)."""
    prefixes, _ = _listing(fetcher, "release/", delimiter=True)
    return sorted(p.split("/")[1] for p in prefixes if re.match(r"release/\d{4}-\d{2}-\d{2}", p))


def _file_box(key: str, options) -> Tuple[float, float, float, float]:
    """Longitude/latitude box of one file, from its GeoParquet metadata (its footer only, about 0.7 MB)."""
    # No gdal_exceptions() here: it switches a setting shared by every thread, and this runs in many at once.
    with _Options(options):
        datasource = ogr.Open(key if os.path.isabs(key) or key.startswith("/vsi") else f"/vsicurl/{BUCKET}/{key}")
        if datasource is None:
            raise IOError(f"{key}: {gdal.GetLastErrorMsg() or 'cannot be opened'}")
        layer = datasource.GetLayer(0)
        geo = json.loads(layer.GetMetadataItem("geo", "_PARQUET_METADATA_") or "{}")
        box = (geo.get("columns", {}).get("geometry", {}) or {}).get("bbox")
        if not box:
            west, east, south, north = layer.GetExtent()
            box = [west, south, east, north]
        layer = datasource = None
        return tuple(float(v) for v in box[:4])


_POOL = None


def _pool():
    """Worker threads kept for the whole session: the Parquet reader of recent GDAL versions (3.13) crashes
    when threads that opened files end and new ones take over (not seen with the GDAL 3.10 of QGIS 3.40)."""
    global _POOL
    if _POOL is None:
        _POOL = concurrent.futures.ThreadPoolExecutor(PARALLEL, thread_name_prefix="poplar-overture")
    return _POOL


def build_index(fetcher, release: str, options=None, cancelled: Optional[Cancelled] = None,
                progress: Optional[Progress] = None) -> Dict[str, object]:
    """Box of every file of a release: reads the footer of each file (about 360 MB for the world).

    Done once per release by ``tools/overture_index.py`` and published with the plugin; on a computer
    only when no published index exists, then kept in the cache.
    """
    options = options if options is not None else _gdal_options(getattr(fetcher, "proxy", None))
    keys = [k for k, _ in release_files(fetcher, release)]
    files, done = [], 0
    futures = {_pool().submit(_file_box, key, options): key for key in keys}
    try:
        for future in concurrent.futures.as_completed(futures):
            if cancelled is not None and cancelled():
                raise DownloadCancelled("overture index")
            files.append([futures[future], *future.result()])
            done += 1
            if progress is not None:
                progress(done / max(1, len(keys)))
    finally:
        for future in futures:                  # « Cancel »: the files not asked yet are dropped at once
            future.cancel()
    return {"release": release, "created": datetime.date.today().isoformat(), "files": sorted(files)}


def load_index(fetcher, release: str, cache_folder: Optional[str] = None) -> Tuple[Optional[dict], str]:
    """(index, where it came from): the cache, the plugin itself, then the project page on GitHub."""
    cached = os.path.join(cache_folder, "overture", f"index_{release}.json") if cache_folder else None
    for place, path in (("cache", cached), ("plugin", os.path.join(INDEX_DIR, f"{release}.json"))):
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                return json.load(handle), place
    for url in INDEX_URLS:
        try:
            index = json.loads(fetcher.text(url.format(release=release)))
        except Exception:  # not published (yet), or no access: try the next place
            continue
        save_index(index, cache_folder)
        return index, "github"
    return None, ""


def save_index(index: dict, cache_folder: Optional[str]) -> None:
    if cache_folder:
        path = os.path.join(cache_folder, "overture", f"index_{index['release']}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(index, handle)


def choose_release(fetcher, cache_folder: Optional[str] = None):
    """(release, index, where): the latest release that has an index, else the latest one (index to build)."""
    online = online_releases(fetcher)
    if not online:
        raise IOError("no Overture release found")
    for release in reversed(online):
        index, place = load_index(fetcher, release, cache_folder)
        if index is not None:
            return release, index, place
    return online[-1], None, ""


def files_in_zone(index: dict, lonlat_bounds) -> List[str]:
    """Files whose box meets the zone (usually one or two for a province)."""
    west, south, east, north = lonlat_bounds
    return [key for key, x0, y0, x1, y1 in index["files"] if x0 <= east and x1 >= west and y0 <= north and y1 >= south]


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
                      progress: Optional[Progress] = None, cancelled: Optional[Cancelled] = None,
                      stage=None) -> Dict[str, object]:
    """Read the buildings of the zone from Overture and write them like the Google download (same fields).

    ``stage(key, **values)`` is told what is being done (finding the files, reading them), for the user.
    """
    if not available():
        raise ParquetMissing("the GDAL of this QGIS has no Parquet driver")
    if kind not in ("points", "polygons"):
        raise ValueError(f"unknown kind {kind!r} (expected points or polygons)")
    fetcher = fetcher or UrllibFetcher()
    progress = progress or (lambda fraction: None)
    options = _gdal_options(getattr(fetcher, "proxy", None))
    stage = stage or (lambda key, **values: None)
    stage("download.stage.index")
    if release:
        index, place = load_index(fetcher, release, cache_folder)
    else:
        release, index, place = choose_release(fetcher, cache_folder)
    if index is None:                                   # no published index: built here, once, then kept
        stage("download.stage.build_index")
        index = build_index(fetcher, release, options, cancelled, lambda f: progress(0.5 * f))
        save_index(index, cache_folder)
        place = "built"
    bounds = zone.lonlat_bounds()
    found = files_in_zone(index, bounds)
    wanted = {SOURCES.get(d, d) for d in datasets} if datasets else None
    start = 0.5 if place == "built" else 0.05
    stage("download.stage.read", files=len(found))

    partial = os.path.splitext(output)[0] + ".part.gpkg"
    try:
        counts, by_source, years = _write(found, zone, partial, kind, min_confidence, wanted, options,
                                          lambda f: progress(start + (1 - start) * f), cancelled,
                                          lambda n: stage("download.stage.read_count", count=f"{n:,}".replace(",", " ")))
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
        "index": place,
        "kind": kind,
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "output": os.path.abspath(output),
        "layer": LAYER,
        "fields": {"area": "area_m2", "confidence": "confidence", "source": "source", "year": "year"},
        "crs_wkt": zone.crs_wkt,
        "zone": {"area_km2": round(zone.area_km2(), 1), "margin_m": zone.margin_m, "limited": zone.limited,
                 "lonlat_bounds": [round(v, 5) for v in bounds]},
        "filters": {"min_confidence": min_confidence, "sources": sorted(wanted) if wanted else None},
        "files": [f"{BUCKET}/{k}" for k in found],
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


def _write(found, zone, output, kind, min_confidence, wanted, options, progress, cancelled, told=None):
    counts = {"read": 0, "outside_zone": 0, "other_source": 0, "low_confidence": 0, "kept": 0}
    by_source: Dict[str, int] = collections.Counter()
    years: Dict[int, int] = collections.Counter()
    bounds = zone.lonlat_bounds()
    mask = zone.mask()
    polygons = kind == "polygons"
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
            for number, key in enumerate(found):
                source, source_layer = _open(key)
                # No SetIgnoredFields(): with the GDAL 3.10 of QGIS 3.40, skipping columns cuts the
                # « sources » field down to its first sub-field. Reading them all costs about a third more.
                source_layer.SetSpatialFilterRect(*bounds)
                out.StartTransaction()
                in_file = 0
                if cancelled is not None and cancelled():
                    raise DownloadCancelled(key)
                for feature in source_layer:
                    counts["read"] += 1
                    in_file += 1
                    if counts["read"] % 2000 == 0:
                        if cancelled is not None and cancelled():
                            raise DownloadCancelled(key)
                        # a province is a few hundred thousand buildings: the bar creeps, never stops
                        progress((number + in_file / (in_file + 100_000)) / max(1, len(found)))
                        if told is not None:
                            told(counts["read"])
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
