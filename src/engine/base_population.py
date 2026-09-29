"""Base population of each unit from a population density raster (spec §3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np
from scipy import sparse

from ._gdal import gdal_exceptions, srs_from_wkt
from .grid import rectangle
from .parameters import to_hab_per_km2
from .raster_io import Raster
from .units import Units
from .vector_io import polygonal_part

AREA_WEIGHTED = "area_weighted"
RENORMALIZED = "renormalized"


@dataclass
class BasePopulationReport:
    """Population balance of the raster against the calculation domain."""

    raster_population_touching: float
    """Population of every pixel that overlaps at least one unit."""
    allocated_population: float
    """Population given to the units (the rest lies in pixel parts outside the domain)."""
    nodata_area_km2: float
    boundary_mode: str


def base_population_from_density(
    units: Units,
    raster: Raster,
    density_unit: str = "hab/km2",
    boundary_mode: str = AREA_WEIGHTED,
) -> Tuple[np.ndarray, BasePopulationReport]:
    """Population of each unit, from the overlap between units and pixels.

    ``area_weighted``: a unit receives density x overlap area. The population
    of pixel parts lying outside the domain is not counted.

    ``renormalized``: the whole population of a pixel is shared among the
    units that cover it, in proportion to their overlap. Use it when the
    raster was built only from buildings inside the domain (as for the
    current BUR71 raster), so that boundary pixels lose nobody.

    Nodata pixels count as zero population; their area is reported.
    """
    if boundary_mode not in (AREA_WEIGHTED, RENORMALIZED):
        raise ValueError(f"unknown boundary_mode: {boundary_mode}")
    with gdal_exceptions():
        if not srs_from_wkt(raster.crs_wkt).IsSame(srs_from_wkt(units.grid.crs_wkt)):
            raise ValueError("the raster and the grid must share the same coordinate system")
    density = to_hab_per_km2(raster.values, density_unit)
    nodata = np.isnan(density)
    density = np.where(nodata, 0.0, density)
    pixel_area_km2 = raster.pixel_area_m2 / 1e6

    wy, wx = _overlap_matrices(units, raster)
    whole = units.whole_cell
    whole_rows = units.row[whole]
    whole_cols = units.col[whole]
    split_idx, split_pix, split_m2 = _split_overlaps(units, raster)

    # Overlap (km2) of every pixel with the domain.
    whole_mask = np.zeros((units.grid.nrows, units.grid.ncols))
    whole_mask[whole_rows, whole_cols] = 1.0
    coverage = _product(wy.T, whole_mask, wx) / 1e6
    np.add.at(coverage.ravel(), split_pix, split_m2 / 1e6)
    touching = coverage > 0
    touching_population = float((density * pixel_area_km2)[touching].sum())

    effective = density
    if boundary_mode == RENORMALIZED:
        effective = np.zeros_like(density)
        effective[touching] = density[touching] * pixel_area_km2 / coverage[touching]

    population = np.zeros(len(units))
    cells = _product(wy, effective, wx.T) / 1e6
    population[whole] = cells[whole_rows, whole_cols]
    np.add.at(population, split_idx, effective.ravel()[split_pix] * split_m2 / 1e6)

    nodata_cells = _product(wy, nodata.astype(float), wx.T) / 1e6
    nodata_area = float(nodata_cells[whole_rows, whole_cols].sum())
    nodata_area += float((nodata.ravel()[split_pix] * split_m2).sum() / 1e6)
    report = BasePopulationReport(touching_population, float(population.sum()), nodata_area, boundary_mode)
    return population, report


def _product(left: sparse.spmatrix, dense: np.ndarray, right: sparse.spmatrix) -> np.ndarray:
    """``left @ dense @ right`` with sparse outer factors, as a dense array."""
    return np.ascontiguousarray((right.T @ (left @ dense).T).T)


def _overlap_matrices(units: Units, raster: Raster) -> Tuple[sparse.csr_matrix, sparse.csr_matrix]:
    """1D overlap lengths (m) between grid rows/columns and raster rows/columns.

    For rectangles, the overlap area of a cell with a pixel is the product of
    the overlaps along each axis, so a whole-cell sum is ``Wy @ D @ Wx.T``.
    """
    grid = units.grid
    gx = grid.x0 + grid.cell_size * np.arange(grid.ncols + 1)
    gy = grid.y0 - grid.cell_size * np.arange(grid.nrows + 1)
    rx = raster.geotransform[0] + raster.pixel_width * np.arange(raster.ncols + 1)
    ry = raster.geotransform[3] - raster.pixel_height * np.arange(raster.nrows + 1)
    wx = _overlap_1d(gx, rx)
    wy = _overlap_1d(-gy, -ry)
    return wy, wx


def _overlap_1d(a: np.ndarray, b: np.ndarray) -> sparse.csr_matrix:
    """Overlap lengths between consecutive intervals of two increasing edge arrays."""
    rows, cols, values = [], [], []
    for i in range(len(a) - 1):
        lo, hi = a[i], a[i + 1]
        first = max(np.searchsorted(b, lo, side="right") - 1, 0)
        last = min(np.searchsorted(b, hi, side="left"), len(b) - 1)
        for j in range(first, last):
            length = min(hi, b[j + 1]) - max(lo, b[j])
            if length > 0:
                rows.append(i)
                cols.append(j)
                values.append(length)
    return sparse.csr_matrix((values, (rows, cols)), shape=(len(a) - 1, len(b) - 1))


def _split_overlaps(units: Units, raster: Raster):
    """(unit index, flat pixel index, overlap m2) for every split unit."""
    x0, pw = raster.geotransform[0], raster.pixel_width
    y0, ph = raster.geotransform[3], raster.pixel_height
    idx, pix, area = [], [], []
    with gdal_exceptions():
        for i, geometry in units.geometries.items():
            xmin, xmax, ymin, ymax = geometry.GetEnvelope()
            raw_c0, raw_c1 = int(np.floor((xmin - x0) / pw)), int(np.ceil((xmax - x0) / pw))
            raw_r0, raw_r1 = int(np.floor((y0 - ymax) / ph)), int(np.ceil((y0 - ymin) / ph))
            c0, c1 = max(raw_c0, 0), min(raw_c1, raster.ncols)
            r0, r1 = max(raw_r0, 0), min(raw_r1, raster.nrows)
            # Fast path: the unit lies inside a single pixel of the raster.
            single = (raw_c0, raw_c1, raw_r0, raw_r1) == (c0, c0 + 1, r0, r0 + 1) and c1 == c0 + 1 and r1 == r0 + 1
            for r in range(r0, r1):
                for c in range(c0, c1):
                    if single:
                        overlap = geometry.GetArea()
                    else:
                        pixel = rectangle(x0 + c * pw, y0 - (r + 1) * ph, x0 + (c + 1) * pw, y0 - r * ph)
                        part = polygonal_part(geometry.Intersection(pixel))
                        overlap = part.GetArea() if part is not None else 0.0
                    if overlap > 0:
                        idx.append(i)
                        pix.append(r * raster.ncols + c)
                        area.append(overlap)
    return np.array(idx, dtype=np.int64), np.array(pix, dtype=np.int64), np.array(area, dtype=np.float64)
