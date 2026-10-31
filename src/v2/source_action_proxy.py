"""Generic GameIR action coverage and cheap numeric *ordering* proxy.

This is not an s/mob prediction, a legality assertion, or L2 executor proof.
Unknown or unsupported effects remain explicitly unresolved and never score as
zero-value proof. Game-specific facts are supplied solely by GameIR effects.
"""
from __future__ import annotations

from math import isfinite
from src.game.runtime.effect_capabilities import effect_role


def _nonnegative(value):
    try:
        result=float(value)
    except (TypeError,ValueError):
        return None
    return result if isfinite(result) and result >= 0 else None


def _feature(effect):
    role=effect_role(effect)
    if role is None:
        return {'role':'unsupported','known':False,'magnitude':None}
    domains={
        'direct_damage':('bonus_damage','flat_damage','base_min','total_base_damage'),
        'periodic_damage':('total_base_damage','base_min'),
        'healing':('total_base_heal','base_min'),
        'control':('duration_s',),
        'target_debuff':('delta',),
        'resource':('amount','amount_per_tick'),
        'combat_enabler':('duration_s','actor_absorb_amount'),
        'summon':('duration_s',),
    }
    fields=domains.get(role,())
    for field in fields:
        n=_nonnegative(abs(getattr(effect,field)) if field == 'delta' and getattr(effect,field,None) is not None else getattr(effect,field,None))
        if n is not None:
            return {'role':role,'known':True,'domain':field,'magnitude':n}
    if role == 'mode_change':
        return {'role':role,'known':True,'domain':'mode_unlock','magnitude':1.0}
    return {'role':role,'known':False,'magnitude':None}


def checkpoint_action_proxy_coverage(ir, *,level:int) -> dict:
    """Audit *all* own IR actions; coarse scores affect ordering only.

    Do not silently exclude actions based on an unknown feature or proxy score.
    The caller separately applies source provenance, mode and legality rules.
    """
    if int(ir.actor.metadata.get('level',-1)) != level:
        raise ValueError('SOURCE_ACTION_PROXY_CHECKPOINT_MISMATCH')
    rows=[]
    for action in ir.actions:
        if action.owner_actor_id != ir.actor.id:
            continue
        minimums=[int(r['value']) for r in action.requirements if r.get('kind')=='minimum_level']
        if minimums and max(minimums)>level:
            continue
        features=[_feature(e) for e in action.effects]
        scores=[f['magnitude'] for f in features if f['known'] and f['magnitude'] is not None]
        # Only an ordering estimate: a 1-second control is not comparable to a
        # 1-damage hit in a final optimization objective.
        magnitude=max(scores,default=0.)
        interval=max(float(action.gcd_s),float(action.cast_time_s),1.0)
        search_priority=magnitude/interval
        rows.append({'action_id':action.id,'search_priority':search_priority,
            'numeric_features':features,'unresolved_effects':sum(not f['known'] for f in features),
            'is_zero_utility_proven':False,'is_l2_search_admitted':None,
            'unknown_roles_are_not_pruned':True})
    return {'source_ir_id':ir.id,'level':level,'ir_actions':rows,
            'action_count':len(rows),
            'not_global_optimality_proof':True,'proxy_not_s_per_mob':True}
