from __future__ import annotations

from pathlib import Path

from src.game.data.forever import build_game_ir_slice
from src.game.model import DamageEffect, PeriodicEffect
from src.game.policy import PriorityPolicy
from src.v2.generic_backend import _policy_combat_evaluation, build_partial_generic_records
from src.game.talents import apply_talent_selection, explicit_seed_selection


def _record(level: int):
    return build_partial_generic_records(class_names=("Druid",), selected_level=level)[0]


def test_g11_legal_rank_selection_uses_highest_source_backed_rank_at_or_below_level():
    ir20 = build_game_ir_slice(class_key="Druid", level=20)
    ids20 = {a.family_key: a.id for a in ir20.actions}
    assert ids20["wrath"] == "wrath:5178"  # rank learned 14
    assert ids20["moonfire"] == "moonfire:8925"  # rank learned 16

    ir28 = build_game_ir_slice(class_key="Druid", level=28)
    ids28 = {a.family_key: a.id for a in ir28.actions}
    assert ids28["wrath"] == "wrath:5179"  # rank learned 22
    assert ids28["moonfire"] == "moonfire:8927"  # rank learned 28

    ir34 = build_game_ir_slice(class_key="Druid", level=34)
    ids34 = {a.family_key: a.id for a in ir34.actions}
    assert ids34["wrath"] == "wrath:5180"  # rank learned 30
    assert ids34["moonfire"] == "moonfire:8928"  # rank learned 34


def test_g11_ir_contains_real_direct_and_periodic_actions():
    ir = build_game_ir_slice(class_key="Druid", level=28)
    by_family = {a.family_key: a for a in ir.actions}
    assert set(by_family) >= {"wrath", "moonfire"}
    assert any(isinstance(x, DamageEffect) for x in by_family["wrath"].effects)
    assert any(isinstance(x, DamageEffect) for x in by_family["moonfire"].effects)
    assert any(isinstance(x, PeriodicEffect) for x in by_family["moonfire"].effects)
    assert by_family["wrath"].costs[0].amount == 50.0
    assert by_family["moonfire"].costs[0].amount == 150.0


def test_g11_policy_executes_moonfire_then_wrath_and_refreshes_when_missing():
    source = build_game_ir_slice(class_key="Druid", level=28)
    talented, _ = apply_talent_selection(source, explicit_seed_selection(source, level=28), level=28)
    evaluation, execution, _ = _policy_combat_evaluation(talented, level=28)
    assert evaluation is not None
    assert execution is not None
    names = [x["action_name"] for x in execution.selected_actions]
    assert names[0] == "Moonfire"
    assert "Wrath" in names[1:]
    assert names.count("Moonfire") >= 2  # canonical G11 seed refreshes after expiry
    assert execution.timeline.target_defeated is True
    assert execution.timeline.periodic_damage > 0
    assert execution.timeline.direct_damage > 0

    rules = talented.policies[0].rules
    assert [x.id for x in rules] == ["periodic_if_missing", "direct_filler"]
    assert rules[0].conditions[1].kind == "aura_missing"


def test_g11_maintenance_phase_surfaces_motw_and_thorns_without_fake_per_pull_execution():
    record = _record(28)
    maintenance = record.policy["maintenance"]
    assert [x["family_key"] for x in maintenance] == ["mark_of_the_wild", "thorns"]

    motw, thorns = maintenance
    assert motw["resource_cost"] == 100.0
    assert motw["duration_s"] == 3600.0
    assert motw["effect"]["all_attributes"] == 5
    assert motw["execution_status"] == "deferred_stat_modifier_aura_runtime"

    assert thorns["resource_cost"] == 105.0
    assert thorns["duration_s"] == 600.0
    assert thorns["effect"]["reactive_nature_damage"] == 11
    assert thorns["execution_status"] == "executable_generic_event_trigger_runtime"

    assert record.capability["maintenance_policy"] is True
    assert record.capability["maintenance_execution"] is False
    assert "maintenance_aura_effect_execution" in record.unsupported_mechanics
    assert "incoming_hit_trigger_runtime" not in record.unsupported_mechanics
    assert "policy_search" not in record.unsupported_mechanics
    assert "policy_execution" not in record.unsupported_mechanics


def test_g11_active_evaluation_is_multi_action_and_still_fail_closed_for_full_leveling_score():
    record = _record(28)
    evaluation = record.provenance["evaluation"]
    assert evaluation["evaluation_scope"] == "combat_plus_recovery"
    assert evaluation["optimization_ready"] is False
    assert record.objective["mobs_per_hour"] is None
    assert record.timing["recovery_seconds_per_mob"] is not None
    assert record.timing["travel_seconds_per_mob"] is None
    assert record.objective["action_count"] == len(record.provenance["policy_execution"]["selected_actions"])
    assert record.objective["damage"]["periodic"] > 0


def test_g11_generic_policy_module_has_no_druid_or_spell_dispatch():
    text = Path("src/game/policy.py").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "druid" not in lowered
    assert "moonfire" not in lowered
    assert "wrath" not in lowered

def test_g11_listener_renders_seed_policy_without_class_specific_dispatch():
    from src import listener
    html = listener.DECISIONS_HTML
    assert "function genericPolicySummary(r)" in html
    assert "Canonical Policy IR" in html
    start = html.index("function genericPolicySummary(r)")
    end = html.index("function genericEvaluationSummary", start)
    renderer = html[start:end].lower()
    assert "druid" not in renderer
    assert "moonfire" not in renderer
    assert "wrath" not in renderer
    assert "mark of the wild" not in renderer
    assert "thorns" not in renderer
