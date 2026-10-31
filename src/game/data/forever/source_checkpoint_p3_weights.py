"""Build-conditional 100-mob finite-difference gear weights and auditable Top N.

No class/item-specific values. Missing combat semantics are *unknown* rather
than zero. Weights are per one unit of source stat, in seconds saved per mob.
A derivative never substitutes for the complete joint optimizer.
"""
from __future__ import annotations

from dataclasses import replace
from .source_checkpoint_p3_chance import (chance_perturbed_ir, context_weapon_speed_semantics)
from hashlib import sha256
from json import dumps
from math import isfinite
from pathlib import Path

from src.game.gear import apply_stat_delta, executable_gear_stats, _replace_equipped_weapon_dps
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
from src.game.data.forever.source_checkpoint_p3_ratings import (apply_source_item_stat_delta, forever_display_chance_fraction_per_raw_point, source_item_stat_to_combat)
from src.rulesets.forever.items.runtime_selection import available_items, item_vector, catalogue_path
from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate

# A source delta in the *input unit*, not a game-specific damage coefficient.
# Stat-specific probe scales are input-unit perturbations, not combat effect coefficients.
# Agility and weapon DPS must cross discrete 100-mob action/kill thresholds.
# These are *minimum item-relevant steps*, not locally reliable derivatives.
PROBE_STEPS = {
    'strength': 5., 'agility': 20., 'stamina': 5., 'intellect': 5.,
    'spirit': 5., 'attack_power': 10., 'spell_power': 10.,
    'healing': 10., 'mp5': 5., 'armor': 100.,
    'weapon_dps': 10., 'wand_dps': 2.,
    'health_regeneration_per_5s': 5.,
}
SOURCE_RATINGS = ('hit', 'crit', 'defense', 'dodge')


def _features(item):
    out = dict(item_vector(item))
    # Typed percentage passives are a separate item axis.  The source ledger
    # supplies the percentage; build-local spirit (etc.) and measured 100-mob
    # primary-stat weight supply its contextual L0 value.
    from src.rulesets.forever.items.source_equipment_semantics import semantic_for_item
    sem=semantic_for_item(item)
    if sem:
        for kind,stat,multiplier in sem.typed_effects:
            if kind=='multiply_actor_stat':
                out[stat+'_percent']=100.*(multiplier-1.)
            elif kind=='add_actor_stat':
                out[stat]=out.get(stat,0.)+multiplier
    from src.rulesets.forever.items.source_numeric_extras import modeled_source_numeric_extras
    out.update(modeled_source_numeric_extras(item))
    for key in SOURCE_RATINGS:
        out[key] = float(getattr(item, key) or 0.0)
    out['weapon_speed'] = float(getattr(item,'weapon_speed',0.) or 0.) if float(getattr(item,'weapon_dps',0.) or 0.) else 0.
    # Bonus armor is already included in `armor`; spldmg is folded into
    # damage spell power. Do not double-count either.
    return out


def _identity(stage):
    winner=stage['gear_policy_result']['winner']
    return sha256(dumps({
        'allocation':stage['allocation'],
        'items':{slot:int(i['item_id']) for slot,i in sorted(winner['gear']['slots'].items())},
        'policy':winner['winner'],
    }, sort_keys=True,default=str).encode()).hexdigest()


def _score(candidate, level, mobs, max_wall_s=None):
    out=evaluate_persistent_candidate(candidate, level=level,mobs=mobs,max_total_events=200000,
                                      max_wall_s=max_wall_s)
    if out.get('status') != 'COMPLETE' or not isfinite(float(out['mean_s_per_mob'])):
        raise ValueError('P3_STAT_PROBE_INCOMPLETE:'+str(out.get('status')))
    return out


def _derivative(candidate, stat, step, level, mobs, equipped_weapon, max_wall_s=None):
    if stat == 'weapon_dps':
        if equipped_weapon <= 0:
            return None, 'NO_EQUIPPED_WEAPON_DPS_BASE'
        changed=_replace_equipped_weapon_dps(candidate.ir,equipped_weapon+step)
    elif stat in SOURCE_RATINGS:
        changed=apply_source_item_stat_delta(candidate.ir,stat,step,level=level)
    else:
        changed=apply_stat_delta(candidate.ir,stat,step)
    test=replace(candidate,ir=changed)
    return _score(test,level,mobs,max_wall_s=max_wall_s), None


