#!/usr/bin/env python3
"""Legacy talent-runtime probe helpers retained for regression tests only.

P2 is retired from formal acceptance. This module has no gate runner; active
P3–P7.5 providers use their own production paths.
"""
from __future__ import annotations

from collections.abc import Mapping
from math import isclose, isfinite
from dataclasses import replace

from src.game.data.forever.source_checkpoint_p2 import _witness
from src.game.data.forever.checkpoint_p2_execution_gate import _executable_filler_witness
from src.game.talents import apply_talent_selection, available_talent_points, validate_talent_selection
from src.game.talent_frontier import source_legal_talent_neighbors
from src.optimization.talent_frontier import allocation_key
from src.game.source_objective_relevance import solo_threat_exclusion


def _runtime_actor_state_delta(before, after):
    """One real production-state probe, including all common legal forms."""
    from src.game.runtime import ActorState
    changes=[]
    modes={m.id for m in before.modes}&{m.id for m in after.modes}
    for mode in [None,*sorted(modes)]:
        a=ActorState.from_ir(before.actor,before.resources,before.modes)
        b=ActorState.from_ir(after.actor,after.resources,after.modes)
        if mode is not None:
            try:a.transition_mode(mode);b.transition_mode(mode)
            except (ValueError,KeyError,AttributeError):continue
        for field in ('stats','resource_capacity','resources'):
            lhs=getattr(a,field,None);rhs=getattr(b,field,None)
            if not isinstance(lhs,dict) or not isinstance(rhs,dict):continue
            for name in sorted(set(lhs)|set(rhs)):
                x,y=lhs.get(name,0),rhs.get(name,0)
                if (isinstance(x,(int,float)) and isinstance(y,(int,float))
                        and abs(x-y)>1e-10):
                    changes.append({'mode':mode or 'initial','field':field,
                        'stat':name,'before':float(x),'after':float(y)})
    return changes


def _effect_change(before, after):
    """Compilation witness only; does NOT certify L2 behavior."""
    return any(getattr(before, name) != getattr(after, name) for name in (
        'actor','resources','actions','modes','auto_attacks','triggers',
        'resource_event_gain_rules','mode_stat_modifiers'
    ) if hasattr(before,name) and hasattr(after,name))


def _action_runtime_probe(ir, action, *, observe_periodic=False,
                          observe_controls=False, target_id='p2_fixture',
                          target_spell_hit=1.0, capture_source_hit=False):
    """Execute real action on a live actor/target; deterministic fixture.

    Only differences that are actually observed in runtime count. No event
    count / ActionStarted shortcut. If not eligible, return no probe.
    """
    from src.game.runtime import ActorState, CombatRuntime, TargetState
    from src.game.runtime.simulator import action_eligibility
    # A sourced positional precondition belongs to the encounter, not to a
    # hardcoded class whitelist. Construct the required controlled situation
    # for this effect probe and separately reject the opposite position.
    # This does NOT certify movement/facing or the full 2D P1/P7 path.
    positions={str(req.get('value') or '') for req in action.requirements
               if req.get('kind')=='relative_position_is'}
    if len(positions)>1 or (positions and not positions <= {'front','behind'}):
        return None
    required_position=next(iter(positions),None)

    def fixture_target(*, opposite=False):
        target=TargetState.with_health(target_id,100000.0,armor=0.0)
        target.metadata['spell_hit'] = float(target_spell_hit)
        if capture_source_hit:
            # The real source-captured target activates the production
            # expected-hit resolver; an ordinary generic dummy intentionally
            # does not apply sourced hit/miss mechanics.
            target.metadata['combat_capture_id'] = 'p2_sourced_hit_fixture'
        if required_position is not None:
            position=({'front':'behind','behind':'front'}[required_position]
                      if opposite else required_position)
            target.metadata['attacker_relative_position']=position
        return target

    # Check the *actual* runtime eligibility in each source mode. A caster mode
    # with an unrestricted enabled_action_ids list does not necessarily permit
    # a Bear-only action (e.g. Swipe). No class-specific mode names here.
    actor=None
    for mode in [None, *(m.id for m in ir.modes)]:
        candidate=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
        if mode is not None and candidate.current_mode_id!=mode:
            try:candidate.transition_mode(mode)
            except (ValueError,KeyError,AttributeError):continue
        target=fixture_target()
        if action_eligibility(action=action,actor=candidate,target=target).eligible:
            actor=candidate
            break
        # Resource availability is adjusted below; initial eligibility can
        # fail simply because Rage/Energy has not yet been seeded.
        for cost in action.costs:
            if cost.resource_id in candidate.resources:
                cap=max(float(cost.amount)+500.0,float(candidate.resource_capacity.get(cost.resource_id,0)))
                candidate.resource_capacity[cost.resource_id]=cap
                candidate.resources[cost.resource_id]=cap
        if action_eligibility(action=action,actor=candidate,target=target).eligible:
            actor=candidate
            break
    if actor is None:return None
    for cost in action.costs:
        if cost.resource_id in actor.resources:
            cap=max(float(cost.amount)+500.0,float(actor.resource_capacity.get(cost.resource_id,0)))
            actor.resource_capacity[cost.resource_id]=cap
            actor.resources[cost.resource_id]=cap
    if 'health' in actor.resources:
        actor.resource_capacity['health']=max(float(actor.resource_capacity.get('health',0)),10000.)
        actor.resources['health']=actor.resource_capacity['health']-1000.
    rt=CombatRuntime(actor=actor,target=fixture_target())
    if not action_eligibility(action=action,actor=actor,target=rt.target).eligible:return None
    if required_position is not None:
        # Positive/negative positional control through production eligibility:
        # a Shred-style rear-only action must remain illegal from the front.
        if action_eligibility(action=action,actor=actor,
                              target=fixture_target(opposite=True)).eligible:
            return None
    before=dict(actor.resources)
    try:
        end=rt.schedule_action(action)
        rt.advance_to(end + 0.01)
        # A target debuff can expire before the final periodic tick. Capture
        # actual applied state immediately, not merely a queued aura intent.
        target_stat_modifiers_on_apply=dict(rt.target.active_stat_modifiers)
        if observe_periodic:
            # Observe the actual tick series, not just the aura application.
            duration=max((float(e.duration_s) for e in action.effects if hasattr(e,'tick_interval_s')),default=0.0)
            if duration>0:rt.advance_to(end+duration+0.02)
    except (ValueError,KeyError,RuntimeError,AttributeError,TypeError):return None
    events=[{'kind':e.kind,'amount':float(e.payload.get('amount',0.0)),
             'periodic':bool(e.payload.get('periodic'))}
            for e in rt.trace if e.kind in ('Damage','Heal')]
    controls=([{'control_id':str(e.payload.get('control_id')),
                'duration_s':float(e.payload.get('duration_s',0.)),
                'proc_chance':float(e.payload.get('proc_chance',0.)),
                'proc_roll':e.payload.get('proc_roll'),
                'proc_triggered':e.payload.get('proc_triggered') is True,
                'applied':e.payload.get('applied') is True,
                'prevents_enemy_actions':e.payload.get('prevents_enemy_actions') is True,
                'breaks_on_damage':e.payload.get('breaks_on_damage') is True}
               for e in rt.trace if e.kind=='ControlApplied']
              if observe_controls else [])
    return {'controls':controls,
            'active_controls':(dict(rt.target.active_controls) if observe_controls else {}),
            'target_stat_modifiers_on_apply':target_stat_modifiers_on_apply,
            'completion_s':float(end), 'gcd_ready_s':float(actor.gcd_ready_s),'spent':{
                c.resource_id:round(before.get(c.resource_id,0)-actor.resources.get(c.resource_id,0),6)
                for c in action.costs},
            'damage':sum(e['amount'] for e in events if e['kind']=='Damage'),
            'heal':sum(e['amount'] for e in events if e['kind']=='Heal'),
            'direct_damage':sum(e['amount'] for e in events if e['kind']=='Damage' and not e['periodic']),
            'periodic_damage':sum(e['amount'] for e in events if e['kind']=='Damage' and e['periodic']),
            'direct_heal':sum(e['amount'] for e in events if e['kind']=='Heal' and not e['periodic']),
            'periodic_heal':sum(e['amount'] for e in events if e['kind']=='Heal' and e['periodic']),
            'events':events}


