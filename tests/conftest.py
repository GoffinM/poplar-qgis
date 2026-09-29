import os

import pytest

from engine._gdal import srs_from_epsg

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MURAMVYA = os.path.join(REPO, "data", "test", "muramvya")
REFERENCE = os.path.join(REPO, "reference_outputs", "muramvya")


@pytest.fixture(scope="session")
def utm35s_wkt():
    return srs_from_epsg(32735).ExportToWkt()
