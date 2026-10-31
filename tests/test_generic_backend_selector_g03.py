from __future__ import annotations

import pytest

from src.v2 import decision_dashboard
from src.v2.generic_backend import build_partial_generic_records


def test_generic_backend_publishes_without_reading_legacy_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(decision_dashboard, "CLASSES", ("druid",))
    # G38 separates legacy-visible and generic-only class registries; this
    # original isolation test scopes both inputs explicitly to one class.
    monkeypatch.setattr(decision_dashboard, "registered_class_keys", lambda: ("druid",))

    def legacy_read_must_not_happen(*args, **kwargs):
        raise AssertionError("generic backend consulted legacy publication")

    monkeypatch.setattr(decision_dashboard, "read_published_class_artifact", legacy_read_must_not_happen)
    monkeypatch.setattr(decision_dashboard, "read_json", legacy_read_must_not_happen)

    payload = decision_dashboard.build_decision_payload(
        tmp_path, selected_level=20, backend_id="generic"
    )
    assert payload["active_backend"] == "generic"
    # G32 supersedes the original G03 no-route product state: generic route
    # navigation is now native and still must remain legacy-independent.
    assert payload["product_surface"]["route_navigation"] is True
    assert payload["generic_routes"]["legacy_fallback"] is False
    assert [x["id"] for x in payload["backends"]] == ["legacy", "generic", "compare"]
    assert len(payload["decisions"]) == 1
    row = payload["decisions"][0]
    assert row["backend"]["id"] == "generic"
    assert row["objective"]["mobs_per_hour"] is None
    assert row["capability"]["combat_evaluation"] is True
    assert row["capability"]["optimization_ready"] is False
    assert row["objective"]["evaluation_scope"] == "combat_plus_recovery"
    assert row["capability"]["recovery_evaluation"] is True
    assert row["capability"]["event_runtime"] is True
    assert row["provenance"]["legacy_fallback"] is False
    assert row["compatibility"] == {}
    assert "combat_event_runtime" not in row["unsupported_mechanics"]
    assert "resource_state_evaluation" not in row["unsupported_mechanics"]
    assert "gcd_cooldown_readiness" not in row["unsupported_mechanics"]
    assert row["capability"]["resource_state_evaluation"] is True
    assert row["capability"]["gcd_cooldown_readiness"] is True


def test_partial_generic_producer_is_backend_neutral_across_classes():
    records = build_partial_generic_records(class_names=("druid", "mage"), selected_level=31)
    assert [r.backend["id"] for r in records] == ["generic", "generic"]
    assert [r.identity["class_name"] for r in records] == ["druid", "mage"]
    assert all(r.identity["level"] == 31 for r in records)
    assert all(r.provenance["legacy_fallback"] is False for r in records)
    assert all(not r.compatibility for r in records)


def test_unknown_backend_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="backend must be one of"):
        decision_dashboard.build_decision_payload(tmp_path, backend_id="mystery")


def test_listener_has_backend_selector_and_requests_selected_backend():
    from src import listener

    html = listener.DECISIONS_HTML
    assert 'id="backendPick"' in html
    assert "backend=${encodeURIComponent(state.backend)}" in html
    assert "backendExplicit?" in html
    assert "function renderBackendPublication()" in html
    assert "legacy fallback ${r.provenance?.legacy_fallback===false?'disabled':'not declared'}" in html


def test_service_client_sends_backend_selector(monkeypatch):
    from src.service.client import ServiceClient

    seen = {}
    def fake(self, method, path, body=None, **kwargs):
        seen['method'] = method
        seen['path'] = path
        return {'active_backend': 'generic'}

    monkeypatch.setattr(ServiceClient, '_request', fake)
    out = ServiceClient().decisions(level=27, backend_id='generic')
    assert out['active_backend'] == 'generic'
    assert seen['method'] == 'GET'
    assert '/api/v1/decisions?' in seen['path']
    assert 'backend=generic' in seen['path']
    assert 'level=27' in seen['path']
