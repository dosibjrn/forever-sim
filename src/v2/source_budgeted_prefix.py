"""On-demand, source-legal ordered-opening discovery on the production runtime.

A fixed hard budget counts every *attempted* combat+recovery evaluation.  No
Cartesian gear/talent grid, no score transfer between different Game IR states.
This is a bounded opening-policy pilot, NOT joint gear/talent optimization.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from itertools import product
from json import dumps
from math import isfinite

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PolicyDefinition, PolicyRuleDefinition, PolicyCondition, ModeChangeEffect
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_button_discovery import discover_source_combat_buttons
from src.v2.source_policy_search import _safe_action, _direct
from src.game.runtime.state import ActorState
from src.game.runtime.simulator import expected_auto_attack_swing
from src.version import SOFTWARE_VERSION


@dataclass(frozen=True)
class PrefixCandidate:
    prefix: tuple[str, ...]
    fallback: str
    # Empty means the historical single-action continuation. A guarded rule
    # is a real priority-policy condition, NOT another forced prefix action.
    guarded_action: str | None = None
    guarded_conditions: tuple[PolicyCondition, ...] = ()


def ordered_prefix_executed(execution, prefix, *, first_n=None) -> bool:
    """Prove the real executor performed the requested ordered actions.

    A failed opening may still kill via auto-attacks or the continuation.
    Such a result is NOT evidence for the advertised prefix/policy candidate.
    """
    if execution is None:
        return False
    prefix = tuple(prefix)
    required = len(prefix) if first_n is None else min(len(prefix), int(first_n))
    actual = tuple(row.get('action_id') for row in execution.selected_actions[:required])
    return len(actual) == required and actual == prefix[:required]


AUTO_ONLY_FALLBACK = '__source_verified_auto_attack_only__'


def _verified_auto_fallback(ir):
    """Only a sourced, damaging player auto in the *actual starting mode*.

    A sentinel is a policy continuation (no button), not a fabricated Action.
    The existing combat event queue performs the auto-attacks and recovery.
    """
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    matches = []
    for auto in ir.auto_attacks:
        if (auto.owner_actor_id != ir.actor.id or not auto.provenance
                or (auto.required_mode_id is not None
                    and auto.required_mode_id != actor.current_mode_id)):
            continue
        if auto.swing_time_s <= 0:
            continue
        outcome = expected_auto_attack_swing(auto, actor=actor)
        if outcome['expected_damage'] > 0:
            matches.append(auto)
    return tuple(matches)


def source_prefix_envelope(ir, *, level: int, include_auto_fallback: bool = False,
                           l0_action_priority: dict[str, int] | None = None) -> dict:
    """Find executable offensive source buttons, plus repeatable direct fillers."""
    discovered = discover_source_combat_buttons(
        ir, level=level, include_resource_actions=include_auto_fallback)
    action_map = {a.id: a for a in ir.actions}
    # Preserve the original generic source-derived L0 priority contract.
    # WF334's optional domain ordering must not erase the legacy default
    # proxy coverage or silently revert to alphabetical search order.
    from src.v2.source_action_proxy import checkpoint_action_proxy_coverage
    proxy_coverage = checkpoint_action_proxy_coverage(ir,level=level)
    default_scores={r['action_id']:r['search_priority'] for r in proxy_coverage['ir_actions']}
    eligible, blocked = [], list(discovered['excluded'])
    for aid in discovered['action_ids']:
        action = action_map[aid]
        # An offensive hit may also generate or consume an IR Resource (for
        # example target-bound combo points). The generic executor already
        # supports these effects; excluding them here erased legal actions.
        # Resource-only actions remain outside this envelope because discovery
        # was called without include_resource_actions.
        ok, reason = _safe_action(action, allow_resource_actions=True)
        if ok:
            eligible.append(aid)
        else:
            blocked.append({'id': aid, 'reason': reason})
    eligible.sort(key=lambda aid:(-default_scores.get(aid,0.),aid))
    # Optional P1 L0 candidate order: a cheap scouting priority, NEVER an
    # exclusion from legality or a replacement for paid L2 scoring.
    if l0_action_priority is not None:
        if any(not isinstance(k, str) or not isinstance(v, int) or v < 0
               for k,v in l0_action_priority.items()):
            raise ValueError('INVALID_L0_CANDIDATE_PRIORITY')
        eligible.sort(key=lambda aid: (l0_action_priority.get(aid, 10**9), aid))
    target_resources = {r.id for r in ir.resources if r.scope == 'target'}
    fillers = [aid for aid in eligible if action_map[aid].cooldown_s == 0
               and (action_map[aid].cast_time_s > 0 or action_map[aid].gcd_s > 0)
               and any(_direct(e) for e in action_map[aid].effects)
               # A target-bound finisher requiring CP cannot repeat forever.
               and not any(req.get('kind') == 'resource_min' and
                           req.get('resource_id') in target_resources
                           for req in action_map[aid].requirements)]
    auto_attacks = _verified_auto_fallback(ir) if include_auto_fallback else ()
    if auto_attacks:
        fillers.append(AUTO_ONLY_FALLBACK)
    # A legal initial-mode transition is a real action, not an offensive
    # spell. Discover its destination-mode buttons from the same IR rather
    # than silently excluding all shapeshift/stance/weapon-mode builds.
    # Only paths with a sourced repeatable direct-damage continuation enter
    # this bounded pilot. Other paths remain explicit discovery gaps.
    initial_modes = [mode for mode in ir.modes if mode.initial]
    mode_paths = []
    if len(initial_modes) == 1:
        initial = initial_modes[0]
        enabled = (None if initial.enabled_action_ids is None
                   else set(initial.enabled_action_ids))
        for entry in ir.actions:
            changes = [e for e in entry.effects if isinstance(e, ModeChangeEffect)]
            if not changes:
                continue
            if len(changes) != 1 or len(entry.effects) != 1:
                blocked.append({'id':entry.id,'reason':'mode_entry_effects_unresolved'})
                continue
            target = changes[0].target_mode_id
            if target == initial.id:
                continue
            if not any(m.id == target for m in ir.modes):
                blocked.append({'id':entry.id,'reason':'unknown_destination_mode'})
                continue
            if enabled is not None and entry.id not in enabled:
                continue
            if not entry.provenance or entry.owner_actor_id != ir.actor.id:
                blocked.append({'id':entry.id,'reason':'mode_entry_provenance_or_owner_missing'})
                continue
            requirements = entry.requirements
            if (not any(r.get('kind') == 'mode_is' and r.get('value') == initial.id
                        for r in requirements)
                or any(r.get('kind') not in ('mode_is','minimum_level')
                       for r in requirements)):
                blocked.append({'id':entry.id,'reason':'unverified_initial_mode_entry_requirements'})
                continue
            try:
                too_high = any(r.get('kind') == 'minimum_level' and int(r['value']) > level
                               for r in requirements)
            except (KeyError, ValueError, TypeError):
                blocked.append({'id':entry.id,'reason':'invalid_mode_entry_minimum_level'})
                continue
            if too_high:
                continue
            destination = discover_source_combat_buttons(
                ir, level=level, mode_id=target, include_resource_actions=True)
            dest_actions = []
            for aid in destination['action_ids']:
                action = action_map[aid]
                ok, reason = _safe_action(action, allow_resource_actions=True)
                if ok:
                    dest_actions.append(aid)
                else:
                    blocked.append({'id':aid,'reason':reason,'mode_id':target})
            dest_actions.sort(key=lambda aid:(-default_scores.get(aid,0.),aid))
            if l0_action_priority is not None:
                dest_actions.sort(key=lambda aid: (l0_action_priority.get(aid, 10**9), aid))
            dest_fillers = [aid for aid in dest_actions
                if action_map[aid].cooldown_s == 0
                and (action_map[aid].cast_time_s > 0 or action_map[aid].gcd_s > 0)
                and any(_direct(e) for e in action_map[aid].effects)
                and not any(r.get('kind') == 'resource_min'
                    and r.get('resource_id') in target_resources
                    for r in action_map[aid].requirements)]
            if dest_fillers:
                mode_paths.append({'entry':entry.id,'mode_id':target,
                    'actions':tuple(dest_actions),'fillers':tuple(dest_fillers)})
            else:
                blocked.append({'id':entry.id,'reason':'mode_without_repeatable_direct_filler',
                                'mode_id':target})
    return {'actions': tuple(eligible), 'fillers': tuple(fillers), 'blocked': blocked,
            'mode_paths':tuple(mode_paths), 'source_ir_id': ir.id,
            'auto_fallback_ids':tuple(a.id for a in auto_attacks),
            'l0_priored_candidate_order_applied':l0_action_priority is not None,
            'l0_action_proxy_coverage':proxy_coverage}


def run_source_budgeted_prefix(*, class_key: str, level: int, max_evaluations: int,
                               max_prefix_length: int = 4, beam_width: int = 2,
                               ir_slice=None, schedule_incoming_attacks: bool = True,
                               l0_action_priority: dict[str, int] | None = None) -> dict:
    """Online search: each next depth>=3 trial is chosen using measured scores.

    At small action counts, all ordered length-one and length-two prefixes
    (including repeats) are attempted before exploitation, when affordable.
    The fallback is a sourced repeatable direct action, not a fabricated spell.
    If the budget is too small, all missing seeds are explicitly counted.
    """
    if max_evaluations < 1 or max_prefix_length < 2 or beam_width < 1:
        raise ValueError('positive budget/beam and prefix length >=2 required')
    ir = ir_slice if ir_slice is not None else build_game_ir_slice(class_key=class_key, level=level)
    if ir is None:
        raise ValueError('no canonical Game IR slice')
    if str(ir.actor.metadata.get('class_key','')).lower() != class_key.lower() or int(ir.actor.metadata.get('level',-1)) != level:
        raise ValueError('IR class/level mismatch')
    envelope = source_prefix_envelope(ir, level=level, l0_action_priority=l0_action_priority)
    actions, fillers = envelope['actions'], envelope['fillers']
    # An executable destination mode can be the only combat branch. Do not
    # suppress it merely because the starting mode has no repeatable filler.
    has_mode_search = any(path['fillers'] for path in envelope['mode_paths'])
    if (not actions or not fillers) and not has_mode_search:
        return {'status': 'BLOCKED_NO_EXECUTABLE_SOURCE_FALLBACK', 'envelope': envelope,
                'attempted': 0, 'evaluated': 0, 'blocked': 0, 'budget': max_evaluations}
    context = sha256(dumps({'software': SOFTWARE_VERSION, 'ir': ir.as_dict(),
                            'level': level, 'class': class_key,
                            'incoming': schedule_incoming_attacks,
                            'objective': 'representative_hp+production_combat_recovery_survival'},
                           sort_keys=True, default=str).encode()).hexdigest()
    candidates = []
    seen = set()
    action_map = {action.id: action for action in ir.actions}
    # WF328: the old prefix search *discovered* source-legal form paths but
    # never submitted one of them to CombatRuntime. Reserve early candidates
    # for each distinct reachable mode before expanding expensive pairs in
    # the initial mode. No build/rotation/legacy winner enters this queue.
    # A mode candidate is a full, executable entry -> destination opening;
    # the fallback is a sourced repeatable action of that same mode.
    mode_actions_by_entry = {}
    for path in envelope['mode_paths']:
        mode_actions_by_entry[path['entry']] = tuple(path['actions'])
        for filler in path['fillers']:
            candidate = PrefixCandidate((path['entry'],filler),filler)
            if candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)
    # A sourced destination-mode spender may start with zero resources.
    # Propose real source-defined resource producer -> consumer paths BEFORE
    # the Cartesian seeds, rather than forcing an impossible direct cast or
    # inventing an initial resource grant. Generic for all classes/levels.
    from src.game.model import ResourceChangeEffect, PeriodicResourceEffect
    for path in envelope['mode_paths']:
        destination_actions = [action_map[aid] for aid in path['actions']]
        for consumer in destination_actions:
            spent_resources = {c.resource_id for c in consumer.costs if c.amount > 0}
            if not spent_resources:
                continue
            for producer in destination_actions:
                if producer.id == consumer.id:
                    continue
                generates = any((isinstance(e, ResourceChangeEffect) and
                                 e.target in ('actor','self') and e.operation=='add'
                                 and e.amount > 0 and e.resource_id in spent_resources)
                                or (isinstance(e, PeriodicResourceEffect) and
                                    e.target in ('actor','self') and e.operation=='add'
                                    and e.amount_per_tick > 0 and e.resource_id in spent_resources)
                                for e in producer.effects)
                if not generates:
                    continue
                for filler in path['fillers']:
                    candidate = PrefixCandidate((path['entry'],producer.id,consumer.id),filler)
                    if candidate not in seen:
                        candidates.append(candidate)
                        seen.add(candidate)
    # Every initial-mode button gets its first candidate before any deep
    # Cartesian seed. Otherwise, at low budgets an early action's numerous
    # fallback combinations can starve the rest of the legal action set.
    for action in actions:
        for filler in fillers:
            candidate = PrefixCandidate((action,),filler)
            if candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)
    # Source-legal form prefixes may require setup actions (resource producer,
    # control, DoT) before their repeatable damage action. They are real paid
    # search candidates, not scoreless preference bonuses.
    for path in envelope['mode_paths']:
        for action in path['actions']:
            for filler in path['fillers']:
                candidate = PrefixCandidate((path['entry'],action),filler)
                if candidate not in seen:
                    candidates.append(candidate)
                    seen.add(candidate)
    for prefix in product(actions,repeat=2):
        for filler in fillers:
            candidate = PrefixCandidate(tuple(prefix),filler)
            if candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)
    seed_total = len(candidates)
    attempted = 0
    successes = []
    failures = []
    trace = []
    cache = {}
    child_attempts = {}

    def evaluate(candidate, *, parent=None):
        nonlocal attempted
        key = (context, candidate.prefix, candidate.fallback)
        if key in cache:
            raise AssertionError('duplicate expensive scorer invocation')
        if attempted >= max_evaluations:
            raise AssertionError('hard budget exceeded')
        attempted += 1  # charge before runtime, including failures
        policy = PolicyDefinition(
            id=f'{ir.id}:budgeted-fallback:{candidate.fallback}',
            label='Sourced repeatable fallback after ordered opening',
            rules=(PolicyRuleDefinition(id='fallback:0', action_id=candidate.fallback),),
            provenance={'authority':'source_budgeted_prefix', 'search_performed': True})
        record = {'attempt': attempted, 'prefix': list(candidate.prefix),
                  'fallback': candidate.fallback, 'parent_score': parent,
                  'cache_context_sha256': context}
        try:
            result, execution, details = _policy_combat_evaluation(
                ir, level=level, policy_override=policy,
                opening_action_ids=candidate.prefix,
                schedule_incoming_attacks=schedule_incoming_attacks)
            if not ordered_prefix_executed(execution, candidate.prefix):
                raise ValueError('BLOCKED_PREFIX_NOT_EXECUTED: '+str(
                    execution.stopped_reason if execution else 'no_execution'))
            if result is None or execution is None or not execution.timeline.target_defeated:
                raise ValueError(str(details.get('stop_reason', 'target_not_defeated') if details else 'target_not_defeated'))
            score = float(result.seconds_per_mob)
            if not isfinite(score) or score <= 0:
                raise ValueError('invalid combat+recovery objective')
            record.update({'score_s_per_mob': score, 'status': 'evaluated',
                           'kill_s': execution.timeline.target_death_s,
                           'recovery_s': details['recovery']['total_s'],
                           'incoming_hits': details['incoming_hit_count'],
                           'actor_survived': details['actor_survived'],
                           'selected_actions': [dict(x) for x in execution.selected_actions],
                           'event_count': len(execution.timeline.events)})
            successes.append(record)
        except (ValueError, RuntimeError) as exc:
            record.update({'status': 'blocked', 'reason': str(exc)})
            failures.append(record)
        cache[key] = record
        trace.append({'attempt': attempted, 'best_s_per_mob':
                      min((x['score_s_per_mob'] for x in successes), default=None),
                      'prefix': record['prefix'], 'status': record['status'],
                      'parent_score': parent})
        return record

    # Seeding is *not scored in advance*. Each evaluation invokes production
    # combat+recovery. All singles and ordered pairs are covered if affordable.
    for candidate in candidates:
        if attempted >= max_evaluations:
            break
        evaluate(candidate)
    skipped_seeds = seed_total - attempted
    # Real score-driven expansion. Every scheduler iteration observes the
    # previous expensive score; parent selection is *not* a pre-scored grid.
    while attempted < max_evaluations:
        parents = sorted((r for r in successes if len(r['prefix']) < max_prefix_length),
                         key=lambda r: (r['score_s_per_mob'], r['prefix']))
        if not parents:
            break
        # Keep several measured parents, and penalize already-expanded ones.
        # This trades exploitation against actual frontier diversity.
        proposals = []
        for parent in parents:
            parent_key = (tuple(parent['prefix']), parent['fallback'])
            # Once a sourced mode entry was used, only explore actions
            # available in the destination mode. In particular never append
            # naked caster actions after switching to Bear/Cat form.
            parent_prefix = tuple(parent['prefix'])
            extension_actions = mode_actions_by_entry.get(parent_prefix[0],actions)
            for action in extension_actions:
                candidate = PrefixCandidate(parent_prefix + (action,), parent['fallback'])
                if candidate in seen:
                    continue
                # Units are seconds/mob.  The novelty premium is a search
                # heuristic, not a gameplay constant or a predicted score.
                acquisition = (parent['score_s_per_mob']
                               + 0.25 * child_attempts.get(parent_key, 0)
                               + 0.03 * (len(candidate.prefix) - 3))
                proposals.append((acquisition, parent['score_s_per_mob'], parent_key, candidate))
        if not proposals:
            break
        # Limit exploitation to a diverse measured beam; this is an online
        # decision because parent scores and child counts change each call.
        distinct_parents = []
        for _, _, parent_key, _ in sorted(proposals, key=lambda row:(row[0],row[3].prefix)):
            if parent_key not in distinct_parents:
                distinct_parents.append(parent_key)
        allowed = set(distinct_parents[:beam_width])
        proposals = [p for p in proposals if p[2] in allowed]
        _, parent_score, parent_key, candidate = min(
            proposals, key=lambda row: (row[0], row[3].prefix, row[3].fallback))
        seen.add(candidate)
        child_attempts[parent_key] = child_attempts.get(parent_key, 0) + 1
        evaluate(candidate, parent=parent_score)
    potential = len(fillers) * sum(len(actions) ** depth for depth in range(1, max_prefix_length + 1))
    potential += sum(len(path['fillers']) * sum(len(path['actions']) ** (depth-1)
                       for depth in range(2,max_prefix_length+1))
                     for path in envelope['mode_paths'])
    winner = min(successes, key=lambda r: (r['score_s_per_mob'], r['prefix'], r['fallback'])) if successes else None
    runner_up = next((r for r in sorted(successes, key=lambda r:(r['score_s_per_mob'],r['prefix'])) if r is not winner), None)
    return {'status': 'EVALUATED_BOUNDED' if winner else 'BLOCKED_NO_KILLING_PREFIX',
            'context_sha256': context, 'class_key': class_key, 'level': level,
            'source_ir_id': ir.id, 'envelope': envelope, 'budget': max_evaluations,
            'attempted': attempted, 'evaluated': len(successes), 'blocked': len(failures),
            'seed_count': seed_total, 'seed_skipped_by_budget': skipped_seeds,
            'unattempted_prefix_fallback_pairs': max(0, potential - attempted),
            'pruned_by_search_budget': max(0, potential - attempted),
            'mode_seed_count':sum(len(p['fillers']) for p in envelope['mode_paths']),
            'paid_mode_prefix_attempts':sum(1 for r in successes + failures
                if r['prefix'] and r['prefix'][0] in mode_actions_by_entry),
            'paid_distinct_mode_entries':sorted({r['prefix'][0] for r in successes + failures
                if r['prefix'] and r['prefix'][0] in mode_actions_by_entry}),
            'winner': winner, 'runner_up': runner_up, 'trials': successes,
            'failures': failures, 'best_vs_budget': trace,
            'complete_search': False,
            'limitations': ['single fixed source actor/gear/talent state',
                            'no adaptive gear/talent proposals',
                            'bounded ordered-prefix plus sourced single-action fallback',
                            'sourced mode-entry paths evaluated through same runtime']}