def _scaled_effect_fields(effect, kind):
    """Which concrete IR fields a percentage talent can change (class-neutral)."""
    from src.game.model.ir import (DamageEffect, WeaponDamageEffect, PeriodicEffect,
        HealEffect, PeriodicHealEffect, ResourceScaledPeriodicEffect,
        ResourceScaledDirectDamageEffect)
    if kind=='effect_damage_pct':
        if isinstance(effect,DamageEffect):
            return (effect.base_min,effect.base_max,effect.spell_power_coefficient)
        if isinstance(effect,WeaponDamageEffect):
            return (effect.weapon_damage_multiplier,effect.flat_damage)
        if isinstance(effect,ResourceScaledDirectDamageEffect):
            return tuple(effect.base_min_by_resource_amount.values())+tuple(effect.base_max_by_resource_amount.values())+(effect.attack_power_coefficient_per_resource,)
        if isinstance(effect,PeriodicEffect):
            return (effect.total_base_damage,effect.spell_power_coefficient_per_tick)
        if isinstance(effect,ResourceScaledPeriodicEffect):
            return tuple(effect.total_base_damage_by_resource_amount.values())
    if kind=='effect_healing_pct':
        if isinstance(effect,HealEffect):
            return (effect.base_min,effect.base_max,effect.spell_power_coefficient)
        if isinstance(effect,PeriodicHealEffect):
            return (effect.total_base_heal,effect.spell_power_coefficient_per_tick)
    if kind=='effect_periodic_pct':
        if isinstance(effect,PeriodicEffect):
            return (effect.total_base_damage,effect.spell_power_coefficient_per_tick)
        if isinstance(effect,PeriodicHealEffect):
            return (effect.total_base_heal,effect.spell_power_coefficient_per_tick)
        if isinstance(effect,ResourceScaledPeriodicEffect):
            return tuple(effect.total_base_damage_by_resource_amount.values())
    return None


def _isolate_scaled_effect(old_effect, new_effect, kind):
    """Transfer ONLY the modifier's amplitude fields, never crit/proc/etc.

    The resulting action can be run with the unchanged baseline actor and
    action requirements, so another modifier cannot manufacture a positive
    runtime witness for this one.
    """
    from src.game.model.ir import (DamageEffect, WeaponDamageEffect, PeriodicEffect,
        HealEffect, PeriodicHealEffect, ResourceScaledPeriodicEffect,
        ResourceScaledDirectDamageEffect)
    names=()
    if kind=='effect_damage_pct':
        if isinstance(old_effect,DamageEffect):
            names=('base_min','base_max','spell_power_coefficient')
        elif isinstance(old_effect,WeaponDamageEffect):
            names=('weapon_damage_multiplier','flat_damage')
        elif isinstance(old_effect,PeriodicEffect):
            names=('total_base_damage','spell_power_coefficient_per_tick')
        elif isinstance(old_effect,ResourceScaledPeriodicEffect):
            names=('total_base_damage_by_resource_amount',)
        elif isinstance(old_effect,ResourceScaledDirectDamageEffect):
            names=('base_min_by_resource_amount','base_max_by_resource_amount','attack_power_coefficient_per_resource')
    elif kind=='effect_healing_pct':
        if isinstance(old_effect,HealEffect):
            names=('base_min','base_max','spell_power_coefficient')
        elif isinstance(old_effect,PeriodicHealEffect):
            names=('total_base_heal','spell_power_coefficient_per_tick')
    elif kind=='effect_periodic_pct':
        if isinstance(old_effect,PeriodicEffect):
            names=('total_base_damage','spell_power_coefficient_per_tick')
        elif isinstance(old_effect,PeriodicHealEffect):
            names=('total_base_heal','spell_power_coefficient_per_tick')
        elif isinstance(old_effect,ResourceScaledPeriodicEffect):
            names=('total_base_damage_by_resource_amount',)
    if not names or type(old_effect) is not type(new_effect):return old_effect
    return replace(old_effect,**{field:getattr(new_effect,field) for field in names})


def _runtime_effect_witness(before,after,mod):
    """Source-scaled IR *and* an observed corresponding L2 outcome are required.

    A changed source field alone does not pass; nor does a change in an unrelated
    action. Paired runtime probes use identical test conditions and event seeds.
    Unsupported situational actions remain unverified instead of being waived.
    """
    kind=mod.kind
    expected=mod.provenance.get('_gate_relative_factor')
    if expected is None:return None
    target=str(mod.target_id)
    old={a.id:a for a in before.actions}
    for new_action in after.actions:
        prior=old.get(new_action.id)
        if prior is None or prior.family_key!=new_action.family_key:continue
        if mod.target_type=='action_family' and new_action.family_key!=target:continue
        if len(prior.effects)!=len(new_action.effects):continue
        numeric=[]
        isolated_effects=[]
        for x,y in zip(prior.effects,new_action.effects):
            a=_scaled_effect_fields(x,kind)
            b=_scaled_effect_fields(y,kind)
            if a is None or b is None or len(a)!=len(b):
                isolated_effects.append(x)
                continue
            if any(not isclose(float(u)*expected,float(v),rel_tol=1e-5,abs_tol=1e-6) for u,v in zip(a,b)):
                numeric=[];break
            if any(abs(float(u))>1e-8 and abs(float(v-u))>1e-8 for u,v in zip(a,b)):
                numeric.append(type(x).__name__)
                isolated_effects.append(_isolate_scaled_effect(x,y,kind))
            else:
                isolated_effects.append(x)
        if not numeric:continue
        periodic=any(x in ('PeriodicEffect','PeriodicHealEffect','ResourceScaledPeriodicEffect') for x in numeric)
        isolated_action=replace(prior,effects=tuple(isolated_effects))
        old_run=_action_runtime_probe(before,prior,observe_periodic=periodic)
        new_run=_action_runtime_probe(before,isolated_action,observe_periodic=periodic)
        if not old_run or not new_run:continue
        if kind=='effect_healing_pct':
            amount_key='periodic_heal' if periodic else 'direct_heal'
        elif kind=='effect_periodic_pct':
            amount_key='periodic_heal' if 'PeriodicHealEffect' in numeric else 'periodic_damage'
        else:
            amount_key='periodic_damage' if periodic and not any(
                x in numeric for x in ('DamageEffect','WeaponDamageEffect','ResourceScaledDirectDamageEffect')) else 'direct_damage'
        earlier=float(old_run[amount_key]); later=float(new_run[amount_key])
        # A no-op, wrong direction, or non-executing fixture never passes.
        if earlier<=0 or (later-earlier)*(expected-1)<=1e-8:continue
        return {'probe':'isolated_production_combat_runtime_effect', 'action_id':new_action.id,
                'effect_classes':numeric,'metric':amount_key,
                'before_amount':round(earlier,6),'after_amount':round(later,6),
                'ir_factor':round(float(expected),8)}
    return None


def _isolated_crit_witness(before, after, mod):
    """Observed expected critical contribution, isolating the talent's crit.

    Crit changes must affect the correct action effect *and* the production
    runtime's expected damage/heal. No deterministic RNG lucky-roll gate.
    """
    from src.game.model.ir import (DamageEffect, HealEffect, PeriodicEffect,
        WeaponDamageEffect, ResourceScaledDirectDamageEffect)
    target=str(mod.target_id)
    old={a.id:a for a in before.actions}
    for action in after.actions:
        prior=old.get(action.id)
        if prior is None or len(prior.effects)!=len(action.effects):continue
        if mod.target_type=='action_family' and action.family_key!=target:continue
        replacement=[]; changed=False; periodic=False; metric=None
        for old_e,new_e in zip(prior.effects, action.effects):
            if type(old_e) is not type(new_e):replacement.append(old_e);continue
            if isinstance(old_e,(DamageEffect,HealEffect,PeriodicEffect,
                                 ResourceScaledDirectDamageEffect)):
                key='crit_chance_bonus'
            elif isinstance(old_e,WeaponDamageEffect):
                key='crit_chance_on_landed_hit'
            else:
                replacement.append(old_e);continue
            before_crit=float(getattr(old_e,key,0))
            after_crit=float(getattr(new_e,key,0))
            # Validate the rank-N vs rank-(N-1) delta, not merely direction.
            if not isclose(after_crit-before_crit,float(mod.value),abs_tol=1e-7,rel_tol=1e-5):
                replacement.append(old_e);continue
            if not changed:
                replacement.append(replace(old_e,**{key:after_crit}))
                changed=True
                periodic=isinstance(old_e,PeriodicEffect)
                metric=('periodic_damage' if periodic else 'direct_heal' if
                    isinstance(old_e,HealEffect) else 'direct_damage')
            else:replacement.append(old_e)
        if not changed:continue
        new_action=replace(prior,effects=tuple(replacement))
        x=_action_runtime_probe(before,prior,observe_periodic=periodic)
        y=_action_runtime_probe(before,new_action,observe_periodic=periodic)
        if x is None or y is None:continue
        if x[metric]>0 and y[metric]>x[metric]+1e-7:
            return {'probe':'isolated_production_crit_expectation',
                    'action_id':action.id,'metric':metric,
                    'before_amount':x[metric],'after_amount':y[metric],
                    'crit_delta':float(mod.value)}
    return None



