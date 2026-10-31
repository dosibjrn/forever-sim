"""Exact source-legal item substitutions, scored by existing 100-mob CombatRuntime.

The stat-weight Top5 is a PROPOSAL frontier. Discrete, nonmonotone effects
must be measured on the actual equipped build, not extrapolated from a slope.
Unresolved item effects remain eligible for L0 but never get a fabricated L2.
"""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json
import multiprocessing as mp
from math import isfinite
from pathlib import Path
from time import monotonic

from src.rulesets.forever.items.runtime_selection import (
    available_items, catalogue_path, item_payload, item_vector, effective_level,
)
from src.rulesets.forever.items.source_equipment_semantics import (
    validate_equipped_item_ids, ledger_path,
)
from src.game.data.forever.source_checkpoint_p3 import source_item_l0
from src.game.data.forever.source_named_gear_proof import audit_named_gear_source
from src.v2.source_persistent_joint_finalists import prepare_candidate, evaluate_persistent_candidate


def _drop_implicit_offhand_for_twohand(slots, swaps, legal):
    """A source-stage incumbent offhand is not an explicitly locked swap."""
    if 'weapon' not in swaps or 'offhand' in swaps:
        return
    weapon = legal[int(swaps['weapon'])]
    if weapon.weapon_hands == 2 or weapon.slot == 'two_hand':
        slots.pop('offhand', None)


def substituted_multi_stage(*,stage,class_key,level,swaps):
    """Atomically rebuild one jointly legal candidate from source item IDs.

    Validate the FINAL weapon/offhand and unique-equipped package, never a
    potentially invalid intermediate state. Do not mutate the input stage.
    """
    gear=stage['gear_policy_result']['winner']['gear']
    if gear['class_key']!=class_key or int(gear['level'])!=level:
        raise ValueError('P3_SWAP_WRONG_CHECKPOINT')
    # A two-handed base build has no offhand slot. A legal one-hand+offhand
    # *package* must still be reachable by the P3 item-swap evaluator.
    # Never allow a standalone offhand on a two-handed weapon.
    absent=set(swaps)-set(gear['slots'])
    if absent and (absent != {'offhand'} or 'weapon' not in swaps):
        raise ValueError('P3_SWAP_SLOT_NOT_EQUIPPED_OR_UNPAIRED_OFFHAND')
    legal={int(x.item_id):x for x in available_items(class_key,level,required_level_policy='observed')}
    new=deepcopy(stage)
    out=new['gear_policy_result']['winner']['gear']
    for slot,iid in swaps.items():
        item=legal.get(int(iid))
        if item is None:raise ValueError('P3_SWAP_ITEM_NOT_SOURCE_LEGAL')
        out['slots'][slot]=item_payload(item,display_slot=str(slot),effective_level=effective_level(item))
    _drop_implicit_offhand_for_twohand(out['slots'], swaps, legal)
    out['item_count']=len(out['slots'])
    validate_equipped_item_ids(int(v['item_id']) for v in out['slots'].values())
    total={}
    for x in out['slots'].values():
        actual=legal.get(int(x['item_id']))
        if actual is None:raise ValueError('P3_SWAP_EXISTING_ITEM_NOT_LEGAL')
        for stat,val in item_vector(actual).items():
            total[stat]=total.get(stat,0.)+float(val)
    out['aggregate_stats']=total
    audit=audit_named_gear_source(class_key=class_key,level=level,gear=out)
    if not audit['equipment_legality_complete']:
        raise ValueError('P3_SWAP_ILLEGAL_EQUIPMENT:'+','.join(
            r['source_status'] for r in audit['items'] if r['source_status']!='VERIFIED_PINNED_EQUIPMENT_LEGALITY'))
    new['score_s_per_mob']=None
    new['stage_score_status']='P3_DIRECT_SWAP_NOT_SOURCE_L2_SCORED'
    new['paid_candidate_origin']='P3_SOURCED_ITEM_SWAP'
    return new


def substituted_stage(*,stage,class_key,level,slot,item_id):
    return substituted_multi_stage(stage=stage,class_key=class_key,level=level,
                                   swaps={slot:int(item_id)})

