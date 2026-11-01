"""WF339: genuine context-weighted slot ordering, fail-closed unknown axes."""
import json
from pathlib import Path
from copy import deepcopy
import pytest
from src.game.data.forever.source_checkpoint_p3_weights import (
    ranked_top_items, verify_weighted_ranking, _discrete_stat_probe,
)
from src.v2.source_persistent_slot_search import _source_slot_proposals

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'evidence/wf346/WF346_TOP5.json'
STAGE=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']


def _report():return json.loads(REPORT.read_text())


def test_non_degenerate_strength_ap_armor_weapon_weights():
    w=_report()['stat_weights']['weights']
    for stat in ['strength','attack_power','armor','agility','weapon_dps']:
        assert w[stat]['status'] in ('MEASURED','DISCRETE_SMOOTHED'), stat
        assert w[stat]['weight_s_saved_per_mob_per_unit']>0., stat
        assert w[stat]['method'] in ('20mob_screen_100mob_confirmed_multiscale_difference',),stat
    for stat in ('hit','crit','defense','dodge'):
        assert w[stat]['status'] in ('UNMODELED_RATING_CONVERSION','PROVISIONAL_UNVERIFIED_FOREVER_RATING','UNMODELED_RATING_OR_EFFECT','SOURCE_DISPLAY_PERCENT_MEASURED_100MOB','PARTIAL_DEFENSE_SKILL_FIRST_ORDER_AVOIDANCE_PROXY')
        if w[stat]['status'] in ('SOURCE_DISPLAY_PERCENT_MEASURED_100MOB',
                                 'PARTIAL_DEFENSE_SKILL_FIRST_ORDER_AVOIDANCE_PROXY'):
            assert w[stat]['weight_s_saved_per_mob_per_unit']>0
        else:
            assert w[stat]['weight_s_saved_per_mob_per_unit'] is None


def test_every_item_is_value_decomposed_and_only_top_five_published():
    r=_report();assert r['total_legal_items']==1171
    assert r['p3_pass'] is True and r['unknown_item_count']>0
    for slot,entry in r['slots'].items():
        ids=entry['all_ranked_item_ids']
        assert len(ids)==len(set(ids))==entry['available_legal']
        assert [x['item_id'] for x in entry['top']]==ids[:5]
        assert all(abs(sum(x['contribution_s_saved_per_mob'] for x in item['contributions'])
            -item['known_score_s_saved_per_mob'])<1e-9 for item in entry['top'])
        # The current frontier deliberately interleaves uncertain challengers
        # with known-score order, so its first five need not be monotone.
        known_ids=entry['known_weight_top_ids']
        assert len(known_ids)==len(set(known_ids))==min(5,entry['available_legal'])


def test_weighted_order_really_drives_paid_slot_proposals():
    r=_report();base=STAGE['gear_policy_result']['winner']['gear']
    proposals,counts=_source_slot_proposals(class_key='druid',level=20,
       base=base,weighted_p3_report=r,seed_stage=STAGE,per_slot=2,max_proposals=45)
    assert proposals
    assert counts['weapon']>0
    for slot,item in proposals:
        gear_used={int(v['item_id']) for k,v in base['slots'].items() if k!=slot}
        assert int(item.item_id) not in gear_used
        assert int(item.item_id) in r['slots'][slot]['all_ranked_item_ids']
    assert any(slot=='weapon' for slot,_ in proposals)
    # First currently unused best legal item per slot is proposed before rank 2.
    weapon_candidates=[iid for iid in r['slots']['weapon']['all_ranked_item_ids']
        if iid not in {int(v['item_id']) for v in base['slots'].values()}]
    assert next(item.item_id for slot,item in proposals if slot=='weapon')==weapon_candidates[0]


def test_mismatched_or_forged_report_is_rejected():
    r=_report();verify_weighted_ranking(r,class_key='druid',level=20,stage=STAGE)
    bad=deepcopy(r);bad['build_identity_sha256']='0'*64
    with pytest.raises(ValueError,match='P3_WEIGHTED_RANKING_STALE'):
        verify_weighted_ranking(bad,class_key='druid',level=20,stage=STAGE)
    bad=deepcopy(r);bad['slots']['weapon']['all_ranked_item_ids'].pop()
    with pytest.raises(ValueError,match='P3_WEIGHTED_RANKING_TRUNCATED'):
        verify_weighted_ranking(bad,class_key='druid',level=20,stage=STAGE)


def test_inconclusive_not_converted_to_negative_stat_weight(monkeypatch):
    from src.game.data.forever import source_checkpoint_p3_weights as p
    monkeypatch.setattr(p,'_score',lambda candidate,level,mobs:{'mean_s_per_mob':10.})
    monkeypatch.setattr(p,'_derivative',lambda *args,**kw:({'mean_s_per_mob':11.,'events':1},None))
    row=_discrete_stat_probe(object(),'armor',10.,20,100,0.,10.)
    assert row['status']=='INCONCLUSIVE_DISCRETE_PROBES'
    assert row['weight_s_saved_per_mob_per_unit'] is None
