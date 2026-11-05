"""WF343: proof the new source display chance weights power optimizer shortlist."""
from pathlib import Path
import json
from math import isclose
from src.game.data.forever.source_checkpoint_p3_weights import verify_weighted_ranking
from src.v2.source_persistent_slot_search import _source_slot_proposals
ROOT=Path(__file__).resolve().parents[1]
REPORT=json.loads((ROOT/'evidence/wf346/WF346_TOP5.json').read_text())
STAGE=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']

def test_top5_for_all_slots_is_weighted_not_round_robin():
    r=REPORT
    assert r['total_legal_items']==1171 and len(r['slots'])==18
    assert r['p3_user_contract_pass'] is False
    assert r['source_item_conversion']['TBC_level_scaling_used'] is False
    assert r['unknown_item_count']>0
    assert r['paid_gear_proposal_count']>0
    w=r['stat_weights']['weights']
    for stat in ('crit','hit','dodge','defense','strength','agility','attack_power','armor'):
        assert w[stat]['weight_s_saved_per_mob_per_unit']>0,stat
    assert w['defense']['first_order_fallback_used'] is True
    assert 'parry_chance' in w['defense']['unmodeled_channels']
    for slot,x in r['slots'].items():
        assert x['available_legal']>=1 and len(x['weighted_top'])==min(5,x['available_legal'])
        for a,b in zip(x['weighted_top'],x['weighted_top'][1:]):
            assert a['known_score_s_saved_per_mob']>=b['known_score_s_saved_per_mob']
        assert x['known_weight_top_ids']==[row['item_id'] for row in x['weighted_top']]
        assert len(x['all_ranked_item_ids'])==len(set(x['all_ranked_item_ids']))==x['available_legal']
        for row in x['weighted_top']:
            assert isclose(row['known_score_s_saved_per_mob'],sum(c['contribution_s_saved_per_mob'] for c in row['contributions']),abs_tol=1e-10)
            assert 'defense_skill' in row and 'displayed_item_chances_pct' in row
    verify_weighted_ranking(r,class_key='druid',level=20,stage=STAGE)

def test_real_paid_gear_uses_this_report():
    gear=STAGE['gear_policy_result']['winner']['gear']
    proposals,counts=_source_slot_proposals(class_key='druid',level=20,base=gear,
        weighted_p3_report=REPORT,seed_stage=STAGE,per_slot=2,max_proposals=45)
    assert len(proposals)==REPORT['paid_gear_proposal_count']
    assert counts==REPORT['paid_gear_slot_coverage']
    assert any(slot=='weapon' for slot,_ in proposals)
    for slot,item in proposals:
        assert item.item_id in REPORT['slots'][slot]['all_ranked_item_ids']
