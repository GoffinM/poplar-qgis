"""Regular calculation grid, aligned on the origin of the base raster."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np
from osgeo import ogr

Extent = Tuple[float, float, float, float]  # xmin, ymin, xmax, ymax


@dataclass(frozen=True)
class Grid:
    """North-up grid of square cells.

    ``x0`` and ``y0`` are the coordinates of the top-left corner. Cells are
    numbered row by row from the north-west corner: ``cell_id = row * ncols + col``.
    """

    x0: float
    y0: float
    cell_size: float
    ncols: int
    nrows: int
    crs_wkt: str

    @classmethod
    def covering(
        cls,
        extent: Extent,
        cell_size: float,
        crs_wkt: str,
        origin: Tuple[float, float] = (0.0, 0.0),
    ) -> "Grid":
        """Smallest grid aligned on ``origin`` that covers ``extent``.

        ``origin`` is usually the top-left corner of the base raster, so that
        grid lines coincide with pixel edges whenever ``cell_size`` is a
        multiple of the pixel size.
        """
        if cell_size <= 0:
            raise ValueError("cell_size must be positive")
        xmin, ymin, xmax, ymax = extent
        ox, oy = origin
        first_col = math.floor((xmin - ox) / cell_size)
        first_row = math.floor((oy - ymax) / cell_size)
        last_col = math.ceil((xmax - ox) / cell_size)
        last_row = math.ceil((oy - ymin) / cell_size)
        return cls(
            x0=ox + first_col * cell_size,
            y0=oy - first_row * cell_size,
            cell_size=float(cell_size),
            ncols=max(last_col - first_col, 1),
            nrows=max(last_row - first_row, 1),
            crs_wkt=crs_wkt,
        )

    @property
    def geotransform(self) -> Tuple[float, float, float, float, float, float]:
        return (self.x0, self.cell_size, 0.0, self.y0, 0.0, -self.cell_size)

    @property
    def cell_area_km2(self) -> float:
        return self.cell_size * self.cell_size / 1e6

    @property
    def ncells(self) -> int:
        return self.ncols * self.nrows

    def locate(self, x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Row and column of each point, and a mask of the points inside the grid."""
        col = np.floor((np.asarray(x, dtype=np.float64) - self.x0) / self.cell_size).astype(np.int64)
        row = np.floor((self.y0 - np.asarray(y, dtype=np.float64)) / self.cell_size).astype(np.int64)
        inside = (col >= 0) & (col < self.ncols) & (row >= 0) & (row < self.nrows)
        return row, col, inside

    def cell_bounds(self, row: int, col: int) -> Extent:
        xmin = self.x0 + col * self.cell_size
        ymax = self.y0 - row * self.cell_size
        return (xmin, ymax - self.cell_size, xmin + self.cell_size, ymax)

    def cell_geometry(self, row: int, col: int) -> ogr.Geometry:
        return rectangle(*self.cell_bounds(row, col))

    def cell_center(self, row: int, col: int) -> Tuple[float, float]:
        xmin, ymin, xmax, ymax = self.cell_bounds(row, col)
        return ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)


def rectangle(xmin: float, ymin: float, xmax: float, ymax: float) -> ogr.Geometry:
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in ((xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax), (xmin, ymin)):
        ring.AddPoint_2D(x, y)
    polygon = ogr.Geometry(ogr.wkbPolygon)
    polygon.AddGeometry(ring)
    return polygon
