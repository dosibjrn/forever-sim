"""Cold, independent Druid L30 source joint discovery with conditional 100-pull scoring.

Never imports a previous winner; uses canonical SQLite -> IR -> source joint
gear/talent/policy discovery -> existing persistent CombatRuntime. The parent
enforces a 30-second whole-process deadline, including startup and writing.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, os, resource, sqlite3, tempfile
from pathlib import Path
from time import monotonic, process_time
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.registry import build_game_ir_slice
from src.game.recovery_between_pulls import BetweenPullPolicy
from src.game.talent_frontier import source_legal_talent_neighbors
from src.v2.source_persistent_gear_neighborhood import refine_source_gear_persistent
from src.v2.source_persistent_policy_neighborhood import refine_source_policy_persistent
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.v2.source_persistent_joint_finalists import (
    select_persistent_finalists, _paid_source_candidate_stages, prepare_candidate, evaluate_persistent_candidate)
from src.rulesets.forever.items.source_equipment_semantics import validate_equipped_item_ids
from tools.wf321_ingest_control_observations import ingest as ingest_control
from tools.wf297_druid_l20_checkpoint import JOINT_ARGS
ROOT = Path(__file__).resolve().parents[1]
RECOVERY = BetweenPullPolicy(.25, .10, exit_action_id='cancel_mode:cat', reentry_action_id='cat_form:768')

def identity(stage):
    gp=stage['gear_policy_result']['winner']; p=gp['winner']
    return json.dumps({'allocation':stage['allocation'],
        'gear':sorted((slot,int(x['item_id'])) for slot,x in gp['gear']['slots'].items()),
        'opening':p['prefix'],'fallback':p['fallback'],
        'guarded_action':p.get('guarded_action'),
        'guarded_conditions':p.get('guarded_conditions')},sort_keys=True,default=str)

def run(*,evaluations=125,events=17000, screens=10, finalists=2, profiles=1,
        neighbors=0, transfer_neighbors=0, gear_neighbors=0, apl_neighbors=0, search_deadline_s=30.):
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    start=monotonic();cpu_start=process_time();children_start=resource.getrusage(resource.RUSAGE_CHILDREN)
    with tempfile.TemporaryDirectory(prefix='wf360_druid_l30_cold_') as tmp:
        db=Path(tmp)/'source.sqlite'
        canonical=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
        with sqlite3.connect(f'file:{canonical.resolve()}?mode=ro',uri=True) as src, sqlite3.connect(db) as dst:
            src.backup(dst)
        ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        db_hash=hashlib.sha256(db.read_bytes()).hexdigest()
        with ability_source_scope(db):
            ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
            opts={**JOINT_ARGS,'level':30,'ir_slice':ir,'max_evaluations':evaluations,
                'max_event_transitions':events,'evaluations_per_talent':35,
                'initial_search':8,'search_per_gear':8,'max_gear_states':2,
                'talent_corridor_reserve':4,'talent_screening_attempts':12,
                'post_talent_refinement_budget':0,'exclude_unknown_item_effects':True}
            if profiles not in (1,3):raise ValueError('ONLY_ONE_OR_THREE_COLD_PROFILES')
            # Every restart starts with source-empty talents. No prior winner
            # is passed to a later profile. A larger budget explores different
            # source-derived role/stat/talent corridors, not legacy candidates.
            variants=[opts]
            if profiles==3:
                variants.extend([
                    {**opts,'max_evaluations':max(400,evaluations),
                        'max_event_transitions':max(55000,events),
                        'talent_corridor_reserve':10,'talent_screening_attempts':30,
                        'post_talent_refinement_budget':90,'max_gear_states':3,
                        'initial_search':10,'search_per_gear':12},
                    {**opts,'max_evaluations':max(400,evaluations),
                        'max_event_transitions':max(55000,events),
                        'talent_corridor_reserve':15,'talent_screening_attempts':45,
                        'post_talent_refinement_budget':110,'max_gear_states':3,
                        'initial_search':12,'search_per_gear':12,
                        'probe_stats':('intellect','spirit','stamina'),
                        'probe_deltas':(10.,25.)}])
            joints=[]
            for profile_index,variant in enumerate(variants):
                one=run_source_budgeted_joint_talents(**variant)
                joints.append(one)
                print('PROFILE_DONE',profile_index+1,'attempts',one['attempted'],
                      'events',one['event_transitions'],'elapsed_wall',monotonic()-start,flush=True)
            paid_stages=[stage for joint in joints for stage in _paid_source_candidate_stages(joint)]
            unique={identity(s) for s in paid_stages if s.get('score_s_per_mob') is not None and
                    ((s.get('gear_policy_result') or {}).get('winner') or {}).get('gear')}
            joint=joints[0]
            combined={'stages':paid_stages}
            if not any(j.get('winner') for j in joints) or not unique:
                raise RuntimeError('NO_LEGAL_JOINT_STAGE')
            discovery_wall=monotonic()-start
            finalist=select_persistent_finalists(class_key='druid',level=30,joint_result=combined,
                source_legal_neighbors_per_seed=neighbors,
                screen_mobs=2,finalist_mobs=100,max_finalists=finalists,
                max_screen_candidates=screens,max_screen_wall_s=2.,max_finalist_wall_s=9.,
                max_shared_evidence_events=55000,max_shared_evidence_cpu_s=12.,
                strict_l2_item_effects=True,recovery_policies=(RECOVERY,))
            winner=finalist.get('winner')
            transfer_trials=[]
            transfer_events=0
            transfer_attempts=0
            transfer_completed=0
            transfer_full=0
            transfer_unique=set()
            transfer_seen=set()
            if winner is not None and transfer_neighbors:
                # Generic source-legal one-point transfers around THIS run's
                # self-discovered winner, not a prior/legacy/oracle seed.
                base=winner
                nearby=source_legal_talent_neighbors(ir,base['allocation'],level=30)
                for n in (n for n in nearby['neighbors'] if n.operation=='point_transfer'):
                    if transfer_attempts>=transfer_neighbors or monotonic()-start>=(23.5 if search_deadline_s<=30 else search_deadline_s*.60):break
                    allocation=dict(n.allocation)
                    stage=copy.deepcopy(base['stage']);stage['allocation']=allocation
                    ident=identity(stage)
                    if ident in transfer_seen:continue
                    transfer_seen.add(ident)
                    transfer_attempts+=1
                    try:
                        candidate=prepare_candidate(class_key='druid',level=30,
                            stage=stage,source_ir=ir,strict_l2_item_effects=True)
                        transfer_unique.add(ident)  # Only source/legal prepared builds count.
                        screen=evaluate_persistent_candidate(candidate,level=30,mobs=2,
                            recovery_policy=RECOVERY,max_wall_s=1.,max_cpu_s=1.,
                            max_total_events=4500)
                    except (ValueError,RuntimeError,KeyError) as exc:
                        screen={'status':'BLOCKED_CANDIDATE','reason':str(exc)[:200]}
                    transfer_events+=int(screen.get('events') or 0)
                    if screen['status']=='COMPLETE':transfer_completed+=1
                    transfer_trials.append({'allocation':allocation,'stage':stage,'screen':screen})
                ranked=sorted((r for r in transfer_trials if r['screen']['status']=='COMPLETE'),
                              key=lambda r:r['screen']['mean_s_per_mob'])
                for row in ranked[:3]:
                    if monotonic()-start>=(26.5 if search_deadline_s<=30 else search_deadline_s*.65):break
                    try:
                        candidate=prepare_candidate(class_key='druid',level=30,
                            stage=row['stage'],source_ir=ir,strict_l2_item_effects=True)
                        verified=evaluate_persistent_candidate(candidate,level=30,mobs=100,
                            recovery_policy=RECOVERY,max_wall_s=6.,max_cpu_s=6.,
                            max_total_events=200000)
                    except (ValueError,RuntimeError,KeyError) as exc:
                        verified={'status':'BLOCKED_CANDIDATE','reason':str(exc)[:200]}
                    transfer_events+=int(verified.get('events') or 0)
                    transfer_full+=1
                    if (verified['status']=='COMPLETE' and
                        verified['mean_s_per_mob']<winner['persistent']['mean_s_per_mob']):
                        winner={'allocation':row['allocation'],'stage':row['stage'],
                                'persistent':verified,
                                'screen_mean_s_per_mob':row['screen']['mean_s_per_mob'],
                                'recovery_policy':vars(RECOVERY)}
            gear_refinement=None
            gear_unique=set()
            if winner is not None and gear_neighbors:
                # Source-selector perturbations start ONLY from this run's own
                # independently discovered and verified stage. They do not
                # load WF358/legacy fixtures or historical winners.
                remaining=min(60.,search_deadline_s-2.0-(monotonic()-start))
                if remaining>0.3:
                    gear_refinement=refine_source_gear_persistent(
                        class_key='druid',level=30,stage=winner['stage'],
                        screen_mobs=2,finalist_mobs=100,max_proposals=gear_neighbors,
                        max_finalists=1 if search_deadline_s<=30 else 3,
                        max_screen_wall_s=1.,max_finalist_wall_s=6.,
                        recovery_policy=RECOVERY,source_ir=ir,
                        strict_l2_item_effects=True,max_total_wall_s=remaining)
                    gear_unique={identity(r['stage']) for r in gear_refinement['finalists']
                                 if r['persistent']['status']=='COMPLETE'}
                    g=gear_refinement.get('winner')
                    if g is not None and g['persistent']['mean_s_per_mob']<winner['persistent']['mean_s_per_mob']:
                        winner={'allocation':g['stage']['allocation'],'stage':g['stage'],
                                'persistent':g['persistent'],
                                'screen_mean_s_per_mob':g['screen']['mean_s_per_mob'],
                                'recovery_policy':vars(RECOVERY)}
            # Optional generic policy evolution on this run's own legal winner.
            # Do NOT seed with a held-out/legacy/reference winner; only source
            # actions in the prepared candidate's current (talented) GameIR.
            apl_refinement=None
            if winner is not None and apl_neighbors:
                remaining=min(24.,search_deadline_s-2.0-(monotonic()-start))
                if remaining>8.:
                    prepared=prepare_candidate(class_key='druid',level=30,
                        stage=winner['stage'],source_ir=ir,strict_l2_item_effects=True)
                    apl_refinement=refine_source_policy_persistent(prepared,level=30,
                        recovery_policy=RECOVERY,max_proposals=apl_neighbors,
                        max_finalists=2 if remaining>=18 else 1,
                        max_total_wall_s=remaining,baseline_100mob=winner['persistent'])
                    apl_win=apl_refinement.get('winner')
                    if (apl_win is not None and
                        apl_win['result']['mean_s_per_mob']<winner['persistent']['mean_s_per_mob']):
                        winner={**winner,'persistent':apl_win['result'],
                                'apl_policy_override':apl_win['policy'],
                                'apl_policy_refinement_origin':'paid_100mob_mutation'}
            if winner is None or winner['persistent']['status']!='COMPLETE':
                raise RuntimeError('NO_COMPLETE_100_MOB_WINNER')
            gp=winner['stage']['gear_policy_result']['winner'];gear=gp['gear'];policy=gp['winner']
            validate_equipped_item_ids(int(x['item_id']) for x in gear['slots'].values())
            # Source/legal IR verification, not a parallel executor or an old-build seed.
            prepare_candidate(class_key='druid',level=30,stage=winner['stage'],source_ir=ir,
                              strict_l2_item_effects=True)
            children=resource.getrusage(resource.RUSAGE_CHILDREN)
            out={'checkpoint':'druid:L30:unrestricted','status':'COMPLETE',
                'independent_discovery':True,'old_winner_seeded':False,
                'source_db_sha256':db_hash,'source_context_sha256':joint['source_context_sha256'],
                'search_profile_context_sha256s':[j['source_context_sha256'] for j in joints],
                'search_profiles':len(joints),
                'recovery_policy':vars(RECOVERY),'wall_s_worker':monotonic()-start,
                'cpu_s_worker_and_children':process_time()-cpu_start+
                    (children.ru_utime+children.ru_stime-children_start.ru_utime-children_start.ru_stime),
                'discovery_wall_s':discovery_wall,'attempts_joint':sum(j['attempted'] for j in joints),
                'evaluated_joint':sum(j['evaluated'] for j in joints),
                'blocked_joint':sum(j['blocked'] for j in joints),
                'events_joint':sum(j['event_transitions'] for j in joints),
                'events_screen_and_final':finalist['paid_persistent_events'],
                'events_transfer_refinement':transfer_events,
                'events_gear_refinement':0 if gear_refinement is None else gear_refinement['events_paid'],
                'attempts_gear_refinement':0 if gear_refinement is None else gear_refinement['attempts_paid'],
                'gear_refinement':None if gear_refinement is None else {
                    'proposals_generated':gear_refinement['proposals_generated'],
                    'attempts_paid':gear_refinement['attempts_paid'],
                    'unique_legal_gear_sets':gear_refinement['unique_legal_gear_sets'],
                    'screen_completed':gear_refinement['screen_completed'],
                    'finalists_completed':gear_refinement['finalists_completed'],
                    'elapsed_wall_s':gear_refinement['elapsed_wall_s'],
                    'status':gear_refinement['status'],
                    'blocked_reasons':[r.get('reason','') for r in gear_refinement['screened']
                                       if r['status']=='BLOCKED_SOURCE_GEAR'][:8]},
                'events_total':sum(j['event_transitions'] for j in joints)+finalist['paid_persistent_events']+transfer_events+(0 if gear_refinement is None else gear_refinement['events_paid'])+(0 if apl_refinement is None else apl_refinement['paid_events']),
                'apl_refinement':None if apl_refinement is None else {
                    'status':apl_refinement['status'],
                    'screen_attempts':apl_refinement['screen_attempts'],
                    'screen_complete':apl_refinement['screen_complete'],
                    'full_attempts':apl_refinement['full_attempts'],
                    'full_complete':apl_refinement['full_complete'],
                    'paid_events':apl_refinement['paid_events'],
                    'source_actions_proposed':apl_refinement['source_actions_proposed'],
                    'source_actions_total':apl_refinement['source_actions_total'],
                    'search_is_exhaustive':False,
                    'elapsed_wall_s':apl_refinement['elapsed_wall_s'],
                    'winner_policy_id':None if apl_refinement['winner'] is None else apl_refinement['winner']['policy_id'],
                    'winner_actual_100mob':None if apl_refinement['winner'] is None else apl_refinement['winner']['result']['mean_s_per_mob']},
                'attempts_total':sum(j['attempted'] for j in joints)+finalist['screen_evaluated']+finalist['finalists_evaluated']+transfer_attempts+transfer_full+(0 if gear_refinement is None else gear_refinement['attempts_paid'])+(0 if apl_refinement is None else apl_refinement['screen_attempts']+apl_refinement['full_attempts']-1),
                'unique_complete_builds_paid_lower_bound':len(unique|transfer_unique|gear_unique),
                'unique_joint_paid_stages':len(unique),
                'transfer_screen_attempts':transfer_attempts,
                'transfer_screen_complete':transfer_completed,
                'transfer_full_100mob_attempts':transfer_full,
                'screen_attempts':finalist['screen_evaluated'],
                'screen_completed':finalist['screen_completed'],
                'finalist_attempts':finalist['finalists_evaluated'],
                'finalist_complete':sum(x['persistent']['status']=='COMPLETE' for x in finalist['finalists']),
                'winner_stage':winner['stage'],
                'winner':{'apl_policy_override':None if winner.get('apl_policy_override') is None else winner['apl_policy_override'].as_dict(),
                    'allocation':winner['allocation'],
                    'gear':{k:int(v['item_id']) for k,v in gear['slots'].items()},
                    'policy':{'opening':policy['prefix'],'fallback':policy['fallback'],
                        'guarded_action':policy.get('guarded_action'),
                        'guarded_conditions':policy.get('guarded_conditions')},
                    'predicted_100mob_s_per_mob':winner['screen_mean_s_per_mob'],
                    'prediction_method':'two-mob conditional-recovery screen (uncertain proxy)',
                    'actual_100mob_s_per_mob':winner['persistent']['mean_s_per_mob'],
                    'actual_100mob_events':winner['persistent']['events'],
                    'actual_100mob_combat_s':winner['persistent']['combat_s'],
                    'actual_100mob_recovery_s':winner['persistent']['recovery_s'],
                    'actual_100mob_maintenance_s':winner['persistent']['maintenance_s']},
                'uncertainty':['source effect unknowns remain L0-only and excluded from L2 finalists',
                               'bounded discovery is not a global optimum proof']}
            return out

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--evaluations',type=int,default=125);p.add_argument('--events',type=int,default=17000)
    p.add_argument('--screens',type=int,default=10);p.add_argument('--finalists',type=int,default=2)
    p.add_argument('--profiles',type=int,default=1);p.add_argument('--neighbors',type=int,default=0)
    p.add_argument('--transfer-neighbors',type=int,default=0)
    p.add_argument('--gear-neighbors',type=int,default=0)
    p.add_argument('--apl-neighbors',type=int,default=0)
    p.add_argument('--search-deadline-s',type=float,default=30.)
    a=p.parse_args();result=run(evaluations=a.evaluations,events=a.events,screens=a.screens,finalists=a.finalists,profiles=a.profiles,neighbors=a.neighbors,transfer_neighbors=a.transfer_neighbors,gear_neighbors=a.gear_neighbors,apl_neighbors=a.apl_neighbors,search_deadline_s=a.search_deadline_s)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    temp=a.output.with_suffix('.tmp');temp.write_text(json.dumps(result,indent=2,sort_keys=True,default=str)+'\n');temp.replace(a.output)
    print(json.dumps({k:result[k] for k in ('status','wall_s_worker','attempts_total','events_total','unique_complete_builds_paid_lower_bound')},sort_keys=True),flush=True)
if __name__=='__main__':main()
