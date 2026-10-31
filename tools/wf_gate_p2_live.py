#!/usr/bin/env python3
"""Class-neutral, live P2 acceptance checks on production GameIR.

No historical semantic-certification labels, dummy rank approvals, or fake L2
behavior coverage. Checks actual talent legality/application and only awards a
behavior PASS where an observable production runtime fixture was executed.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from math import isclose
from hashlib import sha256
import json
from pathlib import Path
from dataclasses import replace
import sqlite3

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint, _witness, check_structural_allocation
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.data.forever.checkpoint_p2_execution_gate import _executable_filler_witness
from src.game.talents import apply_talent_selection, talented_bonus_for_level, available_talent_points, validate_talent_selection
from src.game.talent_frontier import source_legal_talent_neighbors, allocation_key


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


def _action_runtime_probe(ir, action, *, observe_periodic=False):
    """Execute real action on a live actor/target; deterministic fixture.

    Only differences that are actually observed in runtime count. No event
    count / ActionStarted shortcut. If not eligible, return no probe.
    """
    from src.game.runtime import ActorState, CombatRuntime, TargetState
    from src.game.runtime.simulator import action_eligibility
    # Check the *actual* runtime eligibility in each source mode. A caster mode
    # with an unrestricted enabled_action_ids list does not necessarily permit
    # a Bear-only action (e.g. Swipe). No class-specific mode names here.
    actor=None
    for mode in [None, *(m.id for m in ir.modes)]:
        candidate=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
        if mode is not None and candidate.current_mode_id!=mode:
            try:candidate.transition_mode(mode)
            except (ValueError,KeyError,AttributeError):continue
        target=TargetState.with_health('p2_fixture',100000.0,armor=0.0)
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
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('p2_fixture',100000.0, armor=0.0))
    if not action_eligibility(action=action,actor=actor,target=rt.target).eligible:return None
    before=dict(actor.resources)
    try:
        end=rt.schedule_action(action)
        rt.advance_to(end + 0.01)
        if observe_periodic:
            # Observe the actual tick series, not just the aura application.
            duration=max((float(e.duration_s) for e in action.effects if hasattr(e,'tick_interval_s')),default=0.0)
            if duration>0:rt.advance_to(end+duration+0.02)
    except (ValueError,KeyError,RuntimeError,AttributeError,TypeError):return None
    events=[{'kind':e.kind,'amount':float(e.payload.get('amount',0.0)),
             'periodic':bool(e.payload.get('periodic'))}
            for e in rt.trace if e.kind in ('Damage','Heal')]
    return {'completion_s':float(end), 'gcd_ready_s':float(actor.gcd_ready_s),'spent':{
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


def _rank_probe(compiled, talent, rank, witness, *, level, bonus):
    """Legal rank + actual applied runtime behavior, with honest unsupported cases."""
    key=f'{talent.id}:{rank}'
    result={'rank_key':key,'talent_id':talent.id,'rank':rank,
            'witness':dict(witness),'status':'FAIL','reasons':[],
            'behavior_tests':[], 'search_reachable':False}
    r=next((x for x in talent.ranks if x.rank==rank),None)
    if not r or not r.modifiers:
        result['reasons'].append('IMPLEMENTATION_MISSING')
        return result
    # Prefer the canonical source witness; when filler ranks cannot execute,
    # retry the *generic* executable-filler witness before blaming the target.
    attempts=[dict(witness)]
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
            if not applied:
                last_error='TARGET_RANK_NOT_APPLIED'
                continue
            prior=dict(trial)
            if rank==1:prior.pop(talent.id,None)
            else:prior[talent.id]=rank-1
            before,_=apply_talent_selection(compiled,prior,level=level,
                                            bonus_talent_points=bonus)
            witness=trial
            result['witness']=dict(witness)
            break
        except (ValueError,TypeError) as exc:
            last_error=str(exc)
    else:
        result['reasons'].append('ALLOCATION_INVALID:'+str(last_error))
        return result
    if not _effect_change(before,selected):
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
        increments.append(replace(mod,value=float(mod.value)-prior_value,provenance=meta))
    tests,missing=_behavior_fixtures(before,selected,increments)
    result['behavior_tests'].extend(tests)
    if missing:
        result['reasons'].append('BEHAVIOR_TEST_MISSING:'+','.join(missing))
    # Ask the ACTUAL generic optimizer's legal-neighbor generator whether
    # it can propose this exact rank-up. A compiler's acceptance is not proof
    # the optimizer can ever reach the rank. The witness may be a partial
    # allocation: a legal P2 candidate does not need to spend every point.
    from src.game.talents import validate_talent_selection
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
        from src.v2.source_bounded_joint_frontier import _source_unlock_full_point_allocation
        full=_source_unlock_full_point_allocation(compiled,talent,level=level,
                                 bonus_talent_points=bonus,target_rank=rank)
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



def _source_spec_profile(ir, spec: str, *, level: int, bonus: int, step: int,
                         source_sha256=None, frontier_builder=None):
    """Resolve a named profile to SOURCE tree identity and legal full builds.

    A source tree's existence alone does not prove its gameplay *spec* rule.
    Unless the canonical IR provides an independently sourced, build-bound
    profile rule, all results remain diagnostic (not a spec-gate PASS).
    """
    if spec == 'unrestricted':
        return None, {'source_spec_profile_verified': True,
                      'source_spec_tree': None}
    trees={t.tree_key for t in ir.talents}
    if not isinstance(spec,str) or spec not in trees:
        raise ValueError('SPEC_PROFILE_NOT_A_SOURCE_TREE:'+str(spec))
    tier_rows=[int(t.metadata['row']) for t in ir.talents
               if t.tree_key==spec and t.metadata.get('row') is not None]
    if not tier_rows:
        raise ValueError('SPEC_SOURCE_TREE_POSITIONS_MISSING:'+spec)
    points=available_talent_points(level,bonus_talent_points=bonus)
    # Structural candidate only: the deepest sourced tier's unlock floor is
    # NOT itself evidence of a game-defined spec profile or a talent preset.
    tier_floor=max(tier_rows)*step+1
    raw=(ir.provenance.get('source_spec_profile_rules') or {}).get(spec)
    accepted=(isinstance(raw,dict) and raw.get('tree_key')==spec
              and raw.get('class_key')==ir.actor.metadata.get('class_key')
              and raw.get('level')==level
              and isinstance(raw.get('source_url'),str)
              and raw['source_url'].startswith('https://')
              and isinstance(source_sha256,str) and len(source_sha256)==64
              and raw.get('source_db_sha256')==source_sha256
              and raw.get('evidence_status')=='VERIFIED_SOURCE_PROFILE'
              and type(raw.get('minimum_points')) is int
              and tier_floor<=raw['minimum_points']<=points)
    required=raw['minimum_points'] if accepted else tier_floor
    if required>points:
        raise ValueError('SOURCE_SPEC_TREE_UNREACHABLE_AT_LEVEL:'+spec)
    if frontier_builder is None:
        from src.v2.source_bounded_joint_frontier import source_spec_talent_frontier
        frontier_builder = source_spec_talent_frontier
    builds,evidence=frontier_builder(
        ir,(),tree_key=spec,minimum_points=required,level=level,
        bonus_talent_points=bonus,max_frontier=256)
    # Validate even the returned frontier against the *real* source rules.
    definitions={t.id:t for t in ir.talents}
    if not builds:
        raise ValueError('SOURCE_SPEC_FRONTIER_EMPTY')
    for allocation in builds:
        if (not isinstance(allocation, Mapping) or
            any(type(tid) is not str or tid not in definitions
                for tid in allocation) or
            any(type(rank) is not int or rank<=0
                for rank in allocation.values()) or
            sum(allocation.values())!=points or
            sum(rank for tid,rank in allocation.items()
                if definitions[tid].tree_key==spec)<required):
            raise ValueError('SOURCE_SPEC_FRONTIER_ILLEGAL_ALLOCATION')
        # A full point total and a named source tree do NOT establish legal
        # ranks, prerequisites or per-tree tier unlocks. Recheck every returned
        # candidate using the same canonical validator as production search.
        try:
            validate_talent_selection(ir,allocation,level=level,
                                      bonus_talent_points=bonus)
        except (ValueError,TypeError,KeyError) as exc:
            raise ValueError('SOURCE_SPEC_FRONTIER_ILLEGAL_ALLOCATION:'
                             +str(exc)) from exc
    return builds, {
        'source_spec_profile_verified':bool(accepted),
        'source_spec_tree':spec,
        'source_spec_structural_tier_floor':tier_floor,
        'source_spec_required_points':required,
        'source_spec_candidate_count':len(builds),
        'source_spec_candidate_frontier_exhaustive':False,
        'source_spec_profile_authority':(raw['source_url'] if accepted
            else 'UNVERIFIED_SOURCE_TREE_ONLY'),
        'source_spec_frontier_evidence':evidence,
    }


def _source_spec_rank_witness(population, talent_id, rank):
    """Require the *exact* target rank in an executable full-point profile."""
    return next((dict(a) for a in population if a.get(talent_id)==rank),None)


def run_live(root: Path, class_key: str, level: int, *, spec='unrestricted',
             source_db: Path | None=None, bonus_points: int | None=None):
    """One P2 gate execution; fast, class-neutral and fail-closed."""
    result={'class':class_key,'level':level,'spec':spec,'gate':'P2',
            'status':'FAIL','reasons':[],'ranks':[], 'unreachable':[],
            'unresolved':[], 'behavior_probes_executed':0}
    try:
        source_db=Path(source_db or DEFAULT_DB)
        if not source_db.is_file():raise ValueError('CANONICAL_SOURCE_DB_MISSING')
        # Avoid silently using a source database belonging to another class.
        with sqlite3.connect(f'file:{source_db.resolve()}?mode=ro',uri=True) as db:
            if db.execute("SELECT count(*) FROM talent_tree_row_facts WHERE class_key=?",(class_key,)).fetchone()[0]==0:
                raise ValueError('CANONICAL_CLASS_TALENT_ROWS_MISSING')
        ir=build_game_ir_slice(class_key=class_key,level=level,ability_db_path=source_db)
        if ir is None:raise ValueError('CLASS_GAME_IR_NOT_AVAILABLE')
        if ir.actor.metadata.get('class_key')!=class_key or ir.actor.metadata.get('level')!=level:
            raise ValueError('GAME_IR_CHECKPOINT_IDENTITY_MISMATCH')
        compiled,inventory=compile_talent_runtime(ir)
        if not compiled.talents:raise ValueError('NO_SOURCE_TALENTS')
        bonus=talented_bonus_for_level(level) if bonus_points is None else bonus_points
        points=available_talent_points(level,bonus_talent_points=bonus)
        result.update(source_id=sha256(source_db.read_bytes()).hexdigest(),
            engine_id='live_game_ir_compiler_and_runtime',talent_points=points,
            source_talent_count=len(compiled.talents),
            source_rank_total=sum(len(t.ranks) for t in compiled.talents))
        step=int((compiled.provenance.get('talent_tree_rules') or {}).get('points_per_row') or 0)
        if step<=0:raise ValueError('CANONICAL_TALENT_TIER_RULE_MISSING')
        population,profile_info=_source_spec_profile(
            compiled,spec,level=level,bonus=bonus,step=step,
            source_sha256=result['source_id'])
        result.update(profile_info)
        result['rank_probe_scope']=('UNRESTRICTED_SOURCE_RANKS' if population is None
            else 'SOURCE_TREE_FULL_POINT_SPEC_CANDIDATES')
        if not profile_info['source_spec_profile_verified']:
            # Tree names and talent depth do not establish a canonical spec
            # requirement; real rank probes may run but cannot certify P2.
            result['reasons'].append('SPEC_PROFILE_SOURCE_RULE_NOT_VERIFIED')
        checkpoint=P2Checkpoint(class_key,level,profile=spec)
        for talent in compiled.talents:
            row=talent.metadata.get('row')
            for rank in talent.ranks:
                key=f'{talent.id}:{rank.rank}'
                if row is None:
                    result['unresolved'].append({'rank_key':key,'reason':'REACHABILITY_UNRESOLVED:MISSING_TREE_ROW'})
                    continue
                if int(row)*step+int(rank.rank)>points:
                    result['unreachable'].append({'rank_key':key,'reason':'TIER_MINIMUM_EXCEEDS_BUDGET'})
                    continue
                witness=_witness(talent,rank.rank,compiled.talents,points,step)
                if witness is None:
                    result['unresolved'].append({'rank_key':key,'reason':'REACHABILITY_UNRESOLVED:NO_LEGAL_WITNESS'})
                    continue
                if population is not None:
                    witness=_source_spec_rank_witness(population,talent.id,int(rank.rank))
                    if witness is None:
                        # Do not reduce the denominator just because a bounded
                        # spec-constrained search has not found this rank.
                        result['unresolved'].append({
                            'rank_key':key,
                            'reason':'SPEC_PROFILE_EXACT_RANK_FULL_POINT_WITNESS_NOT_FOUND'})
                        continue
                try:
                    check_structural_allocation(compiled,witness,checkpoint,
                                               bonus_talent_points=bonus)
                except ValueError as exc:
                    result['unresolved'].append({'rank_key':key,'reason':'REACHABILITY_UNRESOLVED:'+str(exc)})
                    continue
                tested=_rank_probe(compiled,talent,int(rank.rank),witness,level=level,bonus=bonus)
                result['ranks'].append(tested)
                result['behavior_probes_executed']+=len(tested['behavior_tests'])
        fail=[r for r in result['ranks'] if r['status']!='PASS']
        result['reachability_count']=len(result['ranks'])
        result['pass_count']=len(result['ranks'])-len(fail)
        result['fail_count']=len(fail)
        result['unresolved_count']=len(result['unresolved'])
        result['unreachable_count']=len(result['unreachable'])
        if len(result['ranks'])+len(result['unreachable'])+len(result['unresolved'])!=result['source_rank_total']:
            result['reasons'].append('RANK_PARTITION_INCOMPLETE')
        result['reasons'] += [f"{r['rank_key']}:{'|'.join(r['reasons'])}" for r in fail]
        result['reasons'] += [f"{r['rank_key']}:{r['reason']}" for r in result['unresolved']]
        result['status']='PASS' if not result['reasons'] else 'FAIL'
    except (ImportError,ValueError,KeyError,TypeError,AttributeError,sqlite3.Error,OSError) as exc:
        result['reasons'].append('P2_RUNTIME_SETUP_FAILED:'+type(exc).__name__+':'+str(exc))
    return result