def _discrete_stat_probe(candidate, stat, step, level, mobs, equipped_weapon, base_t):
    """Cheap broad probe followed by genuine 100-mob confirmation.

    CombatRuntime has discrete swing/kill thresholds. A tiny delta giving
    exactly 0 is NOT proof of zero marginal item value. We screen on 20 mobs,
    confirm at least one candidate with the 100-mob objective, and never
    pretend an unconfirmed short-horizon slope is a 100-mob stat weight.
    """
    deltas=(float(step),float(step)*2.,float(step)*4.,float(step)*8.)
    short_mobs=min(20,mobs)
    short_base=_score(candidate,level,short_mobs)['mean_s_per_mob'] if short_mobs!=mobs else base_t
    short=[]
    for delta in deltas:
        try:
            changed,error=_derivative(candidate,stat,delta,level,short_mobs,equipped_weapon)
            if error: raise ValueError(error)
            diff=float(short_base)-float(changed['mean_s_per_mob'])
            short.append({'delta':delta,'mean_s_per_mob':changed['mean_s_per_mob'],
                'improvement_s_per_mob':diff})
        except (RuntimeError,ValueError,KeyError) as exc:
            short.append({'delta':delta,'error':str(exc)})
    valid=[r for r in short if 'improvement_s_per_mob' in r]
    if not valid:return {'status':'PROBE_FAILED','weight_s_saved_per_mob_per_unit':None,
        'reason':'NO_VALID_SHORT_PROBES','short_probes':short}
    # The measured total clock can jump at kill/recovery thresholds.
    # Prefer the strongest observed short-horizon signal for rating axes,
    # while preserving the entire sampled curve and explicit uncertainty.
    ordered=(sorted(valid,key=lambda r:(-r['improvement_s_per_mob'],r['delta']))
             if stat in SOURCE_RATINGS else
             sorted(valid,key=lambda r:(r['improvement_s_per_mob']<=1e-8,r['delta'])))
    full=[]
    for row in ordered[:2]:
        delta=row['delta']
        try:
            outcome,error=_derivative(candidate,stat,delta,level,mobs,equipped_weapon)
            if error: raise ValueError(error)
            diff=base_t-float(outcome['mean_s_per_mob'])
            full.append({'delta':delta,'mean_s_per_mob':outcome['mean_s_per_mob'],
                'improvement_s_per_mob':diff,'events':outcome.get('events')})
            if diff>1e-8:break
        except (RuntimeError,ValueError,KeyError) as exc:
            full.append({'delta':delta,'error':str(exc)})
    positives=[r for r in full if r.get('improvement_s_per_mob',-1.)>1e-8]
    if positives:
        best=positives[0]
        return {'status':'MEASURED' if best['delta']==step else 'DISCRETE_SMOOTHED',
            'weight_s_saved_per_mob_per_unit':best['improvement_s_per_mob']/best['delta'],
            'probe_delta':best['delta'],'perturbed_s_per_mob':best['mean_s_per_mob'],
            'method':'20mob_screen_100mob_confirmed_multiscale_difference',
            'short_probes':short,'full_probes':full,
            'interpretation':'coarse_search_prior_not_continuous_gradient'}
    if all(abs(r['improvement_s_per_mob'])<1e-8 for r in full if 'improvement_s_per_mob' in r) and len(full)==len([r for r in full if 'improvement_s_per_mob' in r]):
        return {'status':'MEASURED_ZERO_RANGE','weight_s_saved_per_mob_per_unit':0.,
            'probe_delta':max(r['delta'] for r in full),'short_probes':short,'full_probes':full,
            'method':'100mob_no_detected_effect_in_tested_range',
            'interpretation':'zero_in_this_fixed_policy_and_tested_range'}
    return {'status':'INCONCLUSIVE_DISCRETE_PROBES','weight_s_saved_per_mob_per_unit':None,
        'reason':'NO_POSITIVE_CONFIRMED_100MOB_PROBE','short_probes':short,'full_probes':full}



