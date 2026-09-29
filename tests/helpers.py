"""Small builders for synthetic test data."""

import numpy as np

from engine.grid import rectangle
from engine.raster_io import Raster


def uniform_raster(wkt, x0, y0, pixel, ncols, nrows, value):
    values = np.full((nrows, ncols), float(value))
    return Raster(values, (x0, pixel, 0.0, y0, 0.0, -pixel), wkt)


def square(xmin, ymin, xmax, ymax):
    return rectangle(xmin, ymin, xmax, ymax)
