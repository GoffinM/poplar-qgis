"""S2 cells (Google's hierarchical grid on the sphere), enough to name the tiles of a dataset.

Pure Python port of the point → cell part of the S2 geometry library: a point
gives the cell containing it at any level, written as a hexadecimal token
(level 4: ``19d``, level 6: ``19c3``). Google Open Buildings splits its files by
these cells.
"""

from __future__ import annotations

import math
from typing import Iterable, List, Set, Tuple

MAX_LEVEL = 30
_SWAP, _INVERT = 1, 2
_POS_TO_IJ = ((0, 1, 3, 2), (0, 2, 3, 1), (3, 2, 0, 1), (3, 1, 0, 2))
_POS_TO_ORIENTATION = (_SWAP, 0, 0, _INVERT | _SWAP)
_LOOKUP_POS = [0] * 1024


def _init_lookup(level: int, i: int, j: int, orientation0: int, pos: int, orientation: int) -> None:
    if level == 4:
        _LOOKUP_POS[(((i << 4) + j) << 2) + orientation0] = (pos << 2) + orientation
        return
    level, i, j, pos = level + 1, i << 1, j << 1, pos << 2
    for k, ij in enumerate(_POS_TO_IJ[orientation]):
        _init_lookup(level, i + (ij >> 1), j + (ij & 1), orientation0, pos + k, orientation ^ _POS_TO_ORIENTATION[k])


for _orientation in range(4):
    _init_lookup(0, 0, 0, _orientation, 0, _orientation)


def _face_uv(x: float, y: float, z: float) -> Tuple[int, float, float]:
    ax, ay, az = abs(x), abs(y), abs(z)
    face = 0 if ax >= ay and ax >= az else (1 if ay >= az else 2)
    if (x, y, z)[face] < 0:
        face += 3
    if face == 0:
        return face, y / x, z / x
    if face == 1:
        return face, -x / y, z / y
    if face == 2:
        return face, -x / z, -y / z
    if face == 3:
        return face, z / x, y / x
    if face == 4:
        return face, z / y, -x / y
    return face, -y / z, -x / z


def _uv_to_st(u: float) -> float:
    return 0.5 * math.sqrt(1 + 3 * u) if u >= 0 else 1 - 0.5 * math.sqrt(1 - 3 * u)


def cell_id(lat: float, lon: float, level: int) -> int:
    """64-bit id of the cell of ``level`` containing the point (degrees)."""
    phi, theta = math.radians(lat), math.radians(lon)
    face, u, v = _face_uv(math.cos(phi) * math.cos(theta), math.cos(phi) * math.sin(theta), math.sin(phi))
    size = 1 << MAX_LEVEL
    i = min(size - 1, max(0, int(size * _uv_to_st(u))))
    j = min(size - 1, max(0, int(size * _uv_to_st(v))))
    n = face << 60
    bits = face & _SWAP
    for k in range(7, -1, -1):
        bits += ((i >> (k * 4)) & 15) << 6
        bits += ((j >> (k * 4)) & 15) << 2
        bits = _LOOKUP_POS[bits]
        n |= (bits >> 2) << (k * 8)
        bits &= _SWAP | _INVERT
    lsb = 1 << (2 * (MAX_LEVEL - level))
    return ((n * 2 + 1) & -lsb) | lsb


def token(cell: int) -> str:
    """Hexadecimal token of a cell id (trailing zeros removed)."""
    return format(cell, "016x").rstrip("0")


def cell_token(lat: float, lon: float, level: int) -> str:
    return token(cell_id(lat, lon, level))


def _steps(low: float, high: float, step: float) -> Iterable[float]:
    count = max(1, int(math.ceil((high - low) / step)))
    return (low + (high - low) * k / count for k in range(count + 1))


def covering_tokens(lonlat_bounds: Tuple[float, float, float, float], level: int,
                    step: float = 0.01, edge_step: float = 0.001) -> List[str]:
    """Tokens of the cells meeting a longitude/latitude box.

    The box is sampled on a grid (``step`` degrees, about 1 km) and along its
    edges (``edge_step``, about 100 m). Cells of level 6 are about 100 km wide,
    so a cell is missed only if it touches the box on a sliver narrower than
    the edge step, at the outer edge of a zone that already includes a margin.
    """
    west, south, east, north = lonlat_bounds
    found: Set[str] = set()
    for lat in _steps(south, north, step):
        for lon in _steps(west, east, step):
            found.add(cell_token(lat, lon, level))
    for lat in _steps(south, north, edge_step):
        found.add(cell_token(lat, west, level))
        found.add(cell_token(lat, east, level))
    for lon in _steps(west, east, edge_step):
        found.add(cell_token(south, lon, level))
        found.add(cell_token(north, lon, level))
    return sorted(found)
