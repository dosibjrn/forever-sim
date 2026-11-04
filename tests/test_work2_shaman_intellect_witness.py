"""Work2 regressions for the native Shaman L20 Intellect P3 witness."""
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _run(monkeypatch, *, fallback="lightning_bolt:915",
         spell_power_weight=0.03283717129264803, attempted=41,
         query_error=None, intellect_positive=True):
    import src.game.checkpoint_p3_smoke as smoke
    import src.game.data.forever.registry as registry
    import src.game.native_p3_item_options as native
    import src.v2.source_budgeted_gear as budgeted
    import src.v2.source_stateful_budgeted as stateful
    import tools.wf_gate_p3_live as p3

    ir = SimpleNamespace(
        actor=SimpleNamespace(metadata={"class_key": "shaman", "level": 20}),
        policies=(), auto_attacks=(),
        actions=(SimpleNamespace(id="lightning_bolt:915", cooldown_s=0),
                 SimpleNamespace(id="rockbiter:8019", cooldown_s=0)))
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **kw: ir)
    monkeypatch.setattr(p3, "_source_profile_build_ir",
                        lambda root, src, cls, lvl, spec:
                        (src, {"profile": spec, "full_point_source_allocation": None}))
    monkeypatch.setattr(p3, "_p3_stat_witness_priority",
                        lambda _ir, _policy: ("spell_power", "intellect", "agility"))
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "native-shaman-test")

    prefix = ["rockbiter:8019", "lightning_bolt:915"]
    record = {"status": "evaluated", "fallback": fallback, "prefix": prefix,
              "score_s_per_mob": 12.5, "guarded_action": None,
              "guarded_conditions": [],
              "selected_actions": [{"action_id": x} for x in prefix]}
    monkeypatch.setattr(budgeted, "run_source_budgeted_gear", lambda **kw: {
        "stages": [{"stage": "source_naked", "winner": record}],
        "sensitivity_history": [{"stage": "source_naked", "values": {
            "spell_power": spell_power_weight, "intellect": 0.0,
            "agility": 0.0, "attack_power": 0.0, "mp5": 0.0, "spirit": 0.0}}],
        "attempted": attempted, "evaluated": attempted,
        "status": "EVALUATED_BOUNDED", "source_context_sha256": "test-source"})
    winner = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted", "search_performed": True},
        rules=(SimpleNamespace(id="fallback:0", action_id=fallback, conditions=()),))
    monkeypatch.setattr(stateful, "_make_policy", lambda *a, **kw: winner)
    monkeypatch.setattr(budgeted, "paid_search_winner_baseline",
                        lambda *a, **kw: 12.5)

    def query(_binary):
        if query_error:
            raise native.NativeItemOptionsError(query_error)
        return {"source": "MYTHICSIM_RUST_PREPARED_V2_PLAYER_SPELLS",
                "engine_revision": "native-test",
                "spell_power_coefficients": {915: 0.714}}
    applied = [{"action_id": "lightning_bolt:915", "spell_id": 915,
                "spell_power_coefficient": 0.714}]
    monkeypatch.setattr(native, "query_native_shaman_spell_coefficients", query)
    monkeypatch.setattr(native, "apply_native_shaman_lightning_bolt_coefficient",
                        lambda src, facts: (src, [] if query_error else applied))

    smoke_calls = []
    def native_smoke(**kw):
        smoke_calls.append(kw)
        weights = kw["weights"]
        blockers = [f"NONPOSITIVE_RELEVANT_WEIGHT:{axis}"
                    for axis in ("spell_power", "intellect", "agility")
                    if weights.get(axis, 0.0) == 0.0]
        return {
            "blockers": blockers,
            "slots": {
                "chest": {"items": [{"item_id": 401, "name": "Native chest",
                                     "stat_values": {"spell_power": 20.0,
                                                     "intellect": 12.0}}]},
                "ring": {"items": [{"item_id": 402, "name": "Native ring",
                                    "stat_values": {"spell_power": 15.0,
                                                    "intellect": 8.0}}]}},
            "legal_item_count": 1955, "tested_item_count": 85, "slot_count": 17,
            "tested_stat_assertions": 204,
            "verified_stat_assertions": (
                93 if len(smoke_calls) == 1 or not intellect_positive else 95),
            "source": "MYTHICSIM_NATIVE_ITEM_OPTIONS", "native_item_options_status": "ok",
            "native_unverified_candidate_count": 0,
            "native_excluded_non_client_item_count": 3075,
            "native_item_options_source": "mythicsim:ItemSparse+SkillLine+SkillRaceClassInfo"}
    monkeypatch.setattr(smoke, "fast_p3_smoke_for_policy", native_smoke)

    calls = []
    def witness(_ir, **kw):
        calls.append(kw)
        axis = kw["stat"]
        positive = axis == "spell_power" or intellect_positive
        result = {
            "status": ("MEASURED_POSITIVE_SOURCE_POLICY_WITNESS" if positive
                       else "NO_POSITIVE_SOURCE_POLICY_WITNESS"),
            "stat": axis,
            "paid_evaluations": 1,
            "attempted_policies": ["forever:shaman:hybrid@20"],
            "attempted_policy_sources": ["source_ir_policy"],
        }
        if positive:
            result.update({
                "weight_s_saved_per_mob_per_unit": (
                    0.01 if axis == "spell_power" else 0.02),
                "baseline_seconds_per_mob": 20.0,
                "perturbed_seconds_per_mob": 19.0,
                "delta": kw["probe_deltas"][0],
                "probe_deltas": list(kw["probe_deltas"]),
                "policy_id": "forever:shaman:hybrid@20",
                "policy_source": "source_ir_policy",
                "opening_action_ids": list(kw["opening_action_ids"]),
            })
        return result
    monkeypatch.setattr(budgeted, "paid_source_policy_stat_witness", witness)
    return p3.run_live(ROOT, "shaman", 20, spec="unrestricted"), record, winner, calls, smoke_calls


