"""Strict 30s wall-clock wrapper. A timeout never becomes a PASS."""
from __future__ import annotations
import json,subprocess,sys
from pathlib import Path
from time import monotonic
ROOT=Path(__file__).resolve().parents[1]
def run(output:Path,deadline_s:float=30.,evaluations:int=145,events:int=17000,finalists:int=3,screens:int=16):
    if not 0<deadline_s<=300:raise ValueError('INVALID_DEADLINE')
    output.parent.mkdir(parents=True,exist_ok=True);output.unlink(missing_ok=True)
    began=monotonic()
    try:
        proc=subprocess.run([sys.executable,'-m','tools.wf340_p4_worker','--output',str(output),
             '--evaluations',str(evaluations),'--events',str(events),
             '--finalists',str(finalists),'--screens',str(screens)],
            cwd=ROOT,capture_output=True,text=True,timeout=deadline_s)
    except subprocess.TimeoutExpired:
        output.unlink(missing_ok=True)
        return {'status':'FAIL_DEADLINE','wall_s':monotonic()-began,'p4_pass':False}
    wall=monotonic()-began
    if proc.returncode or not output.is_file():
        output.unlink(missing_ok=True)
        return {'status':'FAIL_WORKER','wall_s':wall,'error':proc.stderr[-3000:],
            'p4_pass':False}
    result=json.loads(output.read_text());result['end_to_end_wall_s']=wall
    result['timed_search_pass']=wall<=deadline_s and result['winner']['actual_100mob_s_per_mob']>0
    result['p4_pass']=result['timed_search_pass'] if deadline_s<=30 else None
    result['p5_pass']=result['timed_search_pass'] if deadline_s>30 else None
    result['status']=('PASS_TIMED_P4_DIAGNOSTIC' if deadline_s<=30 else 'PASS_TIMED_P5_DIAGNOSTIC') if result['timed_search_pass'] else 'FAIL_DEADLINE'
    output.write_text(json.dumps(result,indent=2,sort_keys=True,default=str))
    return {'status':result['status'],'wall_s':wall,'timed_search_pass':result['timed_search_pass'],
        'winner_100mob_s_per_mob':result['winner']['actual_100mob_s_per_mob'],
        'attempts':result['joint_attempts'],'events':result['joint_events'],
        'distinct_paid_stages_lower_bound':result['distinct_paid_complete_stages_lower_bound']}
if __name__=='__main__':
    r=run(ROOT/'evidence/wf340/WF340_P4_STRICT_30S.json')
    print(json.dumps(r,indent=2),flush=True)
    sys.exit(0 if r['timed_search_pass'] else 1)
