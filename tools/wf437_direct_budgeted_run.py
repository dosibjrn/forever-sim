"""WF436 independent, cold, source-driven quick search and external validation diagnostic."""
import argparse,json,time,hashlib,os
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import (source_cold_start_stage,
    search_bounded_joint_frontier,replay_joint_shortlist_100mob)

ap=argparse.ArgumentParser()
ap.add_argument('--budget',type=int,choices=(30,300))
ap.add_argument('--replay-from',help='Saved source search report containing full validation_shortlist')
ap.add_argument('--replay-row',type=int,help='Zero-based finalist row to independently replay')
ap.add_argument('--compare-30',help='Saved independent 30s cold source report')
ap.add_argument('--compare-300',help='Saved independent 300s cold source report')
ap.add_argument('--output',required=True)
args=ap.parse_args()
if args.compare_30 is not None or args.compare_300 is not None:
    if (not args.compare_30 or not args.compare_300 or args.budget is not None
            or args.replay_from is not None or args.replay_row is not None):
        ap.error('comparison requires --compare-30 and --compare-300 only')
elif args.replay_from is None:
    if args.budget is None or args.replay_row is not None:
        ap.error('cold search requires --budget; --replay-row requires --replay-from')
elif args.budget is not None or args.replay_row is None:
    ap.error('saved replay requires --replay-from and --replay-row, without --budget')
root=Path(__file__).resolve().parents[1]
db=root/'data/forever/staged_druid_l30_talents_70338.sqlite'
sourcehash=hashlib.sha256(db.read_bytes()).hexdigest()
ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
stage=source_cold_start_stage(class_key='druid',level=30,source_ir=ir,gear_role='druid_feral')
if args.compare_30 is not None:
    from src.v2.source_paid_cold_comparison import compare_saved_cold_winners
    search30=json.loads(Path(args.compare_30).read_text())
    search300=json.loads(Path(args.compare_300).read_text())
    comparison=compare_saved_cold_winners(search30,search300,
        source_ir=ir,seed_stage=stage,class_key='druid',level=30,
        source_hash=sourcehash,bonus_talent_points=5)
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(comparison,indent=2,default=str))
    print('INDEPENDENT_SOURCE_COLD_COMPARISON',comparison['status'],
          'T30',comparison['T30_s_per_mob'],
          'T300',comparison['T300_s_per_mob'],
          'ratio',comparison['ratio_T30_T300'],flush=True)
    raise SystemExit(0 if comparison['status'].startswith('PAID_COMPARISON_COMPLETE') else 1)
if args.replay_from is not None:
    saved=json.loads(Path(args.replay_from).read_text())
    if saved.get('source_db_sha256') != sourcehash:
        raise ValueError('REPLAY_SOURCE_SQLITE_SHA256_MISMATCH')
    rows=saved.get('validation_shortlist')
    if not isinstance(rows,list) or not rows:
        raise ValueError('REPLAY_REQUIRES_SAVED_FULL_SOURCE_SHORTLIST')
    if not 0 <= args.replay_row < len(rows):
        raise ValueError('REPLAY_ROW_OUT_OF_RANGE')
    selected=rows[args.replay_row]
    required={'allocation','equipped_gear','opening_action_ids','policy_ir',
              'policy_signature','recovery'}
    if required-set(selected):
        raise ValueError('REPLAY_INCOMPLETE_SAVED_SOURCE_BUILD')
    replay_search={'search_only':True,'validation_shortlist':[selected],
                   'complete_100mob_candidates':0,'wall_s':saved['wall_s'],
                   'spec_constraint':saved.get('spec_constraint')}
    replay=replay_joint_shortlist_100mob(
        replay_search,source_ir=ir,seed_stage=stage,
        class_key='druid',level=30,bonus_talent_points=5,
        pack_size=int(saved['pack_size']),max_per_candidate_wall_s=60.)
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps({
        'source_db_sha256':sourcehash,'replayed_row_index':args.replay_row,
        'replayed_source_build':selected,'validation':replay},indent=2,default=str))
    print('INDEPENDENT_SAVED_SOURCE_REPLAY',args.replay_row,
          replay['status'],[(x['status'],x.get('reason'),x.get('count'))
                            for x in replay['rows']],flush=True)
    # A saved replay is a verification command, not a search diagnostic.
    # An incomplete paid 100-mob run must fail the caller even when its
    # structured result was successfully written for first-failure analysis.
    replay_ok=(replay.get('complete_100mob_replays')==1
               and len(replay.get('rows',()))==1
               and replay['rows'][0].get('status')=='COMPLETE'
               and replay['rows'][0].get('count')==100)
    raise SystemExit(0 if replay_ok else 1)
