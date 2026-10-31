"""WF389: 2H <-> one-hand/offhand moves must be reachable by the paid P3 search."""
from __future__ import annotations
import json
from pathlib import Path
from copy import deepcopy

import pytest

from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.game.data.forever.source_named_gear_proof import audit_named_gear_source
from src.v2 import source_persistent_slot_search as search

ROOT=Path(__file__).resolve().parents[1]
STAGE=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())


def test_2h_seed_generates_legal_atomic_onehand_offhand_packages():
    base=STAGE['gear_policy_result']['winner']['gear']
    assert base['slots']['weapon']['weapon_hands']==2 and 'offhand' not in base['slots']
    packages,coverage=search._source_weapon_package_proposals(
        class_key='druid',level=30,base=base,max_packages=8)
    assert len(packages)>=4
    assert len({tuple(sorted(p.items())) for p in packages})==len(packages)
    assert coverage['one_hand_candidates']>0 and coverage['offhand_candidates']>0
    for swaps in packages:
        assert set(swaps)=={'weapon','offhand'}
        changed=substituted_multi_stage(stage=STAGE,class_key='druid',level=30,swaps=swaps)
        gear=changed['gear_policy_result']['winner']['gear']
        assert gear['slots']['weapon']['weapon_hands']==1
        assert 'offhand' in gear['slots']
        assert audit_named_gear_source(class_key='druid',level=30,gear=gear)['equipment_legality_complete']
    assert STAGE['gear_policy_result']['winner']['gear']==base


def test_package_search_reaches_existing_paid_100mob_evaluator(monkeypatch):
    calls=[]
    real_prepare=search.prepare_candidate
    def measured(candidate,*,level,mobs,**kwargs):
        gear=candidate.source_stage['gear_policy_result']['winner']['gear']
        calls.append((mobs,gear['slots']['weapon']['weapon_hands'], 'offhand' in gear['slots']))
        return {'status':'COMPLETE','mean_s_per_mob':19. if mobs==100 else 18.,'events':5,
                'mob_completed':mobs}
    monkeypatch.setattr(search,'evaluate_persistent_candidate',measured)
    monkeypatch.setattr(search,'prepare_candidate',real_prepare)
    result=search.search_persistent_gear_slots(
        class_key='druid',level=30,seed_stage=deepcopy(STAGE),rounds=1,
        per_slot=1,max_proposals_per_round=8,max_weapon_packages_per_round=4,
        screen_mobs=2,finalist_mobs=100,max_finalists=5,max_cpu_s=30,max_events=50000)
    assert result['status']=='BOUNDED_COORDINATE_SEARCH'
    assert result['weapon_package_attempts']>=1
    assert any(hands==1 and offhand for _,hands,offhand in calls)
    assert result['diagnostic_only'] is False or result['formal_checkpoint_accepted'] is False
    assert not result['formal_checkpoint_accepted']


def test_2h_swap_from_onehand_offhand_is_atomic_and_source_legal():
    packages,_=search._source_weapon_package_proposals(
        class_key='druid',level=30,
        base=STAGE['gear_policy_result']['winner']['gear'],max_packages=2)
    onehand=substituted_multi_stage(stage=STAGE,class_key='druid',level=30,swaps=packages[0])
    from src.rulesets.forever.items.runtime_selection import available_items
    twohand=next(x for x in available_items('druid',30,required_level_policy='observed')
                 if x.item_id==STAGE['gear_policy_result']['winner']['gear']['slots']['weapon']['item_id'])
    changed=substituted_multi_stage(stage=onehand,class_key='druid',level=30,
                                    swaps={'weapon':twohand.item_id})
    gear=changed['gear_policy_result']['winner']['gear']
    assert gear['slots']['weapon']['weapon_hands']==2
    assert 'offhand' not in gear['slots']
    assert audit_named_gear_source(class_key='druid',level=30,gear=gear)['equipment_legality_complete']
    with pytest.raises(ValueError):
        substituted_multi_stage(stage=onehand,class_key='druid',level=30,
                                swaps={'weapon':twohand.item_id,'offhand':packages[0]['offhand']})


def test_all_package_budget_never_exceeds_attempt_limit_and_counts_unique_full_builds(monkeypatch):
    def measured(candidate,*,level,mobs,**kwargs):
        return {'status':'COMPLETE','mean_s_per_mob':19. if mobs==100 else 20.,
                'events':5,'mob_completed':mobs}
    monkeypatch.setattr(search,'evaluate_persistent_candidate',measured)
    from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
    cert=checkpoint_item_l0(class_key='druid',level=30)
    result=search.search_persistent_gear_slots(
        class_key='druid',level=30,seed_stage=deepcopy(STAGE),rounds=1,
        per_slot=1,max_proposals_per_round=2,max_weapon_packages_per_round=2,
        screen_mobs=2,finalist_mobs=100,max_finalists=2,max_cpu_s=30,max_events=50000,
        p3_certificate=cert,allow_unattested_diagnostic=True)
    assert result['attempts']==2
    assert result['weapon_package_attempts']==2
    assert result['unique_full_builds']==3  # incumbent + two distinct 1H/offhand packages
    assert result['full_100mob_evaluations']==3
    assert result['rounds'][0]['proposed']==2


def test_onehand_offhand_incumbent_generates_twohand_package_moves():
    packages,_=search._source_weapon_package_proposals(
        class_key='druid',level=30,base=STAGE['gear_policy_result']['winner']['gear'],
        max_packages=1)
    stage=substituted_multi_stage(stage=STAGE,class_key='druid',level=30,swaps=packages[0])
    base=stage['gear_policy_result']['winner']['gear']
    moves,counts=search._source_weapon_package_proposals(
        class_key='druid',level=30,base=base,max_packages=4)
    assert len(moves)==4 and counts['two_hand_candidates']>0
    for move in moves:
        assert set(move)=={'weapon'}
        changed=substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=move)
        gear=changed['gear_policy_result']['winner']['gear']
        assert gear['slots']['weapon']['weapon_hands']==2 and 'offhand' not in gear['slots']