def _chance_sensitivity(candidate, kind, level, mobs, base_t):
    """Multi-scale existing-CombatRuntime *chance* probe; no rating assumptions."""
    screens=[]
    for delta in (.01,.02,.04,.08):
        try:
            ir = chance_perturbed_ir(candidate.ir,kind,delta)
            sample = _score(replace(candidate,ir=ir),level,min(20,mobs))
            screens.append({'delta_chance_fraction':delta,'s_per_mob':sample['mean_s_per_mob']})
        except (RuntimeError,ValueError,KeyError) as exc:
            screens.append({'delta_chance_fraction':delta,'error':str(exc)})
    valid=[x for x in screens if 's_per_mob' in x]
    if not valid:
        return {'status':'CHANCE_PROBE_UNSUPPORTED', 'weight_s_saved_per_mob_per_chance_fraction':None,
                'screens':screens}
    base_short=_score(candidate,level,min(20,mobs))['mean_s_per_mob']
    valid.sort(key=lambda x:(float(x['s_per_mob'])>=float(base_short)-1e-9,x['delta_chance_fraction']))
    full=[]
    for x in valid[:3]:
        try:
            ir=chance_perturbed_ir(candidate.ir,kind,x['delta_chance_fraction'])
            sample=_score(replace(candidate,ir=ir),level,mobs)
            full.append({'delta_chance_fraction':x['delta_chance_fraction'],
                's_per_mob':sample['mean_s_per_mob'],'events':sample.get('events')})
            if base_t>float(sample['mean_s_per_mob'])+1e-8: break
        except (RuntimeError,ValueError,KeyError) as exc:
            full.append({'delta_chance_fraction':x['delta_chance_fraction'],'error':str(exc)})
    positives=[x for x in full if 's_per_mob' in x and base_t>float(x['s_per_mob'])+1e-8]
    if positives:
        x=positives[0]
        base_chance=float(candidate.ir.provenance['target_combat_profile']['melee_hit']) if kind=='hit' else 0.
        effective_delta=(min(x['delta_chance_fraction'],max(0.,1.-base_chance))
                         if kind=='hit' else x['delta_chance_fraction'])
        if effective_delta <= 0.:raise ValueError('chance perturbation was already capped')
        return {'status':'MEASURED_EXECUTOR_CHANCE_SENSITIVITY',
            'weight_s_saved_per_mob_per_chance_fraction':(base_t-float(x['s_per_mob']))/effective_delta,
            'delta_chance_fraction':x['delta_chance_fraction'],
            'effective_chance_delta_after_cap':effective_delta,'short_probes':screens,
            'full_probes':full,'mobs':mobs,'scope':'fixed_build_melee_and_incoming_physical_only'}
    return {'status':'CHANCE_SENSITIVITY_INCONCLUSIVE',
            'weight_s_saved_per_mob_per_chance_fraction':None,
            'short_probes':screens,'full_probes':full}

