"""P3 proxy uncertainty and strict L2 item-effect admission, no invented zero."""
import json
from pathlib import Path
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0,source_item_l0
from src.game.data.forever.source_checkpoint_p3_weights import verify_weighted_ranking
from src.game.data.forever.gear import select_named_gear
from src.rulesets.forever.items.runtime_selection import available_items

ROOT=Path(__file__).resolve().parents[1]

def test_p3_every_item_assessed_and_uncertainty_not_zero():
    r=json.loads((ROOT/'evidence/wf340/WF340_P3_UNCERTAINTY_AWARE_RANKING.json').read_text())
    assert r['p3_pass'] is True and r['full_numeric_effect_certainty'] is False
    assert r['total_legal_items']==1175 and r['unknown_item_count']>0
    assert len(r['slots'])==18
    for slot,row in r['slots'].items():
        assert len(row['all_ranked_item_ids'])==row['available_legal']
        assert len(set(row['all_ranked_item_ids']))==row['available_legal']
        if row['unknown_challenger_count']:
            assert any(item['unknown_effects'] for item in row['top'])

def test_l2_strict_excludes_unknown_but_l0_keeps_them():
    items=available_items('druid',20,required_level_policy='observed')
    assert len(items)==1171
    uncertain={x.item_id for x in items if source_item_l0(x)['unresolved_effects']}
    assert 210250 in uncertain and 6226 not in uncertain and 21566 not in uncertain
    normal=select_named_gear(class_key='druid',level=20,role='druid_feral',
        stat_weights={'agility':1},required_level_policy='observed')
    strict=select_named_gear(class_key='druid',level=20,role='druid_feral',
        stat_weights={'agility':1},required_level_policy='observed',
        exclude_unknown_item_effects=True)
    assert all(int(x['item_id']) not in uncertain for x in strict.slots.values())
    assert checkpoint_item_l0(class_key='druid',level=20)['unknown_effect_item_count']>0
    assert all(int(x['item_id']) in {y.item_id for y in items} for x in normal.slots.values())

def test_p4_p5_source_identity_and_repeated_pull_saturation():
    p4=json.loads((ROOT/'evidence/wf340/WF340_P4_STRICT_30S.json').read_text())
    p5=json.loads((ROOT/'evidence/wf340/WF340_P5_STRICT_300S.json').read_text())
    assert p4['source_context_sha256']==p5['source_context_sha256']
    assert p4['item_catalogue_sha256']==p5['item_catalogue_sha256']
    assert p4['end_to_end_wall_s']<30 and p5['end_to_end_wall_s']<300
    assert p5['distinct_paid_complete_stages_lower_bound']>p4['distinct_paid_complete_stages_lower_bound']
    assert p4['winner']['actual_100mob_s_per_mob']<=1.01*p5['winner']['actual_100mob_s_per_mob']
    assert p4['total_events']==p4['joint_events']+p4['persistent_events']
    assert p5['total_events']==p5['joint_events']+p5['persistent_events']

def test_unknown_equipped_effect_fails_strict_persistent_l2():
    import pytest
    from src.v2.source_persistent_joint_finalists import prepare_candidate
    import copy
    from src.v2.source_persistent_slot_search import _gear_replace
    stage=copy.deepcopy(json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage'])
    item=next(x for x in available_items('druid',20,required_level_policy='observed') if x.item_id==210250)
    stage['gear_policy_result']['winner']['gear']=_gear_replace(stage['gear_policy_result']['winner']['gear'],'ring1',item)
    with pytest.raises(ValueError,match='BLOCKED_UNTYPED_ITEM_EFFECTS'):
        prepare_candidate(class_key='druid',level=20,stage=stage,strict_l2_item_effects=True)

def test_hard_event_cap_charges_failed_repeated_pull_without_overrun():
    from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
    stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    candidate=prepare_candidate(class_key='druid',level=20,stage=stage)
    result=evaluate_persistent_candidate(candidate,level=20,mobs=100,max_total_events=10)
    assert result['status']=='BLOCKED_EVALUATION_COMPUTE_BUDGET'
    assert 0<result['events']<=10
    assert result['mob_completed']<100
