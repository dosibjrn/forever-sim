from __future__ import annotations

from pathlib import Path
import pytest

from src.v2.decision_dashboard import build_decision_payload
from src.v2.generic_backend import build_partial_generic_records
from src.listener import DECISIONS_HTML
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore
import threading


EXPECTED_CATEGORIES = {
    "action_damage",
    "action_timing",
    "resource",
    "recovery",
    "talent",
    "policy",
    "unsupported_mechanic",
}


def _druid_generic(level: int = 20):
    return build_partial_generic_records(class_names=["Druid"], selected_level=level)[0]


def test_post_death_queued_damage_is_not_counted_by_canonical_evaluation():
    from src.game.data.forever import build_game_ir_slice
    from src.game.talents import apply_talent_selection, explicit_seed_selection
    from src.v2.generic_backend import _policy_combat_evaluation
    source = build_game_ir_slice(class_key="Druid", level=20)
    talented, _ = apply_talent_selection(source, explicit_seed_selection(source, level=20), level=20)
    evaluation_obj, execution, _ = _policy_combat_evaluation(talented, level=20)
    evaluation = evaluation_obj.as_dict()
    timeline = execution.timeline.as_dict()
    damage = evaluation["diagnostics"]["damage"]

    assert damage["ignored_after_target_death_count"] >= 1
    assert damage["accounting_delta_vs_runtime"] == pytest.approx(0.0, abs=1e-12)
    assert damage["total"] == pytest.approx(timeline["total_damage"], abs=1e-12)
    assert damage["runtime_total_damage"] == pytest.approx(timeline["total_damage"], abs=1e-12)
    ignored = [
        e for e in timeline["events"]
        if e["kind"] == "Damage" and e["payload"].get("applied") is False
    ]
    assert ignored
    assert all(e["payload"].get("ignored_reason") == "target_dead" for e in ignored)


def test_compare_backend_decomposes_real_druid_caster_delta(tmp_path):
    # The packaged project root carries the authoritative legacy artifacts; tmp_path
    # is intentionally not used because compare needs those independent publications.
    payload = build_decision_payload(selected_level=20, backend_id="compare")
    assert payload["active_backend"] == "compare"
    assert payload["product_surface"]["comparison"] is True
    assert payload["decisions"] == []
    assert set(payload["class_metadata"]) == {"druid"}

    comparison = payload["comparisons"][0]
    assert comparison["status"] == "classified"
    assert comparison["unexplained_categories"] == []
    assert set(comparison["categories"]) == EXPECTED_CATEGORIES
    assert comparison["authority"]["legacy_values_feed_generic_execution"] is False

    talent = comparison["categories"]["talent"]
    assert talent["shared_ranks"] == {"improved_wrath": 5}
    assert talent["legacy_only_or_different"]["genesis"] == 3
    assert talent["legacy_only_or_different"]["improved_moonfire"] == 2
    assert talent["legacy_only_or_different"]["natures_majesty"] == 1

    damage = comparison["categories"]["action_damage"]["generic"]
    assert damage["damage_accounting_delta"] == pytest.approx(0.0, abs=1e-12)
    assert damage["runtime_applied_damage"] == pytest.approx(damage["evaluation_accounted_damage"], abs=1e-12)
    assert damage["ignored_after_target_death_count"] >= 0
    assert comparison["resolved_generic_mismatches"] == []


def test_compare_catalogue_and_listener_are_backend_neutral_surfaces():
    generic = build_decision_payload(selected_level=20, backend_id="generic")
    assert {x["id"] for x in generic["backends"]} == {"legacy", "generic", "compare"}
    assert 'function renderBackendComparison()' in DECISIONS_HTML
    assert "Comparison is oracle-only" in DECISIONS_HTML
    assert "legacy values do not feed generic execution" in DECISIONS_HTML


def test_compare_is_available_through_real_service_decision_api(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    server = OptimizerHTTPServer(("127.0.0.1", 0), store, project_root=Path.cwd())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ServiceClient(f"http://127.0.0.1:{server.server_address[1]}", timeout=2)
        payload = client.decisions(level=20, backend_id="compare")
        assert payload["active_backend"] == "compare"
        assert payload["comparisons"][0]["status"] == "classified"
        assert payload["comparisons"][0]["authority"]["legacy_values_feed_generic_execution"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