def _sourced_hit_runtime_witness(before, after, mod):
    """Prove sourced spell-hit rank deltas in the real CombatRuntime.

    A full-hit target masks the bonus.  Use a controlled sub-100% hit
    probability and a saturated negative control; require every source-scoped
    action to receive the exact incremental modifier, not just one lucky spell.
    This does NOT certify a separate, unimplemented source range effect.
    """
    from src.game.model.ir import DamageEffect, PeriodicEffect

    if (mod.kind != 'hit_chance_bonus' or mod.target_type != 'action_filter'
            or mod.target_id != 'damage_spell'
            or not 0 < float(mod.value) < 1):
        return None

    def scoped(action):
        return (any(isinstance(e, (DamageEffect, PeriodicEffect))
                    and e.school.lower() != 'physical' for e in action.effects)
                and any(c.resource_id == 'mana' for c in action.costs))

    new = {action.id: action for action in after.actions}
    applicable = [action for action in before.actions if scoped(action)]
    if not applicable:
        return None
    for action in applicable:
        updated = new.get(action.id)
        if updated is None or not any(
                isinstance(p, Mapping) and p.get('stage') == 'talent_modifier'
                and p.get('kind') == mod.kind
                for p in updated.provenance):
            return None
        delta = (float(updated.metadata.get('outgoing_hit_bonus', 0.))
                 - float(action.metadata.get('outgoing_hit_bonus', 0.)))
        if not isclose(delta, float(mod.value), abs_tol=1e-8, rel_tol=1e-6):
            return None
    # The modifier must not leak to other, source-ineligible actions.
    if any(not scoped(action) and action.id in new and not isclose(
            float(new[action.id].metadata.get('outgoing_hit_bonus', 0.)),
            float(action.metadata.get('outgoing_hit_bonus', 0.)),
            abs_tol=1e-8) for action in before.actions):
        return None

    for action in applicable:
        updated = new[action.id]
        previous_bonus = float(action.metadata.get('outgoing_hit_bonus', 0.))
        current_bonus = float(updated.metadata.get('outgoing_hit_bonus', 0.))
        # Avoid the 100% cap in the positive control, including a source
        # bonus from earlier ranks.  Do not invent a source hit coefficient.
        base_hit = min(.5, .95 - current_bonus)
        if base_hit <= 0:
            continue
        isolated = replace(action, metadata={
            **dict(action.metadata), 'outgoing_hit_bonus': current_bonus})
        periodic = any(isinstance(e, PeriodicEffect) for e in action.effects)
        x = _action_runtime_probe(before, action, observe_periodic=periodic,
                                  target_spell_hit=base_hit,
                                  capture_source_hit=True)
        y = _action_runtime_probe(before, isolated, observe_periodic=periodic,
                                  target_spell_hit=base_hit,
                                  capture_source_hit=True)
        # Negative control: at 100% hit, adding a chance bonus has no
        # gameplay effect.  This rejects unrelated damage scaling.
        saturated_x = _action_runtime_probe(
            before, action, observe_periodic=periodic, target_spell_hit=1.,
            capture_source_hit=True)
        saturated_y = _action_runtime_probe(
            before, isolated, observe_periodic=periodic, target_spell_hit=1.,
            capture_source_hit=True)
        if any(z is None for z in (x, y, saturated_x, saturated_y)):
            continue
        if (x['damage'] > 0 and y['damage'] > x['damage'] + 1e-7
                and isclose(saturated_x['damage'], saturated_y['damage'],
                            abs_tol=1e-7, rel_tol=1e-6)):
            return {'probe': 'paired_production_spell_hit_probability',
                    'action_id': action.id,
                    'source_scoped_actions_checked': len(applicable),
                    'controlled_base_hit': base_hit,
                    'before_amount': x['damage'], 'after_amount': y['damage'],
                    'saturated_before': saturated_x['damage'],
                    'saturated_after': saturated_y['damage'],
                    'rank_hit_bonus_delta': float(mod.value)}
    return None


def _critical_damage_runtime_witness(before, after, mod):
    """Observe the sourced critical *bonus* through real combat resolution.

    Rank-N modifiers contain cumulative percentages. Compare their ratio to
    rank N-1, isolate only crit_multiplier, and keep both runs' controlled
    crit probability identical. A compiled field change alone is not PASS.
    """
    from src.game.model.ir import (DamageEffect, PeriodicEffect,
        WeaponDamageEffect, ResourceScaledDirectDamageEffect)

    ratio=mod.provenance.get('_gate_crit_bonus_ratio')
    if (mod.kind!='critical_damage_bonus_pct' or type(ratio) not in (int,float)
            or not isfinite(ratio) or ratio<=1.):
        return None
    old_actions={a.id:a for a in before.actions}
    supported=(DamageEffect,PeriodicEffect,WeaponDamageEffect,
               ResourceScaledDirectDamageEffect)
    checked=[];observed=None
    for action in after.actions:
        prior=old_actions.get(action.id)
        if (prior is None or len(prior.effects)!=len(action.effects)
                or (mod.target_type=='action_family' and
                    action.family_key!=mod.target_id)):
            continue
        if not any(isinstance(p,Mapping) and p.get('stage')=='talent_modifier'
                   and p.get('kind')=='critical_damage_bonus_pct'
                   for p in action.provenance):
            continue
        changed=[]
        for index,(old_effect,new_effect) in enumerate(zip(prior.effects,action.effects)):
            if type(old_effect) is not type(new_effect):
                return None
            if not isinstance(old_effect,supported):
                continue
            earlier=float(old_effect.crit_multiplier)
            later=float(new_effect.crit_multiplier)
            if isclose(earlier,later,abs_tol=1e-9):
                continue
            if (earlier<=1. or not isclose(
                    later-1.,(earlier-1.)*ratio,rel_tol=1e-6,abs_tol=1e-7)):
                return None
            changed.append((index,old_effect,new_effect))
        if not changed:
            continue
        checked.append(action.id)
        if observed is not None:
            continue
        for index,old_effect,new_effect in changed:
            # A controlled nonzero crit chance is a *fixture*, not an invented
            # source stat. It is identical in both real CombatRuntime runs.
            crit_field=('crit_chance_on_landed_hit' if
                isinstance(old_effect,WeaponDamageEffect) else 'crit_chance_bonus')
            controlled=replace(old_effect,**{crit_field:max(
                0.5,float(getattr(old_effect,crit_field)))})
            altered=replace(controlled,crit_multiplier=new_effect.crit_multiplier)
            base_effects=list(prior.effects)
            base_effects[index]=controlled
            base=replace(prior,effects=tuple(base_effects))
            base_effects[index]=altered
            challenger=replace(prior,effects=tuple(base_effects))
            periodic=isinstance(old_effect,PeriodicEffect)
            x=_action_runtime_probe(before,base,observe_periodic=periodic)
            y=_action_runtime_probe(before,challenger,observe_periodic=periodic)
            metric='periodic_damage' if periodic else 'direct_damage'
            if (x is not None and y is not None and x[metric]>0
                    and y[metric]>x[metric]+1e-7):
                observed={'action_id':action.id,'metric':metric,
                          'before_amount':x[metric],'after_amount':y[metric],
                          'before_crit_multiplier':float(old_effect.crit_multiplier),
                          'after_crit_multiplier':float(new_effect.crit_multiplier)}
                break
    if not checked or observed is None:
        return None
    return {'probe':'paired_production_critical_bonus',
            'checked_ir_actions':checked,'source_bonus_ratio':float(ratio),
            **observed}


def _isolated_resource_cost_witness(before,after,mod):
    """Check *all* compiled cost targets; one successful runtime cost witness.

    A broad modifier must not pass because one spell is correct when another
    sourced target is mis-scaled. Runtime probing each rank's every spell is
    unnecessary: verify all GameIR deltas and a representative live executor.
    """
    prior={a.id:a for a in before.actions}
    applicable=[]
    runtime_evidence=None
    for action in after.actions:
        older=prior.get(action.id)
        if older is None:continue
        if mod.target_type=='action_family' and action.family_key!=mod.target_id:continue
        if mod.target_type not in ('action_family','action_filter'):continue
        # Identify targets through compiler provenance, not by a Druid-only
        # list. Other same-kind modifiers on one talent cannot substitute.
        if not any(isinstance(p,dict) and p.get('stage')=='talent_modifier' and
                   p.get('kind')==mod.kind for p in action.provenance):continue
        paired=[(a,b) for a,b in zip(older.costs,action.costs)
                if a.resource_id==b.resource_id and abs(a.amount-b.amount)>1e-8]
        if not paired:continue
        if mod.kind=='resource_cost_flat':
            if any(not isclose(b.amount-a.amount,float(mod.value),
                    rel_tol=1e-5,abs_tol=1e-5) for a,b in paired):return None
        else:
            # Full-rank source values are cumulative; N vs N-1 is a ratio.
            ratio=mod.provenance.get('_gate_cost_ratio')
            if ratio is None or any(not isclose(float(b.amount),float(a.amount)*float(ratio),
                    rel_tol=1e-5,abs_tol=1e-5) for a,b in paired):return None
        applicable.append(action.id)
        if runtime_evidence is not None:continue
        x=_action_runtime_probe(before,older)
        y=_action_runtime_probe(before,action)
        if x is None or y is None:continue
        valid=True; observations=[]
        for a,b in paired:
            old_spend=x['spent'].get(a.resource_id)
            new_spend=y['spent'].get(a.resource_id)
            if old_spend is None or new_spend is None or not isclose(
                    new_spend-old_spend,b.amount-a.amount,rel_tol=1e-4,abs_tol=1e-4):
                valid=False;break
            observations.append({'resource':a.resource_id,'before_cost':a.amount,
                                 'after_cost':b.amount,'before_spent':old_spend,
                                 'after_spent':new_spend})
        if valid:runtime_evidence={'action_id':action.id,'observations':observations}
    if applicable and runtime_evidence is not None:
        return {'probe':'paired_production_resource_spend',
                'checked_ir_actions':applicable,**runtime_evidence}
    return None



