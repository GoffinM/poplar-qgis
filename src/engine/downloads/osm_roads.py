"""OpenStreetMap roads of a zone, downloaded through the Overpass API and written to a GeoPackage.

One request asks every way tagged ``highway`` in the bounding box of the zone (in longitude and
latitude); the answer (OSM XML) is read by the OSM driver of GDAL, the lines are cut by the zone and
written in the calculation CRS with the fields:

- ``highway``: the OSM tag (``primary``, ``track``, ``path``…);
- ``classe``: ``nationale`` (motorway, trunk, primary), ``provinciale`` (secondary, tertiary) or
  ``autre`` (every other road, track or path), the classes of plan_demande_et_routes.md (B-d);
- ``nom``, ``ref``, ``surface``, ``osm_id``, ``longueur_m``.

Overpass servers are shared and sometimes busy: the next one is tried when one refuses (HTTP 429, 504…).
A report (``<name>.download.json``) says what was asked, to which server, when, what was kept and under
which licence (ODbL: « © OpenStreetMap contributors » must be cited).
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.error
import urllib.parse
from typing import Callable, Dict, List, Optional

from osgeo import gdal, ogr, osr

from .._gdal import gdal_exceptions, srs_from_epsg, srs_from_wkt
from .fetch import Cancelled, DownloadCancelled, UrllibFetcher
from .open_buildings import _remove_gpkg
from .zone import DownloadZone

DATASET = "OpenStreetMap – routes (Overpass API)"
SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
LICENCE = "ODbL v1.0 – https://www.openstreetmap.org/copyright"
ATTRIBUTION = "© OpenStreetMap contributors"
LAYER = "routes"
TIMEOUT_S = 300
CLASSES = {
    "nationale": ("motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"),
    "provinciale": ("secondary", "secondary_link", "tertiary", "tertiary_link"),
}
OTHER = "autre"
NOT_ROADS = ("proposed", "construction", "abandoned", "disused", "razed", "platform", "bus_stop", "elevator",
             "corridor", "rest_area", "services")
"""Values of ``highway`` that are not a way one can travel today: left out."""

Progress = Callable[[float], None]


class OverpassError(RuntimeError):
    """No Overpass server gave an answer (each refusal is in the message)."""


def road_class(highway: Optional[str]) -> str:
    for name, values in CLASSES.items():
        if highway in values:
            return name
    return OTHER


def query(zone: DownloadZone) -> str:
    west, south, east, north = zone.lonlat_bounds()
    box = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"
    return (f"[out:xml][timeout:{TIMEOUT_S}];"
            f'(way["highway"]({box}););'
            "(._;>;);out body;")


def report_path(output: str) -> str:
    return os.path.splitext(output)[0] + ".download.json"


def _ask(fetcher, servers: List[str], text: str, path: str, progress: Progress,
         cancelled: Optional[Cancelled]) -> str:
    """The answer of the first server that gives one; returns the URL of that server."""
    refusals = []
    for server in servers:
        url = f"{server}?{urllib.parse.urlencode({'data': text})}"

        def step(received, total):
            # Overpass does not send the length of its answer: a slow approach to 90 %.
            progress(0.9 * (received / total if total else received / (received + 5_000_000)))

        try:
            fetcher.fetch(url, path, step, cancelled)
        except DownloadCancelled:
            raise
        except (urllib.error.URLError, OSError) as error:
            refusals.append(f"{server}: {getattr(error, 'code', '')} {getattr(error, 'reason', error)}".strip())
            continue
        with open(path, "rb") as handle:
            head = handle.read(4096)
        if b"<osm" not in head:
            refusals.append(f"{server}: {head[:200].decode('utf-8', 'replace')}")
            continue
        return server
    raise OverpassError("; ".join(refusals) or "no server")


def _remark(path: str) -> Optional[str]:
    """Overpass sends a <remark> instead of the data when it stops on a limit (time, memory)."""
    with open(path, "rb") as handle:
        handle.seek(max(0, os.path.getsize(path) - 4096))
        tail = handle.read().decode("utf-8", "replace")
    start = tail.find("<remark>")
    if start < 0:
        return None
    return tail[start + len("<remark>"):tail.find("</remark>", start)].strip()


def _tags(other: Optional[str]) -> Dict[str, str]:
    """``"ref"=>"RN7","surface"=>"asphalt"`` (HSTORE of the OSM driver) as a dict."""
    found = {}
    for part in (other or "").split('","'):
        if "=>" in part:
            key, value = part.split("=>", 1)
            found[key.strip('"')] = value.strip('"')
    return found


def download_osm_roads(zone: DownloadZone, output: str, fetcher=None, servers: Optional[List[str]] = None,
                       progress: Optional[Progress] = None,
                       cancelled: Optional[Cancelled] = None) -> Dict[str, object]:
    """Download the roads of the zone and write them to ``output`` (GeoPackage, layer ``routes``)."""
    progress = progress or (lambda fraction: None)
    fetcher = fetcher or UrllibFetcher(timeout=TIMEOUT_S + 60)
    text = query(zone)
    folder = os.path.dirname(os.path.abspath(output))
    os.makedirs(folder, exist_ok=True)
    answer = os.path.splitext(output)[0] + ".part.osm"
    partial = os.path.splitext(output)[0] + ".part.gpkg"
    try:
        server = _ask(fetcher, servers or SERVERS, text, answer, progress, cancelled)
        remark = _remark(answer)
        if remark and "error" in remark.lower():
            raise OverpassError(f"{server}: {remark}")
        counts = _write(answer, zone, partial, cancelled)
    except BaseException:
        _remove_gpkg(partial)
        raise
    finally:
        if os.path.exists(answer):
            os.remove(answer)
    if os.path.exists(report_path(output)):
        os.remove(report_path(output))
    _remove_gpkg(output)
    os.replace(partial, output)
    report = {
        "dataset": DATASET,
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "server": server,
        "query": text,
        "output": os.path.abspath(output),
        "layer": LAYER,
        "fields": {"type": "highway", "class": "classe"},
        "classes": {**{name: list(values) for name, values in CLASSES.items()}, OTHER: "every other highway"},
        "crs_wkt": zone.crs_wkt,
        "zone": {"area_km2": round(zone.area_km2(), 1), "margin_m": zone.margin_m, "limited": zone.limited,
                 "lonlat_bounds": [round(v, 5) for v in zone.lonlat_bounds()]},
        "counts": counts,
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
    }
    with open(report_path(output), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    progress(1.0)
    return report


def _write(answer: str, zone: DownloadZone, output: str, cancelled: Optional[Cancelled]) -> Dict[str, object]:
    counts = {"read": 0, "not_roads": 0, "outside_zone": 0, "kept": 0, "length_km": {}}
    with gdal_exceptions():
        source = gdal.OpenEx(answer, gdal.OF_VECTOR, allowed_drivers=["OSM"])
        lines = source.GetLayerByName("lines")
        target = srs_from_wkt(zone.crs_wkt)
        wgs84 = srs_from_epsg(4326)
        for srs in (target, wgs84):
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        transform = osr.CoordinateTransformation(wgs84, target)
        out = ogr.GetDriverByName("GPKG").CreateDataSource(output)
        layer = out.CreateLayer(LAYER, target, ogr.wkbMultiLineString, ["SPATIAL_INDEX=YES"])
        for name, kind, width in (("osm_id", ogr.OFTString, 20), ("highway", ogr.OFTString, 40),
                                  ("classe", ogr.OFTString, 20), ("nom", ogr.OFTString, 120),
                                  ("ref", ogr.OFTString, 40), ("surface", ogr.OFTString, 40),
                                  ("longueur_m", ogr.OFTReal, 0)):
            field = ogr.FieldDefn(name, kind)
            if width:
                field.SetWidth(width)
            layer.CreateField(field)
        definition = layer.GetLayerDefn()
        names = [lines.GetLayerDefn().GetFieldDefn(i).GetName() for i in range(lines.GetLayerDefn().GetFieldCount())]
        layer.StartTransaction()
        for feature in lines:
            if cancelled is not None and cancelled():
                layer.RollbackTransaction()
                out = None
                raise DownloadCancelled("osm")
            highway = feature.GetField("highway") if "highway" in names else None
            if not highway:
                continue                                   # a line of another kind (a river, a power line…)
            counts["read"] += 1
            if highway in NOT_ROADS:
                counts["not_roads"] += 1
                continue
            geometry = feature.GetGeometryRef()
            if geometry is None:
                continue
            geometry = geometry.Clone()
            geometry.Transform(transform)
            geometry = geometry.Intersection(zone.geometry)
            if geometry is None or geometry.IsEmpty():
                counts["outside_zone"] += 1
                continue
            geometry = ogr.ForceToMultiLineString(geometry)
            if geometry.GetGeometryType() not in (ogr.wkbMultiLineString, ogr.wkbMultiLineString25D) \
                    or geometry.Length() <= 0:
                counts["outside_zone"] += 1
                continue
            tags = _tags(feature.GetField("other_tags") if "other_tags" in names else None)
            classe = road_class(highway)
            row = ogr.Feature(definition)
            row.SetField("osm_id", feature.GetField("osm_id") if "osm_id" in names else None)
            row.SetField("highway", highway)
            row.SetField("classe", classe)
            row.SetField("nom", feature.GetField("name") if "name" in names else None)
            row.SetField("ref", tags.get("ref"))
            row.SetField("surface", tags.get("surface"))
            row.SetField("longueur_m", round(geometry.Length(), 1))
            row.SetGeometry(geometry)
            layer.CreateFeature(row)
            counts["kept"] += 1
            counts["length_km"][classe] = counts["length_km"].get(classe, 0.0) + geometry.Length() / 1000
        layer.CommitTransaction()
        out = None
        source = None
    counts["length_km"] = {k: round(v, 2) for k, v in sorted(counts["length_km"].items())}
    return counts
