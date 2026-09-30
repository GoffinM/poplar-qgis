"""Download of roofs from Google Open Buildings: S2 tiles, zone, cache, filters, GeoPackage and report."""

import gzip
import json
import os

import numpy as np
import pytest
from osgeo import ogr, osr

from engine._gdal import srs_from_epsg
from engine.downloads.fetch import DownloadCancelled, FileCache, RemoteMissing
from engine.downloads.open_buildings import download_open_buildings, estimate, report_path, tile_url, tiles_for
from engine.downloads.s2 import cell_token, covering_tokens
from engine.downloads.zone import DownloadZone, EmptyZone, ZoneLayer
from paths import MURAMVYA

UTM35S = srs_from_epsg(32735).ExportToWkt()
CENTRE = (800_000.0, 9_640_000.0)          # Muramvya, UTM 35 S


def test_s2_tokens_of_known_places():
    assert cell_token(51.5, -0.12, 4) == "487"                         # London
    assert cell_token(-2.47969119, 30.66829286, 6) == "19c5"          # a row of the Google tile 19c5
    assert covering_tokens((29.5308, -3.3799, 29.7793, -3.1541), 6) == ["19c1", "19c3"]   # Muramvya


def _square(path, centre, half, srs_wkt=UTM35S):
    srs = osr.SpatialReference()
    srs.ImportFromWkt(srs_wkt)
    datasource = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    layer = datasource.CreateLayer("zone", srs, ogr.wkbPolygon)
    x, y = centre
    ring = f"{x - half} {y - half},{x + half} {y - half},{x + half} {y + half},{x - half} {y + half},{x - half} {y - half}"
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(ogr.CreateGeometryFromWkt(f"POLYGON(({ring}))"))
    layer.CreateFeature(feature)
    datasource = None
    return str(path)


def _lonlat(points):
    transform = osr.CoordinateTransformation(srs_from_epsg(32735), srs_from_epsg(4326))
    return [transform.TransformPoint(x, y)[:2] for x, y in points]


def _rows(points, areas, confidences, polygons=False):
    rows = []
    for (lon, lat), area, confidence in zip(_lonlat(points), areas, confidences):
        cells = [f"{lat:.8f}", f"{lon:.8f}", f"{area:.4f}", f"{confidence:.4f}"]
        if polygons:
            d = 0.00003
            cells.append(f'"POLYGON(({lon - d} {lat - d}, {lon + d} {lat - d}, {lon + d} {lat + d}, '
                         f'{lon - d} {lat + d}, {lon - d} {lat - d}))"')
        cells.append("6G8GXM9W+MR9C")
        rows.append(",".join(cells))
    return "\n".join(rows) + "\n"


class FakeFetcher:
    """Serves the same rows for every tile of the given list; the other tiles are missing."""

    def __init__(self, content, tiles):
        self.content, self.tiles, self.calls = content.encode(), set(tiles), []

    def _tile(self, url):
        return os.path.basename(url).split("_")[0]

    def size(self, url):
        if self._tile(url) not in self.tiles:
            raise RemoteMissing(url)
        return len(self.content)

    def fetch(self, url, path, progress=None, cancelled=None):
        self.calls.append(url)
        if self._tile(url) not in self.tiles:
            raise RemoteMissing(url)
        with gzip.open(path, "wb") as handle:
            handle.write(self.content)
        if cancelled is not None and cancelled():
            raise DownloadCancelled(url)
        if progress is not None:
            progress(len(self.content), len(self.content))


def _world(tmp_path, polygons=False):
    zone_path = _square(tmp_path / "strata.gpkg", CENTRE, 1000)
    x, y = CENTRE
    points = [(x, y), (x + 900, y - 900), (x + 1500, y), (x - 5000, y), (x + 100, y + 100)]
    content = _rows(points, [30, 40, 50, 60, 70], [0.9, 0.7, 0.8, 0.9, 0.66], polygons)
    return zone_path, content


def _read(output):
    datasource = ogr.Open(output)
    layer = datasource.GetLayer("roofs")
    rows = [(f.GetField("area_m2"), f.GetField("confidence"), f.GetGeometryRef().GetGeometryName())
            for f in layer]
    return sorted(rows)