def _mode_entry_resource_witness(before, after, mod):
    """Class-neutral rank witness for sourced resources gained on form entry.

    Compare the *increment* in the compiled modifier against the source, then
    exercise matched production ActorState transitions. For restores, also
    assert the sourced retention, rate and cap (a mere resource gain is not
    enough to certify the modifier).
    """
    from src.game.runtime import ActorState

    kind_map = {'mode_entry_expected_gain': 'expected_flat_gain',
                'mode_entry_restore_last': 'restore_last_mode_resource'}
    runtime_kind = kind_map.get(mod.kind)
    if runtime_kind is None or mod.target_type != 'mode':
        return None
    mode_id = str(mod.target_id)
    resource_id = str(mod.provenance.get('resource_id') or '')
    if not resource_id:
        return None

    def find_entry(ir):
        mode = next((m for m in ir.modes if m.id == mode_id), None)
        if mode is None:
            return None
        matches = [entry for entry in mode.entry_resource_modifiers
                   if entry.kind == runtime_kind and entry.resource_id == resource_id]
        return matches[0] if len(matches) == 1 else None

    old_entry, new_entry = find_entry(before), find_entry(after)
    if new_entry is None or not isclose(
        new_entry.value-(old_entry.value if old_entry else 0.), float(mod.value),
        rel_tol=1e-6, abs_tol=1e-7):
        return None
    if runtime_kind == 'restore_last_mode_resource':
        for field in ('outside_regen_per_s', 'max_restored'):
            value = mod.provenance.get(field)
            if value is None or not isclose(float(getattr(new_entry, field)),
                             float(value), rel_tol=1e-6, abs_tol=1e-7):
                return None
        source_forbidden = mod.provenance.get('forbidden_mode_ids')
        if source_forbidden is not None and set(new_entry.forbidden_mode_ids) != set(source_forbidden):
            return None

    observations = []
    try:
        for ir, item in ((before, old_entry), (after, new_entry)):
            state = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
            capacity = float(state.resource_capacity.get(resource_id, 0))
            if capacity <= 0 or resource_id not in state.resources:
                return None
            if runtime_kind == 'expected_flat_gain':
                if state.current_mode_id == mode_id:
                    other = next((m.id for m in ir.modes if m.id != mode_id), None)
                    if other is None:
                        return None
                    state.transition_mode(other)
                state.resources[resource_id] = 0.0
                predicted = float(item.value) if item else 0.0
            else:
                forbidden = set(new_entry.forbidden_mode_ids)
                other = next((m.id for m in ir.modes if m.id != mode_id
                              and m.id not in forbidden), None)
                if other is None:
                    return None
                if state.current_mode_id != mode_id:
                    state.transition_mode(mode_id)
                stored = capacity*0.5
                state.resources[resource_id] = stored
                state.current_time_s = 3.0
                state.transition_mode(other)
                state.current_time_s = 4.0
                predicted = (min(float(item.max_restored),
                             stored*float(item.value)+float(item.outside_regen_per_s))
                             if item else 0.0)
            # Do not count a capped resource as evidence of a correct talent.
            if predicted >= capacity - 1e-6:
                return None
            transition = state.transition_mode(mode_id)
            observed = float(state.resources[resource_id])
            if not isclose(observed, predicted, rel_tol=1e-5, abs_tol=1e-5):
                return None
            events = [x for x in transition['resource_changes']
                      if x['phase'] == 'talent_entry' and x['mode_id'] == mode_id
                      and x['resource_id'] == resource_id
                      and x['behavior'] == runtime_kind]
            if item:
                if len(events) != 1 or not isclose(float(events[0]['gained']), observed,
                                                    rel_tol=1e-5, abs_tol=1e-5):
                    return None
            elif events:
                return None
            observations.append({'amount': round(observed, 7),
                                 'source_predicted': round(predicted, 7)})
        observed_delta = observations[1]['amount']-observations[0]['amount']
        if abs(observed_delta) < 1e-7 or not isclose(
                observed_delta, observations[1]['source_predicted']-
                                observations[0]['source_predicted'],
                rel_tol=1e-5, abs_tol=1e-6):
            return None
        return {'probe': 'paired_production_mode_transition',
                'mode_id': mode_id, 'resource_id': resource_id,
                'before': observations[0], 'after': observations[1],
                'source_increment': float(mod.value)}
    except (ValueError, KeyError, AttributeError, TypeError):
        return None

def _periodic_duration_witness(before, after, mod):
    """Check *all* sourced action ranks and observe actual extra/removed ticks.

    A duration-only GameIR change cannot pass on its own. Verify the exact
    sourced extension, stable tick interval and per-tick payload for every
    matching rank, then execute a representative isolated action in the real
    CombatRuntime. No class-, talent- or spell-name assumptions.
    """
    from src.game.model.ir import PeriodicEffect, PeriodicHealEffect

    if mod.target_type != 'action_family' or abs(float(mod.value)) < 1e-9:
        return None
    target = str(mod.target_id)
    originals = {a.id: a for a in before.actions}
    matching = [a for a in after.actions if a.family_key == target]
    if not matching:
        return None
    checked = []
    runtime_candidate = None
    for action in matching:
        old = originals.get(action.id)
        if old is None or len(old.effects) != len(action.effects):
            return None
        isolated = list(old.effects)
        periodic_indices = []
        for i, (lhs, rhs) in enumerate(zip(old.effects, action.effects)):
            if not isinstance(lhs, (PeriodicEffect, PeriodicHealEffect)):
                if isinstance(rhs, (PeriodicEffect, PeriodicHealEffect)):
                    return None
                continue
            if type(lhs) is not type(rhs):
                return None
            interval = float(lhs.tick_interval_s)
            old_duration = float(lhs.duration_s)
            new_duration = float(rhs.duration_s)
            if (interval <= 0 or old_duration <= 0 or new_duration <= 0
                    or not isclose(float(rhs.tick_interval_s), interval, abs_tol=1e-8)
                    or not isclose(new_duration-old_duration, float(mod.value), abs_tol=1e-7)):
                return None
            n_old = round(old_duration / interval)
            n_new = round(new_duration / interval)
            if (n_old < 1 or n_new < 1 or n_new == n_old
                    or not isclose(n_old*interval, old_duration, abs_tol=1e-7)
                    or not isclose(n_new*interval, new_duration, abs_tol=1e-7)):
                return None
            total_field = ('total_base_damage' if isinstance(lhs, PeriodicEffect)
                           else 'total_base_heal')
            old_total = float(getattr(lhs, total_field))
            new_total = float(getattr(rhs, total_field))
            # Extra duration is extra ticks, not stronger existing ticks.
            if (old_total <= 0 or not isclose(new_total/n_new, old_total/n_old,
                                             rel_tol=1e-6, abs_tol=1e-7)):
                return None
            periodic_indices.append((i, type(lhs).__name__, n_old, n_new))
            isolated[i] = rhs
        if not periodic_indices:
            # A sourced target action that the compiled modifier skipped must
            # not be silently ignored or certified by a different rank.
            return None
        checked.append(action.id)
        if runtime_candidate is None and len(periodic_indices) == 1:
            runtime_candidate = (old, replace(old, effects=tuple(isolated)), periodic_indices[0])
    if not runtime_candidate:
        return None
    original, isolated_action, (_, effect_type, n_old, n_new) = runtime_candidate
    old_run = _action_runtime_probe(before, original, observe_periodic=True)
    new_run = _action_runtime_probe(before, isolated_action, observe_periodic=True)
    if old_run is None or new_run is None:
        return None
    event_kind = 'Damage' if effect_type == 'PeriodicEffect' else 'Heal'
    def ticks(result):
        return [float(e['amount']) for e in result['events']
                if e['kind'] == event_kind and e['periodic']]
    old_ticks, new_ticks = ticks(old_run), ticks(new_run)
    if len(old_ticks) != n_old or len(new_ticks) != n_new:
        return None
    if any(x <= 0 for x in old_ticks+new_ticks):
        return None
    old_per_tick = sum(old_ticks)/n_old
    new_per_tick = sum(new_ticks)/n_new
    if not isclose(old_per_tick, new_per_tick, rel_tol=1e-6, abs_tol=1e-6):
        return None
    if not isclose(sum(new_ticks)/sum(old_ticks), n_new/n_old,
                   rel_tol=1e-6, abs_tol=1e-6):
        return None
    return {'probe': 'paired_production_periodic_tick_series',
            'checked_ir_actions': checked, 'action_id': original.id,
            'periodic_effect_type': effect_type, 'source_duration_delta_s': float(mod.value),
            'before_tick_count': n_old, 'after_tick_count': n_new,
            'before_tick_amount': round(old_per_tick, 6),
            'after_tick_amount': round(new_per_tick, 6),
            'before_total': round(sum(old_ticks), 6), 'after_total': round(sum(new_ticks), 6)}


