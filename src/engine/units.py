"""Split grid cells into calculation units (spec §3).

A cell crossed by a boundary (study area, typology zone, no-inflow zone) is
cut into sub-polygons; each piece is a unit with its own area, class,
no-inflow flag and centroid. Cells that no boundary crosses stay whole and
are handled as plain arrays, without any geometry, so that large extents
remain cheap: only boundary cells go through OGR geometry operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from osgeo import gdal, ogr

from ._gdal import gdal_exceptions, srs_from_wkt
from .grid import Grid, rectangle
from .vector_io import memory_datasource, polygonal_part, union_all

NO_CLASS = -1


@dataclass
class Zone:
    """A typology polygon and the name of its class (free text, e.g. ``Rural``)."""

    geometry: ogr.Geometry
    class_name: str


@dataclass
class UnitsReport:
    split_cells: int = 0
    whole_cells: int = 0
    unclassified_area_km2: float = 0.0
    overlap_area_km2: float = 0.0
    dropped_area_km2: float = 0.0


@dataclass
class Units:
    """Calculation units, stored as parallel arrays sorted by cell id.

    ``geometries`` only holds the pieces of split cells; a whole-cell unit
    is the grid cell itself.
    """

    grid: Grid
    cell_id: np.ndarray
    area_km2: np.ndarray
    class_index: np.ndarray
    no_inflow: np.ndarray
    cx: np.ndarray
    cy: np.ndarray
    whole_cell: np.ndarray
    class_names: List[str]
    geometries: Dict[int, ogr.Geometry] = field(default_factory=dict)
    report: UnitsReport = field(default_factory=UnitsReport)

    def __len__(self) -> int:
        return len(self.cell_id)

    @property
    def row(self) -> np.ndarray:
        return self.cell_id // self.grid.ncols

    @property
    def col(self) -> np.ndarray:
        return self.cell_id % self.grid.ncols

    def geometry(self, index: int) -> ogr.Geometry:
        if self.whole_cell[index]:
            cell = int(self.cell_id[index])
            return self.grid.cell_geometry(cell // self.grid.ncols, cell % self.grid.ncols)
        return self.geometries[index]

    def class_name(self, index: int) -> Optional[str]:
        k = int(self.class_index[index])
        return None if k == NO_CLASS else self.class_names[k]

    def per_cell(self, values: np.ndarray) -> np.ndarray:
        """Sum unit values per grid cell, as a (nrows, ncols) array."""
        total = np.zeros(self.grid.ncells, dtype=np.float64)
        np.add.at(total, self.cell_id, values)
        return total.reshape(self.grid.nrows, self.grid.ncols)


def build_units(
    grid: Grid,
    study_area: ogr.Geometry,
    zones: Sequence[Zone],
    no_inflow: Optional[ogr.Geometry] = None,
    min_unit_area_m2: float = 1.0,
    tile_cells: int = 32,
) -> Units:
    """Cut the grid into calculation units.

    ``study_area`` must already exclude the ``outside`` zones (spec §2.4).
    ``zones`` should form a partition of the study area; overlaps and gaps
    are measured in the report (gaps give units without class).
    """
    with gdal_exceptions():
        return _build_units(grid, study_area, zones, no_inflow, min_unit_area_m2, tile_cells)


def _build_units(grid, study_area, zones, no_inflow, min_unit_area_m2, tile_cells) -> Units:
    study_area = polygonal_part(study_area)
    if study_area is None:
        raise ValueError("the study area is empty")
    class_names = sorted({zone.class_name for zone in zones})
    zone_class = np.array([class_names.index(zone.class_name) for zone in zones], dtype=np.int32)
    zone_geoms = [polygonal_part(zone.geometry) for zone in zones]
    zone_env = np.array(
        [_envelope(g) if g is not None else (np.inf, np.inf, -np.inf, -np.inf) for g in zone_geoms],
        dtype=np.float64,
    ).reshape(-1, 4)
    no_inflow = polygonal_part(no_inflow) if no_inflow is not None else None

    # Cell status at the cell centre, and cells touched by any boundary.
    inside = _rasterize(grid, [(study_area, 1)], all_touched=False) == 1
    centre_class = _rasterize(grid, [(g, int(k) + 1) for g, k in zip(zone_geoms, zone_class) if g is not None], False) - 1
    centre_no_inflow = (
        _rasterize(grid, [(no_inflow, 1)], all_touched=False) == 1 if no_inflow is not None else np.zeros_like(inside)
    )
    boundaries = [study_area.Boundary()] + [g.Boundary() for g in zone_geoms if g is not None]
    if no_inflow is not None:
        boundaries.append(no_inflow.Boundary())
    boundary = _rasterize(grid, [(b, 1) for b in boundaries], all_touched=True) == 1

    report = UnitsReport()
    whole = inside & ~boundary
    whole_ids = np.flatnonzero(whole.ravel())
    report.whole_cells = len(whole_ids)
    columns: Dict[str, list] = {name: [] for name in ("cell_id", "area", "cls", "ni", "cx", "cy")}
    geometries: List[Optional[ogr.Geometry]] = []

    rows, cols = np.divmod(whole_ids, grid.ncols)
    cell_area = grid.cell_area_km2
    columns["cell_id"].append(whole_ids)
    columns["area"].append(np.full(len(whole_ids), cell_area))
    columns["cls"].append(centre_class.ravel()[whole_ids].astype(np.int32))
    columns["ni"].append(centre_no_inflow.ravel()[whole_ids])
    columns["cx"].append(grid.x0 + (cols + 0.5) * grid.cell_size)
    columns["cy"].append(grid.y0 - (rows + 0.5) * grid.cell_size)
    geometries.extend([None] * len(whole_ids))

    pieces = _split_boundary_cells(
        grid, boundary, study_area, zone_geoms, zone_class, zone_env, no_inflow,
        min_unit_area_m2, tile_cells, report,
    )
    for cell, geometry, cls, flag in pieces:
        centroid = geometry.Centroid()
        columns["cell_id"].append(np.array([cell]))
        columns["area"].append(np.array([geometry.GetArea() / 1e6]))
        columns["cls"].append(np.array([cls], dtype=np.int32))
        columns["ni"].append(np.array([flag]))
        columns["cx"].append(np.array([centroid.GetX()]))
        columns["cy"].append(np.array([centroid.GetY()]))
        geometries.append(geometry)

    cell_id = np.concatenate(columns["cell_id"]).astype(np.int64)
    order = np.argsort(cell_id, kind="stable")
    class_index = np.concatenate(columns["cls"])[order]
    area_km2 = np.concatenate(columns["area"])[order]
    report.unclassified_area_km2 = float(area_km2[class_index == NO_CLASS].sum())
    report.split_cells = len({piece[0] for piece in pieces})
    geometries = [geometries[i] for i in order]
    return Units(
        grid=grid,
        cell_id=cell_id[order],
        area_km2=area_km2,
        class_index=class_index,
        no_inflow=np.concatenate(columns["ni"]).astype(bool)[order],
        cx=np.concatenate(columns["cx"])[order],
        cy=np.concatenate(columns["cy"])[order],
        whole_cell=np.array([g is None for g in geometries], dtype=bool),
        class_names=class_names,
        geometries={i: g for i, g in enumerate(geometries) if g is not None},
        report=report,
    )


def _split_boundary_cells(
    grid, boundary, study_area, zone_geoms, zone_class, zone_env, no_inflow,
    min_unit_area_m2, tile_cells, report,
) -> List[Tuple[int, ogr.Geometry, int, bool]]:
    """Cut every boundary cell, tile by tile.

    Clipping the input polygons to each tile first keeps every cell
    intersection small, whatever the number of vertices of the inputs.
    """
    pieces: List[Tuple[int, ogr.Geometry, int, bool]] = []
    min_area = min_unit_area_m2
    for tile_row in range(0, grid.nrows, tile_cells):
        for tile_col in range(0, grid.ncols, tile_cells):
            block = boundary[tile_row:tile_row + tile_cells, tile_col:tile_col + tile_cells]
            if not block.any():
                continue
            nr, nc = block.shape
            xmin, _, _, ymax = grid.cell_bounds(tile_row, tile_col)
            tile_env = (xmin, ymax - nr * grid.cell_size, xmin + nc * grid.cell_size, ymax)
            tile = rectangle(*tile_env)
            study_tile = polygonal_part(study_area.Intersection(tile))
            if study_tile is None:
                continue
            candidates = np.flatnonzero(_overlaps(zone_env, tile_env))
            zones_tile = []
            for j in candidates:
                clipped = polygonal_part(zone_geoms[j].Intersection(tile))
                if clipped is not None:
                    zones_tile.append((clipped, int(zone_class[j]), _envelope(clipped)))
            no_inflow_tile = polygonal_part(no_inflow.Intersection(tile)) if no_inflow is not None else None

            for r, c in zip(*np.nonzero(block)):
                row, col = tile_row + r, tile_col + c
                cell_env = grid.cell_bounds(row, col)
                cell_geom = polygonal_part(study_tile.Intersection(rectangle(*cell_env)))
                if cell_geom is None:
                    continue
                cell_pieces = _cell_pieces(cell_geom, cell_env, zones_tile, no_inflow_tile, report)
                cell_pieces = _merge_small(cell_pieces, min_area, report)
                cell = row * grid.ncols + col
                pieces.extend((cell, g, k, flag) for g, k, flag in cell_pieces)
    return pieces


def _cell_pieces(cell_geom, cell_env, zones_tile, no_inflow_tile, report):
    by_class = []
    covered = None
    for zone_geom, cls, env in zones_tile:
        if not _overlaps(np.array([env]), cell_env)[0]:
            continue
        piece = polygonal_part(cell_geom.Intersection(zone_geom))
        if piece is None:
            continue
        if covered is not None:
            trimmed = polygonal_part(piece.Difference(covered))
            report.overlap_area_km2 += (piece.GetArea() - (trimmed.GetArea() if trimmed else 0.0)) / 1e6
            piece = trimmed
            if piece is None:
                continue
            covered = polygonal_part(covered.Union(piece))
        else:
            covered = piece.Clone()
        by_class.append((piece, cls))
    rest = cell_geom if covered is None else polygonal_part(cell_geom.Difference(covered))
    if rest is not None:
        by_class.append((rest, NO_CLASS))

    result = []
    for piece, cls in by_class:
        if no_inflow_tile is None:
            result.append((piece, cls, False))
            continue
        inside = polygonal_part(piece.Intersection(no_inflow_tile))
        outside = polygonal_part(piece.Difference(no_inflow_tile)) if inside is not None else piece
        if inside is not None:
            result.append((inside, cls, True))
        if outside is not None:
            result.append((outside, cls, False))
    return result


def _merge_small(pieces, min_area_m2, report):
    """Attach slivers to the largest piece of the same cell (spec §3)."""
    if len(pieces) <= 1:
        if pieces and pieces[0][0].GetArea() < min_area_m2:
            report.dropped_area_km2 += pieces[0][0].GetArea() / 1e6
            return []
        return pieces
    areas = [p[0].GetArea() for p in pieces]
    keep = [i for i, a in enumerate(areas) if a >= min_area_m2]
    small = [i for i, a in enumerate(areas) if a < min_area_m2]
    if not small:
        return pieces
    if not keep:
        report.dropped_area_km2 += sum(areas) / 1e6
        return []
    largest = max(keep, key=lambda i: areas[i])
    merged = union_all([pieces[largest][0]] + [pieces[i][0] for i in small])
    return [
        (merged, pieces[i][1], pieces[i][2]) if i == largest else pieces[i]
        for i in keep
    ]


def _rasterize(grid: Grid, shapes: Sequence[Tuple[ogr.Geometry, int]], all_touched: bool) -> np.ndarray:
    """Burn geometries on the grid (0 where nothing is burnt). Later shapes win."""
    target = gdal.GetDriverByName("MEM").Create("", grid.ncols, grid.nrows, 1, gdal.GDT_Int32)
    target.SetGeoTransform(grid.geotransform)
    target.SetProjection(grid.crs_wkt)
    if not shapes:
        return np.zeros((grid.nrows, grid.ncols), dtype=np.int32)
    datasource = memory_datasource()
    layer = datasource.CreateLayer("shapes", srs_from_wkt(grid.crs_wkt))
    layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger))
    for geometry, value in shapes:
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(geometry)
        feature.SetField("value", int(value))
        layer.CreateFeature(feature)
    options = ["ATTRIBUTE=value"] + (["ALL_TOUCHED=TRUE"] if all_touched else [])
    gdal.RasterizeLayer(target, [1], layer, options=options)
    return target.GetRasterBand(1).ReadAsArray()


def _envelope(geometry: ogr.Geometry) -> Tuple[float, float, float, float]:
    xmin, xmax, ymin, ymax = geometry.GetEnvelope()
    return (xmin, ymin, xmax, ymax)


def _overlaps(envelopes: np.ndarray, env: Tuple[float, float, float, float]) -> np.ndarray:
    xmin, ymin, xmax, ymax = env
    return (
        (envelopes[:, 0] < xmax) & (envelopes[:, 2] > xmin)
        & (envelopes[:, 1] < ymax) & (envelopes[:, 3] > ymin)
    )


SINK_CLASS = "__sink__"


def build_sink_units(grid: Grid, study_area: ogr.Geometry, width_cells: int = 4) -> Units:
    """Units of the ring of sink cells around the study area (spec §7.2, S5).

    The ring is the study area buffered by ``width_cells`` cells, minus the
    study area itself. The grid must cover the buffered extent.
    """
    if width_cells < 1:
        raise ValueError("the sink ring must be at least one cell wide")
    with gdal_exceptions():
        distance = width_cells * grid.cell_size
        ring = polygonal_part(study_area.Buffer(distance).Difference(study_area))
        if ring is None:
            raise ValueError("the sink ring is empty")
        xmin, ymin, xmax, ymax = _envelope(ring)
        gxmax = grid.x0 + grid.ncols * grid.cell_size
        gymin = grid.y0 - grid.nrows * grid.cell_size
        if xmin < grid.x0 or ymax > grid.y0 or xmax > gxmax or ymin < gymin:
            raise ValueError("the grid does not cover the sink ring: enlarge its extent by the ring width")
    return build_units(grid, ring, [Zone(ring, SINK_CLASS)])
