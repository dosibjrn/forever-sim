"""Source-driven between-mob maintenance, shared by L2 search and L3 replay.

Only legal Game IR action casts update an actor; this module never grants an
always-active aura and never resets an encounter's clock/resources.
"""
from __future__ import annotations
from src.game.runtime import ActorState, CombatRuntime, TargetState, action_eligibility
from src.game.runtime.simulator import EventTransitionBudgetExceeded, ComputeDeadlineExceeded

def _execute_source_maintenance_upkeep(
    ir, actor:ActorState, *, max_new_event_transitions:int|None=None,
    cpu_deadline_ns:int|None=None, wall_deadline_ns:int|None=None
)->tuple[float,int,int]:
    """Recast source-declared timed auras on the actual persistent ActorState.

    Trigger activation is checked independently per event by required_aura_id;
    stale maintenance cannot become a permanently free auto-active trigger.
    This helper never guesses mechanics or an action that is absent from IR.
    """
    begin=float(actor.current_time_s); casts=0; upkeep_events=0
    facts={}
    for policy in ir.policies:
        for fact in policy.maintenance:
            aid=fact.get('maintenance_action_id'); aura_id=fact.get('aura_id')
            if aid and aura_id:
                if aid in facts and facts[aid]!=fact:raise ValueError('CONFLICTING_SOURCE_MAINTENANCE')
                facts[aid]=fact
    actions={action.id:action for action in ir.actions}
    def advance_with_periodics(until):
        nonlocal upkeep_events
        helper=CombatRuntime(actor=actor,target=TargetState.with_health('maintenance_wait',1.,context='self_maintenance'))
        helper.event_budget_cap=None if max_new_event_transitions is None else max(0,int(max_new_event_transitions)-upkeep_events)
        helper.cpu_deadline_ns=cpu_deadline_ns;helper.wall_deadline_ns=wall_deadline_ns
        try:
            helper.advance_to(float(until))
            helper.persist_actor_periodics()
        except EventTransitionBudgetExceeded as exc:
            raise EventTransitionBudgetExceeded(upkeep_events+exc.events_processed) from exc
        except ComputeDeadlineExceeded as exc:
            raise ComputeDeadlineExceeded(upkeep_events+exc.events_processed,exc.kind) from exc
        upkeep_events+=helper.event_transitions

    def charge_helper(helper, action):
        """Apply the same hard runtime budgets to *precombat* as combat."""
        remaining=(None if max_new_event_transitions is None
                   else max(0,int(max_new_event_transitions)-upkeep_events))
        helper.event_budget_cap=remaining
        helper.event_budget_start=helper.event_transitions
        helper.cpu_deadline_ns=cpu_deadline_ns
        helper.wall_deadline_ns=wall_deadline_ns
        try:
            helper.schedule_action(action)
            helper.advance_to(float(actor.current_time_s)+float(action.cast_time_s))
            helper.persist_actor_periodics()
        except EventTransitionBudgetExceeded as exc:
            raise EventTransitionBudgetExceeded(upkeep_events+exc.events_processed) from exc
        except ComputeDeadlineExceeded as exc:
            raise ComputeDeadlineExceeded(upkeep_events+exc.events_processed,exc.kind) from exc
        return helper.event_transitions

    for aid,fact in sorted(facts.items()):
        aura_id=str(fact['aura_id']);aura=actor.active_auras.get(aura_id)
        if aura is not None and float(aura.expires_at_s)>float(actor.current_time_s)+1e-9:
            continue
        if aid not in actions:raise ValueError('BLOCKED_MISSING_SOURCE_MAINTENANCE_CAST_ACTION')
        action=actions[aid]
        # Only use explicit Game IR mode-exit actions, never modify form in code.
        eligibility=action_eligibility(action=action,actor=actor)
        if not eligibility.eligible and any(req.get('kind')=='mode_is' and str(req.get('value'))!=str(actor.current_mode_id) for req in action.requirements):
            modes=[a for a in ir.actions if a.metadata.get('mode_transition')=='exit'
                   and any(getattr(e,'target_mode_id',None)=='caster' for e in a.effects)]
            eligible_exits=[a for a in modes if action_eligibility(action=a,actor=actor).eligible]
            if not eligible_exits:
                # A just-completed sourced form entry may still own the GCD.
                # Advance through the REAL runtime so carried HoT ticks fire.
                delayed=[(a,action_eligibility(action=a,actor=actor)) for a in modes]
                delayed=[(a,g) for a,g in delayed if g.reason=='action not ready: gcd/cooldown']
                if len(delayed)==1:
                    advance_with_periodics(delayed[0][1].next_ready_s)
                    eligible_exits=[a for a in modes if action_eligibility(action=a,actor=actor).eligible]
            if len(eligible_exits)!=1:raise ValueError('BLOCKED_SOURCE_MAINTENANCE_MODE_EXIT')
            helper=CombatRuntime(actor=actor,target=TargetState.with_health('maintenance_context',1.,context='self_maintenance'))
            upkeep_events+=charge_helper(helper, eligible_exits[0])
        eligibility=action_eligibility(action=action,actor=actor)
        if not eligibility.eligible and eligibility.reason=='action not ready: gcd/cooldown':
            advance_with_periodics(eligibility.next_ready_s)
            eligibility=action_eligibility(action=action,actor=actor)
        if not eligibility.eligible:raise ValueError('BLOCKED_SOURCE_MAINTENANCE_CAST: '+str(eligibility.reason))
        helper=CombatRuntime(actor=actor,target=TargetState.with_health('maintenance_context',1.,context='self_maintenance'))
        upkeep_events+=charge_helper(helper,action)
        applied=actor.active_auras.get(aura_id)
        if applied is None or float(applied.expires_at_s)<=float(actor.current_time_s):
            raise ValueError('BLOCKED_SOURCE_MAINTENANCE_AURA_NOT_APPLIED')
        # Casting the actual aura costs mana through CombatRuntime, and its
        # GCD is paid before the next combat action or form entry.
        if actor.gcd_ready_s>actor.current_time_s:
            advance_with_periodics(actor.gcd_ready_s)
        casts+=1
    return float(actor.current_time_s)-begin,casts,upkeep_events

