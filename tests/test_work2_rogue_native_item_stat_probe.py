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

    def native_query(binary, class_key, level, **kwargs):
        requests.append((binary, class_key, level, kwargs))
        return {"items": [{"item_id": 101}]}

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
