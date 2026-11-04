"""Rogue L20 P3 should spend native paid probes on real selected item stat deltas.

This is a Forever forwarding/selection test, not a claim that any native
mechanic or stat slope is positive. Production evaluations remain authoritative.
"""
from pathlib import Path
from types import SimpleNamespace

from tools import wf_gate_p3_live as p3


def test_rogue_l20_native_p3_uses_paid_item_sized_stat_probes(monkeypatch):
    import src.game.checkpoint_p3_smoke as smoke
    import src.game.data.forever.registry as registry
    import src.game.native_p3_item_options as native_options
    import src.v2.source_budgeted_gear as budgeted
    import src.v2.source_stateful_budgeted as stateful

    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-native")
    ir = SimpleNamespace(
        actor=SimpleNamespace(metadata={"class_key": "rogue", "level": 20}),
        policies=(), actions=(), auto_attacks=())
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **kwargs: ir)
    monkeypatch.setattr(
        p3, "_source_profile_build_ir",
        lambda root, source_ir, class_key, level, spec:
            (source_ir, {"profile": spec, "full_point_source_allocation": None}))

    requests = []
    native_payload = {"items": [{"item_id": 101}]}

    def native_query(binary, class_key, level, **kwargs):
        requests.append((binary, class_key, level, kwargs))
        return native_payload

    monkeypatch.setattr(native_options, "query_native_p3_item_options", native_query)
    record = {
        "fallback": "rogue:source-attack", "prefix": [],
        "score_s_per_mob": 10.0, "guarded_action": None,
        "guarded_conditions": [],
    }
    monkeypatch.setattr(budgeted, "run_source_budgeted_gear", lambda **kwargs: {
        "stages": [{"stage": "source_naked", "winner": record}],
        "sensitivity_history": [{
            "stage": "source_naked", "values": {"agility": 0.0}}],
        "stat_probe_axis_selection": {
            "selected_for_paid_probe": ["agility"]},
        "attempted": 40, "evaluated": 40,
        "status": "EVALUATED_NAKED_ONLY_NO_GEAR_ROLES",
        "source_context_sha256": "real-budget-context",
    })
    monkeypatch.setattr(stateful, "_make_policy", lambda *args, **kwargs:
                        SimpleNamespace(id="source-winner", provenance={}, rules=()))
    monkeypatch.setattr(smoke, "fast_p3_smoke_for_policy", lambda **kwargs: {
        "blockers": ["NONPOSITIVE_RELEVANT_WEIGHT:agility"],
        "source": "MYTHICSIM_NATIVE_ITEM_OPTIONS",
        "slots": {
            "chest": {"items": [{
                "item_id": 401, "name": "Native chest",
                "stat_values": {"agility": 15.0}}]},
            "ring": {"items": [{
                "item_id": 402, "name": "Native ring",
                "stat_values": {"agility": 10.0}}]},
        },
        "legal_item_count": 2,
        "tested_item_count": 2,
        "slot_count": 2,
        "tested_stat_assertions": 2,
        "verified_stat_assertions": 0,
        "native_item_options_status": "ok",
        "native_unverified_candidate_count": 0,
        "native_excluded_non_client_item_count": 0,
        "native_item_options_source": "selected-Rust",
    })
    # Both the initial scorer and any re-score must use the exact source
    # snapshot accepted before paid search, not a second native CLI query.
    original_smoke = smoke.fast_p3_smoke_for_policy
    scorer_snapshots = []

    def smoke_with_snapshot(**kwargs):
        scorer_snapshots.append(kwargs.get("native_options_response"))
        return original_smoke(**kwargs)

    monkeypatch.setattr(smoke, "fast_p3_smoke_for_policy", smoke_with_snapshot)
    captures = []

    def paid_witness(source_ir, **kwargs):
        captures.append(kwargs)
        return {
            "status": "MEASURED_ZERO_SOURCE_POLICY_WITNESS",
            "stat": "agility", "weight_s_saved_per_mob_per_unit": 0.0,
            "paid_evaluations": 2,
        }

    monkeypatch.setattr(budgeted, "paid_source_policy_stat_witness", paid_witness)
    result = p3.run_live(Path("."), "rogue", 20, spec="unrestricted")

    assert requests == [("selected-native", "rogue", 20,
                         {"spec": "unrestricted", "slot": "all"})]
    assert scorer_snapshots == [native_payload]
    assert scorer_snapshots[0] is native_payload
    assert len(captures) == 1
    assert captures[0]["stat"] == "agility"
    assert captures[0]["probe_deltas"] == (25.0, 15.0)
    assert captures[0]["max_evaluations"] == 4
    assert result["source_policy_stat_witnesses"][0]["probe_delta_sources"] == [
        {"kind": "two_distinct_native_item_slots", "delta": 25.0,
         "items": [
             {"slot": "chest", "item_id": 401,
              "name": "Native chest", "amount": 15.0},
             {"slot": "ring", "item_id": 402,
              "name": "Native ring", "amount": 10.0},
         ]},
        {"kind": "single_native_item", "delta": 15.0,
         "items": [{"slot": "chest", "item_id": 401,
                    "name": "Native chest", "amount": 15.0}]},
    ]
    assert result["status"] == "FAIL"
    assert result["real_source_search_evaluated"] == 42
    assert result["real_measured_stat_weights"]["agility"] == 0.0


