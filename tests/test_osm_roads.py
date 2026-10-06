"""Download of OpenStreetMap roads through Overpass: query, classes, cut by the zone, report (answers simulated)."""

import json
import os
import urllib.error
import urllib.parse

import pytest
from osgeo import ogr

from engine.__main__ import main
from engine.downloads.fetch import DownloadCancelled
from engine.downloads.osm_roads import (
    LAYER, OverpassError, download_osm_roads, query, report_path, road_class,
)
from engine.downloads.zone import DownloadZone, ZoneLayer
from test_downloads import CENTRE, UTM35S, _lonlat, _square

X, Y = CENTRE


def _osm(ways, remark=None):
    """OSM XML with one node per point and one way per line: [(tags, [(x, y) in UTM 35 S])]."""
    nodes, body, ident = [], [], 1
    for number, (tags, points) in enumerate(ways, start=1):
        refs = []
        for lon, lat in _lonlat(points):
            nodes.append(f'<node id="{ident}" lat="{lat:.8f}" lon="{lon:.8f}" version="1"/>')
            refs.append(f'<nd ref="{ident}"/>')
            ident += 1
        tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        body.append(f'<way id="{100 + number}" version="1">{"".join(refs)}{tag_xml}</way>')
    tail = f"<remark>{remark}</remark>" if remark else ""
    return ('<?xml version="1.0" encoding="UTF-8"?><osm version="0.6" generator="Overpass API">'
            + "".join(nodes) + "".join(body) + tail + "</osm>")


WAYS = [
    ({"highway": "primary", "ref": "RN7", "name": "Route nationale 7", "surface": "asphalt"},
     [(X - 3000, Y), (X + 3000, Y)]),                                    # crosses the zone: cut at 2 km
    ({"highway": "tertiary"}, [(X, Y - 500), (X, Y + 500)]),
    ({"highway": "track"}, [(X - 500, Y + 500), (X + 500, Y + 500)]),
    ({"highway": "residential"}, [(X + 5000, Y + 5000), (X + 6000, Y + 5000)]),  # outside the zone
    ({"highway": "proposed"}, [(X - 200, Y - 200), (X + 200, Y - 200)]),         # not built
    ({"waterway": "river"}, [(X - 800, Y - 800), (X + 800, Y - 800)]),          # not a road
]


class FakeOverpass:
    """Answers with ``content``; the servers in ``refusing`` answer HTTP 429 (too many requests)."""

    def __init__(self, content, refusing=()):
        self.content, self.refusing, self.calls = content.encode(), set(refusing), []

    def fetch(self, url, path, progress=None, cancelled=None):
        self.calls.append(url)
        server = url.split("?")[0]
        if server in self.refusing:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        with open(path, "wb") as handle:
            handle.write(self.content)
        if cancelled is not None and cancelled():
            raise DownloadCancelled(url)
        if progress is not None:
            progress(len(self.content), None)


def _zone(tmp_path):
    return DownloadZone.from_layers(ZoneLayer(_square(tmp_path / "strata.gpkg", CENTRE, 1000)), UTM35S)


def _read(output):
    datasource = ogr.Open(output)
    layer = datasource.GetLayer(LAYER)
    return {f.GetField("highway"): (f.GetField("classe"), f.GetField("longueur_m"), f.GetField("ref"),
                                    f.GetField("nom"), f.GetField("surface")) for f in layer}


def test_classes_of_the_roads():
    assert road_class("trunk") == "nationale" and road_class("primary_link") == "nationale"
    assert road_class("secondary") == "provinciale" and road_class("tertiary") == "provinciale"
    assert road_class("track") == "autre" and road_class("path") == "autre" and road_class(None) == "autre"


def test_query_asks_every_highway_of_the_bounding_box(tmp_path):
    text = query(_zone(tmp_path))
    assert '[out:xml]' in text and 'way["highway"](-3.' in text and "(._;>;);out body;" in text


