"""Plausibility indicators of the free strata mode (fiche §3.5, plan_polygones_libres.md §6).

The study areas have no history of urbanisation to validate against: these
figures only tell whether the fronts behave plausibly. For each polygon and
each horizon (interval between two output years):

- front speed (m/year): area gained divided by the mean outline length and
  the duration; also the growth of the equivalent radius ``sqrt(S/pi)``;
  a front is "capped" when it gained cells at least 3 years in a row (one
  ring per year is the most it can do: one cell size per year);
- spread or densification: elasticity ``(dS/S) / (dP/P)`` (above 1: spread);
- cell densities: 10th, 50th and 90th percentiles, share at capacity;
- compactness: Polsby-Popper ``4 pi S / P^2`` on the smoothed outline;
- new nuclei: number and population, with their flags;
- population not placed;
- reclassification effect (decision S1), per administrative unit;
- mass balance of the run, per horizon: final = start + growth - not placed
  - placed in the sink ring; the gap must be zero;
- roads (plan B): share of the extensions within the reach of a main road,
  against the same share of the rural cells at the start.

Written as ``plausibilite.csv`` (one row per polygon and horizon) and
``plausibilite.json`` (everything, read by the HTML report and by the
comparison of the two modes).
"""

from __future__ import annotations

import csv
import json
import math
import os
from typing import Dict, List, Optional, Sequence

from .polygons import NO_RANK, PolygonHistory

CSV = "plausibilite.csv"
JSON = "plausibilite.json"
SPREAD, DENSIFICATION, STABLE, RETREAT, BIRTH = "etalement", "densification", "stable", "recul", "naissance"
CAPPED_YEARS = 3
"""A front is "capped" when it gained cells this many years in a row (plan P4)."""


def compute(history: PolygonHistory, steps: Sequence, cell_size: float, urban_from: int) -> Dict[str, object]:
    """Every indicator, as plain data."""
    table = history.table
    stats = {(int(round(r["year"])), r["id"]): r for r in history.stats}
    years = sorted(history.membership)
    colonised: Dict[int, set] = {}
    for event in history.events:
        colonised.setdefault(event["polygon"], set()).add(int(round(event["year"])))
    rows = []
    for before, after in zip(years[:-1], years[1:]):
        duration = after - before
        for polygon in range(len(table)):
            end = stats.get((after, polygon))
            if end is None:
                continue
            start = stats.get((before, polygon))
            rows.append(_row(polygon, table, before, after, duration, start, end, colonised.get(polygon, set()),
                             cell_size, urban_from))
    nuclei = [e for e in history.events if e.get("event") == "nouveau_noyau"]
    nucleus_ids = sorted({e["polygon"] for e in nuclei})
    flags: Dict[int, set] = {}
    for event in nuclei:
        flags.setdefault(event["polygon"], set()).update(event.get("flags", []))
    return {
        "cell_size_m": cell_size,
        "speed_cap_m_per_year": cell_size,
        "urban_rank": urban_from,
        "colonised_cells": sum(1 for e in history.events if e.get("event", "extension") == "extension"),
        "horizons": rows,
        "new_nuclei": [{"id": p, "year": int(table.created[p]) if table.created[p] is not None else None,
                        "parent": table.parent[p], "cells": sum(1 for e in nuclei if e["polygon"] == p),
                        "population": sum(e.get("population", 0.0) for e in nuclei if e["polygon"] == p),
                        "to_check": sorted(flags.get(p, set()))} for p in nucleus_ids],
        "reclassification": history.reclassification_by_admin,
        "mass_balance": mass_balance(steps, years),
        "roads": roads_indicators(history, urban_from),
    }


def roads_indicators(history: PolygonHistory, urban_from: int) -> Optional[dict]:
    """Share of the extensions within the reach of a main road, against the same share of the rural cells
    at the start (plan B): above the baseline, the fronts follow the roads."""
    import numpy as np

    roads = history.roads
    if not roads:
        return None
    distance = np.asarray(roads["main_distance"]).ravel()
    reach = float(roads["reach_m"])
    cells = [int(e["cell"]) for e in history.events if e.get("event", "extension") == "extension"]
    start = history.membership[history.start_year].ravel()
    ranks = np.asarray(history.table.rank + [NO_RANK])          # index -1 (no polygon) gives NO_RANK
    rural = (start >= 0) & (ranks[np.where(start >= 0, start, -1)] < urban_from)
    near = distance <= reach
    return {
        "reach_m": reach,
        "extensions": len(cells),
        "extensions_near_share": float(near[cells].mean()) if cells else None,
        "baseline_near_share": float(near[rural].mean()) if rural.any() else None,
        "migration": bool(roads.get("migration")), "colonization": bool(roads.get("colonization")),
        "min_neighbors": roads.get("min_neighbors"), "threshold": roads.get("threshold"),
    }


