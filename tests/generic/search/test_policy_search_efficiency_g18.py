from __future__ import annotations

from dataclasses import replace

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PolicyDefinition
from src.game.policy_search_efficiency import PolicyEvaluationCache, prune_dominated_rules
from src.game.talents import apply_talent_selection, explicit_seed_selection
from src.listener import DECISIONS_HTML
from src.v2.generic_backend import build_partial_generic_records


def _talented_ir():
    source = build_game_ir_slice(class_key="druid", level=20)
    selection = explicit_seed_selection(source, level=20)
    ir, _ = apply_talent_selection(source, selection, level=20)
    return ir


def _resource_threshold(rule, value: float):
    conditions = []
    for condition in rule.conditions:
        if condition.kind == "resource_threshold" and condition.resource_id == "mana":
            conditions.append(replace(condition, value=float(value), threshold_source=None))
        else:
            conditions.append(condition)
    return replace(rule, conditions=tuple(conditions))


def test_g18_conservative_dominance_prunes_unreachable_trailing_rule_only_when_proven():
    ir = _talented_ir()
    periodic, direct = ir.policies[0].rules

    dominated = PolicyDefinition(
        id="direct_then_periodic",
        label="direct then periodic",
        rules=(direct, periodic),
    )
    effective, pruned = prune_dominated_rules(dominated, actions=ir.actions)
    assert [r.id for r in effective.rules] == [direct.id]
    assert [x["rule_id"] for x in pruned] == [periodic.id]
    assert pruned[0]["reason"] == "earlier_rule_guaranteed_match_and_eligibility"

    # If the earlier direct rule requires MORE mana than the later periodic rule,
    # the later rule can become reachable in the 75..79 mana band and must stay.
    not_dominated = replace(
        dominated,
        rules=(_resource_threshold(direct, 80.0), _resource_threshold(periodic, 75.0)),
    )
    effective2, pruned2 = prune_dominated_rules(not_dominated, actions=ir.actions)
    assert [r.id for r in effective2.rules] == [direct.id, periodic.id]
    assert pruned2 == ()


def test_g18_cache_normalizes_action_cost_and_numeric_equivalent_policy():
    ir = _talented_ir()
    direct = ir.policies[0].rules[1]
    implicit = PolicyDefinition(id="implicit", label="implicit", rules=(direct,))
    numeric = PolicyDefinition(id="numeric", label="numeric", rules=(_resource_threshold(direct, 20.0),))
    calls = []

    def expensive(policy):
        calls.append(policy.id)
        return 1.0, {"marker": "evaluated"}

    cache = PolicyEvaluationCache(actions=ir.actions, expensive_evaluate=expensive)
    score1, detail1 = cache.evaluate(implicit)
    score2, detail2 = cache.evaluate(numeric)
    assert score1 == score2 == 1.0
    assert len(calls) == 1
    assert detail1["policy_cache_hit"] is False
    assert detail2["policy_cache_hit"] is True
    assert cache.as_dict()["expensive_evaluations_avoided"] == 1


def _mage_generic_record():
    """Build one source-backed Mage record without broad talent allocation search."""
    from unittest.mock import patch
    import src.game.talent_search as talent_search

    def seed_only(ir_slice, *, level, max_candidates=1024, bonus_talent_points=0):
        return ((explicit_seed_selection(ir_slice, level=level),), False)

    with patch.object(talent_search, "enumerate_legal_talent_allocations", side_effect=seed_only):
        # Keep the production cache test independent of Druid's separate
        # Cat/Claw energy probe; Druid L20 remains covered by direct G18 tests.
        return build_partial_generic_records(class_names=("Mage",), selected_level=20)[0]


def test_g18_active_search_reports_production_cache_efficiency():
    record = _mage_generic_record()
    seconds_per_mob = record.provenance["naked_evaluation"]["seconds_per_mob"]
    assert seconds_per_mob is not None and seconds_per_mob > 0
    policy_provenance = record.provenance["naked_policy"]["provenance"]
    candidate_id = policy_provenance["candidate_id"]
    assert isinstance(candidate_id, str) and candidate_id.startswith("priority:")
    assert "|thresholds:" in candidate_id
    assert policy_provenance["authority"] == "generic_policy_threshold_search"
    efficiency = record.provenance["naked_policy_search_efficiency"]
    assert efficiency == record.provenance["naked_policy"]["provenance"]["search_efficiency"]
    assert efficiency["requests"] >= efficiency["expensive_evaluations"] > 0
    assert efficiency["expensive_evaluations_avoided"] == efficiency["cache_hits"]
    assert efficiency["requests"] == efficiency["expensive_evaluations"] + efficiency["cache_hits"]
    assert efficiency["dominance_pruned_requests"] >= 0
    assert efficiency["dominance_pruned_rule_count"] >= 0
    assert record.capability["policy_search_pruning"] is True
    assert record.capability["policy_search_cache"] is True
    assert record.provenance["legacy_fallback"] is False


def test_g18_listener_surfaces_search_efficiency_and_version():
    assert "const CURRENT_SOFTWARE_VERSION='" in DECISIONS_HTML
    assert "simulations ${esc(eff.expensive_evaluations)}/${esc(eff.requests)}" in DECISIONS_HTML
    assert "dominance-pruned" in DECISIONS_HTML
    assert "cache hits" in DECISIONS_HTML


def test_g18_efficiency_kernel_has_no_class_or_spell_dispatch():
    source = open("src/game/policy_search_efficiency.py", "r", encoding="utf-8").read().lower()
    for forbidden in ("druid", "moonfire", "wrath", "mage", "paladin", "hunter"):
        assert forbidden not in source
