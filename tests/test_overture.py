"""Overture Maps buildings read from GeoParquet (needs the Parquet driver of GDAL, as in QGIS 3.40)."""

import json
import os

import pytest
from osgeo import ogr, osr

from engine._gdal import srs_from_epsg
from engine.downloads import overture
from engine.downloads.open_buildings import report_path
from engine.downloads.zone import DownloadZone, ZoneLayer
from paths import MURAMVYA

pytestmark = pytest.mark.skipif(not overture.available(), reason="GDAL without the Parquet driver")

UTM35S = srs_from_epsg(32735).ExportToWkt()
CENTRE = (800_000.0, 9_640_000.0)


def _square_layer(path, half):
    srs = osr.SpatialReference()
    srs.ImportFromWkt(UTM35S)
    datasource = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    layer = datasource.CreateLayer("zone", srs, ogr.wkbPolygon)
    x, y = CENTRE
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(ogr.CreateGeometryFromWkt(
        f"POLYGON(({x - half} {y - half},{x + half} {y - half},{x + half} {y + half},{x - half} {y + half},"
        f"{x - half} {y - half}))"))
    layer.CreateFeature(feature)
    datasource = None
    return str(path)


BUILDINGS = [  # offset from the centre (m), side (m), source, confidence, year, class
    ((0, 0), 10, "Google Open Buildings", 0.9, "2023", None),
    ((300, -200), 8, "Google Open Buildings", 0.7, "2023", None),
    ((-400, 100), 12, "Microsoft ML Buildings", None, "2021", None),
    ((500, 500), 20, "OpenStreetMap", None, "2015", "hospital"),
    ((5000, 0), 10, "Google Open Buildings", 0.9, "2023", None),          # outside the zone
]


def _parquet(path):
    """A small GeoParquet file laid out like an Overture buildings file (sources as JSON, lon/lat)."""
    wgs84 = srs_from_epsg(4326)
    to_lonlat = osr.CoordinateTransformation(srs_from_epsg(32735), wgs84)
    datasource = ogr.GetDriverByName("Parquet").CreateDataSource(str(path))
    layer = datasource.CreateLayer("buildings", wgs84, ogr.wkbPolygon, ["WRITE_COVERING_BBOX=YES"])
    sources = ogr.FieldDefn("sources", ogr.OFTString)
    sources.SetSubType(ogr.OFSTJSON)
    layer.CreateField(sources)
    for name, kind in (("class", ogr.OFTString), ("subtype", ogr.OFTString), ("height", ogr.OFTReal),
                       ("num_floors", ogr.OFTInteger)):
        layer.CreateField(ogr.FieldDefn(name, kind))
    for (dx, dy), side, dataset, confidence, year, klass in BUILDINGS:
        x, y, h = CENTRE[0] + dx, CENTRE[1] + dy, side / 2
        ring = ogr.Geometry(ogr.wkbLinearRing)
        for px, py in ((x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h), (x - h, y - h)):
            ring.AddPoint_2D(*to_lonlat.TransformPoint(px, py)[:2])
        polygon = ogr.Geometry(ogr.wkbPolygon)
        polygon.AddGeometry(ring)
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(polygon)
        feature.SetField("sources", json.dumps([{"dataset": dataset, "confidence": confidence,
                                                 "update_time": f"{year}-05-01T00:00:00.000Z"}]))
        if klass:
            feature.SetField("class", klass)
            feature.SetField("num_floors", 2)
        layer.CreateFeature(feature)
    datasource = None
    return str(path)


def _read(path):
    datasource = ogr.Open(path)
    return sorted((f.GetField("source"), round(f.GetField("area_m2")), f.GetField("year"), f.GetField("class"))
                  for f in datasource.GetLayer(0))


