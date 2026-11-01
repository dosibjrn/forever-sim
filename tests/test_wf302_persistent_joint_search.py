"""WF302: verify current source winner on real production CombatRuntime, no oracle."""
from pathlib import Path
import json
from copy import deepcopy
import pytest
from src.v2.source_persistent_joint_finalists import (
    prepare_candidate, evaluate_persistent_candidate, select_persistent_finalists,
    run_source_persistent_joint_search,run_source_persistent_profile_search,
)

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'WF299_DRUID_L20_30S_BLIND_EVIDENCE.json'


def _winner():
    return json.loads(SOURCE.read_text())['winner']


def test_100_mob_continuity_from_source_winner_no_existing_oracle():
    candidate=prepare_candidate(class_key='druid',level=20,stage=_winner())
    screen=evaluate_persistent_candidate(candidate,level=20,mobs=2)
    long=evaluate_persistent_candidate(candidate,level=20,mobs=100)
    assert screen['status']==long['status']=='COMPLETE'
    assert long['events']>=100 and long['continuous_actor_state']
    assert long['count']==100 and long['skipped_satisfied_mode_prefixes']==97
    assert abs(long['mean_s_per_mob']-14.123943379252445)<1e-9
    assert abs(screen['mean_s_per_mob']-long['mean_s_per_mob'])>0.1


def test_hard_rejects_invalid_source_prefix_no_autoattack_false_positive():
    modified=deepcopy(_winner())
    modified['gear_policy_result']['winner']['winner']['prefix']=['not_a_legal_action']
    candidate=prepare_candidate(class_key='druid',level=20,stage=modified)
    with pytest.raises(ValueError,match='BLOCKED_ILLEGAL_PREFIX'):
        evaluate_persistent_candidate(candidate,level=20,mobs=2)


def test_two_mob_and_hundred_mob_rerank_two_independent_paid_winners():
    a=_winner()
    other=json.loads((ROOT/'WF298_DRUID_L20_BLIND_FACTORIAL_EVIDENCE.json').read_text())['independent_search_winner']
    r=select_persistent_finalists(class_key='druid',level=20,
        joint_result={'stages':[other,a]},screen_mobs=2,finalist_mobs=100,
        max_screen_candidates=2,max_finalists=2)
    assert r['status']=='PERSISTENT_VERIFIED_BOUNDED'
    assert r['screen_evaluated']==r['finalists_evaluated']==2
    scores=sorted(f['persistent']['mean_s_per_mob'] for f in r['finalists'])
    assert abs(scores[0]-14.123943379252445)<1e-9
    assert abs(scores[1]-14.12395235004445)<1e-9
    assert r['winner']['persistent']['mean_s_per_mob']==scores[0]
    assert not r['candidate_coverage_complete'] and not r['global_optimum_proven']


def test_missing_source_gear_is_blocker():
    modified=deepcopy(_winner())
    slot=next(iter(modified['gear_policy_result']['winner']['gear']['slots'].values()))
    slot['required_level_origin']='inferred'
    with pytest.raises(ValueError,match='BLOCKED_NAMED_GEAR_SOURCE_LEVEL'):
        prepare_candidate(class_key='druid',level=20,stage=modified)


def test_blind_profile_rejects_old_seed_and_duplicate_names():
    with pytest.raises(ValueError,match='blind'):
        run_source_persistent_joint_search(class_key='druid',level=20,
           joint_kwargs={'initial_allocation':{'ferocity':5},'max_evaluations':10})
    with pytest.raises(ValueError,match='unique'):
        run_source_persistent_profile_search(class_key='druid',level=20,
            profiles=(('same',{}),('same',{})))
    with pytest.raises(ValueError,match='blind'):
        run_source_persistent_profile_search(class_key='druid',level=20,
            profiles=(('x',{'initial_allocation':{'ferocity':5}}),))


def test_source_paid_recovery_frontier_is_not_starved_by_tight_screen_budget():
    """Both sourced stage and recovery axes reach actual CombatRuntime."""
    from src.game.recovery_between_pulls import BetweenPullPolicy

    other=json.loads((ROOT/'WF298_DRUID_L20_BLIND_FACTORIAL_EVIDENCE.json').read_text())['independent_search_winner']
    policy=BetweenPullPolicy(health_fraction=.5,mana_fraction=.1)
    result=select_persistent_finalists(
        class_key='druid',level=20,joint_result={'stages':[_winner(),other]},
        screen_mobs=2,finalist_mobs=2,max_screen_candidates=2,max_finalists=2,
        recovery_policies=(None,policy))
    assert result['screen_evaluated']==2
    assert result['screen_completed']==2
    assert result['finalists_evaluated']==2
    assert [row['recovery_policy'] is None for row in result['screening']]==[True,False]
    assert all(row['screen']['count']==2 for row in result['screening'])