def _gcd_runtime_witness(before, after, mod):
    """Validate all target ranks, then observe real runtime GCD readiness.

    An isolated action change avoids another talent modifier manufacturing the
    witness. No talent, class or spell identities are encoded in the checker.
    """
    if mod.target_type != 'action_family' or not float(mod.value):
        return None
    earlier={a.id:a for a in before.actions}
    matching=[a for a in after.actions if a.family_key==mod.target_id]
    if not matching:
        return None
    checked=[]
    candidate=None
    for action in matching:
        prior=earlier.get(action.id)
        if prior is None or prior.family_key != action.family_key:
            return None
        delta=float(action.gcd_s)-float(prior.gcd_s)
        # Every IR rank, not just the first, must carry the sourced difference.
        if (not isclose(delta,float(mod.value),abs_tol=1e-7,rel_tol=1e-6)
                or not (0 <= action.gcd_s < prior.gcd_s if mod.value<0
                        else action.gcd_s>prior.gcd_s)):
            return None
        checked.append(action.id)
        if candidate is None and not prior.metadata.get('ignores_global_cooldown'):
            candidate=(prior,replace(prior,gcd_s=action.gcd_s))
    if candidate is None:
        return None
    old_action,new_action=candidate
    old_run=_action_runtime_probe(before,old_action)
    new_run=_action_runtime_probe(before,new_action)
    if old_run is None or new_run is None:
        return None
    observed=new_run['gcd_ready_s']-old_run['gcd_ready_s']
    if (not isclose(observed,float(mod.value),abs_tol=1e-6,rel_tol=1e-6)
            or not isclose(old_run['completion_s'],new_run['completion_s'],abs_tol=1e-7)):
        return None
    return {'probe':'paired_production_gcd_readiness',
            'checked_ir_actions':checked, 'action_id':old_action.id,
            'source_gcd_delta_s':float(mod.value),
            'before_gcd_ready_s':old_run['gcd_ready_s'],
            'after_gcd_ready_s':new_run['gcd_ready_s']}


def _control_proc_runtime_witness(before, after, mod):
    """Prove sourced control-proc rank deltas with actual CombatRuntime rolls.

    Keep the baseline action's other effects, cast time and actor state fixed.
    Only replace the proc chance. This avoids a simultaneous cast-time talent
    modifier changing the event timestamp (and hence its deterministic roll).
    A mere appended ControlEffect or lucky unrelated stun is not a witness.
    """
    from src.game.model.ir import ControlEffect

    if mod.kind != 'action_control_proc':
        return None
    source=mod.provenance
    control_id=str(source.get('control_id') or '')
    if not control_id:
        return None
    try:
        duration=float(source['duration_s'])
        delta=float(mod.value)
    except (KeyError, TypeError, ValueError):
        return None
    if not 0. < delta <= 1. or not 0. < duration <= 60.:
        return None
    flags=('prevents_enemy_actions','breaks_on_damage')
    if any(type(source.get(flag)) is not bool for flag in flags):
        return None

    previous={a.id:a for a in before.actions}
    checked=[]
    sample=None
    for action in after.actions:
        old=previous.get(action.id)
        if old is None or not any(
                isinstance(p,Mapping) and p.get('stage')=='talent_modifier'
                and p.get('kind')=='action_control_proc'
                for p in action.provenance):
            continue
        newer=[(i,e) for i,e in enumerate(action.effects)
               if isinstance(e,ControlEffect) and e.control_id==control_id]
        older=[(i,e) for i,e in enumerate(old.effects)
               if isinstance(e,ControlEffect) and e.control_id==control_id]
        if not newer:
            continue
        if len(newer)!=1 or len(older)>1:
            return None
        index,new_effect=newer[0]
        old_effect=older[0][1] if older else None
        old_chance=float(old_effect.proc_chance) if old_effect else 0.
        if isclose(float(new_effect.proc_chance),old_chance,abs_tol=1e-10):
            continue
        if (not isclose(float(new_effect.proc_chance)-old_chance,delta,
                        rel_tol=1e-6,abs_tol=1e-8)
                or not isclose(float(new_effect.duration_s),duration,abs_tol=1e-8)
                or any(getattr(new_effect,flag)!=source[flag] for flag in flags)
                or (old_effect is not None and
                    (not isclose(float(old_effect.duration_s),duration,abs_tol=1e-8)
                     or any(getattr(old_effect,flag)!=source[flag] for flag in flags)))):
            return None
        isolated=list(old.effects)
        if old_effect is None:
            if index!=len(isolated):
                return None
            isolated.append(new_effect)
        else:
            if index!=older[0][0]:
                return None
            isolated[index]=new_effect
        checked.append(action.id)
        if sample is None:
            sample=(old,replace(old,effects=tuple(isolated)),
                    old_chance,float(new_effect.proc_chance))
    if not checked or sample is None:
        return None

    baseline,with_proc,old_chance,new_chance=sample
    # Vary only target identity, a legitimate source-independent encounter
    # parameter used by the production event-keyed RNG. Do not force a proc
    # chance to 100%, synthesize a ControlApplied event, or accept a non-proc.
    for seed in range(1,257):
        target_id=f'p2_proc_target_{seed}'
        x=_action_runtime_probe(before,baseline,observe_controls=True,
                                target_id=target_id)
        y=_action_runtime_probe(before,with_proc,observe_controls=True,
                                target_id=target_id)
        if x is None or y is None:
            return None
        old_events=[e for e in x['controls'] if e['control_id']==control_id]
        new_events=[e for e in y['controls'] if e['control_id']==control_id]
        if len(new_events)!=1 or len(old_events)>1:
            return None
        event=new_events[0]
        if (not isclose(event['proc_chance'],new_chance,abs_tol=1e-8)
                or not isclose(event['duration_s'],duration,abs_tol=1e-8)
                or any(event[flag]!=source[flag] for flag in flags)):
            return None
        if old_events:
            old_event=old_events[0]
            if (not isclose(old_event['proc_chance'],old_chance,abs_tol=1e-8)
                    or old_event['proc_roll']!=event['proc_roll']):
                return None
        if (event['proc_triggered'] and event['applied']
                and not any(e['applied'] for e in old_events)
                and y['active_controls'].get(control_id,0.)>y['completion_s']
                and x['active_controls'].get(control_id,0.)<=x['completion_s']):
            return {'probe':'paired_production_control_proc',
                    'action_id':baseline.id,'control_id':control_id,
                    'checked_ir_actions':checked,
                    'before_chance':old_chance,'after_chance':new_chance,
                    'duration_s':duration,'target_id':target_id,
                    'proc_roll':event['proc_roll'],
                    'runtime_control_applied':True}
    return None


def _sourced_granted_action_behavior(before, after, mod):
    """Execute an exact source-granted action, including each supported effect.

    The action must be absent before the talent, sourced from the same parent
    spell and actually change combat state. A cast counter or action registration
    alone cannot satisfy P2; unrecognized effect families remain FAIL.
    """
    if mod.target_type != 'source_action':
        return None
    parent = str(mod.target_id)
    level = after.actor.metadata.get('level')
    if type(level) is not int:
        return None
    candidates = []
    for fact in after.source_facts:
        if not isinstance(fact, dict) or fact.get('family') != 'talent_granted_action_facts':
            continue
        for row in fact.get('actions', ()):
            if (not isinstance(row, dict)
                    or str(row.get('grant_parent_spell_id', row.get('spell_id'))) != parent
                    or type(row.get('required_level')) is not int
                    or row['required_level'] > level):
                continue
            candidates.append(row)
    if not candidates:
        return None
    highest = max(row['required_level'] for row in candidates)
    best = [row for row in candidates if row['required_level'] == highest]
    if len(best) != 1:
        return None
    row = best[0]
    action_id = str(row['family_key']) + ':' + str(row['spell_id'])
    if any(a.id == action_id for a in before.actions):
        return None
    action = next((a for a in after.actions if a.id == action_id), None)
    if action is None or not action.effects:
        return None
    observed = _action_runtime_probe(after, action, observe_periodic=True,
                                     observe_controls=True)
    if observed is None:
        return None
    verified = {
        'direct_damage': observed['direct_damage'] > 0,
        'periodic_damage': observed['periodic_damage'] > 0,
        'direct_heal': observed['direct_heal'] > 0,
        'periodic_heal': observed['periodic_heal'] > 0,
        'target_stat_debuff': any(float(value[1]) != 0
            for value in observed['target_stat_modifiers_on_apply'].values()),
        'control': any(x.get('applied') is True for x in observed['controls']),
    }
    effect_types = [effect.effect_type for effect in action.effects]
    if not all(verified.get(kind, False) for kind in effect_types):
        return None
    return {'probe': 'production_talent_granted_action',
            'action_id': action_id, 'effect_types': effect_types,
            'observed': observed}


