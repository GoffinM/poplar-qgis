"""GDAL helpers shared by the engine modules."""

from __future__ import annotations

import contextlib
from typing import Iterator

from osgeo import gdal, ogr, osr


@contextlib.contextmanager
def gdal_exceptions() -> Iterator[None]:
    """Enable GDAL/OGR/OSR exceptions locally, without changing the global state.

    QGIS and other plugins share the same GDAL bindings, so the engine never
    calls ``UseExceptions()`` globally.
    """
    with contextlib.ExitStack() as stack:
        for module in (gdal, ogr, osr):
            stack.enter_context(module.ExceptionMgr(useExceptions=True))
        yield


def srs_from_wkt(wkt: str) -> osr.SpatialReference:
    """Build a spatial reference with the traditional GIS axis order (x = east)."""
    with gdal_exceptions():
        srs = osr.SpatialReference()
        srs.ImportFromWkt(wkt)
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        return srs


def srs_from_epsg(code: int) -> osr.SpatialReference:
    with gdal_exceptions():
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(code)
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        return srs
