"""WF436 independent, cold, source-driven quick search and external validation diagnostic."""
import argparse,json,time,hashlib,os
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.gear import available_gear_roles
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.talents import talented_bonus_for_level
from src.v2.source_bounded_joint_frontier import (source_cold_start_stage,
    search_bounded_joint_frontier,replay_joint_shortlist_100mob)
from src.v2.source_paid_cold_comparison import (source_gear_catalogue_snapshot,
    verify_saved_source_replay)

ap=argparse.ArgumentParser()
ap.add_argument('--budget',type=int,choices=(30,300))
ap.add_argument('--checkpoint-class',default='druid')
ap.add_argument('--checkpoint-level',type=int,default=30)
ap.add_argument('--checkpoint-spec',default='unrestricted')
ap.add_argument('--gear-slot-offset',type=int,default=0,
    help='Nonnegative source-slot rotation; use the SAME value for paired 30s/300s searches')
ap.add_argument('--replay-from',help='Saved source search report containing full validation_shortlist')
ap.add_argument('--replay-row',type=int,help='Zero-based finalist row to independently replay')
ap.add_argument('--compare-30',help='Saved independent 30s cold source report')
ap.add_argument('--compare-300',help='Saved independent 300s cold source report')
ap.add_argument('--output',required=True)
args=ap.parse_args()
if args.gear_slot_offset<0:
    ap.error('--gear-slot-offset must be nonnegative')
if args.gear_slot_offset and (args.compare_30 is not None or args.compare_300 is not None
                              or args.replay_from is not None):
    ap.error('--gear-slot-offset applies only to a new cold search')
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
class_key=args.checkpoint_class.strip().lower()
level=args.checkpoint_level
spec=args.checkpoint_spec.strip().lower()
if not (1 <= level <= 60):
    ap.error('--checkpoint-level must be 1..60')
if not class_key or not spec:
    ap.error('--checkpoint-class and --checkpoint-spec must be nonempty')
# Use the canonical ability SQLite for every checkpoint. The old L30-only
# staged copy is not a tracked production source or a clean-checkout dependency.
db=Path(DEFAULT_DB)
if not db.is_file():
    raise ValueError('SOURCE_COLD_CHECKPOINT_ABILITY_DB_MISSING')
sourcehash=hashlib.sha256(db.read_bytes()).hexdigest()
ir=build_game_ir_slice(class_key=class_key,level=level,ability_db_path=db)
roles=available_gear_roles(class_key)
if ir is None or not roles:
    raise ValueError('SOURCE_COLD_CHECKPOINT_IR_OR_GEAR_ROLE_UNAVAILABLE')
# Keep the historical L30 Feral seed byte-compatible with the old WF437
# reference; all other checkpoints use the registry's legal source role.
role=('druid_feral' if (class_key,level,spec)==('druid',30,'unrestricted')
      else roles[0])  # legal equipment seed only; no winner preset
bonus=talented_bonus_for_level(level)
spec_params={}
if spec!='unrestricted':
    from tools.wf_source_profile import _load_product_spec_profile
    profile=_load_product_spec_profile(root,class_key,level,spec,
        source_sha256=sourcehash)
    if profile is None:
        raise ValueError('SOURCE_SPEC_PRODUCT_PROFILE_NOT_CONFIGURED')
    spec_params={'spec_tree':profile['tree_key'],
                 'min_spec_points':profile['minimum_points']}
stage=source_cold_start_stage(class_key=class_key,level=level,
    source_ir=ir,gear_role=role)
# Item catalogue and typed effects live outside the staged ability SQLite.
# Pin them independently before search and detect any mid-search mutation.
gear_source_before=source_gear_catalogue_snapshot(class_key,level)
if args.compare_30 is not None:
    from src.v2.source_paid_cold_comparison import compare_saved_cold_winners
    search30=json.loads(Path(args.compare_30).read_text())
    search300=json.loads(Path(args.compare_300).read_text())
    for saved in (search30, search300):
        verify_saved_source_replay(saved, class_key=class_key, level=level,
            spec=spec, source_hash=sourcehash,
            gear_snapshot=gear_source_before, **spec_params)
    comparison=compare_saved_cold_winners(search30,search300,
        source_ir=ir,seed_stage=stage,class_key=class_key,level=level,
        source_hash=sourcehash,bonus_talent_points=bonus)
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(comparison,indent=2,default=str))
    print('INDEPENDENT_SOURCE_COLD_COMPARISON',comparison['status'],
          'T30',comparison['T30_s_per_mob'],
          'T300',comparison['T300_s_per_mob'],
          'ratio',comparison['ratio_T30_T300'],flush=True)
    raise SystemExit(0 if comparison['status'].startswith('PAID_COMPARISON_COMPLETE') else 1)