def _excess_defense_runtime_witness(before, after, mod):
    """Exercise sourced above-threshold armor in real ActorState form changes.

    At ordinary base defense the conditional term can legitimately be zero.
    Compare the *change in rank effect* between defense at the sourced floor
    and defense above it. This removes any unrelated per-level armor bonus
    from the same talent, without inventing a defense/armor game coefficient.
    """
    from src.game.runtime import ActorState
    if mod.target_type != 'mode':
        return None
    mode_id=str(mod.target_id)
    if mode_id not in {m.id for m in before.modes} & {m.id for m in after.modes}:
        return None
    try:
        multiplier=float(mod.provenance['reference_level_multiplier'])
        amount=float(mod.value)
        initial=ActorState.from_ir(before.actor,before.resources,before.modes)
        level=float(initial.metadata['level'])
        if not all(isfinite(x) for x in (multiplier,amount,level)):
            return None
        if multiplier < 0 or level <= 0 or amount == 0:
            return None
        floor=level*multiplier
        # Controlled test input only: the *rule* and threshold are sourced.
        excess=max(10.0,level/3.0)

        def armor(ir, defense):
            actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
            actor.stats['defense']=defense
            actor.transition_mode(mode_id)
            return float(actor.stats.get('armor',0.0))

        low_before=armor(before,floor)
        low_after=armor(after,floor)
        high_before=armor(before,floor+excess)
        high_after=armor(after,floor+excess)
    except (ValueError,TypeError,KeyError,AttributeError):
        return None
    observed=(high_after-high_before)-(low_after-low_before)
    expected=excess*amount
    if (not isfinite(observed) or not isclose(observed,expected,
            rel_tol=1e-6,abs_tol=1e-6) or observed*expected<=0):
        return None
    return {'probe':'paired_production_mode_defense_threshold',
            'mode_id':mode_id,'source_defense_floor':floor,
            'test_defense_above_floor':floor+excess,
            'at_floor_rank_armor_delta':low_after-low_before,
            'above_floor_rank_armor_delta':high_after-high_before,
            'observed_excess_rank_armor_delta':observed,
            'expected_excess_rank_armor_delta':expected}



def _cast_pushback_runtime_witness(before, after, mod):
    """Run the source-scoped rank delta through real CombatRuntime cast delays.

    A separately sourced incoming pushback is a paired controlled fixture,
    not a new Forever player/target rule. The chosen cast is an actual sourced
    GameIR action; only unrelated resource/mode prerequisites are isolated.
    """
    from src.game.model.ir import (
        ActorDefinition, ResourceDefinition, IncomingAttackDefinition,
        DamageEffect, PeriodicEffect)
    from src.game.runtime import ActorState, CombatRuntime, TargetState

    if (mod.kind != 'cast_pushback_avoidance_chance'
            or mod.target_type != 'action_filter'
            or not str(mod.target_id).startswith('damage_schools:')):
        return None
    schools = set(str(mod.target_id).split(':', 1)[1].split(','))
    if not schools or '' in schools or not 0. < float(mod.value) <= 1.:
        return None
    previous = {action.id: action for action in before.actions}
    eligible = []
    for action in after.actions:
        old = previous.get(action.id)
        if old is None:
            continue
        scoped = (float(action.cast_time_s) > 0.
                  and any(isinstance(effect, (DamageEffect, PeriodicEffect))
                          and effect.school.lower() in schools
                          for effect in action.effects))
        prior = float(old.metadata.get('cast_pushback_avoidance_chance', 0.))
        current = float(action.metadata.get('cast_pushback_avoidance_chance', 0.))
        if scoped:
            if not isclose(current - prior, float(mod.value),
                           rel_tol=1e-6, abs_tol=1e-8):
                return None
            if float(action.cast_time_s) > 0.75:
                eligible.append((old, action))
        elif not isclose(prior, current, abs_tol=1e-8):
            return None
    if not eligible:
        return None

    def cast_under_attack(action, *, pushback):
        # Match the actual source action owner so the native production
        # action is eligible in this isolated cast-delay fixture.
        player = str(action.owner_actor_id)
        state = ActorState.from_ir(
            ActorDefinition(player, 'player', base_stats={}),
            (ResourceDefinition('health', 'Health', player,
                                initial_amount=500., capacity=500.),), ())
        runtime = CombatRuntime(
            actor=state, target=TargetState.with_health('p2_target', 100000.))
        # This is the source-built action with costs/mode requirements isolated,
        # not a substitute action or an alternate combat implementation.
        isolated = replace(action, costs=(), requirements=())
        runtime.enqueue_action(isolated)
        at_time = min(.5, float(action.cast_time_s) / 3.)
        runtime.advance_to(at_time)
        attack = IncomingAttackDefinition(
            'p2_pushback_hit', 'Controlled incoming hit', 'p2_target',
            player, 'physical', 10., 1., 'health',
            metadata={'representative_swing_s': 2.,
                      'cast_pushback_on_hit_s': float(pushback),
                      'cast_pushback_source_url':
                      'https://warcraft.wiki.gg/wiki/Pushback'},
            provenance=({'fixture': 'paired_sourced_cast_pushback'},))
        runtime.resolve_incoming_attack(attack, at_time_s=at_time)
        runtime.run_until_idle()
        events = runtime.result().events
        completed = [e.time_s for e in events
                     if e.kind == 'ActionCompleted' and e.action_id == action.id]
        delays = [float(e.payload['delay_s']) for e in events
                  if e.kind == 'CastPushbackApplied' and e.action_id == action.id]
        if len(completed) != 1:
            return None
        return (float(completed[0]), sum(delays))

    for old, action in eligible:
        try:
            base = cast_under_attack(old, pushback=.5)
            boosted = cast_under_attack(action, pushback=.5)
            no_hit_base = cast_under_attack(old, pushback=0.)
            no_hit_boosted = cast_under_attack(action, pushback=0.)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        if any(x is None for x in (base, boosted, no_hit_base, no_hit_boosted)):
            continue
        expected = .5 * float(mod.value)
        if (base[1] > boosted[1] and
                isclose(base[1] - boosted[1], expected, abs_tol=1e-6) and
                isclose(base[0] - boosted[0], expected, abs_tol=1e-6) and
                isclose(no_hit_base[0], no_hit_boosted[0], abs_tol=1e-6) and
                isclose(no_hit_base[1], 0., abs_tol=1e-8) and
                isclose(no_hit_boosted[1], 0., abs_tol=1e-8)):
            return {'probe': 'paired_production_cast_pushback',
                    'action_id': action.id, 'source_scoped_actions_checked':
                    len(eligible), 'rank_delta': float(mod.value),
                    'before_delay_s': base[1], 'after_delay_s': boosted[1],
                    'without_pushback_completion_s': no_hit_base[0]}
    return None


