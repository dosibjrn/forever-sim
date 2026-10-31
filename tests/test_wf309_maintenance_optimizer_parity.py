"""WF309: the optimizer may delete old APLs, NEVER paid source upkeep."""
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice,registered_class_keys
from src.game.policy import remove_combat_policy_seeds_preserve_maintenance
from src.game.runtime import ActorState
from src.game.runtime.source_maintenance import _execute_source_maintenance_upkeep
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate


def test_source_upkeep_survives_combat_policy_stripping_without_apl_seed():
    ir=build_game_ir_slice(class_key='druid',level=20)
    cleaned=remove_combat_policy_seeds_preserve_maintenance(ir)
    assert len(cleaned.policies)==1
    assert not cleaned.policies[0].rules
    assert len(cleaned.policies[0].maintenance)==2
    actor=ActorState.from_ir(cleaned.actor,cleaned.resources,cleaned.modes)
    elapsed,casts,events=_execute_source_maintenance_upkeep(cleaned,actor)
    assert (elapsed,casts,events)==(3.,2,8)
    assert actor.resource_capacity['mana']>614
    # Repeating the operation is idempotent and cannot create new combat seeds.
    assert remove_combat_policy_seeds_preserve_maintenance(cleaned)==cleaned


def test_conflicting_upkeep_fails_closed_not_random_priority():
    ir=build_game_ir_slice(class_key='druid',level=20)
    policy=ir.policies[0]
    conflicting=dict(policy.maintenance[0]);conflicting['resource_cost']=999999
    poisoned=replace(ir,policies=(policy,replace(policy,maintenance=(conflicting,))))
    with pytest.raises(ValueError,match='CONFLICTING_SOURCE_MAINTENANCE'):
        remove_combat_policy_seeds_preserve_maintenance(poisoned)


def test_all_nine_class_policy_stripping_preserves_exact_upkeep_set():
    for cls in registered_class_keys():
        ir=build_game_ir_slice(class_key=cls,level=20)
        original={(x['maintenance_action_id'],x['aura_id']) for p in ir.policies for x in p.maintenance}
        clean=remove_combat_policy_seeds_preserve_maintenance(ir)
        retained={(x['maintenance_action_id'],x['aura_id']) for p in clean.policies for x in p.maintenance}
        assert retained==original
        assert not any(p.rules for p in clean.policies)


def test_real_paid_source_joint_search_l2_matches_first_persistent_pull():
    # Independent source search, no old build or known winning items seeded.
    # WF308 dropped maintenance from the search IR: same settings produced
    # 12.5642 s/mob L2 versus 16.8333 s/mob when replayed with paid upkeep.
    r=run_source_budgeted_joint_talents(
        class_key='druid',level=20,max_evaluations=120,
        evaluations_per_talent=40,initial_search=24,search_per_gear=24,
        max_gear_states=3,max_event_transitions=15000,
        policy_search_backend='stateful',
        stateful_family_budget_mode='measured_balanced',
        required_level_policy='observed')
    assert r['status']=='EVALUATED_BOUNDED'
    assert r['attempted']==120 and 0<r['event_transitions']<=15000
    candidate=prepare_candidate(class_key='druid',level=20,stage=r['winner'])
    actual=evaluate_persistent_candidate(candidate,level=20,mobs=1)
    assert actual['status']=='COMPLETE' and actual['maintenance_casts']==2
    assert abs(r['winner']['score_s_per_mob']-actual['mean_s_per_mob'])<1e-9
