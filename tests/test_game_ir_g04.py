from __future__ import annotations

from src.game.data.forever import build_game_ir_slice
from src.rulesets.forever.classes.druid import wowhead_facts as wh
from src.v2.generic_backend import build_partial_generic_records


def test_wrath_source_fact_normalizes_into_generic_game_ir():
    ir = build_game_ir_slice(class_key="druid", level=20)
    assert ir is not None
    assert ir.schema_version >= 5
    assert ir.actor.id == "player"
    assert ir.actor.actor_type == "player"
    assert [r.id for r in ir.resources[:2]] == ["mana", "health"]

    action = ir.actions[0]
    assert action.family_key == "wrath"
    assert action.name == "Wrath"
    assert action.id == "wrath:5178"
    assert action.requirements == ({"kind": "minimum_level", "value": 14},)
    assert action.costs[0].resource_id == "mana"
    assert action.costs[0].amount == 40.0
    assert action.cast_time_s == 2.0
    assert action.gcd_s == 1.5
    assert action.cooldown_s == 0.0

    effect = action.effects[0]
    assert effect.effect_type == "damage"
    assert effect.school == "nature"
    assert effect.base_min == 48.0
    assert effect.base_max == 55.5
    assert ir.source_facts[0]["damage_min"] == 32.0
    assert ir.source_facts[0]["damage_max"] == 37.0
    assert effect.spell_power_coefficient == 0.571
    assert action.provenance[0]["url"].endswith("spell=5178/wrath")
    assert ir.provenance["source_backed"] is True


def test_game_ir_reads_wrath_source_facts_instead_of_copying_scorer_constants(monkeypatch):
    original = wh.WRATH_RAW_TOOLTIP_RANKS
    monkeypatch.setattr(
        wh,
        "WRATH_RAW_TOOLTIP_RANKS",
        tuple(row for row in original if row[0] != 14) + ((14, 41, 1.9, 33, 38, 0.572),),
    )
    ir = build_game_ir_slice(class_key="druid", level=20)
    action = ir.actions[0]
    assert action.costs[0].amount == 41.0
    assert action.cast_time_s == 1.9
    assert action.effects[0].base_min == 49.5
    assert action.effects[0].base_max == 57.0
    assert ir.source_facts[0]["damage_min"] == 33.0
    assert ir.source_facts[0]["damage_max"] == 38.0
    assert action.effects[0].spell_power_coefficient == 0.572


def test_generic_backend_publishes_real_game_ir_for_druid_but_other_classes_fail_closed():
    druid, mage = build_partial_generic_records(
        class_names=("druid", "mage"), selected_level=20, ruleset="forever"
    )

    assert druid.backend["id"] == "generic"
    assert druid.capability["game_ir"] is True
    assert druid.capability["combat_evaluation"] is True
    assert druid.capability["optimization_ready"] is False
    assert druid.identity["route"] == "generic_game_ir"
    assert [a["name"] for a in druid.actions[:4]] == ["Wrath", "Moonfire", "Healing Touch", "Rejuvenation"]
    assert [r["id"] for r in druid.resources[:2]] == ["mana", "health"]
    assert druid.actors[0]["id"] == "player"
    assert "canonical_game_ir" not in druid.unsupported_mechanics
    assert druid.capability["event_runtime"] is True
    assert "combat_event_runtime" not in druid.unsupported_mechanics
    assert "resource_state_evaluation" not in druid.unsupported_mechanics
    assert "gcd_cooldown_readiness" not in druid.unsupported_mechanics
    assert druid.provenance["legacy_fallback"] is False
    assert druid.provenance["game_ir"]["provenance"]["source_backed"] is True
    assert druid.objective["mobs_per_hour"] is None

    assert mage.capability["game_ir"] is False
    assert mage.actions == ()
    assert "canonical_game_ir" in mage.unsupported_mechanics
    assert mage.provenance["legacy_fallback"] is False


def test_listener_exposes_game_ir_action_without_class_specific_renderer():
    from src import listener

    html = listener.DECISIONS_HTML
    assert "function genericActionSummary(a)" in html
    assert "Source-backed Game IR" in html
    assert "actions.slice(0,6).map(genericActionSummary)" in html
    # Generic renderer is effect/cost based, not a Wrath/Druid special case.
    start = html.index("function genericActionSummary(a)")
    end = html.index("function genericActorStateSummary", start)
    renderer = html[start:end]
    assert "druid" not in renderer.lower()
    assert "wrath" not in renderer.lower()
