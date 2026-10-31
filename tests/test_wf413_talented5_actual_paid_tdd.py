"""Talented 5/5 scenario: explicit ON/OFF and truly paid 26-point L30 candidates."""
import pytest
from src.game.talents import talented_bonus_for_level,talented_point_budget,apply_talent_selection
from src.game.data.forever.source_db_scope import ability_source_scope
from src.v2.source_bounded_joint_frontier import (bounded_full_point_talent_frontier,
    _prepare_joint_policy_candidate,source_talent_unlock_witnesses)
from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate
from tests.test_wf409_talent_unlock_paid_witness_tdd import SOURCE,_source,_stage


def test_talented_legacy_point_budget_is_earned_not_fabricated_after_cap():
    for level,expected in ((1,0),(4,0),(5,1),(9,5),(10,6),(20,16),(30,26),
                           (40,36),(55,51),(60,51)):
        assert talented_point_budget(level)==expected
    assert talented_point_budget(30,enabled=False)==21
    assert talented_point_budget(60,enabled=False)==51
    with pytest.raises(ValueError,match='talented_enabled'):
        talented_bonus_for_level(30,enabled=1)


def test_26_point_druid_legal_payed_policy_rejected_without_talented():
    with ability_source_scope(SOURCE):
        root=_source()
        frontier,proof=bounded_full_point_talent_frontier(root,level=30,
            bonus_talent_points=5,max_frontier=5)
        unlocked=next(a for a in frontier if a.get('primal_bite')==1)
        assert sum(unlocked.values())==26
        with pytest.raises(ValueError,match='budget'):
            apply_talent_selection(root,unlocked,level=30,bonus_talent_points=0)
        selected,application=apply_talent_selection(root,unlocked,level=30,bonus_talent_points=5)
        assert application.spent_points==application.available_points==26
        witness=next(w for w in source_talent_unlock_witnesses(root,selected,_stage())
            if w['action_id']=='primal_bite:25')
        candidate=_prepare_joint_policy_candidate(class_key='druid',level=30,
            stage=_stage(),allocation=unlocked,source_ir=root,
            allow_partial_gear_stats=True,policy_label='talent_unlock:primal_bite:25',
            policy=witness['policy'],bonus_talent_points=5)
        real=evaluate_persistent_candidate(candidate,level=30,mobs=4,max_total_events=200000)
        assert real['status']=='COMPLETE',real
        assert real['source_action_counts']['primal_bite:25']>0
