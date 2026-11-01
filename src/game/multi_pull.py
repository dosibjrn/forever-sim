from __future__ import annotations

"""Stateful repeated-pull scorer over source Game IR.

No class-specific facts or policy templates: the same ActorState, cooldowns,
resources, and pending actor periodic events survive each encounter and recovery
window. Enemy state, incoming-swing queues and enemy DoTs do not survive.
"""

from dataclasses import dataclass, replace
from typing import Any

from src.game.model import ModeChangeEffect
from src.game.policy import execute_priority_policy
from src.game.recovery import recover_actor_to_full
from src.game.runtime import ActorState, CombatRuntime, TargetState, action_eligibility


@dataclass(frozen=True)
class RepeatedPullResult:
    seconds_per_mob: float
    pulls: tuple[dict[str, Any], ...]
    start_time_s: float
    end_time_s: float
    actor: ActorState



def _encounter_pack(*, mob_start: int, mob_count: int, target_health: float,
                    target_metadata: dict, incoming_attacks: tuple):
    """Compile one 2D pack without modifying canonical Action or enemy facts."""
    targets = [TargetState.with_health(f'repeated-pull-target-{mob_start + j}',
               float(target_health), **target_metadata) for j in range(mob_count)]
    if mob_count == 1:
        return targets, None, incoming_attacks
    from src.shared.leveling.spaced_pulls import SpacedPullLayout
    layout = SpacedPullLayout(mob_count, spacing_yards=20.0)
    positions = dict(zip((target.id for target in targets), layout.positions_yards))
    incoming = tuple(replace(attack, id=f'{attack.id}:pack:{mob_start + j}',
               source_actor_id=enemy.id) for j, enemy in enumerate(targets)
               for attack in incoming_attacks)
    return targets, positions, incoming


def _paid_source_pack_upkeep(ir_slice, actor, enabled):
    """Charge source maintenance on the same persistent actor, or do nothing."""
    if not enabled:
        return 0.0, 0, 0
    from src.game.runtime.source_maintenance import _execute_source_maintenance_upkeep
    try:
        return _execute_source_maintenance_upkeep(ir_slice, actor)
    except ValueError as exc:
        raise ValueError('BLOCKED_SOURCE_MAINTENANCE_UPKEEP:' + str(exc)) from exc


def _paid_source_pack_recovery(ir_slice, actor, level, pack_index, pack_total, policy):
    """Reuse the sequential sourced recovery state machine without a reset."""
    from src.game.recovery_between_pulls import between_pull_recovery
    try:
        return between_pull_recovery(ir=ir_slice, actor=actor, level=int(level),
                                     mob_index=pack_index, mob_count=pack_total,
                                     policy=policy)
    except ValueError as exc:
        raise ValueError('BLOCKED_SOURCE_BETWEEN_PULL_RECOVERY:' + str(exc)) from exc


