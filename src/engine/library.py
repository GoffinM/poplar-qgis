"""Library of scenarios (decision of 29/09/2026): a folder of scenario files, filled as work goes on.

The folder can be shared (network drive) so that a team starts from the
same reference scenarios. Each entry is an ordinary scenario file; its
``name`` and ``description`` are shown in the list.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class LibraryEntry:
    path: str
    name: str
    description: str
    modified: str
    """Date of the last change of the file (local time, YYYY-MM-DD HH:MM)."""


def list_library(folder: str) -> List[LibraryEntry]:
    """Scenario files of the folder and its sub-folders, sorted by name."""
    entries = []
    if not folder or not os.path.isdir(folder):
        return entries
    for base, _, files in os.walk(folder):
        for file_name in files:
            if not file_name.lower().endswith(".json"):
                continue
            path = os.path.join(base, file_name)
            try:
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict) or "time" not in data or "parameters" not in data:
                continue  # not a scenario
            modified = dt.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
            entries.append(LibraryEntry(path, str(data.get("name") or os.path.splitext(file_name)[0]),
                                        str(data.get("description") or ""), modified))
    return sorted(entries, key=lambda e: (e.name.lower(), e.path))


def slug(text: str) -> str:
    """File name from a scenario name: « Muramvya – dmax +20 % » → « muramvya_dmax_20 »."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text or "scenario"


def save_to_library(folder: str, data: Dict[str, Any], name: str, description: str = "") -> str:
    """Write the scenario in the library under a new file name; return its path."""
    os.makedirs(folder, exist_ok=True)
    data = dict(data, name=name, description=description)
    base = os.path.join(folder, slug(name))
    path, suffix = f"{base}.json", 2
    while os.path.exists(path):
        path, suffix = f"{base}_{suffix}.json", suffix + 1
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    return path
