from __future__ import annotations

from pathlib import Path
import threading
import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.policy_search import search_priority_policy
from src.game.talents import apply_talent_selection, explicit_seed_selection
from src.listener import DECISIONS_HTML
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore
from src.v2.generic_backend import _policy_combat_evaluation, build_partial_generic_records


def _talented_ir():
    source = build_game_ir_slice(class_key="Druid", level=20)
    selected = explicit_seed_selection(source, level=20)
    talented, _ = apply_talent_selection(source, selected, level=20)
    return talented


def test_g16_bounded_search_enumerates_inclusion_and_priority_without_threshold_mutation():
    ir = _talented_ir()
    seed = ir.policies[0]

    def evaluate(policy):
        ev, execution, _ = _policy_combat_evaluation(ir, level=20, policy_override=policy)
        return (None if ev is None else ev.seconds_per_mob, {"stop_reason": execution.stopped_reason})

    result = search_priority_policy(seed, evaluate=evaluate, max_candidates=64)
    assert result.search_performed is True
    assert len(result.candidates) == 4
    assert {tuple(x["rule_ids"]) for x in result.candidates} == {
        ("periodic_if_missing",),
        ("direct_filler",),
        ("periodic_if_missing", "direct_filler"),
        ("direct_filler", "periodic_if_missing"),
    }
    # G16 mutates only discrete inclusion/order. Numeric/action-cost conditions are copied exactly.
    selected = result.selected_policy
    assert selected is not None
    wrath_rule = selected.rules[0]
    assert wrath_rule.id == "direct_filler"
    assert wrath_rule.conditions == seed.rules[1].conditions
    assert wrath_rule.conditions[-1].threshold_source == "action_cost"


def test_g16_search_selects_real_better_policy_and_keeps_inferior_seed_visible():
    record = build_partial_generic_records(class_names=("Druid",), selected_level=20)[0]
    search = record.provenance["naked_policy_search"]
    assert search["candidate_count"] == 4
    assert search["valid_candidate_count"] == 4
    assert search["selected_candidate_id"] == "priority:direct_filler"
    assert search["selected_seconds_per_mob"] == pytest.approx(19.347826086956523)
    assert search["seed_seconds_per_mob"] == pytest.approx(21.73913043478261)
    assert search["improvement_vs_seed_seconds_per_mob"] == pytest.approx(2.391304347826086)
    seed = next(x for x in search["candidates"] if x["is_seed"])
    assert seed["valid"] is True
    assert seed["seconds_per_mob"] > search["selected_seconds_per_mob"]
    moonfire_only = next(x for x in search["candidates"] if x["rule_ids"] == ["periodic_if_missing"])
    # G29 teaches the generic executor to wake on queued runtime events.  A
    # Moonfire-only policy therefore remains alive while its already-scheduled
    # periodic ticks resolve instead of stopping early as "no legal action".
    assert moonfire_only["valid"] is True
    assert moonfire_only["seconds_per_mob"] == pytest.approx(75.78260869565217)
    assert moonfire_only["stop_reason"] is None


def test_g16_publication_marks_actual_search_and_selected_policy_not_seed():
    record = build_partial_generic_records(class_names=("Druid",), selected_level=20)[0]
    assert record.capability["policy_ir"] is True
    assert record.capability["policy_execution"] is True
    assert record.capability["policy_search"] is True
    assert "policy_search" not in record.unsupported_mechanics
    assert record.provenance["naked_policy_search"]["selected_candidate_id"] == "priority:direct_filler"
    assert record.capability["policy_search_dimensions"] == ["action_inclusion_exclusion", "priority_order", "numeric_condition_thresholds"]
    assert record.capability["policy_threshold_search"] is True
    naked_policy = record.provenance["naked_policy"]
    assert naked_policy["provenance"]["authority"] == "generic_policy_threshold_search"
    assert naked_policy["provenance"]["source_policy_authority"] == "canonical_game_ir"
    assert naked_policy["provenance"]["search_performed"] is True
    assert record.provenance["naked_policy_search"]["selected_candidate_id"] == "priority:direct_filler"
    assert record.provenance["naked_evaluation"]["provenance"]["producer"] == "generic_searched_policy_ir"
    assert record.provenance["naked_evaluation_seed"]["selection"] == "bounded searched Policy IR priority"
    assert record.provenance["naked_policy_search"]["selected_seconds_per_mob"] == pytest.approx(19.347826086956523)
    assert record.provenance["naked_evaluation"]["seconds_per_mob"] == pytest.approx(18.608695652173914)
    assert record.provenance["legacy_fallback"] is False


def test_g16_real_service_and_listener_surface_search_result(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    server = OptimizerHTTPServer(("127.0.0.1", 0), store, project_root=Path.cwd())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ServiceClient(f"http://127.0.0.1:{server.server_address[1]}", timeout=2)
        payload = client.decisions(level=20, backend_id="generic")
        record = next(r for r in payload["decisions"] if str(r["identity"]["class_name"]).lower() == "druid")
        assert record["capability"]["policy_search"] is True
        assert record["provenance"]["naked_policy_search"]["selected_candidate_id"] == "priority:direct_filler"
        assert record["provenance"]["naked_policy"]["provenance"]["authority"] == "generic_policy_threshold_search"
        assert record["provenance"]["naked_policy_search"]["candidate_count"] == 4
        assert record["provenance"]["naked_policy_search"]["selected_candidate_id"] == "priority:direct_filler"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)

    assert "const CURRENT_SOFTWARE_VERSION='0.11.48.153';" in DECISIONS_HTML
    assert "bounded search" in DECISIONS_HTML
    assert "searched Game IR policy" in DECISIONS_HTML
