"""Optional diagnostic only: paid mutations near prior WF367 Cat winner.

NOT an independent cold discovery or checkpoint acceptance run.
"""
import hashlib,json,os,sqlite3,tempfile
from pathlib import Path
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_persistent_joint_finalists import prepare_candidate, evaluate_persistent_candidate
from src.v2.source_persistent_policy_neighborhood import refine_source_policy_persistent
from tools.wf321_ingest_control_observations import ingest as ingest_control
from tools.wf360_l30_p4_worker import RECOVERY,ROOT


def main():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    prior=json.load(open(ROOT/'evidence/wf367/WF367_GEAR_P4_30_FINAL.json'))
    with tempfile.TemporaryDirectory() as td:
        db=Path(td)/'source.sqlite'
        with sqlite3.connect(f'file:{(ROOT/"data/forever/staged_druid_l30_talents_70338.sqlite").resolve()}?mode=ro',uri=True) as src,sqlite3.connect(db) as dst:
            src.backup(dst)
        ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        hash=hashlib.sha256(db.read_bytes()).hexdigest()
        assert hash==prior['source_db_sha256'],(hash,prior['source_db_sha256'])
        with ability_source_scope(db):
            ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
            cand=prepare_candidate(class_key='druid',level=30,stage=prior['winner_stage'],source_ir=ir,
                                   strict_l2_item_effects=True)
            old=evaluate_persistent_candidate(cand,level=30,mobs=100,recovery_policy=RECOVERY,
                                             max_wall_s=10.,max_cpu_s=10.,max_total_events=200000)
            print('PARENT',old['status'],old.get('mean_s_per_mob'),flush=True)
            assert old['status']=='COMPLETE' and old['count']==100
            result=refine_source_policy_persistent(cand,level=30,recovery_policy=RECOVERY,
                        max_proposals=12,max_finalists=2,max_total_wall_s=20.,
                        max_screen_wall_s=1.,max_finalist_wall_s=7.,baseline_100mob=old)
            out={k:v for k,v in result.items() if k not in ('winner','attempts','finalists')}
            out['parent_100mob']=old
            out['winner_policy']=None if result['winner'] is None else result['winner']['policy'].as_dict()
            out['winner_result']=None if result['winner'] is None else result['winner']['result']
            out['candidates']=[{'policy_id':t['policy_id'],'operation':t['operation'],
                                'screen':t['screen']} for t in result['attempts']]
            out['finalists']=[{'policy_id':t['policy_id'],'result':t['result']} for t in result['finalists']]
            out['source_db_sha256']=hash
            out['scope']='WF367 winner seeded LOCAL mutation diagnostic; NOT cold checkpoint search'
            p=ROOT/'evidence/wf369/WF369_DRUID_L30_APL_PROBE.json'
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(json.dumps(out,indent=2,sort_keys=True,default=str)+'\n')
            print('RESULT',out['status'],out.get('winner_result',{}).get('mean_s_per_mob') if out.get('winner_result') else None,flush=True)
if __name__=='__main__':main()