def test_download_keeps_the_roofs_of_the_zone_and_reports(tmp_path):
    zone_path, content = _world(tmp_path)
    zone = DownloadZone.from_layers(ZoneLayer(zone_path), UTM35S)
    tiles = tiles_for(zone)
    fetcher = FakeFetcher(content, tiles[:1])
    cache = FileCache(str(tmp_path / "cache"), fetcher)
    output = str(tmp_path / "toits" / "google.gpkg")
    steps = []
    report = download_open_buildings(zone, output, cache, progress=steps.append)
    assert [r[0] for r in _read(output)] == [30, 40, 70]                # the three roofs inside the square
    assert report["counts"] == {"read": 5, "outside_zone": 2, "low_confidence": 0, "kept": 3}
    assert steps[-1] == 1.0 and steps == sorted(steps)
    with open(report_path(output), encoding="utf-8") as handle:
        saved = json.load(handle)
    assert saved["dataset"] == "Google Open Buildings v3" and "CC BY 4.0" in saved["licence"]
    assert [t["status"] for t in saved["tiles"]] == ["downloaded"] + ["no_buildings"] * (len(tiles) - 1)
    assert saved["tiles"][0]["url"] == tile_url(tiles[0])

    calls = len(fetcher.calls)
    again = download_open_buildings(zone, output, cache, min_confidence=0.75)     # from the cache
    assert len(fetcher.calls) == calls + len(tiles) - 1                 # only the missing tiles are asked again
    assert again["tiles"][0]["status"] == "cached"
    assert again["counts"]["low_confidence"] == 2 and [r[0] for r in _read(output)] == [30]
    assert estimate(zone, cache)["bytes_to_download"] == 0


def test_margin_limit_and_polygons(tmp_path):
    zone_path, content = _world(tmp_path, polygons=True)
    limit = _square(tmp_path / "border.gpkg", (CENTRE[0] + 1000, CENTRE[1]), 1400)     # cuts the west side
    zone = DownloadZone.from_layers(ZoneLayer(zone_path), UTM35S, margin_m=600, limit=ZoneLayer(limit))
    assert zone.limited and zone.area_km2() == pytest.approx(2.0 * 2.8, rel=0.01)   # 2 km (limit) × 2.8 km, corners rounded
    cache = FileCache(str(tmp_path / "cache"), FakeFetcher(content, tiles_for(zone)[:1]))   # tiles never overlap
    output = str(tmp_path / "google.gpkg")
    report = download_open_buildings(zone, output, cache, kind="polygons")
    rows = _read(output)
    assert [r[0] for r in rows] == [30, 40, 50, 70]                     # the roof 1.5 km east is in the margin
    assert {r[2] for r in rows} == {"MULTIPOLYGON"}
    assert report["zone"]["margin_m"] == 600 and report["kind"] == "polygons"

    far = _square(tmp_path / "far.gpkg", (CENTRE[0] + 50_000, CENTRE[1]), 100)
    with pytest.raises(EmptyZone):
        DownloadZone.from_layers(ZoneLayer(zone_path), UTM35S, limit=ZoneLayer(far))


def test_cancelled_download_leaves_no_partial_file(tmp_path):
    zone_path, content = _world(tmp_path)
    zone = DownloadZone.from_layers(ZoneLayer(zone_path), UTM35S)
    cache = FileCache(str(tmp_path / "cache"), FakeFetcher(content, tiles_for(zone)))
    with pytest.raises(DownloadCancelled):
        download_open_buildings(zone, str(tmp_path / "google.gpkg"), cache, cancelled=lambda: True)
    left = [name for _, _, names in os.walk(tmp_path / "cache") for name in names]
    assert left == []


@pytest.mark.skipif(not os.environ.get("POPLAR_NET_TEST"), reason="needs the internet (set POPLAR_NET_TEST=1)")
def test_muramvya_roofs_are_those_of_the_workbooks(tmp_path):
    from scipy.spatial import cKDTree

    zone = DownloadZone.from_layers(ZoneLayer(os.path.join(MURAMVYA, "commune_muramvya.shp")), UTM35S)
    cache = FileCache(os.environ.get("POPLAR_CACHE", str(tmp_path / "cache")))
    output = str(tmp_path / "google.gpkg")
    report = download_open_buildings(zone, output, cache)
    assert report["counts"]["kept"] == 39_126

    def points(path):
        datasource = ogr.Open(path)
        return np.array([(f.GetGeometryRef().GetX(), f.GetGeometryRef().GetY()) for f in datasource.GetLayer(0)])

    distance, _ = cKDTree(points(output)).query(points(os.path.join(MURAMVYA, "buildings_muramvya.gpkg")))
    assert (distance < 1).sum() >= 38_930                               # 38 936 of the 38 942 roofs of Lionel
