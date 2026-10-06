"""Comparison of a run in planned mode with the same scenario in free mode (decision Q11 of 06/10/2026).

``python -m engine compare <planned run> <free run>`` writes, in the free run folder,
``comparaison_modes.csv`` and ``comparaison_modes.html``: for each output year,

- urban area and urban population in each mode. In planned mode the polygons never change, so its urban
  cells are those of the free run at its start; both modes are measured the same way, cell by cell (a cell
  is urban when its polygon, the one covering at least half of it, has an urban rank);
- population not placed (cumulated), in each mode;
- front speeds of the urban polygons in free mode (mean and maximum over the horizon ending that year);
  zero in planned mode, by definition.

The difference between the two modes measures the pressure of urbanisation outside the planned
perimeter (fiche §3.5).
"""

from __future__ import annotations

import csv
import html
import json
import os
from typing import Dict, List, Optional

import numpy as np

from .i18n import format_number
from .plausibility import load as load_indicators
from .raster_io import read_raster

CSV = "comparaison_modes.csv"
HTML = "comparaison_modes.html"


class NotComparable(ValueError):
    """The two folders are not a planned run and a free run of the same scenario."""


def _json(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _legend_ranks(directory: str) -> Dict[int, int]:
    ranks = {}
    with open(os.path.join(directory, "polygones_legende.csv"), encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            ranks[int(row["id"])] = int(row["rang"])
    return ranks


def _unallocated_by_year(report: dict) -> Dict[int, float]:
    total, result = 0.0, {}
    for step in report.get("steps") or []:
        total += float(step.get("unallocated", 0.0))
        result[int(round(step["end"]))] = total
    return result


def compare(planned: str, free: str) -> List[dict]:
    """Rows of the comparison, one per output year common to the two runs."""
    planned_scenario = _json(os.path.join(planned, "scenario_used.json"))
    free_scenario = _json(os.path.join(free, "scenario_used.json"))
    if (free_scenario.get("strata") or {}).get("mode") != "free":
        raise NotComparable(f"{free} is not a run in free mode")
    if (planned_scenario.get("strata") or {}).get("mode", "planned") != "planned":
        raise NotComparable(f"{planned} is not a run in planned mode")
    for key in ("typology", "study_area", "cell_size"):
        if planned_scenario.get(key) != free_scenario.get(key):
            raise NotComparable(f"the two runs differ by {key}")
    indicators = load_indicators(free) or {}
    urban_from = int(indicators.get("urban_rank", 2))
    ranks = _legend_ranks(free)
    lookup = np.full(max(ranks) + 2, -1)
    for polygon, rank in ranks.items():
        lookup[polygon] = rank

    def urban_mask(year_label: str) -> np.ndarray:
        ids = read_raster(os.path.join(free, f"polygon_id_{year_label}.tif")).values
        valid = np.isfinite(ids) & (ids >= 0)
        mask = np.zeros(ids.shape, dtype=bool)
        mask[valid] = lookup[ids[valid].astype(int)] >= urban_from
        return mask

    years = sorted(int(name[len("polygon_id_"):-4]) for name in os.listdir(free)
                   if name.startswith("polygon_id_") and name.endswith(".tif"))
    if not years:
        raise NotComparable(f"no polygon_id raster in {free}")
    start_mask = urban_mask(str(years[0]))
    cell_km2 = float(free_scenario.get("cell_size", 250.0)) ** 2 / 1e6
    left_planned = _unallocated_by_year(_json(os.path.join(planned, "report.json")))
    left_free = _unallocated_by_year(_json(os.path.join(free, "report.json")))
    horizons = indicators.get("horizons") or []
    rows = []
    for year in years:
        planned_raster = os.path.join(planned, f"population_{year}.tif")
        free_raster = os.path.join(free, f"population_{year}.tif")
        if not (os.path.isfile(planned_raster) and os.path.isfile(free_raster)):
            continue
        planned_population = np.nan_to_num(read_raster(planned_raster).values)
        free_population = np.nan_to_num(read_raster(free_raster).values)
        mask = urban_mask(str(year))
        speeds = [h["front_speed_m_per_year"] for h in horizons
                  if h.get("urban") and h["year_end"] == year and h["front_speed_m_per_year"] is not None]
        rows.append({
            "year": year,
            "urban_area_planned_km2": float(start_mask.sum()) * cell_km2,
            "urban_area_free_km2": float(mask.sum()) * cell_km2,
            "urban_population_planned": float(planned_population[start_mask].sum()),
            "urban_population_free": float(free_population[mask].sum()),
            "outside_planned_perimeter": float(free_population[mask & ~start_mask].sum()),
            "unallocated_planned": left_planned.get(year, 0.0),
            "unallocated_free": left_free.get(year, 0.0),
            "front_speed_mean": float(np.mean(speeds)) if speeds else 0.0,
            "front_speed_max": float(np.max(speeds)) if speeds else 0.0,
        })
    return rows


COLUMNS = [
    ("annee", "year"), ("surface_urbaine_planifie_km2", "urban_area_planned_km2"),
    ("surface_urbaine_libre_km2", "urban_area_free_km2"), ("population_urbaine_planifie", "urban_population_planned"),
    ("population_urbaine_libre", "urban_population_free"),
    ("population_hors_perimetre_planifie", "outside_planned_perimeter"),
    ("non_accueillis_planifie", "unallocated_planned"), ("non_accueillis_libre", "unallocated_free"),
    ("vitesse_front_moyenne_m_an", "front_speed_mean"), ("vitesse_front_max_m_an", "front_speed_max"),
]
TITLES_FR = ["Année", "Surface urbaine, planifié (km²)", "Surface urbaine, libre (km²)",
             "Population urbaine, planifié", "Population urbaine, libre", "Dont hors du périmètre planifié",
             "Non accueillis, planifié", "Non accueillis, libre", "Front moyen (m/an)", "Front max (m/an)"]


def write(planned: str, free: str, output: Optional[str] = None) -> List[str]:
    """Write the comparison in ``output`` (the free run folder by default)."""
    rows = compare(planned, free)
    output = output or free
    os.makedirs(output, exist_ok=True)
    csv_path = os.path.join(output, CSV)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow([name for name, _ in COLUMNS])
        for row in rows:
            writer.writerow([f"{row[key]:.6g}".replace(".", ",") if isinstance(row[key], float) else row[key]
                             for _, key in COLUMNS])
    html_path = os.path.join(output, HTML)
    body = "".join("<tr>" + "".join(
        f"<td>{html.escape(format_number(row[key], 'fr', 2 if key.endswith('km2') else 0))}</td>"
        if isinstance(row[key], float) else f"<td>{row[key]}</td>" for _, key in COLUMNS) + "</tr>" for row in rows)
    head = "".join(f"<th>{html.escape(t)}</th>" for t in TITLES_FR)
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write(
            '<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Comparaison des modes</title>'
            "<style>body{font-family:'Segoe UI',system-ui,sans-serif;margin:24px;color:#1d2b2a}"
            "table{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}"
            "th,td{border-bottom:1px solid #d5dedc;padding:4px 8px;text-align:right}"
            "th{background:#f6f8f7;color:#5c6e6c}h1{font-size:20px;color:#1f6f6a}</style></head><body>"
            "<h1>Comparaison des modes planifié et libre</h1>"
            f"<p>Planifié : {html.escape(planned)}<br>Libre : {html.escape(free)}</p>"
            "<p>Surfaces et populations mesurées maille par maille, de la même façon dans les deux modes. "
            "« Dont hors du périmètre planifié » : population libre dans les mailles urbaines qui ne l'étaient "
            "pas au départ, c'est-à-dire la pression d'urbanisation hors du périmètre planifié.</p>"
            f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></body></html>")
    return [csv_path, html_path]
