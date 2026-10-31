"""Re-evaluate four rating axes against the same fixed 100-mob WF339 winner."""
from __future__ import annotations
import json,os,sqlite3,tempfile
from pathlib import Path
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2.source_persistent_joint_finalists import prepare_candidate
from src.game.data.forever.source_checkpoint_p3_weights import (
    _discrete_stat_probe,_score,ranked_top_items,PROBE_STEPS)
from src.game.data.forever.source_checkpoint_p3_ratings import rating_to_chance,SOURCE_STATUS
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1]

def run():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    previous=json.loads((ROOT/'evidence/wf339/WF339_DRUID_L20_WEIGHTED_TOP5_PER_SLOT.json').read_text())
    with tempfile.TemporaryDirectory(prefix='wf341_rating_') as tmp:
        staged=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as db,sqlite3.connect(staged) as out: db.backup(out)
        ingest_observations(staged,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(staged,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(staged):
            candidate=prepare_candidate(class_key='druid',level=20,stage=stage)
            baseline=_score(candidate,20,100)
            old=previous['stat_weights']; weights=dict(old['weights'])
            measurements={}
            for key in ('crit','hit','defense','dodge'):
                step={'crit':2.,'hit':2.,'defense':4.,'dodge':2.}[key]
                x=_discrete_stat_probe(candidate,key,step,20,100,0.,float(baseline['mean_s_per_mob']))
                x.update({'rating_conversion_status':SOURCE_STATUS,
                          'rating_conversion':rating_to_chance(key,1.0,level=20),
                          'is_provisional':True})
                weights[key]=x
                measurements[key]=x
            info={**old,'weights':weights,'rating_probe_source_status':SOURCE_STATUS,
                  'rating_probe_baseline_s_per_mob':baseline['mean_s_per_mob']}
            result=ranked_top_items(class_key='druid',level=20,stage=stage,weight_evidence=info,top_n=5)
            baseline_top={slot:[i['item_id'] for i in v['top']] for slot,v in previous['slots'].items()}
            new_top={slot:[i['item_id'] for i in v['top']] for slot,v in result['slots'].items()}
            return {'rating_evidence':measurements,'baseline':baseline,'top5':result,
                    'changed_slots':{slot:{'before':baseline_top[slot],'after':ids}
                        for slot,ids in new_top.items() if ids!=baseline_top[slot]}}

if __name__=='__main__':
    result=run()
    d=ROOT/'evidence/wf341';d.mkdir(parents=True,exist_ok=True)
    (d/'WF341_RATING_WEIGHTED_TOP5.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print(json.dumps({'baseline':result['baseline']['mean_s_per_mob'],
        'measurements':{k:{'status':v['status'],'w':v['weight_s_saved_per_mob_per_unit'],'full':v.get('full_probes')}
            for k,v in result['rating_evidence'].items()},
        'changed_slots':result['changed_slots'],
        'unknown_items':result['top5']['unknown_item_count']},ensure_ascii=False,indent=2))
