"""Shaman L20 P3: native rank-915 source witness → bounded Intellect probe.

Only Forever's witness scheduling/response propagation is mocked here. These
fixtures are not gate evidence or a substitute for the real no-record run.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    ("native_rank_915_applied", "intellect_positive"),
    [(True, True), (True, False), (False, True)],
)
def test_shaman_intellect_follows_native_spell_power_only(
        monkeypatch, native_rank_915_applied, intellect_positive):
    import src.game.checkpoint_p3_smoke as smoke_module
    import src.game.data.forever.registry as registry
    import src.game.native_p3_item_options as native
    import src.v2.source_budgeted_gear as gear
    import src.v2.source_stateful_budgeted as stateful
    import tools.wf_gate_p3_live as p3

    ir = SimpleNamespace(
        id="shaman-l20-source-fixture",
        actor=SimpleNamespace(metadata={"class_key": "shaman", "level": 20}),
        actions=(SimpleNamespace(id="lightning_bolt", cooldown_s=0),),
        auto_attacks=(), policies=(),
    )
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **_kw: ir)
    monkeypatch.setattr(
        p3, "_source_profile_build_ir",
        lambda _root, source_ir, _class, _level, _spec:
            (source_ir, {"profile": "unrestricted"}),
    )
    monkeypatch.setattr(smoke_module, "policy_uses_weapon_damage",
                        lambda *_args: False)
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-native")
    monkeypatch.setattr(
        native, "query_native_shaman_spell_coefficients",
        lambda _binary: {
            "source": "MYTHICSIM_RUST_PREPARED_V2_PLAYER_SPELLS",
            "engine_revision": "selected-fixture",
        },
    )
    monkeypatch.setattr(
        native, "apply_native_shaman_lightning_bolt_coefficient",
        lambda source_ir, _facts: (
            source_ir,
            [{"action_id": "lightning_bolt", "spell_id": 915}]
            if native_rank_915_applied else [],
        ),
    )

    record = {
        "status": "evaluated", "fallback": "lightning_bolt",
        "prefix": ["shaman:lightning_bolt"],
        "score_s_per_mob": 12.0,
        "guarded_action": None, "guarded_conditions": [],
    }
    search = {
        "stages": [{"stage": "source_naked", "winner": record}],
        "sensitivity_history": [{
            "stage": "source_naked",
            "values": {"spell_power": 0.0, "intellect": 0.0, "agility": 0.0},
        }],
        "attempted": 35, "evaluated": 35,
        "status": "EVALUATED_BOUNDED",
        "source_context_sha256": "fixture-source",
    }
    monkeypatch.setattr(gear, "run_source_budgeted_gear",
                        lambda **_kw: search)
    monkeypatch.setattr(gear, "paid_search_winner_baseline",
                        lambda *_args: 12.0)
    policy = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted"},
        rules=(),
    )
    monkeypatch.setattr(stateful, "_make_policy",
                        lambda *_args, **_kw: policy)

    def native_smoke(**kwargs):
        weights = kwargs["weights"]
        blockers = ["NONPOSITIVE_RELEVANT_WEIGHT:agility"]
        if weights.get("spell_power", 0.0) <= 0:
            blockers.append("NONPOSITIVE_RELEVANT_WEIGHT:spell_power")
        if weights.get("intellect", 0.0) <= 0:
            blockers.append("NONPOSITIVE_RELEVANT_WEIGHT:intellect")
        return {
            "source": "MYTHICSIM_NATIVE_ITEM_OPTIONS",
            "blockers": blockers,
            "legal_item_count": 2, "tested_item_count": 2,
            "slot_count": 2, "tested_stat_assertions": 6,
            "verified_stat_assertions": 6 - len(blockers),
            "slots": {
                "chest": {"items": [{
                    "item_id": 101, "name": "Native chest",
                    "stat_values": {
                        "spell_power": 8.0, "intellect": 12.0, "agility": 5.0,
                    },
                }]},
                "legs": {"items": [{
                    "item_id": 102, "name": "Native legs",
                    "stat_values": {"intellect": 7.0},
                }]},
            },
            "native_item_options_status": "ok",
            "native_unverified_candidate_count": 0,
            "native_item_options_source": "mythicsim:fixture",
        }

    monkeypatch.setattr(smoke_module, "fast_p3_smoke_for_policy",
                        native_smoke)
    calls = []

    def witness(_ir, **kwargs):
        calls.append(kwargs)
        axis = kwargs["stat"]
        positive = axis == "spell_power" or intellect_positive
        return {
            "stat": axis,
            "status": ("MEASURED_POSITIVE_SOURCE_POLICY_WITNESS"
                       if positive else "NO_POSITIVE_SOURCE_POLICY_WITNESS"),
            "paid_evaluations": 1,
            "policy_id": policy.id,
            "baseline_seconds_per_mob": 12.0,
            "perturbed_seconds_per_mob": 11.0 if positive else 12.0,
            "weight_s_saved_per_mob_per_unit": 0.05 if positive else 0.0,
        }

    monkeypatch.setattr(gear, "paid_source_policy_stat_witness", witness)
    report = p3.run_live(Path("."), "shaman", 20, spec="unrestricted")

    expected_axes = (["spell_power", "intellect"]
                     if native_rank_915_applied else ["spell_power"])
    assert [call["stat"] for call in calls] == expected_axes
    assert all(call["max_evaluations"] <= 44 - 35 for call in calls)
    assert all(call["preferred_policy"] is policy for call in calls
               if native_rank_915_applied)
    assert all(call["opening_action_ids"] == ("shaman:lightning_bolt",)
               for call in calls)
    assert calls[0]["probe_deltas"] == (8.0,)
    if native_rank_915_applied:
        assert calls[1]["probe_deltas"] == (19.0, 12.0)
        assert report["source_policy_stat_witnesses"][1][
            "probe_delta_sources"][0]["kind"] == (
                "two_distinct_native_item_slots")
    assert report["behavior_probes_executed"] == 35 + len(calls) <= 44
    assert report["native_paid_winner_spell_probe_enabled"] == (
        native_rank_915_applied)
    assert report["real_measured_stat_weights"]["intellect"] == (
        0.05 if native_rank_915_applied and intellect_positive else 0.0)
    assert report["status"] == "FAIL"