def evaluate_repeated_pulls(
    *, ir_slice, policy, level: int, target_health: float,
    count: int = 2, schedule_incoming_attacks: bool = True,
    post_combat_action_ids: tuple[str, ...] = (),
    pre_combat_action_ids: tuple[str, ...] = (),
    opening_action_ids: tuple[str, ...] = (),
    max_actions: int = 256, carry_actor_periodics: bool = True,
    apply_target_defense: bool = False,
    companion_policy_override: dict | None = None,
    recovery_action_ids: tuple[str, ...] | None = None,
    recovery_mode: str = "always", recovery_health_fraction: float = 0.5,
    recovery_mana_fraction: float = 0.1, retain_mode_between_pulls: bool = False,
    travel_time_s: float = 0.0,
    prepared_first_pull_resources: dict[str, float] | None = None,
    pack_size: int = 1,
    source_maintenance_upkeep: bool = False,
    source_between_pack_policy=None,
) -> RepeatedPullResult:
    if not 1 <= int(count) <= 100:
        raise ValueError('repeated-pull count must be between 1 and 100')
    if type(pack_size) is not int or not 1 <= pack_size <= int(count):
        raise ValueError('pack_size must be a positive integer no larger than mob count')
    if pack_size > 1 and ir_slice.companions:
        raise ValueError('concurrent pack companion policy requires multi-target companion executor')
    if float(target_health) <= 0:
        raise ValueError('target health must be positive')
    if recovery_mode not in ("always", "threshold"):
        raise ValueError("recovery_mode must be always or threshold")
    if not 0.0 <= float(recovery_health_fraction) <= 1.0 or not 0.0 <= float(recovery_mana_fraction) <= 1.0:
        raise ValueError("invalid recovery resource threshold")
    if not 0.0 <= float(travel_time_s) <= 3600.0:
        raise ValueError("invalid travel duration")
    if retain_mode_between_pulls and pre_combat_action_ids and not post_combat_action_ids:
        raise ValueError("mode continuity requires sourced post-combat exit when recovery is needed")
    actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
    # First-encounter preparation is an explicit scenario choice, not a
    # respawn/refill after every kill. Validate before any expensive simulation.
    prepared = dict(prepared_first_pull_resources or {})
    for resource_id, amount in prepared.items():
        cap = actor.resource_capacity.get(resource_id)
        if cap is None or not 0.0 <= float(amount) <= float(cap):
            raise ValueError(f'invalid prepared first-pull resource: {resource_id}')
    start = float(actor.current_time_s)
    results = []
    # Optional source-executed upkeep and conditional recovery use the same
    # ActorState as every pack, never a parallel combat or recovery engine.
    pack_total = (int(count) + pack_size - 1) // pack_size
    # Persist companion resource/cooldown state across consecutive pulls. Each
    # encounter rebuilds base pet stats before applying owner gear-derived
    # actor links, preventing double application of inherited AP/crit.
    companion_carry = {}
    companion_policies = {str(p.provenance['owner_actor_id']): p for p in ir_slice.policies
        if p.provenance.get('companion_policy')}
    if companion_policy_override is not None:
        companion_policies = dict(companion_policy_override)
    if ir_slice.companions and set(companion_policies) != {a.id for a in ir_slice.companions}:
        raise ValueError('companion has no source-executable policy')
    actions = {a.id: a for a in ir_slice.actions}
    # The recovery plan is a genuine optimization axis. Restricting its
    # available heal buttons must not remove combat actions or source facts.
    # None retains the historical all-heals behavior; () means food/water only.
    recovery_actions = ir_slice.actions
    if recovery_action_ids is not None:
        from src.game.model import HealEffect, PeriodicHealEffect
        chosen = set(recovery_action_ids)
        available = {a.id for a in ir_slice.actions if any(
            isinstance(e, (HealEffect, PeriodicHealEffect)) for e in a.effects)}
        if chosen - available:
            raise ValueError('recovery selection contains non-healing or unknown action')
        recovery_actions = tuple(a for a in ir_slice.actions if a.id in chosen)
    initial_mode = next((m.id for m in ir_slice.modes if m.initial), None)
    for index, mob_start in enumerate(range(0, int(count), pack_size)):
        upkeep_s, upkeep_casts, upkeep_events = _paid_source_pack_upkeep(
            ir_slice, actor, source_maintenance_upkeep)
        mob_count = min(pack_size, int(count) - mob_start)
        target_metadata = {}
        if apply_target_defense:
            from src.game.data.forever.target_combat_source import target_combat_metadata
            target_metadata = target_combat_metadata(ir_slice)
        incoming = ir_slice.incoming_attacks if schedule_incoming_attacks else ()
        targets, pack_positions, incoming = _encounter_pack(
            mob_start=mob_start, mob_count=mob_count, target_health=float(target_health),
            target_metadata=target_metadata, incoming_attacks=incoming)
        target = targets[0]
        companions = []
        for companion_ir in ir_slice.companions:
            pet = ActorState.from_ir(companion_ir, ir_slice.resources)
            pet.current_time_s = float(actor.current_time_s)
            previous = companion_carry.get(pet.id)
            if previous:
                pet.resources.update(previous['resources'])
                pet.gcd_ready_s = previous['gcd_ready_s']
                pet.cooldown_ready_s.update(previous['cooldowns'])
            companions.append(pet)
        runtime = CombatRuntime(
            actor=actor, target=target, companions=companions,
            other_targets=tuple(targets[1:]), spatial_positions_yards=pack_positions,
            actor_links=ir_slice.actor_links, timed_summons=ir_slice.timed_summons,
            spell_power=float(actor.stats.get('spell_power', 0.0)),
            auto_attacks=ir_slice.auto_attacks,
            incoming_attacks=incoming,
            mitigation_rules=(ir_slice.mitigation_rules if schedule_incoming_attacks else ()),
            triggers=ir_slice.triggers,
        )
        carried_at_start = sum(e.kind == 'PeriodicTick' and e.payload.get('aura_scope') == 'actor'
                               for _, _, e in runtime.queue._heap)
        for action_id in pre_combat_action_ids:
            entry = actions[action_id]
            target_mode = next((effect.target_mode_id for effect in entry.effects
                                if isinstance(effect, ModeChangeEffect)), None)
            if retain_mode_between_pulls and target_mode and actor.current_mode_id == target_mode:
                continue  # Existing sourced form persists; neither free recast nor resource reset.
            gate = action_eligibility(action=entry, actor=actor, target=target)
            if not gate.eligible and str(gate.reason or '').startswith('action not ready:'):
                runtime.advance_to(float(gate.next_ready_s))
                gate = action_eligibility(action=entry, actor=actor, target=target)
            if not gate.eligible:
                raise ValueError(f'cannot enter combat mode: {gate.reason}')
            runtime.schedule_action(entry)
            if actor.gcd_ready_s > actor.current_time_s:
                runtime.advance_to(actor.gcd_ready_s)
        # No free pack aggro. Each mob occupies a 20yd square-grid cell.
        # Player movement is queued on the SAME clock as sourced APL actions.
        if mob_count > 1:
            runtime.begin_player_route(
                tuple(pack_positions[enemy.id] for enemy in targets[1:]),
                speed_yards_s=7.0,
            )
        # Apply prepared resources AFTER any genuine sourced mode-entry action,
        # immediately before the first hostile action. Never reset on later mobs.
        if index == 0:
            for resource_id, amount in prepared.items():
                actor.resources[resource_id] = float(amount)
        if companions:
            from src.game.multi_actor_policy import execute_multi_actor_priority_policies
            execution = execute_multi_actor_priority_policies(
                runtime=runtime,
                policies={actor.id:policy, **companion_policies},
                actions=ir_slice.actions, max_time_s=180.,
                max_iterations=max(2048, max_actions * 8),
            )
            runtime.run_until_idle(preserve_actor_periodics=True)
            timeline = runtime.result()
        else:
            execution = execute_priority_policy(
                policy=policy, actions=ir_slice.actions, runtime=runtime, max_actions=max_actions,
                opening_action_ids=opening_action_ids, skip_satisfied_mode_opening=True,
            )
            timeline = execution.timeline
        if (str(getattr(execution, 'stopped_reason', '') or '').startswith(('BLOCKED_', 'actor_died'))
                or not timeline.target_defeated or any(
            not actor.resource_positive(str(a.health_resource_id)) for a in runtime.scheduled_incoming_attacks.values()
        )):
            raise ValueError(f'pull {index} failed: {execution.stopped_reason or "actor_died_or_target_survived"}')
        # Decide recovery from real carried HP/mana. These thresholds are explicit
        # scenario parameters, NOT source gameplay facts. Charge final restoration
        # even if it was deferred on intermediate pulls (no free end-state debt).
        health = actor.resource_amount('health')
        health_cap = actor.resource_capacity.get('health')
        mana = actor.resource_amount('mana')
        mana_cap = actor.resource_capacity.get('mana')
        is_final_pack = mob_start + mob_count == int(count)
        needs_restoration = (recovery_mode == 'always' or is_final_pack or
            (health is not None and health_cap is not None and
             health < float(health_cap) * float(recovery_health_fraction)) or
            (mana is not None and mana_cap is not None and
             mana < float(mana_cap) * float(recovery_mana_fraction)))
        exit_wait = 0.0
        between_pack_events = 0
        source_recovery_actions = []
        if source_between_pack_policy is not None:
            step = _paid_source_pack_recovery(
                ir_slice, actor, level, index, pack_total, source_between_pack_policy)
            recovery_s = float(step['elapsed_s'])
            between_pack_events = int(step['events'])
            source_recovery_actions = list(step['actions'])
            heal_actions = list(source_recovery_actions)
            needs_restoration = bool(step['full_recovery'] or source_recovery_actions)
        elif needs_restoration:
            # Source-defined form exit, never a synthetic forced actor reset.
            # A zero-GCD exit may still be blocked by the previous action's GCD.
            for action_id in post_combat_action_ids:
                action = actions[action_id]
                if (initial_mode is None or len(action.effects) != 1
                    or not isinstance(action.effects[0], ModeChangeEffect)
                    or action.effects[0].target_mode_id != initial_mode
                    or action.costs or action.cast_time_s or action.gcd_s or not action.provenance):
                    raise ValueError('post-combat transition must be sourced, free, and return to initial mode')
                if actor.current_mode_id != initial_mode:
                    exit_runtime = CombatRuntime(actor=actor, target=TargetState.with_health('mode_exit', 1.0))
                    gate = action_eligibility(action=action, actor=actor, target=exit_runtime.target)
                    if not gate.eligible and str(gate.reason or '').startswith('action not ready:'):
                        exit_runtime.advance_to(float(gate.next_ready_s))
                        gate = action_eligibility(action=action, actor=actor, target=exit_runtime.target)
                    if not gate.eligible:
                        raise ValueError(f'cannot leave combat mode: {gate.reason}')
                    exit_runtime.schedule_action(action)
                    exit_runtime.persist_actor_periodics()
            exit_wait = max(0.0, float(actor.current_time_s) - float(timeline.target_death_s))
            recovery = recover_actor_to_full(
                actor=actor, level=int(level), actions=recovery_actions,
                start_time_s=float(actor.current_time_s),
                healing_power=float(actor.stats.get('spell_power', 0.0)),
            )
            recovery_s = exit_wait + float(recovery.total_s)
            heal_actions = list(recovery.provenance.get('heal_action_sequence', []))
        else:
            recovery_s = 0.0
            heal_actions = []
        # Travel is paid only when another target remains. The last pack
        # settles recovery debt, but there is no next mob to travel toward.
        # This matches the canonical persistent evaluator's inter-pull route.
        travel_charged_s = float(travel_time_s) if not is_final_pack else 0.0
        if travel_charged_s > 0:
            travel_runtime = CombatRuntime(actor=actor, target=TargetState.with_health('travel', 1.0))
            travel_runtime.advance_to(float(actor.current_time_s) + travel_charged_s)
            travel_runtime.persist_actor_periodics()
        pending_count = sum(e.kind == 'PeriodicTick' for e in actor.pending_actor_periodic_events)
        results.append({
            'pull_index': index,
            'mob_count': mob_count,
            'pack_all_defeated': bool(timeline.target_defeated),
            'enemy_death_s': dict(runtime.pack_summary()['target_death_s']) if mob_count > 1 else {},
            'prepared_first_pull_resources':dict(prepared) if index == 0 else {},
            'kill_s': float(timeline.target_death_s) - float(timeline.start_time_s),
            'recovery_s': float(recovery_s),
            'travel_s': travel_charged_s,
            'recovery_performed': bool(needs_restoration),
            'mode_at_next_pull': actor.current_mode_id,
            'energy_at_next_pull': actor.resource_amount('energy'),
            'carried_ticks_at_start': int(carried_at_start),
            'carried_heal_events_during_combat': sum(
                e.kind == 'Heal' and bool(e.payload.get('periodic')) and e.action_id not in {
                    a['action_id'] for a in execution.selected_actions
                } for e in timeline.events
            ),
            'selected_actions': [dict(x) for x in execution.selected_actions],
            'satisfied_mode_opening_ids': list(getattr(execution, 'satisfied_mode_opening_ids', ())),
            'event_transitions': int(runtime.event_transitions) + upkeep_events + between_pack_events,
            'combat_runtime_events': int(runtime.event_transitions),
            'maintenance_s': float(upkeep_s),
            'maintenance_casts': int(upkeep_casts),
            'maintenance_runtime_events': int(upkeep_events),
            'between_pull_runtime_events': int(between_pack_events),
            'source_recovery_actions': source_recovery_actions,
            'damage_by_role': dict(timeline.damage_by_role),
            'companion_resources_at_kill': {pet.id:dict(pet.resources) for pet in companions},
            'heal_actions': heal_actions,
            'pending_ticks_after_recovery': pending_count,
            'health_after_recovery': actor.resource_amount('health'),
            'mana_after_recovery': actor.resource_amount('mana'),
        })
        for pet in companions:
            elapsed = float(recovery_s) + travel_charged_s
            resources = dict(pet.resources)
            for resource_id, rate in pet.resource_regeneration_per_s.items():
                if resource_id in pet.resource_capacity and resource_id in resources:
                    resources[resource_id] = min(float(pet.resource_capacity[resource_id]),
                        float(resources[resource_id]) + max(0.,float(rate)) * elapsed)
            companion_carry[pet.id] = {'resources':resources,
                'gcd_ready_s':pet.gcd_ready_s,'cooldowns':dict(pet.cooldown_ready_s)}
        if not carry_actor_periodics:
            # Counterfactual for quantifying the pre-fix dropped-aura bias.
            # Never use this mode as a legal production candidate.
            for aura_id in {str(e.payload['aura_id']) for e in actor.pending_actor_periodic_events}:
                actor.remove_aura(aura_id)
            actor.pending_actor_periodic_events = ()
            actor.pending_actor_periodic_actions.clear()
    return RepeatedPullResult(
        seconds_per_mob=(float(actor.current_time_s) - start) / count,
        pulls=tuple(results), start_time_s=start,
        end_time_s=float(actor.current_time_s), actor=actor,
    )


