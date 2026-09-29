"""Split grid cells into calculation units (spec §3).

A cell crossed by a boundary (study area, or any polygon of the partition
layers: typology, parameter zones, exclusions, administrative units) is cut
into sub-polygons; each piece is a unit that carries its own area, centroid
and the value of every layer. Cells that no boundary crosses stay whole and
are handled as plain arrays, without any geometry, so that large extents
remain cheap: only boundary cells go through OGR geometry operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from osgeo import gdal, ogr

from ._gdal import gdal_exceptions, srs_from_wkt
from .grid import Grid, rectangle
from .vector_io import memory_datasource, polygonal_part, union_all

NO_VALUE = -1
NO_CLASS = NO_VALUE
CLASS_LAYER = "class"
NO_INFLOW_LAYER = "no_inflow"
SINK_CLASS = "__sink__"


@dataclass
class Zone:
    """A typology polygon and the name of its class (free text, e.g. ``Rural``)."""

    geometry: ogr.Geometry
    class_name: str


@dataclass
class Layer:
    """A partition layer: polygons and the value each one carries.

    Where polygons overlap, the first one wins (and the overlap is reported).
    """

    name: str
    geometries: List[ogr.Geometry]
    values: List[Any]

    def __post_init__(self) -> None:
        if len(self.geometries) != len(self.values):
            raise ValueError(f"layer {self.name!r}: one value per geometry is required")


@dataclass
class UnitsReport:
    split_cells: int = 0
    whole_cells: int = 0
    unclassified_area_km2: float = 0.0
    overlap_area_km2: float = 0.0
    dropped_area_km2: float = 0.0
    overlap_by_layer_km2: Dict[str, float] = field(default_factory=dict)


@dataclass
class Units:
    """Calculation units, stored as parallel arrays sorted by cell id.

    ``codes[layer]`` gives, for each unit, the index of its value in
    ``labels[layer]`` (``-1`` where the layer does not cover the unit).
    ``geometries`` only holds the pieces of split cells; a whole-cell unit
    is the grid cell itself.
    """

    grid: Grid
    cell_id: np.ndarray
    area_km2: np.ndarray
    cx: np.ndarray
    cy: np.ndarray
    whole_cell: np.ndarray
    codes: Dict[str, np.ndarray]
    labels: Dict[str, List[Any]]
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

    @property
    def class_index(self) -> np.ndarray:
        return self.codes[CLASS_LAYER]

    @property
    def class_names(self) -> List[str]:
        return self.labels[CLASS_LAYER]

    @property
    def no_inflow(self) -> np.ndarray:
        if NO_INFLOW_LAYER not in self.codes:
            return np.zeros(len(self), dtype=bool)
        return self.codes[NO_INFLOW_LAYER] != NO_VALUE

    def values(self, layer: str) -> List[Any]:
        """Value of ``layer`` for each unit (None where the layer is absent)."""
        labels = self.labels[layer]
        return [labels[k] if k != NO_VALUE else None for k in self.codes[layer]]

    def geometry(self, index: int) -> ogr.Geometry:
        if self.whole_cell[index]:
            cell = int(self.cell_id[index])
            return self.grid.cell_geometry(cell // self.grid.ncols, cell % self.grid.ncols)
        return self.geometries[index]

    def class_name(self, index: int) -> Optional[str]:
        k = int(self.class_index[index])
        return None if k == NO_VALUE else self.class_names[k]

    def per_cell(self, values: np.ndarray) -> np.ndarray:
        """Sum unit values per grid cell, as a (nrows, ncols) array."""
        total = np.zeros(self.grid.ncells, dtype=np.float64)
        np.add.at(total, self.cell_id, values)
        return total.reshape(self.grid.nrows, self.grid.ncols)


def build_units(
    grid: Grid,
    study_area: ogr.Geometry,
    zones: Sequence[Zone] = (),
    no_inflow: Optional[ogr.Geometry] = None,
    layers: Sequence[Layer] = (),
    min_unit_area_m2: float = 1.0,
    tile_cells: int = 32,
) -> Units:
    """Cut the grid into calculation units.

    ``study_area`` must already exclude the ``outside`` zones (spec §2.4).
    ``zones`` (the typology) becomes the ``class`` layer and ``no_inflow``
    the ``no_inflow`` layer; ``layers`` adds any other partition. Gaps in
    the typology give units without class, reported in ``report``.
    """
    all_layers = [Layer(CLASS_LAYER, [z.geometry for z in zones], [z.class_name for z in zones])]
    if no_inflow is not None:
        all_layers.append(Layer(NO_INFLOW_LAYER, [no_inflow], [True]))
    all_layers.extend(layers)
    names = [layer.name for layer in all_layers]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate layer names: {names}")
    with gdal_exceptions():
        return _build_units(grid, study_area, all_layers, min_unit_area_m2, tile_cells)


@dataclass
class _PreparedLayer:
    name: str
    geometries: List[ogr.Geometry]
    codes: np.ndarray
    labels: List[Any]
    envelopes: np.ndarray


def _prepare(layer: Layer) -> _PreparedLayer:
    labels = sorted(set(layer.values), key=lambda v: (str(type(v)), v))
    kept = [(polygonal_part(g), labels.index(v)) for g, v in zip(layer.geometries, layer.values)]
    kept = [(g, k) for g, k in kept if g is not None]
    geometries = [g for g, _ in kept]
    envelopes = np.array([_envelope(g) for g in geometries], dtype=np.float64).reshape(-1, 4)
    return _PreparedLayer(layer.name, geometries, np.array([k for _, k in kept], dtype=np.int32), labels, envelopes)


def _build_units(grid, study_area, layers, min_unit_area_m2, tile_cells) -> Units:
    study_area = polygonal_part(study_area)
    if study_area is None:
        raise ValueError("the study area is empty")
    prepared = [_prepare(layer) for layer in layers]

    # Cell status at the cell centre, and cells touched by any boundary.
    inside = _rasterize(grid, [(study_area, 1)], all_touched=False) == 1
    centre_codes = {
        p.name: _rasterize(grid, [(g, int(k) + 1) for g, k in zip(p.geometries, p.codes)][::-1], False) - 1
        for p in prepared
    }
    boundaries = [study_area.Boundary()] + [g.Boundary() for p in prepared for g in p.geometries]
    boundary = _rasterize(grid, [(b, 1) for b in boundaries], all_touched=True) == 1

    report = UnitsReport(overlap_by_layer_km2={p.name: 0.0 for p in prepared})
    whole_ids = np.flatnonzero((inside & ~boundary).ravel())
    report.whole_cells = len(whole_ids)
    rows, cols = np.divmod(whole_ids, grid.ncols)
    cell_ids = [whole_ids]
    areas = [np.full(len(whole_ids), grid.cell_area_km2)]
    cxs = [grid.x0 + (cols + 0.5) * grid.cell_size]
    cys = [grid.y0 - (rows + 0.5) * grid.cell_size]
    codes = {p.name: [centre_codes[p.name].ravel()[whole_ids].astype(np.int32)] for p in prepared}
    geometries: List[Optional[ogr.Geometry]] = [None] * len(whole_ids)

    pieces = _split_boundary_cells(grid, boundary, study_area, prepared, min_unit_area_m2, tile_cells, report)
    for cell, geometry, attrs in pieces:
        centroid = geometry.Centroid()
        cell_ids.append(np.array([cell]))
        areas.append(np.array([geometry.GetArea() / 1e6]))
        cxs.append(np.array([centroid.GetX()]))
        cys.append(np.array([centroid.GetY()]))
        for p in prepared:
            codes[p.name].append(np.array([attrs.get(p.name, NO_VALUE)], dtype=np.int32))
        geometries.append(geometry)

    cell_id = np.concatenate(cell_ids).astype(np.int64)
    order = np.argsort(cell_id, kind="stable")
    area_km2 = np.concatenate(areas)[order]
    unit_codes = {name: np.concatenate(parts)[order] for name, parts in codes.items()}
    report.unclassified_area_km2 = float(area_km2[unit_codes[CLASS_LAYER] == NO_VALUE].sum())
    report.overlap_area_km2 = float(sum(report.overlap_by_layer_km2.values()))
    report.split_cells = len({piece[0] for piece in pieces})
    geometries = [geometries[i] for i in order]
    return Units(
        grid=grid,
        cell_id=cell_id[order],
        area_km2=area_km2,
        cx=np.concatenate(cxs)[order],
        cy=np.concatenate(cys)[order],
        whole_cell=np.array([g is None for g in geometries], dtype=bool),
        codes=unit_codes,
        labels={p.name: p.labels for p in prepared},
        geometries={i: g for i, g in enumerate(geometries) if g is not None},
        report=report,
    )


def _split_boundary_cells(grid, boundary, study_area, prepared, min_area_m2, tile_cells, report):
    """Cut every boundary cell, tile by tile.

    Clipping the input polygons to each tile first keeps every cell
    intersection small, whatever the number of vertices of the inputs.
    """
    pieces: List[Tuple[int, ogr.Geometry, Dict[str, int]]] = []
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
            layers_tile = []
            for p in prepared:
                clipped = []
                for j in np.flatnonzero(_overlaps(p.envelopes, tile_env)):
                    part = polygonal_part(p.geometries[j].Intersection(tile))
                    if part is not None:
                        clipped.append((part, int(p.codes[j]), _envelope(part)))
                layers_tile.append((p.name, clipped))

            for r, c in zip(*np.nonzero(block)):
                row, col = tile_row + r, tile_col + c
                cell_env = grid.cell_bounds(row, col)
                cell_geom = polygonal_part(study_tile.Intersection(rectangle(*cell_env)))
                if cell_geom is None:
                    continue
                cell_pieces = [(cell_geom, {})]
                for name, features in layers_tile:
                    cell_pieces = _split_by_layer(cell_pieces, cell_env, name, features, report)
                cell = row * grid.ncols + col
                pieces.extend((cell, g, attrs) for g, attrs in _merge_small(cell_pieces, min_area_m2, report))
    return pieces


def _split_by_layer(pieces, cell_env, name, features, report):
    candidates = [(g, k) for g, k, env in features if _overlaps(np.array([env]), cell_env)[0]]
    if not candidates:
        return [(g, {**attrs, name: NO_VALUE}) for g, attrs in pieces]
    result = []
    for piece, attrs in pieces:
        covered = None
        for zone_geom, code in candidates:
            part = polygonal_part(piece.Intersection(zone_geom))
            if part is None:
                continue
            if covered is not None:
                trimmed = polygonal_part(part.Difference(covered))
                report.overlap_by_layer_km2[name] += (part.GetArea() - (trimmed.GetArea() if trimmed else 0.0)) / 1e6
                part = trimmed
                if part is None:
                    continue
                covered = polygonal_part(covered.Union(part))
            else:
                covered = part.Clone()
            result.append((part, {**attrs, name: code}))
        rest = piece if covered is None else polygonal_part(piece.Difference(covered))
        if rest is not None:
            result.append((rest, {**attrs, name: NO_VALUE}))
    return result


def _merge_small(pieces, min_area_m2, report):
    """Attach slivers to the largest piece of the same cell (spec §3)."""
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
    return [(merged, pieces[i][1]) if i == largest else pieces[i] for i in keep]


def _rasterize(grid: Grid, shapes: Sequence[Tuple[ogr.Geometry, int]], all_touched: bool) -> np.ndarray:
    """Burn geometries on the grid (0 where nothing is burnt). Later shapes win."""
    if not shapes:
        return np.zeros((grid.nrows, grid.ncols), dtype=np.int32)
    target = gdal.GetDriverByName("MEM").Create("", grid.ncols, grid.nrows, 1, gdal.GDT_Int32)
    target.SetGeoTransform(grid.geotransform)
    target.SetProjection(grid.crs_wkt)
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
