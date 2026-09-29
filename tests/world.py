"""Synthetic data sets written to disk, for end-to-end tests of the simulation."""

import json
import os

import numpy as np
from osgeo import ogr

from engine._gdal import srs_from_epsg
from engine.raster_io import write_raster
from helpers import square

X0, Y0 = 500_000.0, 9_600_000.0


def write_polygons(path, polygons, field="name"):
    """polygons: list of (geometry, value)."""
    if os.path.exists(path):
        os.remove(path)
    datasource = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    layer = datasource.CreateLayer("layer", srs_from_epsg(32735), ogr.wkbUnknown)
    layer.CreateField(ogr.FieldDefn(field, ogr.OFTString))
    for geometry, value in polygons:
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(geometry)
        feature.SetField(field, str(value))
        layer.CreateFeature(feature)
    datasource = None
    return path


def box(c0, r0, c1, r1, cell=100.0):
    """Rectangle covering columns c0..c1 and rows r0..r1 (exclusive) of a grid anchored at X0, Y0."""
    return square(X0 + c0 * cell, Y0 - r1 * cell, X0 + c1 * cell, Y0 - r0 * cell)


def make_world(directory, density, cell=100.0, zones=None, exclusions=(), admin=None, **overrides):
    """Write a raster of ``density`` (hab/km2, rows x cols) and vector layers; return the scenario dict."""
    os.makedirs(directory, exist_ok=True)
    rows, cols = density.shape
    write_raster(os.path.join(directory, "density.tif"), density.astype(float),
                 (X0, cell, 0.0, Y0, 0.0, -cell), srs_from_epsg(32735).ExportToWkt())
    whole = box(0, 0, cols, rows, cell)
    write_polygons(os.path.join(directory, "study.gpkg"), [(whole, "study")])
    write_polygons(os.path.join(directory, "zones.gpkg"), zones or [(whole, "Rural")], field="type")
    scenario = {
        "name": "synthetic",
        "cell_size": cell,
        "study_area": {"source": "study.gpkg"},
        "typology": {"source": "zones.gpkg", "field": "type"},
        "base_population": {"raster": "density.tif"},
        "time": {"base_year": 2024, "end_year": 2030, "time_step": 1, "first_migration_year": 2025},
        "parameters": {"growth_rate": 2.0, "dmax": 10000},
        "output": {"directory": "out"},
    }
    exclusion_specs = []
    for i, (name, geometry, behaviour, year) in enumerate(exclusions):
        path = write_polygons(os.path.join(directory, f"exclusion_{i}.gpkg"), [(geometry, name)])
        exclusion_specs.append({"name": name, "source": os.path.basename(path), "behaviour": behaviour, "year": year})
    if exclusion_specs:
        scenario["exclusions"] = exclusion_specs
    if admin:
        write_polygons(os.path.join(directory, "admin.gpkg"), admin, field="admin")
        scenario["admin_units"] = {"source": "admin.gpkg", "field": "admin"}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(scenario.get(key), dict):
            scenario[key] = {**scenario[key], **value}
        else:
            scenario[key] = value
    path = os.path.join(directory, "scenario.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(scenario, handle)
    return path