def test_native_rogue_item_records_reuse_validated_snapshot_without_second_query():
    from src.game.native_p3_item_options import native_p3_item_records

    snapshot = {
        "status": "ok", "source": "selected-native",
        "unverified_candidate_count": 0,
        "excluded_non_client_item_count": 2775,
        "items": [{
            "item_id": 401, "name": "Native Rogue chest",
            "slot": "chest", "item_level": 12, "required_level": 10,
            "stats": {"Agility": 5.0},
        }],
    }

    def unexpected_query(*args, **kwargs):
        raise AssertionError("P3 must reuse the already accepted native response")

    records, unmapped, metadata = native_p3_item_records(
        "selected-native", "rogue", 20,
        native_response=snapshot, runner=unexpected_query)
    assert len(records) == 1
    assert records[0].item_id == 401
    assert records[0].agility == 5.0
    assert unmapped == {}
    assert metadata["excluded_non_client_item_count"] == 2775


def test_p3_forwards_selected_native_items_to_paid_equipped_executable(monkeypatch):
    import json
    import subprocess

    monkeypatch.setenv("FOREVER_P3_NATIVE_ROGUE_REQUEST", "/tmp/rogue-l20-source.json")
    invocations = []

    def native_script(command, **kwargs):
        invocations.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2,
            "comparison": {"baseline_dps": 10.0,
                           "equipped_dps": 11.0, "delta_dps": 1.0},
            "actor_checkpoint_verified": False,
        }))

    monkeypatch.setattr(subprocess, "run", native_script)
    slots = {"chest": {"selected_ids": [101, 102]}}
    result = p3._paid_native_equipped_probe(
        Path("."), "selected-native", {"slots": slots}, remaining=2)
    assert result["paid_attempts"] == 2
    assert result["comparison"]["delta_dps"] == 1.0
    assert len(invocations) == 1
    command, kwargs = invocations[0]
    assert command[-4:] == [
        "--binary", "selected-native", "--request", "/tmp/rogue-l20-source.json"]
    assert json.loads(kwargs["input"]) == slots
    assert kwargs["timeout"] == 150


def test_p3_native_equipped_pair_does_not_overrun_shared_paid_budget(monkeypatch):
    import subprocess

    monkeypatch.setenv("FOREVER_P3_NATIVE_ROGUE_REQUEST", "/tmp/native.json")
    monkeypatch.setattr(subprocess, "run",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("Do not spend beyond 44 evaluations")))
    result = p3._paid_native_equipped_probe(
        Path("."), "selected-native", {"slots": {}}, remaining=1)
    assert result == {
        "status": "NOT_RUN_PAID_BUDGET_EXHAUSTED", "paid_attempts": 0}
