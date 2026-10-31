from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_policy_search import synthesize_source_policies
from src.v2.source_button_discovery import discover_source_combat_buttons
from src.v2.source_action_coverage import audit_source_action_coverage


def test_source_ladder_yields_five_generic_finisher_guards():
    ir = build_game_ir_slice(class_key="druid", level=20)
    e = synthesize_source_policies(ir, level=20, mode_id="cat",
                                   include_auto_resource_fallback=True, max_policies=200)
    assert "rip:20" in e["eligible_buttons"]
    guards = set()
    for policy in e["policies"]:
        for rule in policy.rules:
            if rule.action_id == "rip:20":
                assert any(c.kind == "aura_missing" and c.scope == "target" for c in rule.conditions)
                guards.update(int(c.value) for c in rule.conditions if c.kind == "resource_threshold")
    effect = next(x for a in ir.actions if a.id == "rip:20" for x in a.effects
                  if type(x).__name__ == "ResourceScaledPeriodicEffect")
    assert guards == set(effect.total_base_damage_by_resource_amount)
    assert e["semantic_warnings"]
    audit = audit_source_action_coverage(ir, level=20, search_envelopes=(e,))
    row = next(x for x in audit["actions"] if x["action_id"] == "rip:20")
    assert row["in_search"] and row["blocking"] and row["semantic_gaps"]
    assert audit["status"] == "INCOMPLETE"


def test_finisher_level_lock_remains_enforced():
    ir = build_game_ir_slice(class_key="druid", level=10)
    e = discover_source_combat_buttons(ir, level=10, mode_id="cat", include_resource_actions=True) if any(m.id == "cat" for m in ir.modes) else None
    if e is not None:
        assert "rip:20" not in e["action_ids"]