def measured_stat_weights(*,candidate, class_key, level, mobs=100, prior_weights=None,
                          measure_provisional_ratings=False):
    """Build-conditional *coarse* marginal stat value, accounting for swing steps.

    Stat weights are per-item ranking priors, not claims that the objective is
    globally monotone. Ratings without sourced conversion remain UNKNOWN.
    """
    if mobs < 1: raise ValueError('P3_INVALID_PROBE_MOBS')
    base=_score(candidate,level,mobs)
    if prior_weights is not None:
        if (prior_weights.get('build_identity_sha256') != _identity(candidate.source_stage)
            or prior_weights.get('class_key') != class_key
            or prior_weights.get('level') != level or prior_weights.get('mobs') != mobs
            or abs(float(prior_weights['base_s_per_mob'])-float(base['mean_s_per_mob']))>1e-8):
            raise ValueError('P3_PRIOR_WEIGHT_EVIDENCE_MISMATCH')
    gear=candidate.source_stage['gear_policy_result']['winner']['gear']
    wdps=float(gear.get('slots',{}).get('weapon',{}).get('weapon_dps') or 0.)
    native=set(executable_gear_stats(candidate.ir))
    stat_keys=set(PROBE_STEPS)|set(SOURCE_RATINGS)
    rows=available_items(class_key,level,required_level_policy='observed')
    stat_keys |= {key for row in rows for key,value in _features(row).items() if float(value)}
    weights={};failures={}
    chance_sensitivities={kind:_chance_sensitivity(candidate,kind,level,mobs,
        float(base['mean_s_per_mob'])) for kind in ('crit','hit','dodge')}
    speed_status=context_weapon_speed_semantics(candidate.ir)
    for stat in sorted(stat_keys):
        if stat in SOURCE_RATINGS:
            prob=chance_sensitivities.get(stat)
            if stat != 'defense':
                factor=forever_display_chance_fraction_per_raw_point(stat,level)
                w=(prob['weight_s_saved_per_mob_per_chance_fraction']*factor
                   if prob and prob.get('weight_s_saved_per_mob_per_chance_fraction') is not None else None)
                weights[stat]={'status':'SOURCE_DISPLAY_PERCENT_MEASURED_100MOB' if w is not None else 'UNRESOLVED_EXECUTOR_SENSITIVITY',
                    'weight_s_saved_per_mob_per_unit':w,
                    'weight_unit':'seconds_saved_per_mob_per_raw_catalogue_point',
                    'display_percent_per_raw_point':factor*100.,
                    'source_urls':source_item_stat_to_combat(stat,1.,level=level)['source_urls'],
                    'chance_sensitivity_status':prob['status'] if prob else 'NOT_MEASURED',
                    'unmodeled_channels':source_item_stat_to_combat(stat,1.,level=level)['unmodeled_channels'],
                    'no_level_scaled_tbc_conversion':True}
            else:
                # Defense is SKILL, not a rating: probe the *real* 2-channel
                # incoming miss+dodge path, but preserve unknown parry/block/crit.
                evidence=_discrete_stat_probe(candidate,stat,4.,level,mobs,wdps,
                    float(base['mean_s_per_mob']))
                # Both executed Defense channels (incoming miss and dodge)
                # reduce the same physical-contact probability. If a small
                # integer skill delta does not clear the discrete 100-mob
                # threshold, use the measured +Dodge probability sensitivity
                # as a conservative first-order proxy for both channels.
                direct=evidence.get('weight_s_saved_per_mob_per_unit')
                dodge_sensitivity=chance_sensitivities.get('dodge',{}).get(
                    'weight_s_saved_per_mob_per_chance_fraction')
                fallback=(dodge_sensitivity*2.*.0004
                          if dodge_sensitivity is not None and dodge_sensitivity>0. else None)
                use_fallback=direct is None and fallback is not None
                weights[stat]={**evidence,
                    'status':('PARTIAL_DEFENSE_SKILL_FIRST_ORDER_AVOIDANCE_PROXY' if use_fallback
                              else 'PARTIAL_DEFENSE_SKILL_100MOB_MEASURED' if direct is not None
                              else 'UNRESOLVED_DEFENSE_SKILL_EFFECT'),
                    'weight_s_saved_per_mob_per_unit':fallback if use_fallback else direct,
                    'method':('100mob_measured_dodge_sensitivity_times_0.0008_for_miss_and_dodge'
                              if use_fallback else evidence.get('method','unresolved')),
                    'direct_probe':evidence,'first_order_fallback_used':use_fallback,
                    'source_urls':source_item_stat_to_combat(stat,1.,level=level)['source_urls'],
                    'unmodeled_channels':source_item_stat_to_combat(stat,1.,level=level)['unmodeled_channels'],
                    'no_level_scaled_tbc_conversion':True}
            continue
        if stat not in native:
            weights[stat]={'status':'UNSUPPORTED_RUNTIME_AXIS','weight_s_saved_per_mob_per_unit':None,
                           'reason':'NO_EXECUTABLE_SOURCE_STAT_SEMANTIC'}
            continue
        if prior_weights is not None and stat in prior_weights['weights']:
            old=prior_weights['weights'][stat]
            if old['status'] not in ('UNMODELED_RATING_CONVERSION',):
                weights[stat]=old
                continue
        step=PROBE_STEPS.get(stat,5.)
        # Only native executable stats are perturbed: never substitute a
        # guessed conversion for hit/crit/defense or unsupported item procs.
        evidence=_discrete_stat_probe(candidate,stat,step,level,mobs,wdps,float(base['mean_s_per_mob']))
        weights[stat]=evidence
        if evidence['status'] in ('PROBE_FAILED','NONMONOTONE_NO_POSITIVE_EVIDENCE'):
            failures[stat]=evidence.get('reason')
    weights['weapon_speed']={'status':'CONTEXTUAL_ZERO_FROM_SOURCE_FORM_FIXED'
        if speed_status == 'FORM_FIXED_WEAPON_SPEED_NO_ITEM_SENSITIVITY'
        else 'UNMODELED_WEAPON_SPEED_SENSITIVITY',
        'weight_s_saved_per_mob_per_unit':0. if speed_status == 'FORM_FIXED_WEAPON_SPEED_NO_ITEM_SENSITIVITY' else None,
        'source_semantics':speed_status}
    return {'base_s_per_mob':base['mean_s_per_mob'],'base_events':base.get('events'),
        'base_actor_stats':{k:float(v) for k,v in candidate.ir.actor.base_stats.items() if isinstance(v,(int,float))},
        'chance_sensitivities':chance_sensitivities, 'weapon_speed_source_status':speed_status,
        'mobs':mobs,'weights':weights,'probe_failures':failures,
        'build_identity_sha256':_identity(candidate.source_stage),
        'class_key':class_key,'level':level,
        'scope':'FIXED_GEAR_TALENTS_POLICY; COARSE_DISCRETE_MARGINAL_PRIOR'}

