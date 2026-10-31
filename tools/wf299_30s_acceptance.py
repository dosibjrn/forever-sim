"""Strict cold-process ≤30-second source joint optimizer benchmark.

A timeout is FAIL, even if a previously cached answer or partial attempt exists.
The parent sees only the result written by the bounded child. No old build
is passed into the search. "Best currently known" != certified global optimum.
"""
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
from time import monotonic


def run(*,class_key:str,level:int,output:Path,deadline_s:float=30.0)->dict:
    if not 1 <= deadline_s <= 30: raise ValueError('deadline must be within 30 seconds')
    if output.exists(): output.unlink()
    began=monotonic()
    try:
        child=subprocess.run([sys.executable,'-m','tools.wf299_30s_worker',
            '--class-key',class_key,'--level',str(level),'--output',str(output)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,text=True,timeout=deadline_s)
        wall=monotonic()-began
    except subprocess.TimeoutExpired as e:
        output.unlink(missing_ok=True)
        return {'status':'FAIL_30_SECOND_DEADLINE','actual_wall_s':monotonic()-began,
            'objective':'s/mob','accepted_checkpoint':False,
            'note':'Timed-out workers are killed; partial/cached results are never accepted.'}
    if child.returncode:
        output.unlink(missing_ok=True)
        return {'status':'FAIL_CHILD_SEARCH','actual_wall_s':wall,
            'error':child.stderr[-2500:],'accepted_checkpoint':False}
    if not output.is_file(): raise AssertionError('worker succeeded without atomic evidence')
    obj=json.loads(output.read_text())
    if obj['fresh_scratch_replay']['score_s_per_mob'] != obj['winner']['score_s_per_mob']:
        raise AssertionError('cold replay mismatch')
    return {'status':'PASS_BLIND_30S_REPRODUCIBLE_MODEL_BENCHMARK'
            if wall <=deadline_s else 'FAIL_30_SECOND_DEADLINE',
            'actual_wall_s':wall,'deadline_s':deadline_s,'class_key':class_key,'level':level,
            'score_s_per_mob':obj['winner']['score_s_per_mob'],
            'attempts':sum(r['attempts'] for r in obj['profile_results']),
            'events':sum(r['events'] for r in obj['profile_results']),
            'profiles':obj['profile_results'],'scratch_replay':obj['fresh_scratch_replay'],
            'search_oracle_seeded':False,'global_optimum_proven':False,
            'source_complete':False,'accepted_checkpoint':False,
            'evidence_file':str(output)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--class-key',default='druid')
    p.add_argument('--level',type=int,default=20)
    p.add_argument('--deadline-s',type=float,default=30.0)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--summary',type=Path,required=True)
    a=p.parse_args()
    result=run(class_key=a.class_key,level=a.level,output=a.output,deadline_s=a.deadline_s)
    a.summary.write_text(json.dumps(result,indent=2,default=str)+'\n')
    print(json.dumps(result,default=str))
    if result['status'].startswith('FAIL'):sys.exit(1)