def _critical_resource_gain_runtime_witness(before, after, mod):
    """Observe a source-ranked critical resource proc in real CombatRuntime.

    The sourced proc probability is checked on the compiled rule. The paired
    witness then requires an actual *sampled* extra resource award on the
    selected mode/trigger, plus a no-crit negative control. A rule merely
    appearing in GameIR cannot pass P2.
    """
    from src.game.model.ir import ResourceChangeEffect
    from src.game.runtime import ActorState, CombatRuntime, TargetState
    from src.game.runtime.simulator import action_eligibility

    source = mod.provenance
    resource_id = str(mod.target_id)
    mode = source.get('required_mode_id')
    generator = source.get('requires_resource_generator')
    amount = source.get('bonus_resource_amount')
    if (mod.kind != 'critical_resource_gain' or mod.target_type != 'resource'
            or not isinstance(mode, str) or not mode
            or type(generator) is not bool or type(amount) not in (int, float)
            or not isfinite(amount) or amount <= 0
            or not 0 < float(mod.value) <= 1):
        return None

    def source_rule(ir):
        matches = [(definition, rule)
            for definition in ir.resources if definition.id == resource_id
            for rule in definition.event_gain_rules
            if rule.id.startswith('source_critical_gain:')
            and rule.event_kind == 'nonperiodic_melee_critical'
            and rule.required_mode_id == mode
            and rule.metadata.get('resolution') == 'sampled_joint_critical'
            and bool(rule.filters.get('required_generated_resource')) == generator]
        return matches[0] if len(matches) == 1 else None

    latest = source_rule(after)
    earlier = source_rule(before)
    if latest is None or (earlier is not None
                          and earlier[1].id != latest[1].id):
        return None
    definition, rule = latest
    old_probability = (float(earlier[1].metadata['proc_probability'])
                       if earlier is not None else 0.)
    new_probability = float(rule.metadata.get('proc_probability', -1))
    if (not isclose(new_probability - old_probability, float(mod.value),
                    abs_tol=1e-8, rel_tol=1e-7)
            or not isclose(float(rule.multiplier), float(amount), abs_tol=1e-8)
            or definition.scope not in ('actor', 'target')):
        return None

    def execute(ir, *, crit, seed):
        actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
        try:
            actor.transition_mode(mode)
        except (ValueError, KeyError, AttributeError):
            return None
        actor.stats['melee_crit_chance'] = crit
        target = TargetState.with_health('enemy', 1000000.)
        if generator:
            # Discover a real sourced resource-generating melee action, not a
            # class-specific Claw name or a synthetic trigger event.
            actions = [a for a in ir.actions
                if any(isinstance(e, ResourceChangeEffect)
                       and e.resource_id == resource_id and e.target in ('target', 'enemy')
                       and e.operation == 'add' and e.amount > 0
                       for e in a.effects)]
            for action in actions:
                for cost in action.costs:
                    if cost.resource_id in actor.resources:
                        actor.resources[cost.resource_id] = float(
                            actor.resource_capacity[cost.resource_id])
                if action_eligibility(action=action, actor=actor,
                                      target=target).eligible:
                    break
            else:
                return None
            rt = CombatRuntime(actor=actor, target=target, sampling_seed=seed)
            try:
                end = rt.schedule_action(action)
                rt.advance_to(end + .02)
            except (ValueError, KeyError, RuntimeError, TypeError):
                return None
        else:
            if resource_id not in actor.resources or not ir.auto_attacks:
                return None
            actor.resources[resource_id] = min(
                50., float(actor.resource_capacity[resource_id]) / 2.)
            rt = CombatRuntime(actor=actor, target=target,
                               auto_attacks=ir.auto_attacks, sampling_seed=seed)
            try:
                rt.advance_to(4.)
            except (ValueError, KeyError, RuntimeError, TypeError):
                return None
        events = [e for e in rt.trace if e.kind == 'ResourceEventGain'
                  and e.payload.get('rule_id') == rule.id
                  and e.payload.get('resource_id') == resource_id
                  and e.payload.get('event_kind') == 'nonperiodic_melee_critical'
                  and e.payload.get('event_value') == 1.
                  and float(e.payload.get('gained', 0.)) > 0.]
        return {'gain': sum(float(e.payload['gained']) for e in events),
                'events': len(events)}

    # The event-keyed production RNG is deterministic for a fixed scenario.
    # Probe genuine encounter seeds to witness a 0.5 -> 1.0 chance increment;
    # never force the proc or manufacture a ResourceEventGain.
    for seed in range(1, 65):
        old = execute(before, crit=1., seed=seed)
        new = execute(after, crit=1., seed=seed)
        if old is None or new is None:
            return None
        if new['gain'] <= old['gain'] + 1e-8 or new['events'] == 0:
            continue
        old_zero = execute(before, crit=0., seed=seed)
        new_zero = execute(after, crit=0., seed=seed)
        if (old_zero is None or new_zero is None
                or old_zero['gain'] != 0. or new_zero['gain'] != 0.):
            return None
        return {'probe': 'paired_production_critical_resource_gain',
                'resource_id': resource_id, 'mode_id': mode,
                'source_probability_increment': float(mod.value),
                'before_probability': old_probability,
                'after_probability': new_probability,
                'before_gain': old['gain'], 'after_gain': new['gain'],
                'no_crit_control_gain': new_zero['gain'],
                'sampling_seed': seed}
    return None


def _behavior_fixtures(before, after, modifiers):
    """Require an observed L2 effect for *each* rank modifier, not just one.

    A source delta in the IR is only compilation evidence; the probes below
    construct actual runtime actors or execute abilities in CombatRuntime.
    Unknown/conditional families get explicit TEST_MISSING rather than PASS.
    """
    actor_kinds={'actor_stat_pct','actor_stat_flat','mode_stat_pct','mode_stat_flat',
                 'mode_derived_stat_pct','mode_resource_capacity_pct',
                 'mode_move_speed_pct','mode_armor_per_level'}
    action_kinds={'cast_time_delta_s','resource_cost_flat','resource_cost_pct'}
    changes=_runtime_actor_state_delta(before,after) if any(
        m.kind in actor_kinds for m in modifiers) else []
    old_actions={a.id:a for a in before.actions}
    runtime_action_cache={}
    tests=[];missing=[]
    for index,mod in enumerate(modifiers):
        kind=mod.kind; target=str(mod.target_id)
        match=None
        if kind in actor_kinds:
            if mod.target_type=='actor_stat':
                relevant=[x for x in changes if x['field']=='stats' and x['stat']==target]
            elif mod.target_type=='mode':
                relevant=[x for x in changes if x['mode']==target and
                    (x['field']=='resource_capacity' if kind=='mode_resource_capacity_pct'
                     else x['field']=='stats')]
            else:relevant=[]
            # An unrelated stat changed by the same talent must NOT certify
            # this modifier. Target and direction (and for direct flat/% actor
            # stats the numeric sourced delta) have to match.
            expected_stat=(target if mod.target_type=='actor_stat' else str(
                mod.provenance.get('target_stat') or mod.provenance.get('target_id') or
                mod.provenance.get('source_stat') or ('armor' if kind=='mode_armor_per_level' else 'movement_speed_pct')))
            expected_resource=str(mod.provenance.get('target_id') or '')
            relevant=[x for x in relevant if x['stat']==(
                expected_resource if kind=='mode_resource_capacity_pct' else expected_stat)]
            verified=[]
            for delta in relevant:
                change=delta['after']-delta['before']
                if not change or change*float(mod.value)<=0:continue
                if kind=='actor_stat_flat' and not isclose(change,float(mod.value),abs_tol=1e-7,rel_tol=1e-6):continue
                if kind=='actor_stat_pct':
                    # Increment observed effect can coexist with previous
                    # cumulative multiplier; direction/target matter more than
                    # an assumed unboosted base that the runtime has not exposed.
                    pass
                if kind=='mode_stat_flat' and not isclose(change,float(mod.value),abs_tol=1e-7,rel_tol=1e-6):continue
                verified.append(delta)
            if verified:
                match={'probe':'production_actor_state_from_ir',
                    'observable_changes':verified[:6]}
        elif kind == 'mode_armor_excess_defense':
            match=_excess_defense_runtime_witness(before,after,mod)
        elif kind in ('effect_damage_pct','effect_healing_pct','effect_periodic_pct'):
            match=_runtime_effect_witness(before,after,mod)
        elif kind == 'periodic_duration_delta_s':
            match=_periodic_duration_witness(before,after,mod)
        elif kind == 'gcd_delta_s':
            match=_gcd_runtime_witness(before,after,mod)
        elif kind in ('mode_entry_expected_gain','mode_entry_restore_last'):
            match=_mode_entry_resource_witness(before,after,mod)
        elif kind=='crit_chance_pct':
            match=_isolated_crit_witness(before,after,mod)
        elif kind=='hit_chance_bonus':
            match=_sourced_hit_runtime_witness(before,after,mod)
        elif kind=='cast_pushback_avoidance_chance':
            match=_cast_pushback_runtime_witness(before,after,mod)
        elif kind=='critical_damage_bonus_pct':
            match=_critical_damage_runtime_witness(before,after,mod)
        elif kind=='action_control_proc':
            match=_control_proc_runtime_witness(before,after,mod)
        elif kind=='critical_resource_gain':
            match=_critical_resource_gain_runtime_witness(before,after,mod)
        elif kind=='grant_source_action':
            match=_sourced_granted_action_behavior(before,after,mod)
        elif kind in ('resource_cost_flat','resource_cost_pct'):
            match=_isolated_resource_cost_witness(before,after,mod)
        elif kind in action_kinds:
            for action in after.actions:
                older=old_actions.get(action.id)
                if (older is None or older==action or action.family_key!=target):continue
                if kind=='cast_time_delta_s' and action.cast_time_s==older.cast_time_s:continue
                if kind.startswith('resource_cost_') and action.costs==older.costs:continue
                if action.id not in runtime_action_cache:
                    runtime_action_cache[action.id]=(
                        _action_runtime_probe(before,older),_action_runtime_probe(after,action))
                x,y=runtime_action_cache[action.id]
                if x is None or y is None:continue
                difference=(y['completion_s']-x['completion_s'] if kind=='cast_time_delta_s'
                    else sum(y['spent'].values())-sum(x['spent'].values()))
                # For action-family modifiers, applying a positive bonus must
                # not accidentally certify a reduction in the wrong direction.
                # An exact sourced-value assertion is possible for cast-time
                # deltas and resource_cost_flat, but percentage cost can be
                # affected by existing reductions and rounding.
                expected=(float(mod.value) if kind!='resource_cost_pct' else
                    sum(x['spent'].values())*float(mod.value))
                if (difference*expected>0 and
                    (kind=='resource_cost_pct' or isclose(
                        difference,expected,rel_tol=1e-5,abs_tol=1e-5))):
                    match={'probe':'production_combat_runtime_action',
                           'action_id':action.id,'before':x,'after':y}
                    break
        if match:
            tests.append({'modifier_index':index,'kind':kind,'target':target,
                'actually_executed':True,'passed':True,**match})
        else:missing.append(f'{index}:{kind}:{target}')
    return tests,missing