def ranked_top_items(*,class_key,level,stage,weight_evidence,top_n=5,source_certificate=None):
    """All legal rows valued with the SAME vector; rank at most N per slot.

    Any unknown non-zero component makes the total a *known contribution*
    rather than a fully identified ranking.  This must fail P3 readiness.
    """
    if top_n<1: raise ValueError('P3_BAD_TOP_N')
    if (weight_evidence.get('build_identity_sha256')!=_identity(stage)
        or weight_evidence.get('class_key')!=class_key or weight_evidence.get('level')!=level):
        raise ValueError('P3_WEIGHT_BUILD_MISMATCH')
    source=source_certificate or checkpoint_item_l0(class_key=class_key,level=level)
    expected_sha=sha256(Path(catalogue_path()).read_bytes()).hexdigest()
    if source.get('catalogue_sha256')!=expected_sha:raise ValueError('P3_WEIGHT_CATALOGUE_MISMATCH')
    weights=weight_evidence['weights']
    rows=available_items(class_key,level,required_level_policy='observed')
    by_id={int(x.item_id):x for x in rows}
    all_rows={}
    uncertain_ids=[]
    for record in source['source_items']:
        item=by_id[int(record['item_id'])]
        parts=[];unknown=[];total=0.;provisional_delta=0.;provisional_parts=[]
        for stat,val in sorted(_features(item).items()):
            if not val:continue
            # E.g. a sourced +5% Spirit relic is worth 5% of the equipped
            # build's Spirit, then evaluated using the measured Spirit weight.
            # This is explicitly a local linear proxy, not an exact L2 delta.
            effective_stat=stat
            effective_val=val
            if stat.endswith('_percent'):
                effective_stat=stat[:-8]
                baseline=weight_evidence.get('base_actor_stats',{}).get(effective_stat)
                if baseline is None:
                    unknown.append({'stat':stat,'amount':val,'reason':'MISSING_BUILD_BASE_STAT_FOR_PERCENT_EFFECT'})
                    continue
                effective_val=val*float(baseline)/100.
            w=weights.get(effective_stat)
            if not w or w['weight_s_saved_per_mob_per_unit'] is None:
                predicted = (w.get('measured_100mob_provisional_weight_per_rating')
                             if w and w.get('measured_100mob_provisional_weight_per_rating') is not None
                             else w.get('provisional_historical_weight_per_rating') if w else None)
                if predicted is not None:
                    contrib = float(val)*float(predicted)
                    provisional_delta+=contrib
                    provisional_parts.append({'stat':stat,'amount':val,'provisional_contribution':contrib,
                        'reason':'MEASURED_RUNTIME_SENSITIVITY_UNVERIFIED_CONVERSION'
                          if w.get('measured_100mob_provisional_weight_per_rating') is not None
                          else 'HISTORICAL_RATING_CONVERSION_UNVERIFIED_IN_FOREVER'})
                unknown.append({'stat':stat,'amount':val,'reason':w['status'] if w else 'NO_WEIGHT'})
            else:
                delta=effective_val*float(w['weight_s_saved_per_mob_per_unit'])
                total+=delta
                parts.append({'stat':stat,'amount':val,'effective_stat_delta':effective_val,
                              'weight':w['weight_s_saved_per_mob_per_unit'],
                              'contribution_s_saved_per_mob':delta})
        unknown.extend({'stat':'item_effect','reason':effect} for effect in record['unresolved_effects']
                       if not effect.startswith('unconverted_rating:'))
        report={'item_id':int(item.item_id),'name':item.name,'item_url':item.source_url,
            'displayed_item_chances_pct':{kind:float(getattr(item,kind) or 0.)/base
                  for kind,base in (('crit',14.),('hit',10.),('dodge',12.))},
            'defense_skill':float(item.defense or 0.),
            'known_score_s_saved_per_mob':total,
            'provisional_rating_adjusted_score':total+provisional_delta,
            'provisional_rating_contributions':provisional_parts,'contributions':sorted(parts,key=lambda x:-abs(x['contribution_s_saved_per_mob'])),
            'unknown_effects':unknown,'fully_rankable':not unknown,
            'slot_requirements':{'weapon_hands':item.weapon_hands,'catalogue_slot':item.slot}}
        if unknown:uncertain_ids.append(int(item.item_id))
        all_rows[int(item.item_id)]=report
    result={}
    for slot,record in sorted(source['slot_frontiers'].items()):
        candidates=[all_rows[int(i)] for i in record['priority_item_ids']]
        # Source legality is slot-bound, but offhand gear may require a
        # compatible 1H weapon; never claim a standalone 2H+offhand build.
        # Do not silently treat unknown historical ratings as verified.
        # The real Top-N remains strictly known-score ranked, while a separate
        # provisional sensitivity list exposes how its ordering could change.
        known=sorted(candidates,key=lambda x:(-x['known_score_s_saved_per_mob'],x['item_id']))
        uncertain=[x for x in known if x['unknown_effects']]
        prioritized=[];seen=set()
        for depth in range(len(known)):
            for lane in (known,uncertain):
                if depth<len(lane) and lane[depth]['item_id'] not in seen:
                    prioritized.append(lane[depth]);seen.add(lane[depth]['item_id'])
        candidates=prioritized
        converted_top=sorted(candidates,key=lambda x:(-x['known_score_s_saved_per_mob'],x['item_id']))[:top_n]
        result[slot]={'available_legal':len(candidates),'top':candidates[:top_n],
                      'weighted_top':known[:top_n],
                      'all_ranked_item_ids':[x['item_id'] for x in candidates],
                      'known_weight_top_ids':[x['item_id'] for x in known[:top_n]],
                      'converted_display_percent_top_ids':[x['item_id'] for x in converted_top],
                      'ranking_complete':all(x['fully_rankable'] for x in candidates),
                      'unknown_challenger_count':len(uncertain),
                      'ranking_interpretation':'KNOWN_SCORE_WITH_EXPLICIT_UNCERTAIN_EXPLORATION'}
    return {'checkpoint':source['checkpoint'],'build_identity_sha256':weight_evidence['build_identity_sha256'],
        'catalogue_sha256':expected_sha,
        'equipment_semantics_sha256':source['equipment_semantics_sha256'],'class_key':class_key,'level':level,'requested_top_n':top_n,
        'total_legal_items':len(all_rows),'unknown_item_count':len(uncertain_ids),
        'stat_weights':weight_evidence,'slots':result,
        'p3_pass':len(all_rows)==len(source['source_items']) and all(
            len(x['all_ranked_item_ids'])==x['available_legal'] and x['available_legal']>0
            for x in result.values()),
        'full_numeric_effect_certainty':not uncertain_ids and all(x['ranking_complete'] for x in result.values()),
        'ranking_method':'100mob_build_conditioned_stat_weights_with_source_display_percentage_mapping',
        'selection_limitations':['Build-local linear approximation, not L2 evaluation of every item',
          'Weapon+offhand packages and fixed-stat interactions require joint-gear search',
          'Unresolved procs and partial defense/spell-crit semantics prevent an unconditional top-N proof']}


