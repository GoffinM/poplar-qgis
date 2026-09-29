"""One folder per run (decision of 29/09/2026).

With ``output.per_run`` the results of each run go to a time-stamped
sub-folder of the output folder, so a new run never overwrites files that
QGIS still has open. Runs are temporary unless marked as kept; the plugin
offers to delete the others at the end of the session.

Each run folder holds a small marker file (``poplar_run.json``). Only
folders with this marker are listed or deleted, so a wrong output folder
never loses user data.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Set

MARKER = "poplar_run.json"
RUNNING = "running"
"""Status of a run still in progress, or interrupted (crash, QGIS closed)."""
SUCCESSFUL = ("success", "success_with_adjustments")


@dataclass
class RunFolder:
    directory: str
    created: str
    """ISO date and time of the start of the run (local time)."""
    name: str = ""
    """Name of the scenario."""
    status: str = RUNNING
    years: List[str] = field(default_factory=list)
    kept: bool = False
    label: str = ""

    @property
    def folder_name(self) -> str:
        return os.path.basename(self.directory)

    def size_bytes(self) -> int:
        return folder_size(self.directory)


def new_run_directory(root: str, now: Optional[dt.datetime] = None) -> str:
    """Create ``root/YYYY-MM-DD_HHMMSS`` (with a suffix if two runs start in the same second)."""
    now = now or dt.datetime.now()
    base = os.path.join(root, now.strftime("%Y-%m-%d_%H%M%S"))
    directory, suffix = base, 2
    while os.path.exists(directory):
        directory, suffix = f"{base}_{suffix}", suffix + 1
    os.makedirs(directory)
    write_marker(RunFolder(directory, now.isoformat(timespec="seconds")))
    return directory


def write_marker(run: RunFolder) -> None:
    data = {"created": run.created, "name": run.name, "status": run.status, "years": run.years,
            "kept": run.kept, "label": run.label}
    with open(os.path.join(run.directory, MARKER), "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def read_run(directory: str) -> Optional[RunFolder]:
    """The run stored in ``directory`` (None if the folder is not a run folder)."""
    try:
        with open(os.path.join(directory, MARKER), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return RunFolder(directory, str(data.get("created", "")), str(data.get("name", "")),
                     str(data.get("status", RUNNING)), [str(y) for y in data.get("years", [])],
                     bool(data.get("kept", False)), str(data.get("label", "")))


def finish_run(directory: str, name: str, status: str, years: Iterable[str]) -> None:
    """Record the outcome of a run in its marker (kept flag and label are preserved)."""
    run = read_run(directory)
    if run is None:
        return
    run.name, run.status, run.years = name, status, list(years)
    write_marker(run)


def set_kept(directory: str, kept: bool, label: Optional[str] = None) -> None:
    run = read_run(directory)
    if run is None:
        raise ValueError(f"{directory}: not a run folder")
    run.kept = kept
    if label is not None:
        run.label = label
    write_marker(run)


def list_runs(root: str) -> List[RunFolder]:
    """Run folders directly under ``root``, oldest first."""
    if not root or not os.path.isdir(root):
        return []
    runs = []
    for entry in os.listdir(root):
        directory = os.path.join(root, entry)
        if os.path.isdir(directory):
            run = read_run(directory)
            if run is not None:
                runs.append(run)
    return sorted(runs, key=lambda r: (r.created, r.folder_name))


def latest_run(root: str) -> Optional[RunFolder]:
    runs = list_runs(root)
    return runs[-1] if runs else None


def default_deletion(runs: Sequence[RunFolder]) -> Set[str]:
    """Folders proposed for deletion: every run not kept.

    When no run is kept, the latest successful run is spared, so that the
    final results survive a quick "Delete" (decision of 29/09/2026).
    """
    spared = {r.directory for r in runs if r.kept}
    if not spared:
        successful = sorted((r for r in runs if r.status in SUCCESSFUL), key=lambda r: (r.created, r.folder_name))
        if successful:
            spared.add(successful[-1].directory)
    return {r.directory for r in runs if r.directory not in spared}


def delete_run(directory: str) -> List[str]:
    """Delete a run folder; return the files that could not be deleted (locked, read-only)."""
    if read_run(directory) is None:
        raise ValueError(f"{directory}: not a run folder, nothing deleted")
    failed: List[str] = []

    def on_error(function, path, error):
        failed.append(path)

    # Python >= 3.12 renames the callback; both receive (function, path, error).
    try:
        shutil.rmtree(directory, onexc=on_error)
    except TypeError:
        shutil.rmtree(directory, onerror=on_error)
    return [p for p in failed if os.path.exists(p)]


def folder_size(directory: str) -> int:
    total = 0
    for base, _, files in os.walk(directory):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total
