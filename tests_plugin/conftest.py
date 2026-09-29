"""Plugin tests: they run inside QGIS (headless). Skipped when QGIS is not installed."""

import pytest

pytest.importorskip("qgis.core")

from qgis_env import FakeIface  # noqa: E402  (also starts QGIS)


@pytest.fixture
def iface():
    return FakeIface()


@pytest.fixture(scope="session")
def processing_ready():
    from processing.core.Processing import Processing

    Processing.initialize()
    return True