def verify_weighted_ranking(report, *,class_key,level,stage):
    from src.rulesets.forever.items.source_equipment_semantics import ledger_path
    if report.get('equipment_semantics_sha256')!=sha256(ledger_path().read_bytes()).hexdigest():
        raise ValueError('P3_WEIGHTED_RANKING_STALE_EQUIPMENT_SEMANTICS')
    if (report['class_key']!=class_key or report['level']!=level
            or report['build_identity_sha256']!=_identity(stage)
            or report['catalogue_sha256']!=sha256(Path(catalogue_path()).read_bytes()).hexdigest()):
        raise ValueError('P3_WEIGHTED_RANKING_STALE_OR_WRONG_BUILD')
    if report['total_legal_items']!=len(available_items(class_key,level,required_level_policy='observed')):
        raise ValueError('P3_WEIGHTED_RANKING_INCOMPLETE')
    for slot,section in report['slots'].items():
        ids=section['all_ranked_item_ids']
        if len(ids)!=len(set(ids)) or len(ids)!=section['available_legal']:
            raise ValueError('P3_WEIGHTED_RANKING_TRUNCATED')
        if [r['item_id'] for r in section['top']]!=ids[:len(section['top'])]:
            raise ValueError('P3_WEIGHTED_TOP_N_INCONSISTENT')


