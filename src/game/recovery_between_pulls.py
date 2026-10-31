"""Optional source-executed between-pull recovery on the shared ActorState.

This is a recovery *policy*, not a new combat engine or a new acceptance gate.
The caller supplies source action IDs, not class-specific spell names.  HoTs
and cooldowns survive into the next CombatRuntime encounter.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from src.game.model import ModeChangeEffect, PeriodicHealEffect
from src.game.runtime import CombatRuntime, TargetState, action_eligibility
from src.game.runtime.simulator import EventTransitionBudgetExceeded, ComputeDeadlineExceeded
from src.game.recovery import recover_actor_to_full


@dataclass(frozen=True)
class BetweenPullPolicy:
    health_fraction: float
    mana_fraction: float
    hot_action_id: str | None = None
    exit_action_id: str | None = None
    reentry_action_id: str | None = None
    hot_min_missing_health_fraction: float = 0.0

    def __post_init__(self):
        if not all(isfinite(float(v)) and 0 <= float(v) <= 1 for v in
                   (self.health_fraction, self.mana_fraction,self.hot_min_missing_health_fraction)):
            raise ValueError('INVALID_BETWEEN_PULL_THRESHOLD')
        if self.hot_action_id and not self.exit_action_id and self.reentry_action_id:
            raise ValueError('REENTRY_WITHOUT_EXIT')


def _mode_target(action):
    changes=[e for e in action.effects if isinstance(e,ModeChangeEffect)]
    return changes[0].target_mode_id if len(changes)==1 and len(action.effects)==1 else None


def _cast_source_action(ir, actor, action_id, *, cpu_deadline_ns, wall_deadline_ns,
                        remaining_events):
    actions={a.id:a for a in ir.actions}
    if action_id not in actions:
        raise ValueError('UNKNOWN_SOURCE_RECOVERY_ACTION:'+str(action_id))
    action=actions[action_id]
    if not action.provenance or action.metadata.get('never_l2_legal') or action.metadata.get('execution_tier')=='L1_PARTIAL_ONLY':
        raise ValueError('UNSOURCED_OR_UNEXECUTABLE_RECOVERY_ACTION:'+str(action_id))
    runtime=CombatRuntime(actor=actor,target=TargetState.with_health('between_pull_self',1.0),
                          spell_power=float(actor.stats.get('spell_power',0.0)))
    runtime.cpu_deadline_ns=cpu_deadline_ns
    runtime.wall_deadline_ns=wall_deadline_ns
    runtime.event_budget_cap=remaining_events
    gate=action_eligibility(action=action,actor=actor,target=runtime.target)
    if not gate.eligible and gate.reason=='action not ready: gcd/cooldown':
        runtime.advance_to(float(gate.next_ready_s))
        gate=action_eligibility(action=action,actor=actor,target=runtime.target)
    if not gate.eligible:
        raise ValueError('RECOVERY_ACTION_INELIGIBLE:'+str(action_id)+':'+str(gate.reason))
    runtime.schedule_action(action)
    runtime.persist_actor_periodics()
    return runtime.event_transitions


def between_pull_recovery(*, ir, actor, level:int, mob_index:int, mob_count:int,
                          policy:BetweenPullPolicy, cpu_deadline_ns=None,
                          wall_deadline_ns=None, max_new_events=None):
    """Execute conditional recovery, charge form changes and preserve HoT ticks.

    The final mob settles remaining HP/mana debt. Intermediate pulls do not
    receive free health/mana resets. Return elapsed actor-clock time and events.
    """
    start=float(actor.current_time_s)
    initial_mode=next((m.id for m in ir.modes if m.initial),None)
    mode_at_kill=actor.current_mode_id
    actions={a.id:a for a in ir.actions}
    for aid in (policy.exit_action_id,policy.reentry_action_id):
        if aid is not None and (aid not in actions or _mode_target(actions[aid]) is None):
            raise ValueError('INVALID_SOURCE_MODE_TRANSITION:'+str(aid))
    if policy.exit_action_id is not None and _mode_target(actions[policy.exit_action_id])!=initial_mode:
        raise ValueError('RECOVERY_EXIT_NOT_INITIAL_MODE')
    # Combat may finish in a different form from the opening (for example,
    # after an emergency heal). Reentry describes the NEXT pull's sourced
    # combat mode, not necessarily the mode in which the last target died.
    reentry_target=(None if policy.reentry_action_id is None else
                    _mode_target(actions[policy.reentry_action_id]))
    if policy.reentry_action_id is not None:
        reentry=actions[policy.reentry_action_id]
        initial_definition=next((m for m in ir.modes if m.id==initial_mode),None)
        if (initial_definition is None or
            (initial_definition.enabled_action_ids is not None and
             reentry.id not in initial_definition.enabled_action_ids) or
            any(req.get('kind')=='mode_is' and str(req.get('value'))!=str(initial_mode)
                for req in reentry.requirements)):
            raise ValueError('RECOVERY_REENTRY_NOT_SOURCE_LEGAL_FROM_INITIAL_MODE')
    if policy.hot_action_id is not None:
        action=actions.get(policy.hot_action_id)
        if action is None or not any(isinstance(e,PeriodicHealEffect) for e in action.effects):
            raise ValueError('RECOVERY_HOT_NOT_SOURCE_PERIODIC_HEAL')
    def fraction(resource):
        cap=actor.resource_capacity.get(resource)
        value=actor.resource_amount(resource)
        return 1.0 if cap is None or value is None or cap<=0 else float(value)/float(cap)
    full=(mob_index==mob_count-1 or fraction('health')<policy.health_fraction or
          fraction('mana')<policy.mana_fraction)
    # Never attempt a HoT/form cycle that cannot pay its sourced mana costs.
    # Choose genuine full recovery instead; no free mana or silent cast skip.
    hot_action=actions.get(policy.hot_action_id) if policy.hot_action_id else None
    hot_auras=[e.aura_id for e in hot_action.effects if isinstance(e,PeriodicHealEffect)] if hot_action else []
    hot_already_active=any(a in actor.active_auras and actor.active_auras[a].expires_at_s>actor.current_time_s for a in hot_auras)
    should_hot=bool(hot_action and not hot_already_active and
        1-fraction('health')>policy.hot_min_missing_health_fraction+1e-9)
    if not full and should_hot:
        cycle=[actions[policy.hot_action_id]]
        if mode_at_kill!=initial_mode:
            if policy.exit_action_id is None or policy.reentry_action_id is None:
                raise ValueError('RECOVERY_HOT_REQUIRES_SOURCED_MODE_CYCLE')
            cycle.append(actions[policy.exit_action_id])
        if policy.reentry_action_id and reentry_target!=initial_mode:
            cycle.append(actions[policy.reentry_action_id])
        mana_needed=sum(float(cost.amount) for action in cycle for cost in action.costs if cost.resource_id=='mana')
        if mana_needed>float(actor.resource_amount('mana') or 0.)+1e-9:
            full=True
    events=0;casts=[];recovery=None
    def cast(aid):
        nonlocal events
        if max_new_events is not None and events>=max_new_events:
            raise EventTransitionBudgetExceeded(events)
        count=_cast_source_action(ir,actor,aid,cpu_deadline_ns=cpu_deadline_ns,
            wall_deadline_ns=wall_deadline_ns,
            remaining_events=None if max_new_events is None else max_new_events-events)
        events+=count;casts.append(aid)
    def exit_form():
        if actor.current_mode_id!=initial_mode:
            if policy.exit_action_id is None:
                raise ValueError('RECOVERY_REQUIRES_SOURCED_FORM_EXIT')
            cast(policy.exit_action_id)
    def reenter_for_next_pull():
        if policy.reentry_action_id and actor.current_mode_id!=reentry_target:
            cast(policy.reentry_action_id)
    if full:
        exit_form()
        recovery=recover_actor_to_full(actor=actor,level=level,actions=ir.actions,
            start_time_s=float(actor.current_time_s),
            healing_power=float(actor.stats.get('spell_power',0.0)),
            cpu_deadline_ns=cpu_deadline_ns,wall_deadline_ns=wall_deadline_ns)
        if mob_index<mob_count-1:
            reenter_for_next_pull()
    elif should_hot:
        exit_form()
        cast(policy.hot_action_id)
        reenter_for_next_pull()
    return {'elapsed_s':float(actor.current_time_s)-start,'events':events,
            'actions':casts,'full_recovery':full,
            'hot_cast':policy.hot_action_id in casts,
            'pending_actor_ticks':sum(e.kind=='PeriodicTick' for e in actor.pending_actor_periodic_events),
            'recovery_method':None if recovery is None else recovery.method,
            'water_s':0.0 if recovery is None else float(recovery.water_s),
            'food_s':0.0 if recovery is None else float(recovery.food_s)}
