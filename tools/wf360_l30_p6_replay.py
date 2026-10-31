"""Fresh same-source/same-recovery 100-mob replay of two blind search winners."""
from __future__ import annotations
import argparse,hashlib,json,os,sqlite3,tempfile
from pathlib import Path
from time import monotonic,process_time
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.source_checkpoint_p3_swaps import subprocess_stage_100mob
from tools.wf321_ingest_control_observations import ingest as ingest_control
from tools.wf360_l30_p4_worker import RECOVERY,ROOT

def run(p4:Path,p5:Path):
    a=json.loads(p4.read_text());b=json.loads(p5.read_text())
    if not (a['status']==b['status']=='PASS' and a['checkpoint']==b['checkpoint']=='druid:L30:unrestricted'):
        raise ValueError('SEARCH_PORTS_NOT_PASS')
    if a['source_db_sha256']!=b['source_db_sha256']:
        raise ValueError('NOT_IDENTICAL_SOURCE')
    if a['recovery_policy']!=b['recovery_policy']:
        raise ValueError('NOT_IDENTICAL_RECOVERY')
    if b['unique_complete_builds_paid_lower_bound']<=a['unique_complete_builds_paid_lower_bound']:
        raise ValueError('P5_DID_NOT_EXPLORE_MORE_UNIQUE_BUILDS')
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    start=monotonic();cpu=process_time()
    with tempfile.TemporaryDirectory(prefix='wf360_l30_p6_') as tmp:
        db=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as src,sqlite3.connect(db) as dst:src.backup(dst)
        ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        digest=hashlib.sha256(db.read_bytes()).hexdigest()
        if digest!=a['source_db_sha256']:raise ValueError('REPLAY_SOURCE_DIFFERS_FROM_SEARCH')
        x=subprocess_stage_100mob(stage=a['winner_stage'],source_db_path=db,
            timeout_s=30.,recovery_policy=RECOVERY)
        y=subprocess_stage_100mob(stage=b['winner_stage'],source_db_path=db,
            timeout_s=30.,recovery_policy=RECOVERY)
    if x['status']!='COMPLETE' or y['status']!='COMPLETE':
        return {'status':'FAIL_INCOMPLETE_100_MOB','p4_replay':x,'p5_replay':y}
    t30=x['mean_s_per_mob'];t300=y['mean_s_per_mob']
    relative=t30/t300-1.
    return {'checkpoint':'druid:L30:unrestricted','status':'PASS' if relative<=.01 else 'FAIL',
        't30_s_per_mob':t30,'t300_s_per_mob':t300,'relative_t30_vs_t300':relative,
        'relative_percent':100*relative,'criterion':'T30 <= 1.01 * T300',
        'p4_replay':x,'p5_replay':y,'replay_wall_s':monotonic()-start,
        'replay_parent_cpu_s':process_time()-cpu,
        'source_db_sha256':digest,'recovery_policy':a['recovery_policy'],
        'global_optimality_proven':False}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--p4',type=Path,required=True)
    p.add_argument('--p5',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=run(a.p4,a.p5);a.output.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:r.get(k) for k in ('status','t30_s_per_mob','t300_s_per_mob','relative_percent','replay_wall_s')}),flush=True)
