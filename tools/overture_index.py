"""Index of the Overture Maps building files: the box of each file, for each release still published.

    python tools/overture_index.py            # latest release (and the others still online, if missing)

With it, the plugin reads only the file(s) of the zone, instead of asking the 512 files of the release
(about 360 MB and 2 000 requests: half an hour on a slow line). A new release comes out every month:
run this, commit ``src/engine/downloads/overture_index/<release>.json``, and the plugin finds it on
GitHub (installed plugins too). Indexes of releases no longer published are removed. Needs a GDAL with the
Parquet driver (QGIS 3.40, or conda-forge ``gdal`` + ``libgdal-arrow-parquet``).
"""

from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from engine.downloads import overture  # noqa: E402
from engine.downloads.fetch import UrllibFetcher  # noqa: E402


def main(argv=None) -> int:
    if not overture.available():
        print("GDAL has no Parquet driver", file=sys.stderr)
        return 1
    fetcher = UrllibFetcher()
    online = overture.online_releases(fetcher)
    wanted = (argv or sys.argv[1:]) or online
    os.makedirs(overture.INDEX_DIR, exist_ok=True)
    for release in wanted:
        path = os.path.join(overture.INDEX_DIR, f"{release}.json")
        if os.path.exists(path):
            print(f"{release}: already indexed")
            continue
        start = time.perf_counter()
        index = overture.build_index(fetcher, release)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(index, handle, separators=(",", ":"))
        print(f"{release}: {len(index['files'])} files, {time.perf_counter() - start:.0f} s → {path}")
    for name in os.listdir(overture.INDEX_DIR):
        if name.endswith(".json") and name[:-5] not in online:
            os.remove(os.path.join(overture.INDEX_DIR, name))
            print(f"{name[:-5]}: no longer published, index removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
