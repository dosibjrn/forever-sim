"""Search for 100-mob counterexamples using canonical one-point talent edits.

Screen all source-legal local neighbors at two mobs, then evaluate the most
competitive on 100 mobs using the same CombatRuntime, exact named gear and
same policy. This is an adversarial check, not a global optimum certification.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from time import monotonic
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_frontier import source_legal_talent_neighbors
from tools.wf299_100_mob_continuity_probe import run

def test_neighbors(evidence:Path, *, finalist_count:int=6)->dict:
    source=json.loads(evidence.read_text());cls=str(source['class_key']);level=int(source['level'])
    current=source['winner']['allocation'];ir=build_game_ir_slice(class_key=cls,level=level)
    n=source_legal_talent_neighbors(ir,current,level=level)
    began=monotonic()
    baseline_short=run(evidence,mobs=2)
    baseline_long=run(evidence,mobs=100)
    rows=[]
    for proposal in n['neighbors']:
        assignment=dict(proposal.allocation)
        try:
            trial=run(evidence,mobs=2,allocation_override=assignment)
            if trial['status']!='COMPLETE_100_MOBS':
                raise ValueError(trial['status']+':'+str(trial.get('stopped_reason')))
            rows.append({'allocation':assignment,'operation':proposal.operation,
                        'status':'COMPLETE_2_MOBS', 'two_mob_mean_s':trial['mean_s_per_mob']})
        except (RuntimeError,ValueError,KeyError) as exc:
            rows.append({'allocation':assignment,'operation':proposal.operation,
                        'status':'BLOCKED_2_MOBS','error':str(exc)})
    promising=sorted((r for r in rows if r['status']=='COMPLETE_2_MOBS'),
                     key=lambda v:(v['two_mob_mean_s'],sorted(v['allocation'].items())))[:finalist_count]
    finalists=[]
    for candidate in promising:
        try:
            trial=run(evidence,mobs=100,allocation_override=candidate['allocation'])
            if trial['status']!='COMPLETE_100_MOBS':raise ValueError(trial['status'])
            finalists.append({'allocation':candidate['allocation'],
                'two_mob_mean_s':candidate['two_mob_mean_s'],
                'mean_100_mobs_s':trial['mean_s_per_mob'],
                'total_100_mobs_s':trial['total_s'],
                'events':trial['events'],'status':'COMPLETE_100_MOBS'})
        except (ValueError,KeyError,RuntimeError) as exc:
            finalists.append({'allocation':candidate['allocation'],'status':'BLOCKED_100_MOBS','error':str(exc)})
    better=[v for v in finalists if v['status']=='COMPLETE_100_MOBS'
            and v['mean_100_mobs_s']<baseline_long['mean_s_per_mob']-1e-9]
    return {'schema':'wf300_adversarial_talent_neighbors_100mob_v1',
      'class_key':cls,'level':level,'source_generated_legal_neighbor_count':len(n['neighbors']),
      'evaluated_2_mob':len(rows),'blocked_2_mob':sum(r['status']!='COMPLETE_2_MOBS' for r in rows),
      'evaluated_100_mob':len(finalists),
      'baseline_2_mob_mean_s':baseline_short['mean_s_per_mob'],
      'baseline_100_mob_mean_s':baseline_long['mean_s_per_mob'],
      'two_mob_screening':rows,'hundred_mob_finalists':finalists,
      'better_adversarial_candidates':better,
      'incumbent_is_best_among_tested_finalists':not bool(better),
      'same_named_gear_and_policy_all_candidates':True,
      'gear_or_policy_reoptimized':False,'global_optimum_proven':False,
      'wall_s':monotonic()-began}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--finalists',type=int,default=6)
    a=p.parse_args();v=test_neighbors(a.evidence,finalist_count=a.finalists)
    a.output.write_text(json.dumps(v,indent=2)+'\n')
    print(json.dumps({k:v[k] for k in ['evaluated_2_mob','blocked_2_mob','evaluated_100_mob',
        'baseline_100_mob_mean_s','better_adversarial_candidates','wall_s']},indent=2))
