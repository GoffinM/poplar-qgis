import os

import pytest

from engine._gdal import srs_from_epsg

from paths import MURAMVYA, REFERENCE, REPO  # noqa: F401


@pytest.fixture(scope="session")
def utm35s_wkt():
    return srs_from_epsg(32735).ExportToWkt()


@pytest.fixture(scope="session")
def muramvya_case():
    """Raster, grid and units of Muramvya: commune typology, forest as no-inflow zone."""
    from engine.grid import Grid
    from engine.raster_io import read_raster
    from engine.units import Zone, build_units
    from engine.vector_io import read_features, union_all

    raster = read_raster(os.path.join(MURAMVYA, "pop2023_muramvya.tif"))
    communes = read_features(os.path.join(MURAMVYA, "commune_muramvya.shp"), target_crs_wkt=raster.crs_wkt)
    forest = read_features(os.path.join(MURAMVYA, "zone_sans_migration.shp"), target_crs_wkt=raster.crs_wkt)
    study = union_all(f.geometry for f in communes)
    xmin, xmax, ymin, ymax = study.GetEnvelope()
    grid = Grid.covering(
        (xmin, ymin, xmax, ymax), 250, raster.crs_wkt, origin=(raster.geotransform[0], raster.geotransform[3])
    )
    zones = [Zone(f.geometry, f.attributes["Type"]) for f in communes]
    units = build_units(grid, study, zones, union_all(f.geometry for f in forest))
    return raster, grid, units