def budgeted_measured_stat_weights(*,candidate,class_key,level,mobs=100,max_wall_s=95.,
                                   delta_multiplier=1.,max_measured_axes=7):
    """Bounded build-local 100-mob marginal item prior.

    A finite-difference evaluation is paid for on exactly `mobs` kills for
    every completed stat probe. Never transfer other build/level weights or
    invent values when a probe is timed out/inconclusive. This is cheaper
    than the exhaustive multiscale option above, at lower sensitivity.
    """
    from time import monotonic
    from src.game.gear import executable_gear_stats
    if mobs!=100 or max_measured_axes<1 or not isfinite(max_wall_s) or max_wall_s<=0:
        raise ValueError('P3_BUDGETED_MEASUREMENT_REQUIRES_100MOB_FINITE_BUDGET')
    started=monotonic()
    base=_score(candidate,level,mobs)
    rows=available_items(class_key,level,required_level_policy='observed')
    native=set(executable_gear_stats(candidate.ir))
    axis=set(PROBE_STEPS)|set(SOURCE_RATINGS)
    axis|={k for row in rows for k,v in _features(row).items() if float(v)}
    # Prefer common important stats but do not hide axes outside the budget.
    order=('strength','agility','stamina','intellect','spirit','attack_power',
           'spell_power','armor','mp5','health_regeneration_per_5s',
           'hit','crit','dodge','defense','healing','wand_dps','weapon_dps')
    order=tuple(dict.fromkeys([*order,*sorted(axis)]))
    gear=candidate.source_stage['gear_policy_result']['winner']['gear']
    weapon=float(gear.get('slots',{}).get('weapon',{}).get('weapon_dps') or 0.)
    weights={};completed=[]
    for stat in order:
        if stat not in axis or stat=='weapon_speed':continue
        if len(completed)>=max_measured_axes:
            weights[stat]={'status':'NOT_MEASURED_AXIS_COUNT_BUDGET',
                'weight_s_saved_per_mob_per_unit':None}
            continue
        if stat not in native and stat not in SOURCE_RATINGS:
            weights[stat]={'status':'UNSUPPORTED_RUNTIME_AXIS','weight_s_saved_per_mob_per_unit':None,
                'reason':'not_executable_in_current_ir'}
            continue
        if monotonic()-started>max_wall_s-12.:
            weights[stat]={'status':'NOT_MEASURED_WITHIN_WALL_BUDGET','weight_s_saved_per_mob_per_unit':None}
            continue
        step=(4. if stat=='defense' else PROBE_STEPS.get(stat,5.))
        if stat in ('hit','crit','dodge'):
            step=10. if stat=='hit' else (14. if stat=='crit' else 12.)
        step*=delta_multiplier
        probes=[]
        for multiplier in (1.,2.):
            if monotonic()-started>max_wall_s-10.:break
            delta=step*multiplier
            try:
                value,error=_derivative(candidate,stat,delta,level,mobs,weapon,
                    max_wall_s=min(6.,max(0.1,max_wall_s-(monotonic()-started))))
                if error:raise ValueError(error)
                improvement=float(base['mean_s_per_mob'])-float(value['mean_s_per_mob'])
                probes.append({'delta':delta,'s_per_mob':value['mean_s_per_mob'],
                               'improvement_s_per_mob':improvement,'events':value.get('events')})
                if abs(improvement)>1e-8:break
            except (RuntimeError,ValueError,KeyError) as exc:
                probes.append({'delta':delta,'error':str(exc)})
                break
        print('P3 stat probe',stat,'elapsed',round(monotonic()-started,1),
              'attempts',len(probes), 'valid',sum('improvement_s_per_mob' in p for p in probes),flush=True)
        measured=[p for p in probes if 'improvement_s_per_mob' in p]
        if not measured:
            weights[stat]={'status':'INCONCLUSIVE_OR_BUDGETED_OUT',
                'weight_s_saved_per_mob_per_unit':None,'probes':probes}
            continue
        selected=next((x for x in measured if abs(x['improvement_s_per_mob'])>1e-8),None)
        if selected is None:
            if len(measured)<2:
                weights[stat]={'status':'INCONCLUSIVE_DISCRETE_ZERO_SINGLE_STEP',
                    'weight_s_saved_per_mob_per_unit':None,'probes':probes}
                continue
            selected=measured[-1]
            status='TESTED_ZERO_RANGE_ONLY'
        else:status='MEASURED_100MOB_FINITE_DIFFERENCE'
        weights[stat]={'status':status,
            'weight_s_saved_per_mob_per_unit':selected['improvement_s_per_mob']/selected['delta'],
            'probe_delta':selected['delta'], 'probes':probes,
            'method':'exact_same_fixed_build_100mob_finite_difference',
            'uncertainty':'local_non_smooth_and_talent_gear_interactions_not_proved'}
        if stat=='defense':
            weights[stat]['unmodeled_channels']=['parry','block','incoming_crit']
        completed.append(stat)
    for stat in sorted(axis):
        if stat not in weights and stat!='weapon_speed':
            weights[stat]={'status':'NOT_MEASURED_WITHIN_WALL_BUDGET',
                'weight_s_saved_per_mob_per_unit':None}
    speed=context_weapon_speed_semantics(candidate.ir)
    weights['weapon_speed']={'status':'CONTEXTUAL_ZERO_FROM_SOURCE_FORM_FIXED'
         if speed=='FORM_FIXED_WEAPON_SPEED_NO_ITEM_SENSITIVITY' else 'UNMODELED_WEAPON_SPEED_SENSITIVITY',
         'weight_s_saved_per_mob_per_unit':0. if speed=='FORM_FIXED_WEAPON_SPEED_NO_ITEM_SENSITIVITY' else None,
         'source_semantics':speed}
    return {'base_s_per_mob':base['mean_s_per_mob'],'base_events':base.get('events'),
        'base_actor_stats':{k:float(v) for k,v in candidate.ir.actor.base_stats.items()
            if isinstance(v,(int,float))},
        'chance_sensitivities':{},'weapon_speed_source_status':speed,
        'mobs':mobs,'weights':weights,'probe_failures':{},
        'build_identity_sha256':_identity(candidate.source_stage),
        'class_key':class_key,'level':level,
        'scope':'FIXED_L30_SEARCH_DISCOVERED_BUILD_COARSE_MEASURED_100MOB_MARGINAL',
        'completed_stat_probes':completed,'elapsed_wall_s':monotonic()-started,
        'budget_wall_s':max_wall_s,'max_measured_axes':max_measured_axes,
        'limitation':'finite-difference values at local steps, not global or continuously differentiable'}
