import json

import numpy as np
import pytest

from engine.i18n import available_languages, catalog, format_number, message, translate
from engine.nonconvergence import MigrationSettings, NonConvergenceError, UNALLOCATED, migrate_with_policy
from engine.report import StepReport


def test_french_and_english_catalogs_have_the_same_codes():
    assert {"fr", "en"} <= set(available_languages())
    assert set(catalog("fr")) == set(catalog("en"))


def test_number_formats():
    assert format_number(171280.5, "fr") == "171 280"
    assert format_number(171280, "en") == "171,280"
    assert format_number(2.5, "fr") == "2,5"
    assert format_number(2.5, "en") == "2.5"
    assert format_number(1234567, "es") == "1.234.567"


def test_messages_in_both_languages():
    m = message("capacity_insufficient", deficit=1500)
    assert m.render("fr").startswith("Capacité insuffisante : 1 500 habitants")
    assert m.render("en").startswith("Insufficient capacity: 1,500 inhabitants")


def test_missing_language_falls_back_to_french():
    assert translate("status_success", "rn") == translate("status_success", "fr")


def test_non_convergence_error_carries_translatable_messages():
    with pytest.raises(NonConvergenceError) as error:
        migrate_with_policy(np.array([15.0, 10.0]), np.ones(2), np.array([8.0, 8.0]), np.full(2, 10.0),
                            np.zeros(2, bool), np.arange(2.0), np.zeros(2), MigrationSettings())
    assert "5 inhabitants" in error.value.messages[0].render("en")


def test_report_text_and_json_follow_the_language():
    outcome = migrate_with_policy(np.array([15.0, 10.0]), np.ones(2), np.array([8.0, 8.0]), np.full(2, 10.0),
                                  np.zeros(2, bool), np.arange(2.0), np.zeros(2),
                                  MigrationSettings(policy=UNALLOCATED))
    report = StepReport.from_outcome(2024, 2025, 22.0, 25.0, outcome)
    assert "Pas 2024 → 2025 : partiel" in report.to_text("fr")
    assert "Step 2024 → 2025: partial" in report.to_text("en")
    data = json.loads(report.to_json("en"))
    assert [m["code"] for m in data["messages"]] == [
        "capacity_insufficient", "no_convergence_no_receivers", "recorded_as_unallocated"]
