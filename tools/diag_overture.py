"""Overture diagnosis: how much does GDAL download, in how many requests, for Muramvya?

In the QGIS Python console:
    exec(open(r"C:/chemin/vers/diag_overture.py", encoding="utf-8").read())

It reads the Muramvya buildings exactly as Poplar does and prints the GDAL and Arrow versions, the
time taken, the number of HTTP requests and the megabytes received. Nothing is saved apart from a
GDAL log in the temporary folder.
"""
import os
import tempfile
import time

from osgeo import gdal, ogr

URL = ("/vsicurl/https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/2026-09-23.1/"
       "theme=buildings/type=building/part-00149-19d2ca6d-fff8-5bfe-84c9-c14b8030a481-c000.zstd.parquet")
BOUNDS = (29.5218, -3.3889, 29.7883, -3.1450)      # Muramvya and a 1 km margin, in degrees

driver = gdal.GetDriverByName("Parquet")
print("GDAL", gdal.VersionInfo("RELEASE_NAME"), "– Arrow", driver.GetMetadataItem("ARROW_VERSION") if driver else "absent")
log = os.path.join(tempfile.gettempdir(), "poplar_diag_overture.log")
if os.path.exists(log):
    os.remove(log)
settings = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_DEBUG": "ON", "CPL_LOG": log}
previous = {key: gdal.GetConfigOption(key) for key in settings}
for key, value in settings.items():
    gdal.SetConfigOption(key, value)
began = time.perf_counter()
try:
    source = ogr.Open(URL)
    layer = source.GetLayer(0)
    layer.SetSpatialFilterRect(*BOUNDS)
    count = sum(1 for _ in layer)
    layer = source = None
finally:
    for key, value in previous.items():
        gdal.SetConfigOption(key, value)
seconds = time.perf_counter() - began
sizes = []
with open(log, encoding="utf-8", errors="replace") as handle:
    for line in handle:
        if "VSICURL: Downloading" in line:
            first, last = line.split("Downloading ")[1].split(" ")[0].split("-")
            sizes.append(int(last) - int(first) + 1)
print(f"{count} bâtiments, {seconds:.1f} s, {len(sizes)} requêtes, {sum(sizes) / 1e6:.1f} Mo reçus")
print("Ici (Arrow 22) : 105 867 bâtiments, 7 s, 10 requêtes, 51 Mo")