def search_repeated_pull_policies(*, ir_slice, level: int, target_health: float,
                                  count: int = 3, schedule_incoming_attacks: bool = True):
    """Evaluate every source-declared policy under the same consecutive-pull objective.

    This is a policy-scope search, NOT independent talent/gear discovery. Mode
    entry/exit is resolved by sourced Action IR, never by class/form names.
    """
    initial_mode = next((m.id for m in ir_slice.modes if m.initial), None)
    actions = {a.id: a for a in ir_slice.actions}
    results = []
    for policy in ir_slice.policies:
        entry_id = str(policy.provenance.get('entry_action_id') or '')
        pre = (entry_id,) if entry_id else ()
        post = ()
        try:
            if entry_id:
                entry = actions[entry_id]
                mode_effects = [e for e in entry.effects if isinstance(e, ModeChangeEffect)]
                if len(mode_effects) != 1 or initial_mode is None:
                    raise ValueError('source mode entry has no unique mode target')
                exit_actions = [a for a in ir_slice.actions
                                if a.provenance and not a.costs and not a.cast_time_s
                                and not a.gcd_s and len(a.effects) == 1
                                and isinstance(a.effects[0], ModeChangeEffect)
                                and a.effects[0].target_mode_id == initial_mode
                                and a.requirements and any(
                                    (req.get('value') if isinstance(req, dict) else getattr(req, 'mode_id', None)) == mode_effects[0].target_mode_id
                                    for req in a.requirements)]
                if len(exit_actions) != 1:
                    raise ValueError('source mode entry has no unique legal free exit')
                post = (exit_actions[0].id,)
            result = evaluate_repeated_pulls(
                ir_slice=ir_slice, policy=policy, level=level,
                target_health=target_health, count=count,
                schedule_incoming_attacks=schedule_incoming_attacks,
                pre_combat_action_ids=pre, post_combat_action_ids=post,
            )
            results.append({'policy_id': policy.id, 'status': 'evaluated',
                            'seconds_per_mob': result.seconds_per_mob,
                            'entry_action_ids': list(pre), 'exit_action_ids': list(post),
                            'pulls': list(result.pulls)})
        except (ValueError, KeyError) as exc:
            results.append({'policy_id': policy.id, 'status': 'unavailable',
                            'reason': str(exc)})
    ranked = sorted((r for r in results if r['status'] == 'evaluated'),
                    key=lambda r: (r['seconds_per_mob'], r['policy_id']))
    return {'winner': ranked[0] if ranked else None, 'candidates': results,
            'candidate_count': len(results), 'evaluated_count': len(ranked),
            'search_scope': 'all source-declared policy candidates; fixed source gear/talent IR',
            'global_optimum_proven': False}