def _full_point_unlock_witness(compiled, talent, rank, witness, *, level, bonus):
    """Reuse a proven legal full-point allocation before constructing another.

    A spec frontier has already verified this exact full-point candidate with
    the canonical talent validator. Rebuilding it with the unrestricted greedy
    allocator can fail spuriously or silently leave the requested spec.
    Unrestricted partial-rank probes still need the generic full-point builder.
    """
    points = available_talent_points(level, bonus_talent_points=bonus)
    if witness.get(talent.id) == rank and sum(witness.values()) == points:
        return dict(witness)
    from src.v2.source_bounded_joint_frontier import _source_unlock_full_point_allocation
    return _source_unlock_full_point_allocation(
        compiled, talent, level=level, bonus_talent_points=bonus,
        target_rank=rank)


def _rank_probe(compiled, talent, rank, witness, *, level, bonus,
                profile_tree=None):
    """Legal rank + actual applied runtime behavior, with honest unsupported cases."""
    key=f'{talent.id}:{rank}'
    result={'rank_key':key,'talent_id':talent.id,'rank':rank,
            'witness':dict(witness),'control_witness':None,
            'status':'FAIL','reasons':[],
            'behavior_tests':[], 'search_reachable':False}
    r=next((x for x in talent.ranks if x.rank==rank),None)
    if r is None:
        result['reasons'].append('IMPLEMENTATION_MISSING')
        return result
    exclusion = solo_threat_exclusion(compiled, r) if not r.modifiers else None
    if not r.modifiers and exclusion is None:
        result['reasons'].append('IMPLEMENTATION_MISSING')
        return result
    # Prefer the canonical source witness; when filler ranks cannot execute,
    # retry the *generic* executable-filler witness before blaming the target.
    # Preserve the optimizer's verified full-point profile witness for
    # search/unlock reachability. An isolated rank N versus N-1 behavioral
    # control may need fewer points: removing a prerequisite from a complete
    # 51-point build can invalidate unrelated higher-tier talents.
    profile_full = dict(witness) if profile_tree is not None else None
    attempts=[dict(witness)]
    if profile_full is not None:
        step=int((compiled.provenance.get('talent_tree_rules') or {}).get('points_per_row') or 5)
        isolated=_witness(talent,rank,compiled.talents,
            available_talent_points(level,bonus_talent_points=bonus),step)
        if isolated is not None and isolated!=witness:
            try:
                validate_talent_selection(compiled,isolated,level=level,
                                          bonus_talent_points=bonus)
            except (ValueError,TypeError,KeyError):
                pass
            else:
                attempts.insert(0,dict(isolated))
    # A legal full-point optimizer build can rely on the target rank's last
    # point to unlock an unrelated higher-tier talent. Decrementing the target
    # alone then makes the paired control illegal (e.g. a 15-point tier floor
    # becomes 14). P2 compares the target's behavior in a *legal* paired
    # setup, not necessarily in a full-point search build. Try dropping one
    # other talent from BOTH sides; apply_talent_selection below validates
    # each side independently. Keep the original full-point profile candidate
    # as the separate, already validated search-reachability witness.
    if profile_full is not None:
        for other_id in sorted(profile_full):
            if other_id == talent.id:
                continue
            reduced = dict(profile_full)
            reduced.pop(other_id)
            if reduced not in attempts:
                attempts.append(reduced)
    # An unrestricted rank probe can use a different executable filler.
    # The spec's full-point search candidate must never be replaced by it.
    if profile_tree is None:
        alt=_executable_filler_witness(talent,rank,compiled.talents,
            points=available_talent_points(level,bonus_talent_points=bonus),
            step=int((compiled.provenance.get('talent_tree_rules') or {}).get('points_per_row') or 5))
        if alt is not None and alt!=witness:attempts.append(alt)
    last_error=None
    for trial in attempts:
        try:
            selected,receipt=apply_talent_selection(compiled,trial,
                                        level=level,bonus_talent_points=bonus)
            applied=[x for x in receipt.applied_modifiers
                     if x.get('talent_id')==talent.id and int(x.get('rank',-1))==rank]
            if not applied and exclusion is None:
                last_error='TARGET_RANK_NOT_APPLIED'
                continue
            prior=dict(trial)
            if rank==1:prior.pop(talent.id,None)
            else:prior[talent.id]=rank-1
            before,_=apply_talent_selection(compiled,prior,level=level,
                                            bonus_talent_points=bonus)
            witness=trial
            result['witness']=dict(witness)
            result['control_witness']=dict(prior)
            break
        except (ValueError,TypeError) as exc:
            last_error=str(exc)
    else:
        result['reasons'].append('ALLOCATION_INVALID:'+str(last_error))
        return result
    if exclusion is not None:
        # No effect probe is claimed. The source-only threat clause is checked
        # against the actual single-actor solo IR; legal rank and search checks
        # below still run. Group/pet scenarios remain FAIL, not silent no-ops.
        result['objective_exclusion'] = exclusion
    elif not _effect_change(before,selected):
        result['reasons'].append('IMPLEMENTATION_MISSING:NO_GAME_IR_DELTA')
        return result
    # Every modifier's applicable effect family needs an executed behavior
    # fixture. One actor-stat change cannot certify a second, unrelated proc.
    # Talent rank descriptors normally contain cumulative rank-1..N values.
    # Runtime tests compare rank N against rank N-1, so compare incremental
    # values rather than incorrectly demanding the full rank-N value again.
    prior_rank=next((x for x in talent.ranks if x.rank==rank-1),None)
    increments=[]
    for i, mod in enumerate(r.modifiers):
        previous=(prior_rank.modifiers[i] if prior_rank and i<len(prior_rank.modifiers)
            else None)
        aligned=(previous is not None and (previous.kind,previous.target_type,previous.target_id)==
            (mod.kind,mod.target_type,mod.target_id))
        prior_value=float(previous.value) if aligned else 0.0
        meta=dict(mod.provenance)
        if mod.kind in ('effect_damage_pct','effect_healing_pct','effect_periodic_pct') and (1+prior_value)>0:
            meta['_gate_relative_factor']=(1+float(mod.value))/(1+prior_value)
        if mod.kind=='resource_cost_pct' and (1+prior_value)>0:
            meta['_gate_cost_ratio']=(1+float(mod.value))/(1+prior_value)
        if mod.kind=='critical_damage_bonus_pct' and (1+prior_value)>0:
            meta['_gate_crit_bonus_ratio']=(1+float(mod.value))/(1+prior_value)
        increments.append(replace(mod,value=float(mod.value)-prior_value,provenance=meta))
    if exclusion is None:
        tests,missing=_behavior_fixtures(before,selected,increments)
        result['behavior_tests'].extend(tests)
        if missing:
            result['reasons'].append('BEHAVIOR_TEST_MISSING:'+','.join(missing))
    # The sourced tooltip contains *two* independent effects: hit chance and
    # increased offensive range.  Proving hit alone must never turn this rank
    # GREEN while its real travel/pull-distance behavior is explicitly absent.
    if any(m.provenance.get('range_status') ==
           'travel_and_pull_distance_not_yet_modeled' for m in increments):
        result['reasons'].append(
            'IMPLEMENTATION_MISSING:source_offensive_range_world_behavior')
    # Ask the ACTUAL generic optimizer's legal-neighbor generator whether
    # it can propose this exact rank-up. A compiler's acceptance is not proof
    # the optimizer can ever reach the rank. The witness may be a partial
    # allocation: a legal P2 candidate does not need to spend every point.
    if profile_full is not None:
        # This exact complete allocation came from the real optimizer's
        # source_spec_talent_frontier and passed canonical validation in
        # _source_spec_profile. A one-point predecessor need not itself
        # satisfy the profile's minimum-tree-points constraint.
        result['search_witness']=profile_full
        result['search_reachable']=True
    else:
        try:
            frontier=source_legal_talent_neighbors(compiled,prior,level=level,
                                                   bonus_talent_points=bonus)
            offered={n.allocation for n in frontier['neighbors']}
            if allocation_key(witness) not in offered:
                result['reasons'].append('SEARCH_RANK_NOT_GENERATED')
            else:
                result['search_reachable']=True
        except (ValueError,KeyError,TypeError) as exc:
            result['reasons'].append('SEARCH_RANK_GENERATION_FAILED:'+str(exc))
    # Full-point winner preparation and sourced action families are separate
    # from the rank-up reachability test above.
    unlocked={m.target_id for m in r.modifiers if m.kind=='unlock_action_family'}
    granted=any(m.kind.startswith('grant_source_') for m in r.modifiers)
    if unlocked or granted:
        full=(profile_full if profile_full is not None else
              _full_point_unlock_witness(compiled,talent,rank,witness,
                                         level=level,bonus=bonus))
        if full is None:
            result['reasons'].append('SEARCH_ACTION_MISSING:FULL_POINT_WITNESS')
        else:
            try:
                generated,_=apply_talent_selection(compiled,full,level=level,
                                                   bonus_talent_points=bonus)
                families={a.family_key for a in generated.actions}
                missing=sorted(unlocked-families)
                if missing:
                    result['reasons'].append('SEARCH_ACTION_MISSING:'+','.join(missing))
                else:
                    # Rank-up reachability was established above.
                    pass
            except (ValueError,TypeError) as exc:
                result['reasons'].append('SEARCH_ACTION_MISSING:'+str(exc))
    result['status']='PASS' if not result['reasons'] else 'FAIL'
    return result
