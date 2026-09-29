"""Calculation coordinate system and reprojection of the population raster.

Every area and distance of the engine is computed in a projected CRS whose
unit is the metre. The input layers may use any CRS: they are reprojected
to the calculation CRS. A CRS in degrees is refused for the calculation.

Area checks rely on the authalic (equal-area) latitude of the WGS 84
ellipsoid, so that the true area of a shape on the ellipsoid can be
compared with its area in the calculation CRS.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from osgeo import gdal, osr

from ._gdal import gdal_exceptions, srs_from_epsg, srs_from_wkt
from .raster_io import Raster

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
_E2 = WGS84_F * (2 - WGS84_F)
_E = math.sqrt(_E2)

AUTO_UTM = "auto-utm"
AUTO_EQUAL_AREA = "auto-equal-area"
MAX_AREA_DISTORTION = 0.005
"""Largest acceptable area scale error (0.5 %) before suggesting an equal-area CRS."""


def _q(sin_phi):
    sin_phi = np.asarray(sin_phi, dtype=np.float64)
    es = _E * sin_phi
    return (1 - _E2) * (sin_phi / (1 - es * es) - np.log((1 - es) / (1 + es)) / (2 * _E))


_QP = float(_q(1.0))
AUTHALIC_RADIUS = WGS84_A * math.sqrt(_QP / 2)


def authalic_sine(lat_deg) -> np.ndarray:
    """Sine of the authalic latitude (equal-area mapping of the ellipsoid)."""
    return _q(np.sin(np.radians(lat_deg))) / _QP


def ellipsoid_area_m2(lon_deg: np.ndarray, lat_deg: np.ndarray) -> float:
    """Area on the WGS 84 ellipsoid of a small polygon given in degrees (closed or not)."""
    x = AUTHALIC_RADIUS * np.radians(np.asarray(lon_deg, dtype=np.float64))
    y = AUTHALIC_RADIUS * authalic_sine(lat_deg)
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2)


def band_area_km2(lat1_deg, lat2_deg, dlon_deg) -> np.ndarray:
    """Exact ellipsoidal area of a cell bounded by two parallels and ``dlon`` of longitude."""
    s1, s2 = authalic_sine(lat1_deg), authalic_sine(lat2_deg)
    return AUTHALIC_RADIUS ** 2 * np.radians(dlon_deg) * np.abs(s2 - s1) / 1e6


def is_metric_projected(wkt: str) -> bool:
    with gdal_exceptions():
        srs = srs_from_wkt(wkt)
        return bool(srs.IsProjected()) and abs(srs.GetLinearUnits() - 1.0) < 1e-9


def utm_wkt(lon: float, lat: float) -> str:
    zone = int(math.floor((lon + 180) / 6)) % 60 + 1
    return srs_from_epsg((32600 if lat >= 0 else 32700) + zone).ExportToWkt()


def equal_area_wkt(lon: float, lat: float) -> str:
    """Lambert azimuthal equal-area projection centred on the study area."""
    with gdal_exceptions():
        srs = osr.SpatialReference()
        srs.ImportFromProj4(f"+proj=laea +lat_0={lat:.4f} +lon_0={lon:.4f} +datum=WGS84 +units=m +no_defs")
        return srs.ExportToWkt()


def area_scale(crs_wkt: str, x: float, y: float, side: float = 1000.0) -> float:
    """Area in the CRS of a small square divided by its true area on the ellipsoid."""
    with gdal_exceptions():
        to_geo = osr.CoordinateTransformation(srs_from_wkt(crs_wkt), srs_from_epsg(4326))
        h = side / 2
        corners = [(x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h)]
        lonlat = np.array(to_geo.TransformPoints(corners))
    return side * side / ellipsoid_area_m2(lonlat[:, 0], lonlat[:, 1])


@dataclass
class CrsChoice:
    wkt: str
    source: str
    """How it was chosen: ``scenario``, ``raster``, ``auto-utm`` or ``auto-equal-area``."""
    max_area_distortion: float
    suggestion: Optional[str] = None
    """Equal-area CRS proposed when the distortion exceeds :data:`MAX_AREA_DISTORTION`."""


def choose_crs(requested: Optional[str], raster_wkt: str, lonlat_bounds: Tuple[float, float, float, float]) -> CrsChoice:
    """Calculation CRS (spec §3): the requested one, else the raster's if metric, else UTM.

    ``lonlat_bounds`` is the extent of the study area in WGS 84 degrees.
    Raises ValueError for a CRS that is not projected in metres.
    """
    lon_c = (lonlat_bounds[0] + lonlat_bounds[2]) / 2
    lat_c = (lonlat_bounds[1] + lonlat_bounds[3]) / 2
    if requested == AUTO_EQUAL_AREA:
        wkt, source = equal_area_wkt(lon_c, lat_c), AUTO_EQUAL_AREA
    elif requested == AUTO_UTM:
        wkt, source = utm_wkt(lon_c, lat_c), AUTO_UTM
    elif requested:
        with gdal_exceptions():
            srs = osr.SpatialReference()
            srs.SetFromUserInput(requested)
            wkt = srs.ExportToWkt()
        source = "scenario"
        if not is_metric_projected(wkt):
            raise ValueError(f"the calculation CRS must be projected in metres: {requested}")
    elif is_metric_projected(raster_wkt):
        wkt, source = raster_wkt, "raster"
    else:
        wkt, source = utm_wkt(lon_c, lat_c), AUTO_UTM
    distortion = max_area_distortion(wkt, lonlat_bounds)
    suggestion = equal_area_wkt(lon_c, lat_c) if distortion > MAX_AREA_DISTORTION else None
    return CrsChoice(wkt, source, distortion, suggestion)


def max_area_distortion(crs_wkt: str, lonlat_bounds: Tuple[float, float, float, float]) -> float:
    """Largest relative area error of the CRS over the corners, edges and centre of the extent."""
    with gdal_exceptions():
        to_crs = osr.CoordinateTransformation(srs_from_epsg(4326), srs_from_wkt(crs_wkt))
        lon0, lat0, lon1, lat1 = lonlat_bounds
        points = [(lon, lat) for lon in (lon0, (lon0 + lon1) / 2, lon1) for lat in (lat0, (lat0 + lat1) / 2, lat1)]
        projected = to_crs.TransformPoints(points)
    return max(abs(area_scale(crs_wkt, px, py) - 1.0) for px, py, *_ in projected)


def population_to_density(raster: Raster, value_type: str, density_factor: float = 1.0) -> Raster:
    """Density raster (hab/km2) from a density (scaled by ``density_factor``) or a count per pixel.

    For a raster in degrees, each row gets the true ellipsoidal area of its pixels.
    """
    if value_type == "density":
        return Raster(raster.values * density_factor, raster.geotransform, raster.crs_wkt)
    if value_type != "count":
        raise ValueError(f"unknown value type: {value_type!r} (expected 'density' or 'count')")
    return Raster(raster.values / pixel_areas_km2(raster), raster.geotransform, raster.crs_wkt)


def pixel_areas_km2(raster: Raster) -> np.ndarray:
    """Area of every pixel in km2 (a column vector broadcast over the rows for rasters in degrees)."""
    with gdal_exceptions():
        srs = srs_from_wkt(raster.crs_wkt)
        geographic = bool(srs.IsGeographic())
    if not geographic:
        if not is_metric_projected(raster.crs_wkt):
            raise ValueError("the population raster must be in degrees or in a CRS in metres")
        return np.full((raster.nrows, 1), raster.pixel_area_m2 / 1e6)
    top = raster.geotransform[3] - raster.pixel_height * np.arange(raster.nrows)
    return band_area_km2(top, top - raster.pixel_height, raster.pixel_width).reshape(-1, 1)


def reproject_density(raster: Raster, target_wkt: str, target_pixel_m: float) -> Tuple[Raster, float]:
    """Reproject a density raster (hab/km2) to the calculation CRS.

    Densities are resampled with an area-weighted average onto pixels no
    larger than the source pixels, so that the density field, and hence the
    population of any area, is preserved away from the raster edges.
    Returns the new raster and the ratio between the population of the new
    raster and that of the source raster (edge effects only).
    """
    nodata = -1.0
    with gdal_exceptions():
        source = gdal.GetDriverByName("MEM").Create("", raster.ncols, raster.nrows, 1, gdal.GDT_Float64)
        source.SetGeoTransform(raster.geotransform)
        source.SetProjection(raster.crs_wkt)
        band = source.GetRasterBand(1)
        band.WriteArray(np.where(np.isnan(raster.values), nodata, raster.values))
        band.SetNoDataValue(nodata)
        warped = gdal.Warp(
            "", source, format="MEM", dstSRS=target_wkt, xRes=target_pixel_m, yRes=target_pixel_m,
            resampleAlg="average", srcNodata=nodata, dstNodata=nodata, targetAlignedPixels=True,
        )
        values = warped.GetRasterBand(1).ReadAsArray().astype(np.float64)
        geotransform = warped.GetGeoTransform()
    values[values == nodata] = np.nan
    before = float(np.nansum(raster.values * pixel_areas_km2(raster)))
    after = float(np.nansum(values) * target_pixel_m * target_pixel_m / 1e6)
    return Raster(values, tuple(geotransform), target_wkt), (after / before if before > 0 else 1.0)


def native_pixel_m(raster: Raster) -> float:
    """Approximate pixel size in metres (mean over the raster for rasters in degrees)."""
    return float(math.sqrt(pixel_areas_km2(raster).mean() * 1e6))
