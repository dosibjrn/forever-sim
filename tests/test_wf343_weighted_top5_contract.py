"""WF343: proof the new source display chance weights power optimizer shortlist."""
from pathlib import Path
import json
from copy import deepcopy
from math import isclose
from src.game.data.forever.source_checkpoint_p3_weights import verify_weighted_ranking
from src.v2.source_persistent_slot_search import _source_slot_proposals,_gear_replace
from src.v2.source_persistent_joint_finalists import prepare_candidate
from src.rulesets.forever.items.runtime_selection import available_items
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

def test_prepare_candidate_consumes_display_percent_and_defense_by_default():
    rows={int(r.item_id):r for r in available_items('druid',20,required_level_policy='observed')}
    from src.game.data.forever.source_db_scope import ability_source_scope
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    from src.game.data.forever.source_observed_rank_parity import ingest_observations
    from tools.wf321_ingest_control_observations import ingest as ingest_control
    import sqlite3,tempfile
    with tempfile.TemporaryDirectory() as folder:
        from pathlib import Path
        target=Path(folder)/'s.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as old,sqlite3.connect(target) as new:old.backup(new)
        ingest_observations(target,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(target,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(target):
            a=prepare_candidate(class_key='druid',level=20,stage=STAGE)
            modified=deepcopy(STAGE)
            modified['gear_policy_result']['winner']['gear']=_gear_replace(
                modified['gear_policy_result']['winner']['gear'],'hands',rows[7348])
            b=prepare_candidate(class_key='druid',level=20,stage=modified)
            assert isclose(b.ir.actor.base_stats.get('melee_crit_chance',0)-a.ir.actor.base_stats.get('melee_crit_chance',0),.01,abs_tol=1e-10)
            assert b.ir.provenance['source_equipped_item_combat_stats']['displayed_crit_pct']==1.
            modified['gear_policy_result']['winner']['gear']=_gear_replace(
                STAGE['gear_policy_result']['winner']['gear'],'ring1',rows[12985])
            c=prepare_candidate(class_key='druid',level=20,stage=modified)
            assert isclose(c.ir.actor.base_stats.get('dodge_chance',0)-a.ir.actor.base_stats.get('dodge_chance',0),.0016,abs_tol=1e-10)
