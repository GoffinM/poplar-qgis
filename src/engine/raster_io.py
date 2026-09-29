"""Raster reading and writing with GDAL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from osgeo import gdal

from ._gdal import gdal_exceptions

GeoTransform = Tuple[float, float, float, float, float, float]


@dataclass
class Raster:
    """A single-band raster held in memory.

    ``values`` is float64 with NaN where the source is nodata, so that
    sums and comparisons never pick up nodata sentinels.
    """

    values: np.ndarray
    geotransform: GeoTransform
    crs_wkt: str

    @property
    def nrows(self) -> int:
        return self.values.shape[0]

    @property
    def ncols(self) -> int:
        return self.values.shape[1]

    @property
    def pixel_width(self) -> float:
        return self.geotransform[1]

    @property
    def pixel_height(self) -> float:
        """Positive pixel height (the geotransform stores it as a negative value)."""
        return -self.geotransform[5]

    @property
    def pixel_area_m2(self) -> float:
        return self.pixel_width * self.pixel_height


def read_raster(path: str, band: int = 1) -> Raster:
    with gdal_exceptions():
        dataset = gdal.Open(path, gdal.GA_ReadOnly)
        geotransform = dataset.GetGeoTransform()
        if geotransform[2] != 0 or geotransform[4] != 0:
            raise ValueError(f"{path}: rotated rasters are not supported")
        if geotransform[5] >= 0:
            raise ValueError(f"{path}: north-up rasters are required (negative pixel height)")
        raster_band = dataset.GetRasterBand(band)
        values = raster_band.ReadAsArray().astype(np.float64)
        nodata = raster_band.GetNoDataValue()
        if nodata is not None:
            values[values == nodata] = np.nan
        values[~np.isfinite(values)] = np.nan
        return Raster(values, tuple(geotransform), dataset.GetProjection())


def write_raster(
    path: str,
    values: np.ndarray,
    geotransform: GeoTransform,
    crs_wkt: str,
    nodata: Optional[float] = None,
    dtype: int = gdal.GDT_Float32,
) -> None:
    """Write a single-band compressed GeoTIFF. NaN values are written as ``nodata``."""
    with gdal_exceptions():
        driver = gdal.GetDriverByName("GTiff")
        nrows, ncols = values.shape
        dataset = driver.Create(
            path, ncols, nrows, 1, dtype, options=["COMPRESS=DEFLATE", "TILED=YES"]
        )
        dataset.SetGeoTransform(geotransform)
        dataset.SetProjection(crs_wkt)
        band = dataset.GetRasterBand(1)
        data = values
        if nodata is not None:
            band.SetNoDataValue(nodata)
            data = np.where(np.isnan(values), nodata, values)
        band.WriteArray(data)
        band.FlushCache()
        dataset = None
