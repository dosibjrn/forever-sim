"""Checkpoint-scoped P2 optimizer proof. No level-specific builds or seeds.

Example: PYTHONPATH=. python -m tools.wf336_p2_optimizer_pilot \
  --class-key druid --level 20 \
  --source-file evidence/wf336/druid_l20_talent_rank_observations_70338.json
"""
from argparse import ArgumentParser
from pathlib import Path
from time import perf_counter
import json

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint, evaluate_p2
from src.game.data.forever.source_checkpoint_p2_optimizer import rank_opportunity_frontier
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents


def run(class_key:str,level:int,source_file:str,*,profile='unrestricted',
        source_build='1.60.1.70338',max_evaluations=48,spellbook_file=None):
    cp=P2Checkpoint(class_key,level,profile=profile,source_build=source_build)
    ir=build_game_ir_slice(class_key=class_key,level=level)
    certificate=evaluate_p2(ir,cp,source_observations_path=source_file,spellbook_path=spellbook_file)
    if not certificate['p2_pass']:
        raise ValueError('P2_LEGAL_TALENT_RANK_COVERAGE_UNPROVEN')
    frontier=rank_opportunity_frontier(certificate,class_key=class_key,level=level)
    t=perf_counter()
    search=run_source_budgeted_joint_talents(class_key=class_key,level=level,
        max_evaluations=max_evaluations,evaluations_per_talent=10,
        initial_search=5,search_per_gear=5,max_gear_states=1,
        ir_slice=ir,talent_l0_certificate=certificate)
    elapsed=perf_counter()-t
    measured={'schema':'source_checkpoint_p2_optimizer_proof_v1',
        'checkpoint':dict(frontier['checkpoint']),
        'talent_families_l0':frontier['families'],
        'talent_ranks_l0':frontier['rank_count'],
        'source_only_l0_ranks':frontier['source_only_count'],
        'source_only_still_l2_unsupported':True,
        'paid_joint_attempts':search['attempted'],
        'paid_joint_evaluated':search['evaluated'],
        'paid_joint_blocked':search['blocked'],
        'l0_priority_queries_in_optimizer':search['talent_l0_priority_queries'],
        'l0_influenced_candidate_order':search['talent_l0_influenced_candidate_order'],
        'distinct_allocations_paid_l2':search['distinct_talent_allocations_paid_L2'],
        'all_rank_l0_frontier_exposed_to_optimizer':len(search['talent_l0_rank_frontier'])==frontier['rank_count'],
        'joint_search_wall_s':elapsed,
        'legacy_prefix_backend_event_counter':search['event_transitions'],
        'legacy_prefix_backend_event_counter_not_proven_reliable':True,
        'pilot_is_not_p4_or_p5':True,
        'pilot_not_100_mobs':True,
        'p2_pass': bool(frontier['ready'] and
                        search['talent_l0_influenced_candidate_order'] and
                        len(search['talent_l0_rank_frontier'])==frontier['rank_count']),
        'accepted_checkpoints':0}
    output=Path(f'evidence/wf336/{class_key}_l{level}_p2_optimizer_proof.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(measured,indent=2,sort_keys=True)+'\n')
    return measured

if __name__=='__main__':
    parser=ArgumentParser()
    parser.add_argument('--class-key',required=True)
    parser.add_argument('--level',type=int,required=True)
    parser.add_argument('--source-file',required=True)
    parser.add_argument('--profile',default='unrestricted')
    parser.add_argument('--source-build',default='1.60.1.70338')
    parser.add_argument('--max-evaluations',type=int,default=48)
    parser.add_argument('--spellbook-file',default=None)
    a=parser.parse_args()
    print(json.dumps(run(a.class_key,a.level,a.source_file,profile=a.profile,
          source_build=a.source_build,max_evaluations=a.max_evaluations,spellbook_file=a.spellbook_file),indent=2))
