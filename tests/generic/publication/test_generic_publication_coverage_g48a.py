"""G48a all-class generic DecisionRecord coverage and listener route authority."""

from pathlib import Path

import pytest

from src.game.data.forever.registry import registered_class_keys
from src.v2.decision_dashboard import _generic_decision_payload
from src.v2.generic_publication_coverage import SECTION_NAMES
from src.version import SOFTWARE_VERSION


@pytest.fixture(scope="module")
def generic_l10():
    return _generic_decision_payload(10)


@pytest.fixture(scope="module")
def generic_l20():
    return _generic_decision_payload(20)


def _rows(payload):
    return {r["identity"]["class_name"]: r for r in payload["decisions"]}


def _section(row, key):
    return row["capability"]["publication_sections"]["sections"][key]


def test_all_registered_classes_have_explicit_consistent_sections(generic_l10, generic_l20):
    for payload in (generic_l10, generic_l20):
        rows = _rows(payload)
        assert set(rows) == set(registered_class_keys())
        for name, row in rows.items():
            publication = row["capability"]["publication_sections"]
            assert publication["schema_version"] == 1
            assert tuple(publication["sections"]) == SECTION_NAMES
            assert all(x["status"] in {"available", "partial", "unavailable", "out_of_scope"}
                       and x["reason"] for x in publication["sections"].values())
            assert row["provenance"]["legacy_fallback"] is False
            assert _section(row, "fidelity_provenance")["status"] == "partial"
            assert _section(row, "timing")["status"] == "partial"  # no travel model
            assert _section(row, "policy")["status"] == "available"


def test_route_publication_matches_actual_native_route_not_stale_copy(generic_l10, generic_l20):
    druid = generic_l10["generic_class_routes"]["druid"]
    assert druid["normal_route_selectable"] is True
    assert druid["normal_route_selectable"] == generic_l10["generic_routes"]["normal_route_selectable"]
    assert druid["normal_route_step_count"] == generic_l10["generic_routes"]["normal_route_step_count"]
    for cls in ("druid", "warrior", "rogue"):
        assert _section(_rows(generic_l10)[cls], "route")["status"] == "partial"
        assert "not route-scored" in _section(_rows(generic_l10)[cls], "route")["reason"]
        assert _section(_rows(generic_l20)[cls], "route")["status"] == "out_of_scope"
    for cls in ("mage", "priest", "shaman", "warlock"):
        assert _section(_rows(generic_l10)[cls], "route")["status"] == "unavailable"
        assert _section(_rows(generic_l20)[cls], "route")["status"] == "unavailable"


def test_no_gear_or_stat_weight_invention(generic_l10):
    rows = _rows(generic_l10)
    for cls in ("priest", "shaman", "warlock", "warrior", "rogue"):
        assert _section(rows[cls], "gear")["status"] == "unavailable"
        assert _section(rows[cls], "stat_weights")["status"] == "unavailable"
        assert not rows[cls]["stat_weights"]
    for cls in ("druid", "mage"):
        assert _section(rows[cls], "gear")["status"] == "available"
        assert _section(rows[cls], "stat_weights")["status"] == "available"


def test_generic_listener_renders_all_sections_without_class_branches():
    source = Path("src/listener.py").read_text()
    assert "function genericPublicationCoverage(r)" in source
    assert "${genericPublicationCoverage(r)}" in source
    assert "Generic publication coverage" in source
    assert "selected_build','gear','stat_weights','policy','timing','route','fidelity_provenance" in source
    assert tuple(map(int, SOFTWARE_VERSION.split("."))) >= (0, 11, 48, 174)


def test_source_only_provider_without_ir_does_not_claim_fidelity():
    from src.v2.generic_publication_coverage import summarize_generic_sections
    record = {
        "identity": {"level": 10}, "gear": {}, "stat_weights": {},
        "talents": {}, "policy": {}, "timing": {},
        "fidelity": {"rating": "capability_limited"},
        "provenance": {"legacy_fallback": False, "game_ir": None},
    }
    result = summarize_generic_sections(record, class_metadata={}, route_publication=None)
    assert result["sections"]["fidelity_provenance"]["status"] == "unavailable"
    assert result["sections"]["selected_build"]["status"] == "unavailable"
    assert result["sections"]["route"]["status"] == "unavailable"
