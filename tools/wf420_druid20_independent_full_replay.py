"""Rebuild WF420 winning paid gear/talent/policy from cold SQLite, no oracle.

Reads the cold search's candidate identity only AFTER search. Does not seed
or otherwise influence P4/P5. Recoveries/gear/policy use the same production
source adapters as the search. Explicitly report unresolved stat sensitivities.
"""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import source_cold_start_stage,_recovery_variants
from src.v2.source_persistent_slot_search import _source_stat_package_proposals
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.v2.source_reoptimized_stat_sensitivity import reoptimized_stat_sensitivity
from src.rulesets.forever.items.runtime_selection import catalogue_path

ROOT=Path(__file__).resolve().parents[1]
P4=ROOT/'evidence/wf420/WF420_DRUID_L20_COLD_P4_30S.json'
OUT=ROOT/'evidence/wf420/WF420_P4_INDEPENDENT_100MOB_AND_STAT_PROBE.json'

def rebuild_result_winner(path=P4):
    evidence=json.loads(Path(path).read_text())
    if evidence['seed_origin']!='COLD_SQLITE_SOURCE_NO_PREVIOUS_WINNER':
        raise ValueError('REPLAY_REQUIRES_REAL_COLD_SOURCE_SEARCH')
    klass=evidence['class_key'];level=int(evidence['level'])
    winner=evidence['winner']
    source_ir=build_game_ir_slice(class_key=klass,level=level)
    stage=source_cold_start_stage(class_key=klass,level=level,source_ir=source_ir,
        gear_role='druid_feral')
    move=str(winner['gear_move'])
    if move.startswith('source_stat_package:'):
        axis=move.split(':',1)[1]
        packages,_=_source_stat_package_proposals(class_key=klass,level=level,
            base=stage['gear_policy_result']['winner']['gear'],max_packages=4)
        stage=substituted_multi_stage(stage=stage,class_key=klass,level=level,
            swaps=dict(packages)[axis])
    elif move!='incumbent':
        raise ValueError('REPLAY_UNSUPPORTED_WINNER_GEAR_MOVE:'+move)
    if winner['policy']!='incumbent':
        raise ValueError('REPLAY_UNSUPPORTED_WINNER_POLICY:'+str(winner['policy']))
    candidate=prepare_candidate(class_key=klass,level=level,stage=stage,
        allocation_override=winner['allocation'],source_ir=source_ir,
        bonus_talent_points=int(evidence['bonus_talent_points']),allow_partial_gear_stats=True)
    recovery=dict(_recovery_variants(candidate.ir,stage,3))[winner['recovery']]
    return evidence,candidate,recovery

def main():
    evidence,candidate,recovery=rebuild_result_winner()
    w=evidence['winner']
    actual=evaluate_persistent_candidate(candidate,level=20,mobs=100,
        recovery_policy=recovery,max_wall_s=18.)
    if actual['status']!='COMPLETE' or actual['count']!=100 or actual['events']!=w['full_events'] or abs(actual['mean_s_per_mob']-w['seconds_per_mob'])>1e-9:
        raise ValueError('P4_INDEPENDENT_100MOB_REPLAY_MISMATCH')
    measures={}
    # Explicit bounded sensitivity, no small epsilon / no forced positivity.
    for axis,delta in [('stamina',20.),('spirit',20.),('spell_power',30.),('mp5',10.),
                       ('intellect',20.),('armor',200.),('agility',20.),('strength',20.)]:
        try:
            measures[axis]=reoptimized_stat_sensitivity(candidate=candidate,stat=axis,
                delta=delta,level=20,recovery_policies=(recovery,),mobs=100,
                max_wall_s_per_eval=18.)
        except (ValueError,KeyError) as exc:
            measures[axis]={'status':'UNSUPPORTED_OR_UNRESOLVED','reason':str(exc)}
    report={'release':'WF420','checkpoint':'druid:L20:talented_on_16_points',
      'p4_source_result_sha256':sha256(P4.read_bytes()).hexdigest(),
      'source_item_db_sha256':sha256(catalogue_path().read_bytes()).hexdigest(),
      'replay':{'status':actual['status'],'mobs':actual['count'],
                'seconds_per_mob':actual['mean_s_per_mob'],'events':actual['events'],
                'exact_result':True},
      'talents':w['allocation'],'gear_move':w['gear_move'],
      'equipped_item_ids':{k:int(v['item_id']) for k,v in candidate.source_stage['gear_policy_result']['winner']['gear']['slots'].items()},
      'source_100mob_stat_sensitivity_fixed_best_recovery':measures,
      'p3_status':'NOT_CERTIFIED_FULL_16PT_WEIGHT_COVERAGE_NOT_YET_MET',
      'p5_p6_p7_status':'SEPARATE',
      'accepted_checkpoint':False}
    OUT.parent.mkdir(exist_ok=True,parents=True)
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'replay':report['replay'],
        'stat_probes':{k:round(v.get('weight_s_saved_per_mob_per_unit') or 0.,7) for k,v in measures.items()},
        'statuses':{k:v['status'] for k,v in measures.items()}},indent=2))

if __name__=='__main__':main()
