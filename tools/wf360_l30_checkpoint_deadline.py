"""Hard wall-clock budget around the *whole* existing source->IR->joint->100mob process.

No partial search is promoted to PASS when the worker times out, errors,
or fails to produce a legal complete 100-mob finalist.
"""
from __future__ import annotations
import argparse,json,os,subprocess,sys
from pathlib import Path
from time import monotonic
ROOT=Path(__file__).resolve().parents[1]

def run(*,output:Path,deadline_s:float,evaluations:int,events:int,screens:int,finalists:int,profiles:int=1,neighbors:int=0,transfer_neighbors:int=0,gear_neighbors:int=0):
    if deadline_s not in (30.,300.):raise ValueError('ONLY_CONTRACT_30_OR_300')
    output.parent.mkdir(parents=True,exist_ok=True);output.unlink(missing_ok=True)
    began=monotonic()
    cmd=[sys.executable,'-m','tools.wf360_l30_p4_worker','--output',str(output),
        '--evaluations',str(evaluations),'--events',str(events),
        '--screens',str(screens),'--finalists',str(finalists),
        '--profiles',str(profiles),'--neighbors',str(neighbors),
        '--transfer-neighbors',str(transfer_neighbors),
        '--gear-neighbors',str(gear_neighbors),'--search-deadline-s',str(deadline_s)]
    try:
        proc=subprocess.run(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                            text=True,timeout=deadline_s)
    except subprocess.TimeoutExpired as e:
        output.unlink(missing_ok=True)
        return {'status':'FAIL_DEADLINE','deadline_s':deadline_s,'wall_s':monotonic()-began,
                'worker_stdout':(e.stdout or b'').decode(errors='replace')[-1000:] if isinstance(e.stdout,bytes) else str(e.stdout)[-1000:]}
    wall=monotonic()-began
    if proc.returncode or not output.is_file():
        output.unlink(missing_ok=True)
        return {'status':'FAIL_WORKER','deadline_s':deadline_s,'wall_s':wall,
                'worker_stderr':proc.stderr[-2500:]}
    result=json.loads(output.read_text())
    valid=result['status']=='COMPLETE' and result['winner']['actual_100mob_s_per_mob']>0 and wall<=deadline_s
    result.update({'status':'PASS' if valid else 'FAIL','deadline_s':deadline_s,
                   'end_to_end_wall_s':wall,'worker_stdout':proc.stdout[-1000:],
                   'budget':{'evaluations':evaluations,'events':events,'screens':screens,'finalists':finalists,'profiles':profiles,'neighbors':neighbors,'transfer_neighbors':transfer_neighbors,'gear_neighbors':gear_neighbors}})
    output.write_text(json.dumps(result,indent=2,sort_keys=True,default=str)+'\n')
    return {'status':result['status'],'wall_s':wall,'cpu_s':result['cpu_s_worker_and_children'],
            'attempts':result['attempts_total'],'events':result['events_total'],
            'unique':result['unique_complete_builds_paid_lower_bound'],
            'actual_s_per_mob':result['winner']['actual_100mob_s_per_mob'],
            'prediction_s_per_mob':result['winner']['predicted_100mob_s_per_mob']}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--deadline',type=float,required=True);p.add_argument('--evaluations',type=int,required=True)
    p.add_argument('--events',type=int,required=True);p.add_argument('--screens',type=int,required=True)
    p.add_argument('--finalists',type=int,required=True)
    p.add_argument('--profiles',type=int,default=1);p.add_argument('--neighbors',type=int,default=0)
    p.add_argument('--transfer-neighbors',type=int,default=0)
    p.add_argument('--gear-neighbors',type=int,default=0)
    a=p.parse_args();r=run(output=a.output,deadline_s=a.deadline,evaluations=a.evaluations,
                            events=a.events,screens=a.screens,finalists=a.finalists,profiles=a.profiles,neighbors=a.neighbors,transfer_neighbors=a.transfer_neighbors,gear_neighbors=a.gear_neighbors)
    print(json.dumps(r,sort_keys=True),flush=True)
    sys.exit(0 if r['status']=='PASS' else 1)
