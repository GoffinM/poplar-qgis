"""Build data/test/muramvya/buildings_muramvya.gpkg from the legacy calibration workbooks.

Development tool only: it needs openpyxl, which is not a dependency of the
engine. The workbooks in legacy/calage/ are read, never modified.

Usage: python tools/extract_legacy_buildings.py
"""

import os
import sys

import openpyxl
from osgeo import ogr, osr

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = {
    "Rural": os.path.join(REPO, "legacy", "calage", "demand_conso_Muramvya-Rural.xlsx"),
    "Urbain": os.path.join(REPO, "legacy", "calage", "demand_conso_Muramvya-Urbain.xlsx"),
}
TARGET = os.path.join(REPO, "data", "test", "muramvya", "buildings_muramvya.gpkg")


def main() -> int:
    ogr.UseExceptions()
    osr.UseExceptions()
    if os.path.exists(TARGET):
        os.remove(TARGET)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32735)
    datasource = ogr.GetDriverByName("GPKG").CreateDataSource(TARGET)
    layer = datasource.CreateLayer("buildings", srs, ogr.wkbPoint)
    for name, kind in (("source_id", ogr.OFTString), ("stratum", ogr.OFTString),
                       ("area_m2", ogr.OFTReal), ("legacy_pop", ogr.OFTReal)):
        layer.CreateField(ogr.FieldDefn(name, kind))
    layer.StartTransaction()
    count = 0
    for stratum, path in SOURCES.items():
        sheet = openpyxl.load_workbook(path, data_only=True, read_only=True)["Donnees_SIG"]
        for row in sheet.iter_rows(min_row=2, max_col=11, values_only=True):
            if row[2] is None:
                continue
            feature = ogr.Feature(layer.GetLayerDefn())
            point = ogr.Geometry(ogr.wkbPoint)
            point.AddPoint_2D(float(row[4]), float(row[5]))
            feature.SetGeometry(point)
            feature.SetField("source_id", str(row[1]))
            feature.SetField("stratum", stratum)
            feature.SetField("area_m2", float(row[2]))
            feature.SetField("legacy_pop", float(row[10]))
            layer.CreateFeature(feature)
            count += 1
    layer.CommitTransaction()
    datasource = None
    print(f"{count} buildings written to {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