if args.replay_from is not None:
    saved=json.loads(Path(args.replay_from).read_text())
    verify_saved_source_replay(saved, class_key=class_key, level=level,
        spec=spec, source_hash=sourcehash,
        gear_snapshot=gear_source_before, **spec_params)
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
                   'bonus_talent_points':saved['bonus_talent_points'],
                   'spec_constraint':saved.get('spec_constraint')}
    replay=replay_joint_shortlist_100mob(
        replay_search,source_ir=ir,seed_stage=stage,
        class_key=class_key,level=level,bonus_talent_points=bonus,
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
params=dict(class_key=class_key,level=level,source_ir=ir,seed_stage=stage,
    bonus_talent_points=bonus,max_talents=80,
    # Both independent cold budgets search the SAME source-legal gear/APL
    # candidate universe. Time and paid-candidate caps may differ, but a
    # 300s-only expansion would invalidate the same-space P4/P5 comparison.
    max_gear_moves=16,
    gear_slot_offset=args.gear_slot_offset,
    max_policies=8,
    max_recovery_policies=2,
    max_paid_builds=(1000 if args.budget==30 else 20000),
    max_cpu_s=float(args.budget),screen_mobs=2,finalist_mobs=100,
    per_candidate_wall_s=1.,search_only=True,screen_evaluator_backend='direct',
    # The short search previously promoted only four paid parent builds;
    # measured 30s/100-mob production runs missed later legal talent
    # transfers. Keep source-neutral exploration across twelve paid parents
    # in three rounds, with broader legal neighbors within the same 30s clock.
    # The 300s strategy remains unchanged and both budgets cold-start.
    refinement_top_n=12,
    refinement_rounds=3,
    refinement_talent_neighbors=(6 if args.budget==30 else 2),
    refinement_stat_axes=('spell_power','strength','agility','intellect','spirit','stamina'),
    refinement_probe_delta=20.,refinement_gear_candidates=(3 if args.budget==30 else 5),
    refinement_policy_candidates=(3 if args.budget==30 else 5),pack_size=2,
    **spec_params)
print('START',args.budget,'params',str({k:v for k,v in params.items() if k not in ('source_ir','seed_stage')}),flush=True)
r=search_bounded_joint_frontier(**params)
print('SEARCH_FINISHED',args.budget,'wall',r['wall_s'],'attempts',r['paid_candidates'],
      'unique',r['unique_full_builds'],'screen_complete',r['screen_complete_candidates'],
      'refine_rounds',r['refinement']['rounds_completed'],'stat_probes',r['refinement']['stat_probes'],
      'gear_probes',r['refinement']['gear_probes'],'winner_proxy',
      (r['search_winner'] or {}).get('screen_s_per_mob'),flush=True)
rv=replay_joint_shortlist_100mob(r,source_ir=ir,seed_stage=stage,
    class_key=class_key,level=level,bonus_talent_points=bonus,pack_size=2,
    max_per_candidate_wall_s=60.) if r['validation_shortlist'] else {'status':'NO_VALIDATION_SHORTLIST'}
print('VALIDATION',args.budget,'status',rv['status'],'wall',rv.get('wall_s_outside_search_budget'),
      'replayed',rv.get('100mob_replays'),'completed',rv.get('complete_100mob_replays'),
      'ranking_reversal',rv.get('ranking_reversal'),'result',[(x['screen_s_per_mob'],x['full_s_per_mob']) for x in rv.get('rows',[])],flush=True)
summary={k:v for k,v in r.items() if k not in ('rows','validation_shortlist','baseline_results','refinement')}
summary['refinement']={k:v for k,v in r['refinement'].items() if k!='rows'}
summary['source_db_sha256']=sourcehash
summary['source_db_path']=str(db)
gear_source_after=source_gear_catalogue_snapshot(class_key,level)
if gear_source_before != gear_source_after:
    raise ValueError('COLD_SOURCE_GEAR_CATALOGUE_CHANGED_DURING_SEARCH')
summary['source_gear_catalogue_snapshot']=gear_source_after
# Explicitly retain the legal proposal-universe limits for later P4/P5
# same-space verification; budget-specific exploration depth is separate.
summary['source_search_space']={k:params[k] for k in (
    'class_key','level','bonus_talent_points','max_talents',
    'max_gear_moves','gear_slot_offset','max_policies','max_recovery_policies',
    'screen_mobs','finalist_mobs','pack_size')}
summary['source_search_space']['gear_role']=role
if (class_key,level,spec)!=('druid',30,'unrestricted'):
    summary['source_search_space']['checkpoint_spec']=spec
if spec_params:
    summary['source_search_space'].update(spec_params)
# Record what the production search actually ran, not a CLI-local version.
summary['source_search_space']['gear_slot_sampling_version']=r['source_slot_proposal_coverage']['strategy']
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
