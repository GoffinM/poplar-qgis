"""Download speed test: Overture (Amazon S3, us-west-2) against Google Open Buildings.

In the QGIS Python console:
    exec(open(r"C:/chemin/vers/test_debit.py", encoding="utf-8").read())

It reads 16 MB of the Overture file that covers Muramvya, once in a single request and once in
eight parallel requests, and 16 MB of the Google tile, then prints the speed of each. Nothing is saved.
"""
import concurrent.futures
import time
import urllib.request

OVERTURE = ("https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/2026-09-23.1/theme=buildings/"
            "type=building/part-00149-19d2ca6d-fff8-5bfe-84c9-c14b8030a481-c000.zstd.parquet")
GOOGLE = "https://storage.googleapis.com/open-buildings-data/v3/points_s2_level_6_gzip_no_header/19c3_buildings.csv.gz"
START = 409108480            # a part of the file that Poplar really reads for Muramvya
SIZE = 16 * 1024 * 1024


def _get(url, first, last):
    request = urllib.request.Request(url, headers={"Range": f"bytes={first}-{last}"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return len(response.read())


def _measure(label, url, start, streams):
    part = SIZE // streams
    ranges = [(start + i * part, start + (i + 1) * part - 1) for i in range(streams)]
    began = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(streams) as pool:
        received = sum(pool.map(lambda r: _get(url, *r), ranges))
    seconds = time.perf_counter() - began
    print(f"{label:<32} {received / 1e6:5.1f} Mo en {seconds:6.1f} s  = {received / 1e6 / seconds:5.2f} Mo/s")


for label, url, start, streams in (("Overture, 1 requête", OVERTURE, START, 1),
                                   ("Overture, 8 requêtes en parallèle", OVERTURE, START, 8),
                                   ("Google, 1 requête", GOOGLE, 0, 1)):
    try:
        _measure(label, url, start, streams)
    except Exception as error:  # report and go on with the next test
        print(f"{label:<32} échec : {error}")
