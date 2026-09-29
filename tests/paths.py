"""Paths of the test data (imported by the tests; conftest modules are not importable by name)."""

import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MURAMVYA = os.path.join(REPO, "data", "test", "muramvya")
REFERENCE = os.path.join(REPO, "reference_outputs", "muramvya")
