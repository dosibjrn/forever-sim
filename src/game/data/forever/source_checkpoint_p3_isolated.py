"""Isolated, resumable 100-kill gear-stat measurements.

Linux fork allows the already prepared GameIR to be shared copy-on-write.
Each probe is a separate OS process; a non-cooperative recovery search is
terminated by its parent regardless of in-runtime cancellation handling.
The cache key includes the actual build, base score and entire item catalogue.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import time
from hashlib import sha256
from pathlib import Path
from math import isfinite

# The two most threshold-sensitive axes require an actual TWO-STEP curve.
# A single positive step is never evidence of an additive gear weight.
COARSE_MULTISCALE_AXES = frozenset({'agility', 'weapon_dps'})

from .source_checkpoint_p3_weights import (
    PROBE_STEPS, SOURCE_RATINGS, _features, _identity, _derivative,
)
from .source_checkpoint_p3_chance import context_weapon_speed_semantics
from src.game.gear import executable_gear_stats
from src.rulesets.forever.items.runtime_selection import available_items, catalogue_path


def _probe_worker(q, candidate, stat, delta, level, mobs, weapon_dps):
    try:
        result, error = _derivative(candidate, stat, delta, level, mobs,
                                    weapon_dps, max_wall_s=None)
        if error:
            q.put({'status': 'UNSUPPORTED', 'reason': error})
        elif result is None or result.get('status') != 'COMPLETE':
            q.put({'status': 'INCOMPLETE', 'reason': str(result)[:200]})
        else:
            q.put({'status': 'COMPLETE', 's_per_mob': result['mean_s_per_mob'],
                   'events': result.get('events')})
    except BaseException as e:
        q.put({'status': 'ERROR', 'reason': type(e).__name__+':'+str(e)[:250]})


def isolated_process_probe(candidate, stat, delta, *, level=30, mobs=100,
                           weapon_dps=0., timeout_s=8., worker=None):
    if not (0 < timeout_s <= 600) or not isfinite(float(delta)):
        raise ValueError('P3_BAD_ISOLATED_PROBE_BUDGET')
    # No silent fallback to an unbounded thread or in-process executor.
    if 'fork' not in mp.get_all_start_methods():
        return {'status':'UNSUPPORTED_PLATFORM_NO_SAFE_FORK'}
    ctx=mp.get_context('fork'); q=ctx.Queue(maxsize=1)
    proc=ctx.Process(target=worker or _probe_worker,
                     args=(q,candidate,stat,float(delta),level,mobs,float(weapon_dps)))
    started=time.monotonic();proc.start();proc.join(timeout_s)
    if proc.is_alive():
        proc.terminate();proc.join(1.)
        if proc.is_alive():
            proc.kill();proc.join(1.)
        out={'status':'OS_TIMEOUT','timeout_s':timeout_s}
    else:
        try:out=q.get(timeout=.2)
        except Exception:out={'status':'WORKER_EXIT_WITHOUT_RESULT','exitcode':proc.exitcode}
    q.close();q.join_thread()
    return {**out,'elapsed_wall_s':time.monotonic()-started}


def measured_axis_suite(*, candidate, class_key, level, base_score_s_per_mob,
                        out_dir, per_probe_timeout_s=8., axes=None,
                        prior_weights=None, worker=None):
    """Measured, persisted, no guessed zeros. Each delta is one 100-mob run.

    `prior_weights` from a previous release is accepted only for the *same*
    identity and base score; otherwise the suite fails closed. Every record
    is persisted atomically before the next probe begins.
    """
    if level < 1 or not isfinite(base_score_s_per_mob):
        raise ValueError('P3_BAD_BASE_SCORE')
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True)
    build=_identity(candidate.source_stage)
    catalogue=sha256(Path(catalogue_path()).read_bytes()).hexdigest()
    base=float(base_score_s_per_mob)
    fingerprint=sha256(json.dumps({'build':build,'catalogue':catalogue,
        'class_key':class_key,'level':level,'mobs':100,'base':base,
        'source_context':candidate.source_stage.get('source_context_sha256'),
        'probe_step_policy': {axis: PROBE_STEPS[axis] for axis in COARSE_MULTISCALE_AXES},
        'probe_step_policy_version': 2},sort_keys=True).encode()).hexdigest()
    if prior_weights is not None:
        if (prior_weights.get('build_identity_sha256')!=build or
            prior_weights.get('class_key')!=class_key or
            prior_weights.get('level')!=level or
            abs(float(prior_weights['base_s_per_mob'])-base)>1e-8):
            raise ValueError('P3_STALE_PRIOR_WEIGHT_CONTEXT')
    native=set(executable_gear_stats(candidate.ir))
    items=available_items(class_key,level,required_level_policy='observed')
    item_axes={k for row in items for k,v in _features(row).items() if float(v)}
    supported=item_axes & (native|set(SOURCE_RATINGS))
    # Some stat pathways are not an actual item stat axis, e.g. weapon speed.
    requested=axes if axes is not None else ('weapon_dps','spell_power','armor','mp5',
             'health_regeneration_per_5s','hit','crit','dodge','defense','healing','wand_dps')
    order=tuple(requested) if axes is not None else tuple(stat for stat in requested if stat in item_axes)
    if any(axis not in item_axes for axis in order):
        raise ValueError('P3_REQUESTED_AXIS_NOT_IN_CATALOGUE')
    gear=candidate.source_stage['gear_policy_result']['winner']['gear']
    weapon=float(gear.get('slots',{}).get('weapon',{}).get('weapon_dps') or 0.)
    weights=dict(prior_weights.get('weights',{}) if prior_weights else {})
    # Old positive signals measured at +5 Agility / +2 weapon DPS must never
    # survive as ranking coefficients just because the build identity matches.
    for critical in COARSE_MULTISCALE_AXES:
        old=weights.get(critical, {})
        if old.get('probe_delta') is not None and abs(float(old['probe_delta'])) < PROBE_STEPS[critical]:
            weights[critical]={'status':'STALE_SMALL_STEP_REQUIRES_REMEASUREMENT',
                               'weight_s_saved_per_mob_per_unit':None,
                               'minimum_delta':PROBE_STEPS[critical]}
    events=[]
    for stat in order:
        cache=out_dir/(stat+'.json')
        if cache.exists():
            saved=json.loads(cache.read_text())
            if saved.get('fingerprint')!=fingerprint:raise ValueError('P3_STALE_PROBE_CACHE:'+stat)
            row=saved['row'];weights[stat]=row
            events.append({'axis':stat,'action':'CACHED','status':row['status']});continue
        if stat not in supported:
            row={'status':'UNSUPPORTED_RUNTIME_AXIS','weight_s_saved_per_mob_per_unit':None,
                 'reason':'item-axis-not-executable'}
        else:
            step=(4. if stat=='defense' else PROBE_STEPS.get(stat,5.))
            if stat in ('hit','crit','dodge'):
                step={'hit':10.,'crit':14.,'dodge':12.}[stat]
            attempts=[]
            for multiplier in (1.,2.):
                delta=step*multiplier
                result=isolated_process_probe(candidate,stat,delta,level=level,mobs=100,
                    weapon_dps=weapon,timeout_s=per_probe_timeout_s,worker=worker)
                trial={'delta':delta,**result}
                if result['status']=='COMPLETE':
                    improvement=base-float(result['s_per_mob'])
                    trial['improvement_s_per_mob']=improvement
                attempts.append(trial)
                if stat not in COARSE_MULTISCALE_AXES and (
                    result['status']!='COMPLETE' or abs(trial.get('improvement_s_per_mob',0.))>1e-8
                ):
                    break
            success=[a for a in attempts if a['status']=='COMPLETE']
            found=next((a for a in success if abs(a['improvement_s_per_mob'])>1e-8),None)
            if stat in COARSE_MULTISCALE_AXES:
                if len(success)!=2:
                    row={'status':'INCOMPLETE_COARSE_MULTISCALE','weight_s_saved_per_mob_per_unit':None,
                         'probes':attempts,'minimum_delta':step}
                else:
                    a,b=success
                    # Do not convert nonmonotone or strongly nonlinear measured
                    # threshold effects to one linear additive ranking weight.
                    a_imp=a['improvement_s_per_mob']; b_imp=b['improvement_s_per_mob']
                    a_slope=a_imp/a['delta']; b_slope=b_imp/b['delta']
                    monotone=(a_imp>=-0.005 and b_imp+0.005>=a_imp)
                    significant=(a_imp>0.005 and b_imp>0.005)
                    ratio=max(a_slope,b_slope)/min(a_slope,b_slope) if significant else float('inf')
                    if significant and monotone and ratio<=4.:
                        row={'status':'MEASURED_COARSE_MULTISCALE_PRIOR',
                             'weight_s_saved_per_mob_per_unit':b_slope,
                             'probe_delta':b['delta'], 'probes':attempts,
                             'method':'exact_100mob_two_positive_coarse_steps',
                             'uncertainty':'item-dependent thresholds; direct swap replay still required'}
                    else:
                        row={'status':'NONLINEAR_OR_UNRESOLVED_NO_SCALAR',
                             'weight_s_saved_per_mob_per_unit':None,
                             'probes':attempts, 'minimum_delta':step,
                             'reason':'ADVERSE_NONMONOTONE_OR_CURVATURE'}
            elif found is not None:
                row={'status':'MEASURED_100MOB_OS_ISOLATED','weight_s_saved_per_mob_per_unit':
                    found['improvement_s_per_mob']/found['delta'],'probe_delta':found['delta'],
                    'method':'exact_100mob_fixed_build_finite_difference', 'probes':attempts,
                    'uncertainty':'discrete_nonmonotone_local_prior_only'}
            elif len(success)==2:
                row={'status':'TESTED_ZERO_RANGE_ONLY','weight_s_saved_per_mob_per_unit':0.,
                     'probe_delta':success[-1]['delta'],'probes':attempts,
                     'uncertainty':'only two tested deltas; not general proof of zero'}
            else:
                row={'status':'INCONCLUSIVE_OR_TIMEOUT','weight_s_saved_per_mob_per_unit':None,
                     'probes':attempts}
            if stat=='defense':row['unmodeled_channels']=['block','parry','incoming_crit']
        obj={'fingerprint':fingerprint,'axis':stat,'row':row}
        tmp=cache.with_suffix('.tmp');tmp.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n');os.replace(tmp,cache)
        weights[stat]=row
        events.append({'axis':stat,'action':'NEW','status':row['status']})
    for stat in item_axes:
        if stat not in weights:
            weights[stat]={'status':'UNMEASURED','weight_s_saved_per_mob_per_unit':None}
    speed=context_weapon_speed_semantics(candidate.ir)
    weights['weapon_speed']={'status':'CONTEXTUAL_ZERO_FROM_SOURCE_FORM_FIXED'
        if speed=='FORM_FIXED_WEAPON_SPEED_NO_ITEM_SENSITIVITY' else 'UNMODELED_WEAPON_SPEED_SENSITIVITY',
        'weight_s_saved_per_mob_per_unit':0. if speed=='FORM_FIXED_WEAPON_SPEED_NO_ITEM_SENSITIVITY' else None,
        'source_semantics':speed}
    return {'base_s_per_mob':base,'mobs':100,'class_key':class_key,'level':level,
        'build_identity_sha256':build,'catalogue_sha256':catalogue,'fingerprint':fingerprint,
        'weights':weights,'base_actor_stats':dict(prior_weights.get('base_actor_stats',{}) if prior_weights else {
            k:float(v) for k,v in candidate.ir.actor.base_stats.items() if isinstance(v,(int,float))}),
        'chance_sensitivities':{},'worker_events':events,
        'scope':'EXACT_BUILD_100MOB_PER_AXIS_OS_ISOLATED',
        'interpretation':'marginal_prior_not_global_optimum'}
