"""Source of the roofs and use of each roof (spec §3 bis.2, decisions T1 to T4 of 29/09/2026).

The roofs are read from any source GDAL can open (file or database), or
from Google Open Buildings CSV tiles. Each roof gets a weight from its
usage category (housing = 1, mixed = 0.5, shop = 0…); categories missing
from the table take the default ``*`` (1 unless set otherwise). An
optional confidence threshold (off by default) drops doubtful roofs.
Every roof left out is counted, with its reason, for the report.
"""

from __future__ import annotations

import csv
import gzip
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .buildings import OPEN_BUILDINGS_COLUMNS, Buildings, read_footprints, read_open_buildings_csv
from .grid import Extent

DEFAULT_KEY = "*"
AUTO = "auto"
OPEN_BUILDINGS = "open_buildings"


@dataclass
class RoofSource:
    source: str
    layer: Optional[str] = None
    where: Optional[str] = None
    format: str = AUTO
    """``auto`` (Google Open Buildings CSV recognised from its columns) or ``open_buildings``."""
    area_field: Optional[str] = None
    """Roof area in m² (required for points); polygons are measured in the calculation CRS."""
    usage_field: Optional[str] = None
    usage_coefficients: Dict[str, float] = field(default_factory=dict)
    min_confidence: Optional[float] = None
    """Off (None) by default (T2)."""
    confidence_field: Optional[str] = None
    point_on_surface: bool = False
    year: Optional[float] = None
    """Year of the imagery the roofs were drawn from (reported only)."""

    @classmethod
    def from_dict(cls, data: Dict) -> "RoofSource":
        keys = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in keys})


@dataclass
class RoofSet:
    buildings: Buildings
    weight: np.ndarray
    """Usage coefficient of each roof kept (> 0)."""
    report: Dict[str, object]


def is_open_buildings(path: str) -> bool:
    """A CSV (possibly gzip-compressed) with the columns of Google Open Buildings."""
    lower = path.lower()
    if not (lower.endswith(".csv") or lower.endswith(".csv.gz")):
        return False
    opener = gzip.open if lower.endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8", newline="") as handle:
            header = next(csv.reader(handle))
    except (OSError, StopIteration, UnicodeDecodeError):
        return False
    return all(column in header for column in OPEN_BUILDINGS_COLUMNS[:3])


def download_origin(source: str) -> Optional[Dict[str, object]]:
    """Where roofs downloaded by Poplar come from (the ``.download.json`` written next to them), else None."""
    from .downloads.open_buildings import report_path

    if not source or source.startswith("PG:") or not os.path.isfile(source):
        return None
    try:
        with open(report_path(source), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    keys = ("dataset", "kind", "date", "output", "imagery_year", "licence", "attribution", "zone", "filters", "counts")
    return {k: data[k] for k in keys if k in data}


def usage_weights(usage: Optional[np.ndarray], coefficients: Dict[str, float]):
    """Coefficient of each roof, and the categories found that the table does not list (T1)."""
    default = float(coefficients.get(DEFAULT_KEY, 1.0))
    if usage is None:
        return None, []
    categories, index = np.unique(usage.astype(str), return_inverse=True)
    table = np.array([float(coefficients.get(c, default)) for c in categories])
    unknown = [str(c) for c in categories if c not in coefficients]
    return table[index], unknown


def usage_counts(usage: Optional[np.ndarray]) -> Dict[str, int]:
    if usage is None:
        return {}
    categories, counts = np.unique(usage.astype(str), return_counts=True)
    return {str(c): int(n) for c, n in zip(categories, counts)}


def read_roofs(spec: RoofSource, crs_wkt: str, extent: Optional[Extent] = None) -> RoofSet:
    """Read the roofs of the study extent, apply the confidence threshold and the usage coefficients."""
    open_buildings = spec.format == OPEN_BUILDINGS or (spec.format == AUTO and is_open_buildings(spec.source))
    if open_buildings:
        buildings = read_open_buildings_csv(spec.source, crs_wkt, extent=extent)
    else:
        buildings = read_footprints(spec.source, crs_wkt, layer=spec.layer, extent=extent,
                                    area_field=spec.area_field, point_on_surface=spec.point_on_surface,
                                    where=spec.where, usage_field=spec.usage_field,
                                    confidence_field=spec.confidence_field)
    report: Dict[str, object] = {"source": "open_buildings" if open_buildings else "layer", "read": len(buildings),
                                 "usage": usage_counts(buildings.usage)}
    download = download_origin(spec.source)
    if download:
        report["download"] = download
    keep = np.ones(len(buildings), dtype=bool)
    if spec.min_confidence is not None:
        if buildings.confidence is None:
            raise ValueError("a confidence threshold needs a confidence field")
        low = ~(buildings.confidence >= spec.min_confidence)    # NaN (no value) is left out as well
        report["low_confidence"] = int(low.sum())
        keep &= ~low
    weight, unknown = usage_weights(buildings.usage, spec.usage_coefficients)
    if weight is None:
        weight = np.ones(len(buildings))
    else:
        zero = keep & (weight <= 0)
        report["usage_zero"] = int(zero.sum())
        report["unknown_usage"] = unknown
        keep &= weight > 0
    report["kept"] = int(keep.sum())
    return RoofSet(buildings.subset(keep), weight[keep], report)
