"""Merge already measured 100-mob rating probes with WF341 sourced P3 Top 5.

For full recomputation, first run `tools.wf341_rating_probe` in this worktree.
The two evidence JSON files are embedded in the cumulative handover and pinned
by fixed build identity, 100-mob baseline and item catalogue hash.
"""
from __future__ import annotations
import json,sqlite3,tempfile,os
from pathlib import Path
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.game.data.forever.source_checkpoint_p3_weights import ranked_top_items,verify_weighted_ranking
ROOT=Path(__file__).resolve().parents[1]

def run():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    wf341=json.loads((ROOT/'evidence/wf341/WF341_DRUID_L20_CHANCE_SENSITIVITY_TOP5.json').read_text())
    direct=json.loads((ROOT/'evidence/wf341/WF341_RATING_WEIGHTED_TOP5.json').read_text())
    assert direct['baseline']['count']==100
    assert abs(direct['baseline']['mean_s_per_mob']-wf341['stat_weights']['base_s_per_mob'])<1e-10
    assert wf341['build_identity_sha256']==direct['top5']['build_identity_sha256']
    assert wf341['catalogue_sha256']==direct['top5']['catalogue_sha256']
    weights=json.loads(json.dumps(wf341['stat_weights']))
    for stat,row in direct['rating_evidence'].items():
        current=weights['weights'][stat]
        current['measured_100mob_provisional_weight_per_rating']=row['weight_s_saved_per_mob_per_unit']
        current['measured_100mob_provisional_status']=row['status']
        current['measured_100mob_provisional_evidence']=row
        assert current['weight_s_saved_per_mob_per_unit'] is None, 'not source-verified full-L2 rating'
    stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    with tempfile.TemporaryDirectory(prefix='wf342_reporting_source_') as tmp:
        staged=Path(tmp)/'s.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as db,sqlite3.connect(staged) as out:db.backup(out)
        ingest_observations(staged,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(staged,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(staged):
            report=ranked_top_items(class_key='druid',level=20,stage=stage,weight_evidence=weights,top_n=5)
            verify_weighted_ranking(report,class_key='druid',level=20,stage=stage)
    # User's stronger P3 contract: a numerically-valued historic approximation
    # is useful for exploring the ranking but NOT enough for an accepted gate.
    report['p3_user_contract_pass']=False
    report['p3_user_contract_blockers']=[
        'Forever_70338_client_rating_conversions_not_authenticated',
        'defense_parry_block_incoming_crit_and_rounding_not_executed',
        'procs_relics_and_other_untypeable_item_effects_remain_uncertain']
    report['rating_probes_replayed']=True
    report['provisional_rating_weights']={k:weights['weights'][k]['measured_100mob_provisional_weight_per_rating']
        for k in ('crit','hit','defense','dodge')}
    return report

if __name__=='__main__':
    r=run()
    d=ROOT/'evidence/wf342';d.mkdir(parents=True,exist_ok=True)
    (d/'WF342_PROVISIONAL_RATING_TOP5.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
    print(json.dumps({'items':r['total_legal_items'],'slots':len(r['slots']),
        'rating_weights':r['provisional_rating_weights'],'uncertain_items':r['unknown_item_count'],
        'changed_provisional_slots':[slot for slot,v in r['slots'].items()
        if v['known_weight_top_ids']!=v['historical_rating_sensitivity_top_ids']]},indent=2))