def _worker(q,candidate,level):
    try:
        r=evaluate_persistent_candidate(candidate,level=level,mobs=100,
            max_total_events=200000,max_wall_s=15.,max_cpu_s=15.)
        q.put({k:r.get(k) for k in ('status','mean_s_per_mob','events','combat_s',
                                   'recovery_s','maintenance_s','elapsed_wall_s','elapsed_cpu_s','mob_completed')})
    except BaseException as e:
        q.put({'status':'ERROR','reason':type(e).__name__+':'+str(e)[:250]})


def isolated_100mob(candidate,*,level,timeout_s=8.,worker=None):
    """Kill a stuck recovery evaluator; no incomplete score can rank a swap."""
    if not 0<timeout_s<=300 or 'fork' not in mp.get_all_start_methods():
        raise ValueError('P3_NO_SAFE_OS_ISOLATION_OR_INVALID_TIMEOUT')
    ctx=mp.get_context('fork');q=ctx.Queue(maxsize=1)
    p=ctx.Process(target=worker or _worker,args=(q,candidate,level))
    t=monotonic();p.start();p.join(timeout_s)
    if p.is_alive():
        p.terminate();p.join(1.)
        if p.is_alive():p.kill();p.join(1.)
        result={'status':'OS_TIMEOUT'}
    else:
        try:result=q.get(timeout=.3)
        except Exception:result={'status':'WORKER_EXIT_WITHOUT_RESULT','exitcode':p.exitcode}
    q.close();q.join_thread()
    if result.get('status')=='COMPLETE':
        score=result.get('mean_s_per_mob')
        if score is None or not isfinite(float(score)) or score<=0:
            result={'status':'INVALID_100MOB_SCORE'}
    return {**result,'outer_wall_s':monotonic()-t}


def _stage_worker(q,stage,source_ir,class_key,level,slot,item_id):
    """Both candidate preparation AND 100mob must be in the killable child."""
    try:
        candidate_stage=(substituted_stage(stage=stage,class_key=class_key,level=level,
                             slot=slot,item_id=item_id) if slot is not None else stage)
        candidate=prepare_candidate(class_key=class_key,level=level,stage=candidate_stage,
                                    source_ir=source_ir,strict_l2_item_effects=True)
        result=evaluate_persistent_candidate(candidate,level=level,mobs=100,
                     max_total_events=200000,max_wall_s=15.,max_cpu_s=15.)
        q.put({k:result.get(k) for k in ('status','mean_s_per_mob','events','combat_s',
                   'recovery_s','maintenance_s','elapsed_wall_s','elapsed_cpu_s','mob_completed')})
    except BaseException as e:
        q.put({'status':'ERROR','reason':type(e).__name__+':'+str(e)[:350]})


def isolated_stage_100mob(*,stage,source_ir,class_key,level,slot=None,item_id=None,
                          timeout_s=8.,worker=None):
    """Hard-bound whole gear->IR->policy->100mob chain, not just combat."""
    if not 0<timeout_s<=300 or 'fork' not in mp.get_all_start_methods():
        raise ValueError('P3_NO_SAFE_OS_ISOLATION_OR_INVALID_TIMEOUT')
    ctx=mp.get_context('fork');q=ctx.Queue(maxsize=1)
    p=ctx.Process(target=worker or _stage_worker,
                  args=(q,stage,source_ir,class_key,level,slot,item_id))
    t=monotonic();p.start();p.join(timeout_s)
    if p.is_alive():
        p.terminate();p.join(1.)
        if p.is_alive():p.kill();p.join(1.)
        result={'status':'OS_TIMEOUT'}
    else:
        try:result=q.get(timeout=.3)
        except Exception:result={'status':'WORKER_EXIT_WITHOUT_RESULT','exitcode':p.exitcode}
    q.close();q.join_thread()
    if result.get('status')=='COMPLETE':
        score=result.get('mean_s_per_mob')
        if score is None or not isfinite(float(score)) or score<=0:
            result={'status':'INVALID_100MOB_SCORE'}
    return {**result,'outer_wall_s':monotonic()-t}