def _paid_pack_evidence(result: RepeatedPullResult, *, wall_s: float, cpu_s: float) -> dict:
    """Canonical repeated-pull totals for the generic policy optimizer."""
    return {'status': 'COMPLETE', 'mob_completed': sum(p['mob_count'] for p in result.pulls),
            'packs': len(result.pulls), 'mean_s_per_mob': result.seconds_per_mob,
            'events': sum(p['event_transitions'] for p in result.pulls),
            'recovery_s': sum(p['recovery_s'] for p in result.pulls),
            'kill_s': sum(p['kill_s'] for p in result.pulls),
            'elapsed_wall_s': wall_s, 'elapsed_cpu_s': cpu_s}


def search_repeated_pull_evolved_policies(
    *, ir_slice, level: int, target_health: float, pack_size: int = 1,
    budget: int = 32, seed=None, opening_action_ids: tuple[str, ...] = (),
    pre_combat_action_ids: tuple[str, ...] = (),
    post_combat_action_ids: tuple[str, ...] = (),
    schedule_incoming_attacks: bool = True, recovery_mode: str = 'always',
    max_actions: int = 256,
):
    """Cold/mutated source APLs ranked by 100 real kills + paid recovery.

    The caller owns the *legal* talent and equipment GameIR. This is one
    policy axis of joint search, not an independent gear/talent optimizer.
    """
    from time import monotonic, process_time
    from src.game.policy_evolution import search_evolved_policies, source_policy_uncertainties

    def evaluate(policy):
        wall_start, cpu_start = monotonic(), process_time()
        uncertainties = source_policy_uncertainties(policy, ir_slice.actions,
            extra_action_ids=(*opening_action_ids, *pre_combat_action_ids, *post_combat_action_ids))
        try:
            result = evaluate_repeated_pulls(
                ir_slice=ir_slice, policy=policy, level=level,
                target_health=target_health, count=100, pack_size=pack_size,
                schedule_incoming_attacks=schedule_incoming_attacks,
                opening_action_ids=opening_action_ids,
                pre_combat_action_ids=pre_combat_action_ids,
                post_combat_action_ids=post_combat_action_ids,
                recovery_mode=recovery_mode, max_actions=max_actions,
            )
        except (ValueError, KeyError, RuntimeError) as exc:
            return {'status': 'INCOMPLETE', 'reason': str(exc),
                    'exception_type': type(exc).__name__,
                    'proxy_uncertainties': uncertainties,
                    'elapsed_wall_s': monotonic()-wall_start,
                    'elapsed_cpu_s': process_time()-cpu_start}
        return {**_paid_pack_evidence(result, wall_s=monotonic()-wall_start,
                                      cpu_s=process_time()-cpu_start),
                'proxy_uncertainties': uncertainties}

    return search_evolved_policies(ir_slice, evaluate=evaluate,
                                   seed=seed, budget=budget, include_scratch=True)
