"""WF300 Druid L20: adversarial equal-terms 100-mob warm-state comparison.

The optimizer's cold, unseeded evidence is imported BEFORE any historical
fixture; no challenger is passed to source search. Neither world XP nor route
continuity is required. This checks only the source-modelled kill+recovery
encounter objective under a single persistent ActorState.
"""
from __future__ import annotations
import argparse, json
from hashlib import sha256
from pathlib import Path
from tools.wf299_100_mob_continuity_probe import run

ROOT=Path(__file__).resolve().parents[1]

def go(winner_evidence:Path, historical_fixture:Path, *, mobs:int=100)->dict:
    if mobs!=100: raise ValueError('THIS_ACCEPTANCE_REQUIRES_100_MOBS')
    winner=json.loads(winner_evidence.read_text())
    if winner['class_key']!='druid' or winner['level']!=20: raise ValueError('WRONG_CHECKPOINT')
    if winner['old_fixture_not_imported_or_read_before_or_after_search'] is not True:
        raise ValueError('BLIND_DISCOVERY_NOT_ATTESTED')
    # Evaluate independent unseeded result before opening the held-out case.
    first=run(winner_evidence,mobs=mobs)
    fixture=json.loads(historical_fixture.read_text())
    if fixture['class_key']!='druid' or fixture['level']!=20: raise ValueError('WRONG_HELDOUT')
    historical=run(historical_fixture,mobs=mobs,historical=True)
    for label,r in [('winner',first),('frozen',historical)]:
        if r['status']!='COMPLETE_100_MOBS' or r['count']!=100 or not r['continuous_actor_state']:
            raise ValueError(f'{label}:MISSING_COMPLETE_100_MOB')
        if not r['all_mobs_executed_at_least_one_action'] or not r['all_mobs_ended_full_health']:
            raise ValueError(f'{label}:AUTOKILL_OR_REGEN_INCONSISTENCY')
        if not r['same_combat_runtime_and_recovery'] or r['events']<=0:
            raise ValueError(f'{label}:DIFFERENT_EXECUTOR')
    result={'schema':'wf300_continuous_100mob_equal_L2_v1',
       'class_key':'druid','level':20,'mobs':100,
       'winner_search_evidence_sha256':sha256(winner_evidence.read_bytes()).hexdigest(),
       'heldout_fixture_sha256':sha256(historical_fixture.read_bytes()).hexdigest(),
       'new':first,'old_frozen':historical,
       'new_minus_old_total_s':first['total_s']-historical['total_s'],
       'new_minus_old_mean_s_per_mob':first['mean_s_per_mob']-historical['mean_s_per_mob'],
       'new_relative_improvement_pct':100*(historical['total_s']-first['total_s'])/historical['total_s'],
       'new_beats_old':first['total_s']<historical['total_s'],
       'same_runtime':True,'same_fresh_target_and_level':True,
       'no_independent_actor_reset':True,'no_opening_cast_if_state_already_satisfied':True,
       'blind_winner_search_proven_but_100mob_objective_not_optimized':True,
       'full_source_ability_and_global_optimum_not_proven':True,
       'formal_checkpoint_accepted':False,'accepted_checkpoint_total':0}
    if not result['new_beats_old']:raise ValueError('FROZEN_CHALLENGER_NOT_BEATEN')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--fixture',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result=go(args.evidence,args.fixture)
    args.output.write_text(json.dumps(result,indent=2,default=str)+'\n')
    print(json.dumps({k:result[k] for k in ('new_minus_old_total_s',
         'new_minus_old_mean_s_per_mob','new_relative_improvement_pct','new_beats_old',
         'formal_checkpoint_accepted')},indent=2))