start=time.monotonic()
params=dict(class_key='druid',level=30,source_ir=ir,seed_stage=stage,
    bonus_talent_points=5,max_talents=80,
    # Both independent cold budgets search the SAME source-legal gear/APL
    # candidate universe. Time and paid-candidate caps may differ, but a
    # 300s-only expansion would invalidate the same-space P4/P5 comparison.
    max_gear_moves=16,
    max_policies=8,
    max_recovery_policies=2,
    max_paid_builds=(1000 if args.budget==30 else 20000),
    max_cpu_s=float(args.budget),screen_mobs=2,finalist_mobs=100,
    per_candidate_wall_s=1.,search_only=True,screen_evaluator_backend='direct',
    refinement_top_n=(4 if args.budget==30 else 12),
    refinement_rounds=(1 if args.budget==30 else 3),
    refinement_stat_axes=('spell_power','strength','agility','intellect','spirit','stamina'),
    refinement_probe_delta=20.,refinement_gear_candidates=(3 if args.budget==30 else 5),
    refinement_policy_candidates=(3 if args.budget==30 else 5),pack_size=2)
print('START',args.budget,'params',str({k:v for k,v in params.items() if k not in ('source_ir','seed_stage')}),flush=True)
r=search_bounded_joint_frontier(**params)
print('SEARCH_FINISHED',args.budget,'wall',r['wall_s'],'attempts',r['paid_candidates'],
      'unique',r['unique_full_builds'],'screen_complete',r['screen_complete_candidates'],
      'refine_rounds',r['refinement']['rounds_completed'],'stat_probes',r['refinement']['stat_probes'],
      'gear_probes',r['refinement']['gear_probes'],'winner_proxy',
      (r['search_winner'] or {}).get('screen_s_per_mob'),flush=True)
rv=replay_joint_shortlist_100mob(r,source_ir=ir,seed_stage=stage,
    class_key='druid',level=30,bonus_talent_points=5,pack_size=2,
    max_per_candidate_wall_s=60.) if r['validation_shortlist'] else {'status':'NO_VALIDATION_SHORTLIST'}
print('VALIDATION',args.budget,'status',rv['status'],'wall',rv.get('wall_s_outside_search_budget'),
      'replayed',rv.get('100mob_replays'),'completed',rv.get('complete_100mob_replays'),
      'ranking_reversal',rv.get('ranking_reversal'),'result',[(x['screen_s_per_mob'],x['full_s_per_mob']) for x in rv.get('rows',[])],flush=True)
summary={k:v for k,v in r.items() if k not in ('rows','validation_shortlist','baseline_results','refinement')}
summary['refinement']={k:v for k,v in r['refinement'].items() if k!='rows'}
summary['source_db_sha256']=sourcehash
summary['source_db_path']=str(db)
# Explicitly retain the legal proposal-universe limits for later P4/P5
# same-space verification; budget-specific exploration depth is separate.
summary['source_search_space']={k:params[k] for k in (
    'class_key','level','bonus_talent_points','max_talents',
    'max_gear_moves','max_policies','max_recovery_policies',
    'screen_mobs','finalist_mobs','pack_size')}
summary['source_search_space']['gear_role']='druid_feral'
summary['search_runner_wall_s']=time.monotonic()-start
summary['validation']=rv
# Preserve exact source-legal gear, talent ranks, APL, opening and recovery.
# Without this, a failed 300s finalist cannot be replayed without rerunning
# the entire cold search, and its first failed pull cannot be investigated.
summary['validation_shortlist']=r['validation_shortlist']
summary['shortlist_summary']=[{k:x.get(k) for k in ('allocation','gear_move','policy','recovery',
    'policy_signature','screen_status','screen_s_per_mob','refinement_round','stat_weights_measured')}
    for x in r['validation_shortlist']]
summary['p4_acceptance_status']='NOT_ACCEPTED_SOURCE_COVERAGE_GATES_NOT_PROVEN'
summary['p5_acceptance_status']='NOT_ACCEPTED_SOURCE_COVERAGE_GATES_NOT_PROVEN'
summary['p6_acceptance_status']='NOT_RUN_TWO_BUDGETS_IN_THIS_PROCESS'
Path(args.output).parent.mkdir(parents=True,exist_ok=True)
Path(args.output).write_text(json.dumps(summary,indent=2,default=str))
print('WROTE',args.output,'elapsed',summary['search_runner_wall_s'],flush=True)
