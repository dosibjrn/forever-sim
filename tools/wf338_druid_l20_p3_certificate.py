"""P3 certificate and a bounded *non-checkpoint* paid L2 integration pilot."""
from __future__ import annotations
import json,os,sqlite3,tempfile
from pathlib import Path
from time import process_time,monotonic
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0,verify_checkpoint_item_l0
from src.game.data.forever.source_db_scope import ability_source_scope
from src.v2.source_persistent_slot_search import search_persistent_gear_slots


def main():
    root=Path(__file__).resolve().parents[1]
    cert=checkpoint_item_l0(class_key='druid',level=20)
    verify_checkpoint_item_l0(cert,class_key='druid',level=20)
    dest=root/'evidence/wf338';dest.mkdir(parents=True,exist_ok=True)
    (dest/'WF338_DRUID_L20_P3_ITEM_CERTIFICATE.json').write_text(json.dumps(cert,indent=2))
    fixture=json.loads((root/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())
    stage=fixture['finalist']['winner']['stage']
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    from src.game.data.forever.source_observed_rank_parity import ingest_observations
    from tools.wf321_ingest_control_observations import ingest as ingest_control
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    with tempfile.TemporaryDirectory(prefix='wf338_p3_') as tmp:
        dbpath=Path(tmp)/'source_stage.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as source,sqlite3.connect(dbpath) as dst:
            source.backup(dst)
        ingest_observations(dbpath,root/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(dbpath,root/'evidence/wf321/druid_l20_control_observations.json')
        t=monotonic();c=process_time()
        with ability_source_scope(dbpath):
            result=search_persistent_gear_slots(class_key='druid',level=20,seed_stage=stage,
                rounds=1,per_slot=1,max_proposals_per_round=18,screen_mobs=8,
                finalist_mobs=100,max_finalists=3,max_cpu_s=18,max_events=120000,
                p3_certificate=cert)
    evidence={'checkpoint':'druid_L20_unrestricted_use_runes_false',
        'p1':True,'p2':True,'p3_l0':cert['p3_pass'],
        'item_count':cert['legal_item_count'],'l0_assessed':cert['l0_assessed_count'],
        'unknown_effect_items':cert['unknown_effect_item_count'],
        'slot_counts':{k:v['legal_item_count'] for k,v in cert['slot_frontiers'].items()},
        'pilot_is_not_independent_joint_p4_p5_p6':True,
        'pilot_l2_result':{k:result.get(k) for k in ('status','attempts','events','cpu_s','wall_s',
            'full_100mob_evaluations','p3_l0_priority_used','rounds')},
        'pilot_initial_100mob_s_per_mob':result.get('initial',{}).get('mean_s_per_mob'),
        'pilot_best_100mob_s_per_mob':result.get('winner',{}).get('mean_s_per_mob'),
        'actual_cpu_s':process_time()-c,'actual_wall_s':monotonic()-t,
        'accepted_checkpoints':0}
    (dest/'WF338_VALIDATION.json').write_text(json.dumps(evidence,indent=2,default=str))
    print(json.dumps(evidence,indent=2,default=str))

if __name__=='__main__':main()