def direct_swap_trial(*,stage,source_ir,class_key,level,slot,item_id,timeout_s=8.):
    legal={int(x.item_id):x for x in available_items(class_key,level,required_level_policy='observed')}
    item=legal.get(int(item_id))
    if item is None:return {'status':'NOT_SOURCE_LEGAL','slot':slot,'item_id':int(item_id)}
    l0=source_item_l0(item)
    if l0['unresolved_effects']:
        return {'status':'L0_ONLY_UNRESOLVED_EFFECT','slot':slot,'item_id':int(item_id),
                'unresolved_effects':l0['unresolved_effects']}
    result=isolated_stage_100mob(stage=stage,source_ir=source_ir,class_key=class_key,
               level=level,slot=slot,item_id=item_id,timeout_s=timeout_s)
    return {'slot':slot,'item_id':int(item_id),'source_url':item.source_url,**result}


def subprocess_stage_100mob(*,stage,source_db_path,slot=None,item_id=None,
                            swaps=None,timeout_s=9.,work_dir=None,recovery_policy=None,
                            allow_partial_gear_stats=False):
    """OS process starts from source SQLite; hard-bound entire preparation.

    Unlike repeated `fork` from a threaded optimizer, this never inherits
    deadlocked locks from the parent. A timeout cannot return a valid score.
    """
    import subprocess,sys,tempfile,os,signal
    if not 0<timeout_s<=300:raise ValueError('P3_INVALID_SUBPROCESS_TIMEOUT')
    db=Path(source_db_path)
    if not db.is_file():raise ValueError('P3_MISSING_STAGED_SOURCE_DB')
    t=monotonic()
    with tempfile.TemporaryDirectory(prefix='p3_source_swap_',dir=work_dir) as tmp:
        stage_path=Path(tmp)/'stage.json';output=Path(tmp)/'score.json'
        stage_path.write_text(json.dumps(stage,sort_keys=True,default=str))
        cmd=[sys.executable,'-m','tools.wf353_p3_eval_worker','--stage',str(stage_path),
             '--source-db',str(db),'--output',str(output)]
        if slot is not None:cmd.extend(['--slot',str(slot),'--item-id',str(int(item_id))])
        if swaps is not None:
            swaps_path=Path(tmp)/'swaps.json';swaps_path.write_text(json.dumps(swaps,sort_keys=True))
            cmd.extend(['--swaps-json',str(swaps_path)])
        if allow_partial_gear_stats:
            cmd.append('--allow-partial-gear-stats')
        if recovery_policy is not None:
            from dataclasses import asdict,is_dataclass
            payload=asdict(recovery_policy) if is_dataclass(recovery_policy) else dict(recovery_policy)
            policy_path=Path(tmp)/'recovery_policy.json'
            policy_path.write_text(json.dumps(payload,sort_keys=True))
            cmd.extend(['--recovery-policy-json',str(policy_path)])
        proc=subprocess.Popen(cmd,cwd=Path(__file__).resolve().parents[4],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        try:
            stdout,stderr=proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            # Kill *process group*, not just the direct child: descendant
            # recovery workers may otherwise hold inherited pipes open.
            os.killpg(proc.pid,signal.SIGKILL)
            try:proc.communicate(timeout=2.)
            except subprocess.TimeoutExpired:pass
            return {'status':'OS_TIMEOUT','outer_wall_s':monotonic()-t}
        if not output.exists():
            return {'status':'WORKER_EXIT_WITHOUT_RESULT','returncode':proc.returncode,
                    'stderr':stderr[-400:],'outer_wall_s':monotonic()-t}
        result=json.loads(output.read_text())
        if proc.returncode and result.get('status')=='COMPLETE':
            result={'status':'INCONSISTENT_WORKER_EXIT','returncode':proc.returncode}
        return {**result,'outer_wall_s':monotonic()-t}

def source_context_fingerprint(*,stage,class_key,level,source_db_sha256):
    """Cache key must invalidate on *build*, staged source, or item semantics."""
    gear=stage['gear_policy_result']['winner']['gear']
    policy=stage['gear_policy_result']['winner']['winner']
    payload={'class_key':class_key,'level':level,'source_db_sha256':source_db_sha256,
             'catalogue_sha256':sha256(Path(catalogue_path()).read_bytes()).hexdigest(),
             'semantics_sha256':sha256(ledger_path().read_bytes()).hexdigest(),
             'allocation':stage['allocation'],
             'items':sorted((k,int(v['item_id'])) for k,v in gear['slots'].items()),
             'policy':policy,'mobs':100}
    return sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()