def test_overture_buildings_of_the_zone(tmp_path, monkeypatch):
    local = _parquet(tmp_path / "part-00000.parquet")
    elsewhere = str(tmp_path / "part-00001.parquet")                  # never opened: its box is far away
    index = {"release": "test", "files": [[local, 29.0, -4.0, 30.0, -3.0], [elsewhere, -80.0, 40.0, -70.0, 45.0]]}
    monkeypatch.setattr(overture, "load_index", lambda *args: (index, "plugin"))
    zone = DownloadZone.from_layers(ZoneLayer(_square_layer(tmp_path / "zone.gpkg", 1000)), UTM35S)
    output = str(tmp_path / "overture.gpkg")
    steps, stages = [], []
    report = overture.download_overture(zone, output, release="test", progress=steps.append,
                                        stage=lambda key, **values: stages.append(key))
    assert report["index"] == "plugin" and report["files"] == [f"{overture.BUCKET}/{local}"]
    assert stages[0] == "download.stage.index" and "download.stage.read" in stages
    assert _read(output) == [("google", 64, 2023, None), ("google", 100, 2023, None),
                             ("microsoft", 144, 2021, None), ("osm", 400, 2015, "hospital")]
    assert report["counts"]["kept"] == 4 and report["counts"]["read"] == 4     # the far one is not even read
    assert report["by_source"] == {"google": 2, "microsoft": 1, "osm": 1} and report["imagery_year"] == 2023
    assert "ODbL" in report["licence"] and steps[-1] == 1.0
    with open(report_path(output), encoding="utf-8") as handle:
        assert json.load(handle)["release"] == "test"

    # the threshold only applies to the sources that give a confidence; sources can be left out
    report = overture.download_overture(zone, output, release="test", min_confidence=0.8,
                                        datasets=["Google Open Buildings", "OpenStreetMap"], kind="polygons")
    assert [row[0] for row in _read(output)] == ["google", "osm"]
    assert report["counts"]["low_confidence"] == 1 and report["counts"]["other_source"] == 1
    datasource = ogr.Open(output)
    assert datasource.GetLayer(0).GetGeomType() == ogr.wkbMultiPolygon


def test_index_is_built_once_then_found_in_the_cache(tmp_path, monkeypatch):
    local = _parquet(tmp_path / "part-00000.parquet")
    monkeypatch.setattr(overture, "release_files", lambda *args: [(local, 1)])
    monkeypatch.setattr(overture, "online_releases", lambda fetcher: ["2026-08-19.0", "2099-01-01.0"])
    monkeypatch.setattr(overture, "INDEX_DIR", str(tmp_path / "none"))

    class Offline:
        proxy = None

        def text(self, url):
            raise IOError("offline")

    assert overture.choose_release(Offline(), str(tmp_path)) == ("2099-01-01.0", None, "")
    zone = DownloadZone.from_layers(ZoneLayer(_square_layer(tmp_path / "zone.gpkg", 1000)), UTM35S)
    report = overture.download_overture(zone, str(tmp_path / "o.gpkg"), str(tmp_path), Offline())
    assert report["index"] == "built" and report["release"] == "2099-01-01.0" and report["counts"]["kept"] == 4
    index, place = overture.load_index(Offline(), "2099-01-01.0", str(tmp_path))
    assert place == "cache" and index["files"][0][0] == local
    west, south, east, north = index["files"][0][1:]
    assert 29.5 < west < east < 29.9 and -3.4 < south < north < -3.2   # the box of the buildings written
    with pytest.raises(overture.DownloadCancelled):
        overture.build_index(Offline(), "2099-01-01.0", cancelled=lambda: True)


def test_published_indexes_cover_the_releases_with_boxes():
    names = sorted(os.listdir(overture.INDEX_DIR))
    assert names and all(n.endswith(".json") for n in names)
    with open(os.path.join(overture.INDEX_DIR, names[-1]), encoding="utf-8") as handle:
        index = json.load(handle)
    assert len(index["files"]) > 100
    burundi = overture.files_in_zone(index, (29.0, -4.5, 30.9, -2.3))
    assert 1 <= len(burundi) <= 6                                     # 5 files for the whole country


def test_release_listing_is_read_and_kept(tmp_path):
    class Listing:
        calls = 0

        def text(self, url):
            Listing.calls += 1
            if "delimiter" in url:
                return ('<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                        "<CommonPrefixes><Prefix>release/2026-08-19.0/</Prefix></CommonPrefixes>"
                        "<CommonPrefixes><Prefix>release/2026-09-23.1/</Prefix></CommonPrefixes></ListBucketResult>")
            return ('<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                    "<Contents><Key>release/x/a.parquet</Key><Size>10</Size></Contents>"
                    "<Contents><Key>release/x/_SUCCESS</Key><Size>0</Size></Contents></ListBucketResult>")

    assert overture.latest_release(Listing()) == "2026-09-23.1"
    assert overture.release_files(Listing(), "2026-09-23.1", str(tmp_path)) == [("release/x/a.parquet", 10)]
    calls = Listing.calls
    assert overture.release_files(Listing(), "2026-09-23.1", str(tmp_path)) == [("release/x/a.parquet", 10)]
    assert Listing.calls == calls                                    # from the cache the second time


@pytest.mark.skipif(not os.environ.get("POPLAR_NET_TEST"), reason="needs the internet (set POPLAR_NET_TEST=1)")
def test_muramvya_from_overture(tmp_path):
    zone = DownloadZone.from_layers(ZoneLayer(os.path.join(MURAMVYA, "commune_muramvya.shp")), UTM35S)
    report = overture.download_overture(zone, str(tmp_path / "overture.gpkg"), cache_folder=str(tmp_path))
    assert 38_000 < report["counts"]["kept"] < 41_000
    assert set(report["by_source"]) >= {"google", "microsoft"}
