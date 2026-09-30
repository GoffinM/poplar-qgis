"""Overture diagnosis: how long does GDAL alone take to read the Muramvya buildings?

In the QGIS Python console:
    exec(open(r"C:/chemin/vers/diag_overture.py", encoding="utf-8").read())

It reads the Muramvya buildings as Poplar does, without Poplar's own processing, and prints the GDAL and
Arrow versions and the time taken. Nothing is saved. Poplar's full download adds the processing of each
building (about 6 s here since 0.7.2).
"""
import time

from osgeo import gdal, ogr

URL = ("/vsicurl/https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/2026-09-23.1/"
       "theme=buildings/type=building/part-00149-19d2ca6d-fff8-5bfe-84c9-c14b8030a481-c000.zstd.parquet")
BOUNDS = (29.5218, -3.3889, 29.7883, -3.1450)      # Muramvya and a 1 km margin, in degrees

driver = gdal.GetDriverByName("Parquet")
print("GDAL", gdal.VersionInfo("RELEASE_NAME"), "– Arrow", driver.GetMetadataItem("ARROW_VERSION") if driver else "absent")
settings = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"}
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
print(f"{count} bâtiments lus par GDAL en {seconds:.1f} s (51 Mo à télécharger)")
print("Ici : 105 867 bâtiments en 6 s, à environ 10 Mo/s")