def test_intellect_follows_exact_native_rank_915_spell_power_witness(monkeypatch):
    result, record, winner, calls, smoke_calls = _run(monkeypatch)
    assert [call["stat"] for call in calls] == ["spell_power", "intellect"]
    assert calls[0]["preferred_policy"] is winner
    assert calls[1]["preferred_policy"] is winner
    assert calls[1]["baseline_record"]["fallback"] == "lightning_bolt:915"
    assert calls[1]["allow_paid_winner_after_nonpositive"] is True
    assert calls[1]["probe_deltas"] == (20.0, 12.0)
    rows = result["source_policy_stat_witnesses"]
    assert [row["stat"] for row in rows] == ["spell_power", "intellect"]
    intellect = rows[1]
    assert intellect["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS"
    assert intellect["policy_id"] == "forever:shaman:hybrid@20"
    assert intellect["opening_action_ids"] == record["prefix"]
    assert intellect["baseline_seconds_per_mob"] > intellect["perturbed_seconds_per_mob"] > 0
    assert intellect["probe_delta_sources"][0]["kind"] == "two_distinct_native_item_slots"
    assert intellect["probe_delta_sources"][0]["items"] == [
        {"slot": "chest", "item_id": 401, "name": "Native chest", "amount": 12.0},
        {"slot": "ring", "item_id": 402, "name": "Native ring", "amount": 8.0}]
    assert result["native_spell_coefficients_applied"][0]["action_id"] == "lightning_bolt:915"
    assert result["native_paid_winner_spell_probe_enabled"] is True
    assert result["real_measured_stat_weights"]["intellect"] == 0.02
    assert result["pass_count"] == 95 and result["reachability_count"] == 204
    assert result["real_source_search_evaluated"] == 43
    assert result["behavior_probes_executed"] <= 44
    assert len(smoke_calls) == 2


def test_nonpositive_intellect_does_not_increase_weight_or_p3_assertions(monkeypatch):
    result, _record, _winner, calls, smoke_calls = _run(
        monkeypatch, intellect_positive=False)

    assert [call["stat"] for call in calls] == ["spell_power", "intellect"]
    witnesses = result["source_policy_stat_witnesses"]
    assert [row["status"] for row in witnesses] == [
        "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS",
        "NO_POSITIVE_SOURCE_POLICY_WITNESS",
    ]
    intellect = witnesses[1]
    assert intellect["probe_delta_sources"][0]["kind"] == (
        "two_distinct_native_item_slots")
    assert "baseline_seconds_per_mob" not in intellect
    assert result["real_measured_stat_weights"]["intellect"] == 0.0
    assert result["pass_count"] == 93
    assert result["reachability_count"] == 204
    assert result["real_source_search_evaluated"] == 43
    assert result["behavior_probes_executed"] <= 44
    # The re-score is still required for the positive Spell Power witness,
    # but a nonpositive Intellect probe cannot add item assertions.
    assert len(smoke_calls) == 2


def test_intellect_is_not_probed_for_non_rank_915_fallback(monkeypatch):
    result, _record, _winner, calls, _smokes = _run(
        monkeypatch, fallback="rockbiter:8019", spell_power_weight=0.0, attempted=40)
    assert [call["stat"] for call in calls] == ["spell_power"]
    assert calls[0]["preferred_policy"] is None
    assert calls[0]["baseline_record"] is None
    assert calls[0]["allow_paid_winner_after_nonpositive"] is False
    assert all(row["stat"] != "intellect" for row in result["source_policy_stat_witnesses"])
    assert result["real_source_search_evaluated"] == 41


def test_intellect_is_not_probed_without_native_rank_915_coefficient(monkeypatch):
    result, _record, _winner, calls, _smokes = _run(
        monkeypatch, spell_power_weight=0.0, attempted=40,
        query_error="P3_NATIVE_SHAMAN_LIGHTNING_BOLT_915_COEFFICIENT_UNAVAILABLE")
    assert calls == []
    assert result["native_spell_coefficients_applied"] == []
    assert result["native_spell_coefficients_error"] == (
        "P3_NATIVE_SHAMAN_LIGHTNING_BOLT_915_COEFFICIENT_UNAVAILABLE")
    assert result["source_policy_stat_witnesses"] == []
    assert result["pass_count"] == 93 and result["reachability_count"] == 204
