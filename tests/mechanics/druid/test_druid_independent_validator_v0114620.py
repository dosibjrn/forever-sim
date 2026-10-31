from copy import deepcopy

import pytest

pytestmark = pytest.mark.skip(reason="historical L20/L40/L60 frozen oracle retired from active validation in v0.11.47.16")

from src.rulesets.forever.classes.druid.mechanics import experimental_level_score
from src.rulesets.forever.classes.druid.reference_validator import CASES, build_reference_report


def test_druid_independent_oracle_covers_l20_l40_l60_and_is_green():
    report = build_reference_report()
    assert report["production_helper_reuse"] is False
    assert report["levels"] == [20, 40, 60]
    assert report["ok"] is True
    assert all(row["allocation_points"] == row["level"] - 9 for row in report["rows"])


def test_druid_oracle_falsifies_wrong_profile_decision():
    def broken(level, talents, profile):
        row = deepcopy(experimental_level_score(level, talents, profile))
        if level == 40:
            row["profile"] = "cat"
            row["rotation"] = "Claw spam"
        return row
    report = build_reference_report(broken)
    assert report["ok"] is False
    row = next(x for x in report["rows"] if x["level"] == 40)
    assert any(x.startswith("profile:") for x in row["failures"])
    assert any(x.startswith("rotation_missing:") for x in row["failures"])


def test_druid_oracle_falsifies_resource_regression():
    def broken(level, talents, profile):
        row = deepcopy(experimental_level_score(level, talents, profile))
        if level == 60:
            row["incoming_damage_rage_rate_proxy"] = 0.0
            row["swipe_rate_per_s"] = 0.0
            row["maul_rate_per_s"] = 0.0
        return row
    report = build_reference_report(broken)
    assert report["ok"] is False
    row = next(x for x in report["rows"] if x["level"] == 60)
    assert any(x.startswith("incoming_damage_rage_rate_proxy:") for x in row["failures"])
    assert any(x.startswith("swipe_rate_per_s:") for x in row["failures"])
    assert any(x.startswith("maul_rate_per_s:") for x in row["failures"])


def test_druid_oracle_falsifies_throughput_regression():
    def broken(level, talents, profile):
        row = deepcopy(experimental_level_score(level, talents, profile))
        if level == 20:
            row["mobs_per_hour"] *= 0.5
        return row
    report = build_reference_report(broken)
    assert report["ok"] is False
    row = next(x for x in report["rows"] if x["level"] == 20)
    assert any(x.startswith("mobs_per_hour:") or x.startswith("mph_cycle_identity:") for x in row["failures"])