def _row(polygon, table, before, after, duration, start, end, colonised_years, cell_size, urban_from) -> dict:
    s0 = start["area_km2"] if start else 0.0
    s1 = end["area_km2"]
    p0 = start["population"] if start else 0.0
    p1 = end["population"]
    gained_m2 = (s1 - s0) * 1e6
    perimeters = [r["perimeter_cells_m"] for r in (start, end) if r and r.get("perimeter_cells_m")]
    mean_perimeter = sum(perimeters) / len(perimeters) if perimeters else 0.0
    front = gained_m2 / (mean_perimeter * duration) if mean_perimeter > 0 and duration > 0 else 0.0
    radius = (math.sqrt(s1 * 1e6 / math.pi) - math.sqrt(s0 * 1e6 / math.pi)) / duration if duration > 0 else 0.0
    years_with_gain = sum(1 for y in colonised_years if before < y <= after)
    capped = any(all(y - k in colonised_years for k in range(CAPPED_YEARS))
                 for y in colonised_years if before < y <= after)
    elasticity = None
    if s0 > 0 and p0 > 0 and p1 != p0:
        elasticity = ((s1 - s0) / s0) / ((p1 - p0) / p0)
    if s1 < s0 - 1e-12:
        reading = RETREAT
    elif abs(s1 - s0) <= 1e-12:
        reading = DENSIFICATION if p1 > p0 else STABLE
    else:
        reading = SPREAD if elasticity is None or elasticity > 1 or elasticity < 0 else DENSIFICATION
    if start is None:                     # a new nucleus born in this horizon: no front moved yet
        front = radius = elasticity = None
        reading = BIRTH
    smooth = end.get("perimeter_smooth_m")
    compactness = 4 * math.pi * s1 * 1e6 / smooth ** 2 if smooth else None
    rank = table.rank[polygon]
    return {
        "year_start": before, "year_end": after, "id": polygon, "stratum": table.stratum[polygon],
        "rank": rank, "urban": rank != NO_RANK and rank >= urban_from,
        "area_start_km2": s0, "area_end_km2": s1, "population_start": p0, "population_end": p1,
        "front_speed_m_per_year": front, "radius_speed_m_per_year": radius,
        "years_with_colonisation": years_with_gain, "capped": capped,
        "elasticity": elasticity, "reading": reading,
        "density_p10": end.get("density_p10"), "density_p50": end.get("density_p50"),
        "density_p90": end.get("density_p90"), "saturated_share": end.get("saturated_share"),
        "compactness": compactness, "unallocated": end.get("unallocated", 0.0), "cells": end.get("cells"),
    }


def mass_balance(steps: Sequence, years: Sequence[int]) -> List[dict]:
    """Per horizon: start, growth, not placed, sink, end, and the gap (zero when everything is accounted for)."""
    rows = []
    for before, after in zip(years[:-1], years[1:]):
        inside = [s for s in steps if before - 1e-9 <= s.start and s.end <= after + 1e-9]
        if not inside:
            continue
        start = inside[0].population_before_growth
        growth = sum(s.population_after_growth - s.population_before_growth for s in inside)
        left = sum(s.unallocated for s in inside)
        sink = sum(s.placed_in_sink for s in inside)
        end = inside[-1].population_after_migration
        rows.append({"year_start": before, "year_end": after, "start": start, "growth": growth,
                     "unallocated": left, "sink": sink, "end": end, "gap": end - (start + growth - left - sink)})
    return rows


COLUMNS = [
    ("annee_debut", "year_start"), ("annee_fin", "year_end"), ("id", "id"), ("strate", "stratum"),
    ("rang", "rank"), ("urbain", "urban"), ("surface_debut_km2", "area_start_km2"),
    ("surface_fin_km2", "area_end_km2"), ("population_debut", "population_start"),
    ("population_fin", "population_end"), ("vitesse_front_m_an", "front_speed_m_per_year"),
    ("vitesse_rayon_m_an", "radius_speed_m_per_year"), ("annees_colonisees", "years_with_colonisation"),
    ("front_bride", "capped"), ("elasticite", "elasticity"), ("lecture", "reading"),
    ("densite_p10", "density_p10"), ("densite_p50", "density_p50"), ("densite_p90", "density_p90"),
    ("part_saturee", "saturated_share"), ("compacite", "compactness"), ("non_accueillis", "unallocated"),
    ("mailles", "cells"),
]


def write(directory: str, indicators: Dict[str, object]) -> List[str]:
    csv_path = os.path.join(directory, CSV)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow([name for name, _ in COLUMNS])
        for row in indicators["horizons"]:
            writer.writerow([_cell(row.get(key)) for _, key in COLUMNS])
    json_path = os.path.join(directory, JSON)
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(indicators, handle, ensure_ascii=False, indent=1)
    return [csv_path, json_path]


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, float):
        return f"{value:.6g}".replace(".", ",")
    return str(value)


def load(directory: str) -> Optional[Dict[str, object]]:
    path = os.path.join(directory, JSON)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)
