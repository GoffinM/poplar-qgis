"""Polygons that change in time ("free" strata mode, fiche §3.5, plan_polygones_libres.md).

The state of the model is one polygon identifier per calculation unit
(``polygon_id``). A polygon carries a stratum (a typology class) and the
properties of that stratum: rank, whether it can be colonised, growth rate,
maximum density and colonisation parameters. Colonising a unit means giving
it the identifier of its neighbouring polygon, so it inherits every property
of that polygon from the next step on.

Colonisation rule (plan §3c, decision B1 of 06/10/2026), evaluated after the
migration of a step, on the state at the start of the step:

1. the candidate units of the cell are all at capacity;
2. the colonising polygon exported, during the step, beyond its own units,
   at least the minimum inflow (inhabitants, or a share of the capacity of
   the candidate units). Decision B of 06/10/2026: a saturated cell can no
   longer receive anyone, so the pressure is what the polygon sends out, not
   what the cell receives: the overflow passes over the full cell;
3. the colonising polygon is saturated: the share of its habitable area at
   capacity reaches its ``saturation_share``;
4. at least ``min_neighbors`` of the 8 neighbouring cells belong to the
   colonising polygon (fewer near a road, plan B), or the cell itself
   already does (residue, P13);
5. the colonising polygon has a strictly higher rank; units in exclusion
   zones and units of strata that cannot be colonised never change.

A cell belongs to a polygon when that polygon covers at least
``membership_share`` of the area of the cell inside the study area (B2).
Conflicts go to the highest rank, then to the polygon that exported the
most during the step, then to the lowest identifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from osgeo import ogr

from .migration import Inflow
from .units import Layer, Units, Zone
from .vector_io import polygonal_part

NO_POLYGON = -1
"""Unit outside every polygon (a gap of the typology), or cell without a majority polygon."""
NO_CELL = -2
"""Cell without any unit (outside the study area), in the cell rasters."""
PART_LAYER = "polygon_part"
NO_RANK = -1

SHARE_OF_CAPACITY = "share_of_capacity"
INHABITANTS = "inhabitants"
INFLOW_UNITS = (SHARE_OF_CAPACITY, INHABITANTS)

_NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


@dataclass
class Stratum:
    """Rules of a stratum (typology class) in free mode."""

    rank: int = NO_RANK
    colonizable: bool = True


@dataclass
class PolygonTable:
    """Properties of each polygon, indexed by its identifier."""

    stratum: List[str] = field(default_factory=list)
    rank: List[int] = field(default_factory=list)
    colonizable: List[bool] = field(default_factory=list)
    parent: List[int] = field(default_factory=list)
    created: List[Optional[float]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.stratum)

    def add(self, stratum: str, strata: Dict[str, Stratum], parent: int = NO_POLYGON,
            created: Optional[float] = None) -> int:
        rule = strata.get(stratum, Stratum())
        self.stratum.append(stratum)
        self.rank.append(int(rule.rank))
        self.colonizable.append(bool(rule.colonizable))
        self.parent.append(int(parent))
        self.created.append(created)
        return len(self.stratum) - 1

    def ranks(self) -> np.ndarray:
        return np.array(self.rank, dtype=np.int64)

    def colonizables(self) -> np.ndarray:
        return np.array(self.colonizable, dtype=bool)


@dataclass
class ColonisationRules:
    min_neighbors: int = 3
    membership_share: float = 0.5
    tolerance: float = 1.0
    """Free places under which a unit is at capacity: the migration tolerance."""
    min_inflow_unit: str = SHARE_OF_CAPACITY
    near_road: Optional[np.ndarray] = None
    """Cells (flat) near a road (roads, plan B): they need only ``min_neighbors_road`` neighbours."""
    min_neighbors_road: int = 2


@dataclass
class Colonisation:
    """Outcome of one colonisation pass."""

    polygon_id: np.ndarray
    """New identifier of each unit (effective from the next step)."""
    changed: np.ndarray
    """Units that changed polygon."""
    cells: np.ndarray
    """Cells colonised in this pass (cell ids)."""
    winners: np.ndarray
    """Colonising polygon of each cell in ``cells``."""
    exported: np.ndarray
    """Population exported during the step by the winner of each cell."""
    saturation: np.ndarray
    """Share of the habitable area at capacity, per polygon (NaN without habitable area)."""


# --- initial state ----------------------------------------------------------------------------


def part_layer(zones: Sequence[Zone]) -> Layer:
    """One value per connected part of each typology feature: ``(feature, part)`` (decision P2).

    Built from the same geometries as the typology, in the same order, so that
    it cuts the cells exactly like the typology does.
    """
    geometries, values = [], []
    for index, zone in enumerate(zones):
        polygonal = polygonal_part(zone.geometry)
        if polygonal is None:
            continue
        for part in range(polygonal.GetGeometryCount()):
            single = ogr.Geometry(ogr.wkbMultiPolygon)
            single.AddGeometry(polygonal.GetGeometryRef(part))
            geometries.append(single)
            values.append((index, part))
    return Layer(PART_LAYER, geometries, values)


def initial_polygons(units: Units, zones: Sequence[Zone], strata: Dict[str, Stratum],
                     year: Optional[float] = None) -> Tuple[np.ndarray, PolygonTable]:
    """Identifier of each unit at the start, and the table of the polygons.

    ``units`` must have been built with :func:`part_layer` among its layers.
    """
    table = PolygonTable()
    labels = units.labels[PART_LAYER]
    for feature, _ in labels:
        table.add(zones[feature].class_name, strata, created=year)
    codes = units.codes[PART_LAYER]
    polygon_id = np.where(codes >= 0, codes, NO_POLYGON).astype(np.int32)
    return polygon_id, table


# --- views of the state ---------------------------------------------------------------------


def cell_membership(units: Units, polygon_id: np.ndarray, share: float = 0.5) -> np.ndarray:
    """Polygon of each cell, as a (rows, cols) raster (B2a).

    A cell belongs to the polygon that covers at least ``share`` of its area
    inside the study area; otherwise it is :data:`NO_POLYGON`. Cells without
    any unit are :data:`NO_CELL`.
    """
    grid = units.grid
    result = np.full(grid.ncells, NO_CELL, dtype=np.int32)
    cell_area = np.bincount(units.cell_id, weights=units.area_km2, minlength=grid.ncells)
    result[cell_area > 0] = NO_POLYGON
    pid = np.asarray(polygon_id, dtype=np.int64)
    known = pid >= 0
    if known.any():
        npoly = int(pid[known].max()) + 1
        keys, inverse = np.unique(units.cell_id[known] * npoly + pid[known], return_inverse=True)
        area = np.bincount(inverse.ravel(), weights=units.area_km2[known], minlength=len(keys))
        cells, polygons = np.divmod(keys, npoly)
        fraction = area / cell_area[cells]
        majority = fraction >= share - 1e-9
        result[cells[majority]] = polygons[majority]
    return result.reshape(grid.nrows, grid.ncols)


def at_capacity(population: np.ndarray, capacity: np.ndarray, tolerance: float = 1.0) -> np.ndarray:
    """Units that cannot receive anyone any more: fewer free places than the migration tolerance."""
    return (np.asarray(capacity, dtype=np.float64) - np.asarray(population, dtype=np.float64)) < tolerance


def saturation_shares(polygon_id: np.ndarray, area_km2: np.ndarray, full: np.ndarray, protected: np.ndarray,
                      npolygons: int) -> np.ndarray:
    """Share of the habitable area of each polygon at capacity (exclusion zones left out)."""
    pid = np.asarray(polygon_id, dtype=np.int64)
    habitable = (pid >= 0) & ~np.asarray(protected, dtype=bool)
    total = np.bincount(pid[habitable], weights=area_km2[habitable], minlength=npolygons)
    saturated = np.bincount(pid[habitable & full], weights=area_km2[habitable & full], minlength=npolygons)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(total > 0, saturated / np.where(total > 0, total, 1.0), np.nan)


# --- colonisation -----------------------------------------------------------------------------


def exported_by_polygon(inflow: Inflow, polygon_id: np.ndarray, npolygons: int) -> np.ndarray:
    """Population each polygon sent during the step to units outside itself (direct sender)."""
    if inflow is None or len(inflow.keys) == 0:
        return np.zeros(npolygons)
    unit, label = np.divmod(inflow.keys, inflow.nlabels)
    outside = (label < npolygons) & (np.asarray(polygon_id)[unit] != label)
    return np.bincount(label[outside], weights=inflow.amounts[outside], minlength=npolygons)[:npolygons]


def colonise(units: Units, polygon_id: np.ndarray, table: PolygonTable, population: np.ndarray,
             capacity: np.ndarray, protected: np.ndarray, inflow: Inflow, min_inflow: np.ndarray,
             saturation_share: np.ndarray, rules: ColonisationRules = ColonisationRules()) -> Colonisation:
    """One colonisation pass (plan §3c): at most one ring of cells per polygon.

    ``min_inflow`` and ``saturation_share`` are given per polygon (those of the
    colonising polygon apply). ``protected`` marks the units that never change:
    exclusion zones (fixed or dated) and evacuated zones.
    """
    if rules.min_inflow_unit not in INFLOW_UNITS:
        raise ValueError(f"unknown inflow unit {rules.min_inflow_unit!r} (expected one of {INFLOW_UNITS})")
    pid = np.asarray(polygon_id, dtype=np.int32)
    population = np.asarray(population, dtype=np.float64)
    capacity = np.asarray(capacity, dtype=np.float64)
    protected = np.asarray(protected, dtype=bool)
    npoly = len(table)
    ranks = table.ranks()
    colonizable = table.colonizables()
    full = at_capacity(population, capacity, rules.tolerance)
    saturation = saturation_shares(pid, units.area_km2, full, protected, npoly)
    min_inflow = np.asarray(min_inflow, dtype=np.float64)
    saturation_share = np.asarray(saturation_share, dtype=np.float64)

    def outcome(new_pid, cells=(), winners=(), pressure=()):
        return Colonisation(new_pid, new_pid != pid, np.asarray(cells, dtype=np.int64),
                            np.asarray(winners, dtype=np.int64), np.asarray(pressure, dtype=np.float64), saturation)

    known = pid >= 0
    safe = np.where(known, pid, 0)
    unit_rank = np.where(known, ranks[safe], NO_RANK)
    candidate = known & ~protected & colonizable[safe] & (unit_rank != NO_RANK)
    with np.errstate(invalid="ignore"):
        saturated_polygon = (ranks != NO_RANK) & (saturation >= saturation_share - 1e-12)
    if not candidate.any() or not saturated_polygon.any():
        return outcome(pid.copy())

    grid = units.grid
    membership = cell_membership(units, pid, rules.membership_share)
    padded = np.pad(membership, 1, constant_values=NO_CELL)
    cells = np.unique(units.cell_id[candidate])
    rows, cols = np.divmod(cells, grid.ncols)
    neighbours = np.stack([padded[rows + 1 + dr, cols + 1 + dc] for dr, dc in _NEIGHBOURS], axis=1)
    own = membership.ravel()[cells]

    # Pairs (cell, colonising polygon): every polygon seen around the cell, or the cell's own.
    pair_cell = np.concatenate([np.repeat(np.arange(len(cells)), 8), np.arange(len(cells))])
    pair_poly = np.concatenate([neighbours.ravel(), own]).astype(np.int64)
    keep = pair_poly >= 0
    pair_keys = np.unique(pair_cell[keep] * npoly + pair_poly[keep])
    pair_cell, pair_poly = np.divmod(pair_keys, npoly)
    counts = (neighbours[pair_cell] == pair_poly[:, None]).sum(axis=1)
    needed_neighbours = np.full(len(cells), rules.min_neighbors)
    if rules.near_road is not None:
        needed_neighbours = np.where(np.asarray(rules.near_road, bool)[cells],
                                     min(rules.min_neighbors, rules.min_neighbors_road), rules.min_neighbors)
    contiguous = (counts >= needed_neighbours[pair_cell]) | (own[pair_cell] == pair_poly)
    usable = contiguous & saturated_polygon[pair_poly]
    pair_cell, pair_poly = pair_cell[usable], pair_poly[usable]
    if len(pair_cell) == 0:
        return outcome(pid.copy())

    # Units of each pair's cell (units are sorted by cell id).
    first = np.searchsorted(units.cell_id, cells[pair_cell], side="left")
    last = np.searchsorted(units.cell_id, cells[pair_cell], side="right")
    sizes = last - first
    pair_of = np.repeat(np.arange(len(pair_cell)), sizes)
    unit = np.repeat(first - np.cumsum(sizes) + sizes, sizes) + np.arange(sizes.sum())
    colonising = pair_poly[pair_of]
    taken = candidate[unit] & (unit_rank[unit] < ranks[colonising]) & (pid[unit] != colonising)

    npairs = len(pair_cell)
    n_taken = np.bincount(pair_of, weights=taken, minlength=npairs)
    n_full = np.bincount(pair_of, weights=taken & full[unit], minlength=npairs)
    exported = exported_by_polygon(inflow, pid, npoly)
    pair_inflow = exported[pair_poly]
    pair_capacity = np.bincount(pair_of, weights=np.where(taken, capacity[unit], 0.0), minlength=npairs)
    if rules.min_inflow_unit == SHARE_OF_CAPACITY:
        needed = min_inflow[pair_poly] * pair_capacity
    else:
        needed = min_inflow[pair_poly]
    valid = (n_taken > 0) & (n_full == n_taken) & (pair_inflow > 0) & (pair_inflow >= needed - 1e-9)
    if not valid.any():
        return outcome(pid.copy())

    # Conflicts: highest rank, then most exported, then lowest identifier.
    candidates = np.flatnonzero(valid)
    order = np.lexsort((pair_poly[candidates], -pair_inflow[candidates], -ranks[pair_poly[candidates]],
                        pair_cell[candidates]))
    ordered = candidates[order]
    first_of_cell = np.ones(len(ordered), dtype=bool)
    first_of_cell[1:] = pair_cell[ordered][1:] != pair_cell[ordered][:-1]
    winners = ordered[first_of_cell]

    new_pid = pid.copy()
    won = np.zeros(npairs, dtype=bool)
    won[winners] = True
    change = taken & won[pair_of]
    new_pid[unit[change]] = colonising[change]
    return outcome(new_pid, cells[pair_cell[winners]], pair_poly[winners], pair_inflow[winners])


# --- new nuclei (P8/P17) ------------------------------------------------------------------------


@dataclass
class NucleusRules:
    """Creation of new polygons away from any polygon of the same or a higher rank (off by default).

    A cluster of at least ``min_cells`` touching cells (8 neighbours, 16 by default), all saturated, whose units belong to
    colonisable strata of a lower rank than ``stratum`` and that touch no polygon of that rank or higher,
    becomes a new polygon of ``stratum``. It is flagged « to check » when an artificial constraint may
    explain it: an enclave of habitable land smaller than ``enclave_km2``, or units fed mostly by the
    migration of the step (inflow / population at least ``migration_share``).
    """

    enabled: bool = False
    stratum: Optional[str] = None
    min_cells: int = 16
    """16 cells of 250 m = 1 km² (decision D2 of 06/10/2026)."""
    enclave_km2: float = 5.0
    migration_share: float = 0.5


@dataclass
class Nucleus:
    polygon: int
    cells: np.ndarray
    population: float
    flags: List[str]


def new_nuclei(units: Units, polygon_id: np.ndarray, table: PolygonTable, population: np.ndarray,
               capacity: np.ndarray, protected: np.ndarray, inflow: Optional[Inflow], rules: NucleusRules,
               strata: Dict[str, Stratum], year: float, tolerance: float = 1.0,
               membership_share: float = 0.5) -> Tuple[np.ndarray, List[Nucleus]]:
    """New polygons born in this step, if the rule is on; returns the new identifiers of the units."""
    from scipy import ndimage

    pid = np.asarray(polygon_id, dtype=np.int32)
    if not rules.enabled or not rules.stratum or rules.stratum not in strata:
        return pid, []
    level = strata[rules.stratum].rank
    if level == NO_RANK:
        return pid, []
    grid = units.grid
    ranks = table.ranks()
    colonizable = table.colonizables()
    known = pid >= 0
    safe = np.where(known, pid, 0)
    unit_rank = np.where(known, ranks[safe], NO_RANK)
    candidate = known & ~np.asarray(protected, bool) & colonizable[safe] & (unit_rank != NO_RANK) & (unit_rank < level)
    full = at_capacity(population, capacity, tolerance)
    ncells = grid.ncells
    n_candidates = np.bincount(units.cell_id[candidate], minlength=ncells)
    n_full = np.bincount(units.cell_id[candidate & full], minlength=ncells)
    eligible = (n_candidates > 0) & (n_full == n_candidates)
    membership = cell_membership(units, pid, membership_share).ravel()
    higher = np.zeros(ncells, dtype=bool)
    member = membership >= 0
    higher[member] = ranks[membership[member]] >= level
    near = ndimage.binary_dilation(higher.reshape(grid.nrows, grid.ncols), structure=np.ones((3, 3), bool))
    eligible &= ~near.ravel()
    labels, count = ndimage.label(eligible.reshape(grid.nrows, grid.ncols), structure=np.ones((3, 3), bool))
    if count == 0:
        return pid, []
    sizes = np.bincount(labels.ravel(), minlength=count + 1)
    big = np.flatnonzero(sizes >= max(1, rules.min_cells))
    big = big[big > 0]
    if len(big) == 0:
        return pid, []
    habitable = np.zeros(ncells, dtype=bool)
    habitable[units.cell_id[~np.asarray(protected, bool)]] = True
    land, _ = ndimage.label(habitable.reshape(grid.nrows, grid.ncols), structure=np.ones((3, 3), bool))
    land_area = np.bincount(land.ravel(), weights=units.per_cell(units.area_km2).ravel(), minlength=land.max() + 1)
    received = np.zeros(len(pid))
    if inflow is not None and len(inflow.keys):
        unit, _ = np.divmod(inflow.keys, inflow.nlabels)
        np.add.at(received, unit, inflow.amounts)
    new_pid = pid.copy()
    found = []
    flat = labels.ravel()
    for label in big:
        cells = np.flatnonzero(flat == label)
        members = np.isin(units.cell_id, cells) & candidate
        parents = pid[members]
        parent = int(np.bincount(parents).argmax()) if len(parents) else NO_POLYGON
        polygon = table.add(rules.stratum, strata, parent=parent, created=year)
        new_pid[members] = polygon
        flags = []
        if land_area[land.ravel()[cells[0]]] < rules.enclave_km2:
            flags.append("enclave")
        people = float(population[members].sum())
        if people > 0 and received[members].sum() / people >= rules.migration_share:
            flags.append("migration")
        found.append(Nucleus(polygon, cells, people, flags))
    return new_pid, found


@dataclass
class PolygonHistory:
    """What the free mode did during a run: the state, its changes, and views for the outputs."""

    units: Units
    table: PolygonTable
    initial: np.ndarray
    final: np.ndarray
    events: List[dict] = field(default_factory=list)
    """One entry per colonised cell: ``year``, ``cell``, ``row``, ``col``, ``polygon``, ``exported``."""
    membership: Dict[int, np.ndarray] = field(default_factory=dict)
    """Polygon of each cell (raster) at the start and at each output year."""
    reclassification: Optional[np.ndarray] = None
    """Population added per unit by the change of growth rate of colonised units (plan §4, S1)."""
    ids: Dict[int, np.ndarray] = field(default_factory=dict)
    """Polygon of each unit at the start and at each output year."""
    stats: List[dict] = field(default_factory=list)
    """Per polygon and output year: area, population, density, share at capacity, cells."""
    start_year: int = 0
    reclassification_by_admin: List[dict] = field(default_factory=list)
    """Cumulated reclassification effect per administrative unit, at the start and at each output year."""
    roads: Optional[dict] = None
    """Roads (plan B): ``main_distance`` (cell raster, m), ``reach_m``, settings used."""
