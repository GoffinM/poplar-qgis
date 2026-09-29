"""Build the installable plugin: dist/poplar-<version>.zip (QGIS: Plugins > Install from ZIP).

The engine (src/engine) is copied into the plugin, so nothing else needs to
be installed. The help pages are regenerated first.

Usage: python tools/build_plugin.py
"""

import configparser
import os
import shutil
import subprocess
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "plugin", "poplar")
DIST = os.path.join(REPO, "dist")
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIXES = (".pyc", ".pyo")


def main() -> int:
    subprocess.run([sys.executable, os.path.join(REPO, "tools", "build_help.py")], check=True, stdout=subprocess.DEVNULL)
    parser = configparser.ConfigParser()
    parser.read(os.path.join(PLUGIN, "metadata.txt"), encoding="utf-8")
    version = parser.get("general", "version")
    os.makedirs(DIST, exist_ok=True)
    target = os.path.join(DIST, f"poplar-{version}.zip")
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        # os.walk(followlinks=True) resolves the engine symlink into a real copy.
        for folder, dirs, files in os.walk(PLUGIN, followlinks=True):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(files):
                if name.endswith(SKIP_SUFFIXES):
                    continue
                path = os.path.join(folder, name)
                archive.write(path, os.path.join("poplar", os.path.relpath(path, PLUGIN)))
                count += 1
    print(f"{target} ({count} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