def test_roads_of_the_zone_are_cut_classed_and_reported(tmp_path):
    zone = _zone(tmp_path)
    fetcher = FakeOverpass(_osm(WAYS))
    output = str(tmp_path / "routes" / "osm.gpkg")
    steps = []
    report = download_osm_roads(zone, output, fetcher, servers=["https://a/api", "https://b/api"],
                                progress=steps.append)
    roads = _read(output)
    assert set(roads) == {"primary", "tertiary", "track"}
    assert roads["primary"][:5] == ("nationale", pytest.approx(2000, abs=1), "RN7", "Route nationale 7", "asphalt")
    assert roads["tertiary"][:2] == ("provinciale", pytest.approx(1000, abs=1))
    assert roads["track"][0] == "autre"
    assert report["counts"]["read"] == 5 and report["counts"]["not_roads"] == 1
    assert report["counts"]["outside_zone"] == 1 and report["counts"]["kept"] == 3
    assert report["counts"]["length_km"]["nationale"] == pytest.approx(2.0, abs=0.01)
    assert steps[-1] == 1.0 and steps == sorted(steps)
    saved = json.load(open(report_path(output), encoding="utf-8"))
    assert saved["server"] == "https://a/api" and "ODbL" in saved["licence"]
    assert saved["attribution"] == "© OpenStreetMap contributors"
    assert urllib.parse.parse_qs(urllib.parse.urlparse(fetcher.calls[0]).query)["data"][0] == saved["query"]
    assert sorted(os.listdir(tmp_path / "routes")) == ["osm.download.json", "osm.gpkg"]     # no .osm left


def test_a_busy_server_hands_over_to_the_next(tmp_path):
    fetcher = FakeOverpass(_osm(WAYS), refusing={"https://a/api"})
    report = download_osm_roads(_zone(tmp_path), str(tmp_path / "osm.gpkg"), fetcher,
                                servers=["https://a/api", "https://b/api"])
    assert report["server"] == "https://b/api" and len(fetcher.calls) == 2


def test_refusals_and_overpass_errors_are_explained_and_keep_the_roads_already_there(tmp_path):
    output = str(tmp_path / "osm.gpkg")
    download_osm_roads(_zone(tmp_path), output, FakeOverpass(_osm(WAYS)), servers=["https://a/api"])
    with pytest.raises(OverpassError) as error:
        download_osm_roads(_zone(tmp_path), output, FakeOverpass(_osm(WAYS), refusing={"https://a/api"}),
                           servers=["https://a/api"])
    assert "429" in str(error.value)
    with pytest.raises(OverpassError) as error:
        download_osm_roads(_zone(tmp_path), output, FakeOverpass(_osm([], remark="runtime error: Query timed out")),
                           servers=["https://a/api"])
    assert "timed out" in str(error.value)
    with pytest.raises(OverpassError):                                  # an HTML page instead of data
        download_osm_roads(_zone(tmp_path), output, FakeOverpass("<html>busy</html>"), servers=["https://a/api"])
    with pytest.raises(DownloadCancelled):
        download_osm_roads(_zone(tmp_path), output, FakeOverpass(_osm(WAYS)), servers=["https://a/api"],
                           cancelled=lambda: True)
    assert len(_read(output)) == 3                                      # the first roads are still there
    assert sorted(os.listdir(tmp_path)) == ["osm.download.json", "osm.gpkg", "strata.gpkg"]


def test_command_line(tmp_path, monkeypatch, capsys):
    import engine.downloads.osm_roads as osm_roads

    fetcher = FakeOverpass(_osm(WAYS))
    monkeypatch.setattr(osm_roads, "UrllibFetcher", lambda **kwargs: fetcher)
    zone = _square(tmp_path / "strata.gpkg", CENTRE, 1000)
    output = str(tmp_path / "routes.gpkg")
    assert main(["download-roads", zone, output, "--crs", "EPSG:32735"]) == 0
    assert "3" in capsys.readouterr().out and len(_read(output)) == 3


def test_requests_say_who_they_are():
    from engine import __version__
    from engine.downloads.fetch import UrllibFetcher

    agent = dict(UrllibFetcher()._opener.addheaders)["User-Agent"]
    assert agent.startswith(f"Poplar/{__version__}") and "Python-urllib" not in agent
