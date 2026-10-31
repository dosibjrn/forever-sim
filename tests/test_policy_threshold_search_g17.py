from __future__ import annotations

from pathlib import Path
import threading
import pytest

from src.listener import DECISIONS_HTML
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore
from src.v2.generic_backend import build_partial_generic_records


def _record():
    return build_partial_generic_records(class_names=("Druid",), selected_level=20)[0]


def test_g17_threshold_search_selects_numeric_condition_that_beats_g16_structure():
    record = _record()
    search = record.provenance["naked_policy_threshold_search"]
    assert search["search_dimensions"] == ["action_inclusion_exclusion", "priority_order", "numeric_condition_thresholds"]
    assert search["candidate_count"] == 128
    assert search["valid_candidate_count"] == 114
    assert search["selected_seconds_per_mob"] == pytest.approx(18.608695652173914)
    assert record.provenance["naked_policy"]["provenance"]["improvement_vs_structural_seconds_per_mob"] == pytest.approx(0.7391304347826093)
    assert record.provenance["naked_policy"]["provenance"]["improvement_vs_seed_seconds_per_mob"] == pytest.approx(3.1304347826086953)


def test_g17_selected_policy_identity_and_conditions_publish_numeric_thresholds():
    record = _record()
    provenance = record.provenance["naked_policy"]["provenance"]
    assert provenance["authority"] == "generic_policy_threshold_search"
    assert provenance["threshold_search_performed"] is True
    assert provenance["threshold_values"] == {
        "periodic_if_missing.resource.mana": 75.0,
        "periodic_if_missing.target.health_pct": 0.1,
        "direct_filler.resource.mana": 20.0,
    }
    assert "target.health_pct=0.1" in provenance["candidate_id"]
    periodic, filler = record.provenance["naked_policy"]["rules"]
    health_gate = next(c for c in periodic["conditions"] if c.get("field") == "health_pct")
    assert health_gate == {"kind": "target_state", "field": "health_pct", "operator": "gte", "value": 0.1}
    periodic_mana = next(c for c in periodic["conditions"] if c.get("resource_id") == "mana")
    filler_mana = next(c for c in filler["conditions"] if c.get("resource_id") == "mana")
    assert periodic_mana["value"] == 75.0 and "threshold_source" not in periodic_mana
    assert filler_mana["value"] == 20.0 and "threshold_source" not in filler_mana


def test_g17_active_evaluation_and_capability_use_threshold_searched_policy():
    record = _record()
    assert record.provenance["naked_evaluation"]["kill_seconds_per_mob"] == pytest.approx(13.5)
    assert record.provenance["naked_evaluation"]["recovery_seconds_per_mob"] == pytest.approx(5.108695652173914)
    assert record.provenance["naked_evaluation"]["seconds_per_mob"] == pytest.approx(18.608695652173914)
    assert record.capability["policy_threshold_search"] is True
    assert record.capability["policy_search"] is True
    assert record.capability["policy_search_dimensions"] == ["action_inclusion_exclusion", "priority_order", "numeric_condition_thresholds"]
    assert "policy_threshold_search" not in record.unsupported_mechanics
    assert record.provenance["legacy_fallback"] is False
    # The optimized health gate suppresses the wasteful late Moonfire refresh.
    actions = [x["action_id"] for x in record.provenance["naked_policy_execution"]["selected_actions"]]
    assert actions.count("moonfire:8925") == 1
    assert actions.count("wrath:5178") == 8


def test_g17_real_service_and_listener_surface_threshold_policy(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    server = OptimizerHTTPServer(("127.0.0.1", 0), store, project_root=Path.cwd())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ServiceClient(f"http://127.0.0.1:{server.server_address[1]}", timeout=2)
        payload = client.decisions(level=20, backend_id="generic")
        record = next(r for r in payload["decisions"] if str(r["identity"]["class_name"]).lower() == "druid")
        assert record["capability"]["policy_threshold_search"] is True
        assert record["provenance"]["naked_policy"]["provenance"]["authority"] == "generic_policy_threshold_search"
        assert record["provenance"]["naked_policy"]["provenance"]["threshold_values"]["periodic_if_missing.target.health_pct"] == 0.1
        assert record["provenance"]["naked_evaluation"]["seconds_per_mob"] == pytest.approx(18.608695652173914)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)

    assert "const CURRENT_SOFTWARE_VERSION='0.11.48.153';" in DECISIONS_HTML
    assert "threshold-searched Game IR policy" in DECISIONS_HTML
    assert "target ${esc(c.field||'state')}" in DECISIONS_HTML
