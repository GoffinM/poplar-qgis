#!/bin/bash
# Installs the development tools of the engine (GDAL, numpy, scipy, pytest)
# in Claude Code on the web sessions. These libraries ship with QGIS: they
# are not new runtime dependencies of the plugin.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PYTHON=/usr/bin/python3.12
if "$PYTHON" -c "from osgeo import gdal; import numpy, scipy, pytest" >/dev/null 2>&1; then
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
# Some third-party apt sources may be unreachable through the proxy; the
# Ubuntu archive is enough, so a partial update is not fatal.
apt-get update -qq || true
apt-get install -y -qq python3-gdal python3-numpy python3-scipy python3-pytest gdal-bin >/dev/null

"$PYTHON" -c "from osgeo import gdal; import numpy, scipy, pytest; print('GDAL', gdal.__version__)"
