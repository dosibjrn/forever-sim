"""WF261: generic stateful, multi-fidelity *real-executor* policy discovery.

The game-specific facts live in canonical Game IR; this module only schedules
experiments. L0 and L1 are untrusted predictions. L2 is the sole score authority.
Snapshots are captured inside the existing production combat runtime and never
shared between different source IR/configurations or scenarios.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from itertools import product
from json import dumps
from math import isfinite, ceil
from time import process_time_ns, monotonic_ns

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import DamageEffect, PeriodicEffect, WeaponDamageEffect, ResourceChangeEffect, PolicyDefinition, PolicyRuleDefinition, PolicyCondition
from src.game.runtime.simulator import EventTransitionBudgetExceeded, ComputeDeadlineExceeded
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_budgeted_prefix import (PrefixCandidate, source_prefix_envelope,
    ordered_prefix_executed, AUTO_ONLY_FALLBACK, _verified_auto_fallback)
from src.v2.source_policy_search import _rule_options
from src.version import SOFTWARE_VERSION


def _unsafe_semantics(action):
    return [dict(x) for effect in action.effects
            for x in getattr(effect, 'unsupported_semantics', ())
            if str(x.get('status', '')).lower() not in ('explicit_approximation', 'supported', 'modeled', 'resolved')]


def _analytic_fallback(fallback_id, action_map, ir, spell_power, actor_state):
    if fallback_id != AUTO_ONLY_FALLBACK:
        return _analytic_action(action_map[fallback_id], spell_power, actor_state)
    from src.game.runtime.simulator import expected_auto_attack_swing
    autos = _verified_auto_fallback(ir)
    if not autos:
        raise ValueError('auto fallback lost its source-qualified initial-mode attack')
    # Sum the concurrent sourced auto-attack streams as an L0 rate proxy;
    # the real executor, not this analytic estimate, owns the L2 score.
    dps = sum(expected_auto_attack_swing(a, actor=actor_state)['expected_damage'] /
              a.swing_time_s for a in autos)
    return {'damage':max(.01, dps), 'delayed_damage':0., 'seconds':1., 'cost':0.}


def _analytic_action(action, spell_power, actor_state=None):
    """L0 rough damage/time/resource *ranking*, not a simulated kill."""
    dmg = 0.0
    delayed = 0.0
    for effect in action.effects:
        if isinstance(effect, DamageEffect):
            dmg += (effect.base_min + effect.base_max) / 2 + effect.spell_power_coefficient * spell_power
        elif isinstance(effect, PeriodicEffect):
            ticks = effect.duration_s / effect.tick_interval_s
            delayed += effect.total_base_damage + ticks * effect.spell_power_coefficient_per_tick * spell_power
        elif isinstance(effect, WeaponDamageEffect) and actor_state is not None:
            # Reuse the *same* generic expected-value weapon primitive as the
            # real executor. This is a ranking feature, not terminal scoring.
            from src.game.runtime.simulator import expected_weapon_damage
            dmg += expected_weapon_damage(effect, actor=actor_state)['expected_damage']
    return {'damage': max(0.0, dmg), 'delayed_damage': max(0.0, delayed),
            'seconds': max(0.05, action.cast_time_s, action.gcd_s),
            'cost': sum(max(0.0, c.amount) for c in action.costs)}


def _resource_flow_proxy(candidate, action_map, ir, filler_count):
    """Untrusted, data-driven net flow; never a legality or dominance proof.

    Source IR defines regeneration, capacity, and explicit action resource gains.
    Event-dependent gains (for example on hit) cannot be inferred from an
    analytic prefix; mark them uncertain rather than treating them as zero fact.
    Health costs are a survival risk, not recoverable casting-resource debt.
    """
    resources = {r.id: r for r in ir.resources if r.active_by_default and
                 r.owner_actor_id == ir.actor.id}
    amounts = {rid: max(0., float(r.initial_amount or 0.)) for rid, r in resources.items()}
    resource_wait_s = 0.
    uncovered = {}
    health_spent = 0.
    event_gain_unknown = set()
    for rid, r in resources.items():
        if r.event_gain_rules:
            event_gain_unknown.add(rid)
    sequence = (*candidate.prefix, *((candidate.fallback,) * filler_count))
    for aid in sequence:
        if aid == AUTO_ONLY_FALLBACK:
            # This is idle continuation while real sourced auto-attacks run.
            # The approximation never creates an executable player action.
            duration = 1.0
            for rid, r in resources.items():
                amounts[rid] += max(0., float(r.regeneration_per_s)) * duration
                if r.capacity is not None:
                    amounts[rid] = min(float(r.capacity), amounts[rid])
            continue
        action = action_map[aid]
        duration = max(.05, float(action.cast_time_s), float(action.gcd_s))
        for cost in action.costs:
            rid = cost.resource_id
            if rid not in resources:
                uncovered[rid] = uncovered.get(rid, 0.) + max(0., float(cost.amount))
                continue
            amount = max(0., float(cost.amount))
            if rid == 'health':
                health_spent += amount
            remaining = amounts[rid] - amount
            if remaining < 0:
                regen = max(0., float(resources[rid].regeneration_per_s))
                if regen > 0:
                    wait = -remaining / regen
                    resource_wait_s += wait
                    amounts[rid] = 0.
                else:
                    # Event gains, form transitions and absent regeneration may
                    # eventually make this legal. No false hard-pruning.
                    uncovered[rid] = uncovered.get(rid, 0.) + -remaining
                    amounts[rid] = 0.
            else:
                amounts[rid] = remaining
        for effect in action.effects:
            if not isinstance(effect, ResourceChangeEffect):
                continue
            # A target-bound resource (e.g. combo points) is stored on the
            # actor with scope='target' in canonical IR. Only accept a change
            # aimed at the matching scope, never apply an enemy resource gain
            # to the actor's mana/energy pool.
            rid = effect.resource_id
            if rid in resources:
                target_scope = getattr(resources[rid], 'scope', 'actor')
                is_target_resource = target_scope == 'target'
                if (effect.target in ('enemy', 'target')) != is_target_resource:
                    continue
            elif effect.target not in ('actor', 'self'):
                continue
            rid = effect.resource_id
            if rid not in resources:
                uncovered[rid] = uncovered.get(rid, 0.) + abs(float(effect.amount))
                continue
            if effect.operation == 'add':
                amounts[rid] += float(effect.amount)
            elif effect.operation == 'set':
                amounts[rid] = float(effect.amount)
            else:
                uncovered[rid] = uncovered.get(rid, 0.) + abs(float(effect.amount))
            if resources[rid].capacity is not None:
                amounts[rid] = min(float(resources[rid].capacity), amounts[rid])
            amounts[rid] = max(0., amounts[rid])
        for rid, r in resources.items():
            amounts[rid] += max(0., float(r.regeneration_per_s)) * duration
            if r.capacity is not None:
                amounts[rid] = min(float(r.capacity), amounts[rid])
    return {'net_resource_wait_s': resource_wait_s,
            'uncovered_resource_deficit': uncovered,
            'event_gain_uncertain_resources': sorted(event_gain_unknown),
            'health_spent': health_spent,
            'end_resources_proxy': amounts}


def _l0_proxy(candidate, action_map, ir, level, *, actor_state=None):
    from src.shared.leveling.objective import representative_hp
    spell_power = float(ir.actor.base_stats.get('spell_power', 0.0))
    actions = [action_map[a] for a in candidate.prefix]
    if actor_state is None:
        from src.game.runtime.state import ActorState
        actor_state = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    fallback = _analytic_fallback(candidate.fallback, action_map, ir, spell_power, actor_state)
    sequence = [_analytic_action(a, spell_power, actor_state) for a in actions]
    direct = sum(x['damage'] for x in sequence)
    # Delayed damage is deliberately discounted; the exact event scheduler
    # determines how many ticks land before death.
    delayed = sum(x['delayed_damage'] * .5 for x in sequence)
    spent = sum(x['cost'] for x in sequence)
    elapsed = sum(x['seconds'] for x in sequence)
    target_hp = float(representative_hp(level))
    remaining = max(0.0, target_hp - direct - delayed)
    filler_damage = max(0.01, fallback['damage'] + fallback['delayed_damage'] * .25)
    fallback_count = min(256, int(ceil(remaining / filler_damage)))
    predicted = elapsed + remaining / filler_damage * fallback['seconds']
    flow = _resource_flow_proxy(candidate, action_map, ir, fallback_count)
    # A gap without modeled regen is uncertainty, not an infinite score or a
    # declaration that the source action is illegal. L2 owns that decision.
    gap = sum(flow['uncovered_resource_deficit'].values())
    resource_penalty = flow['net_resource_wait_s'] + 8. * gap / max(
        1., sum(float(r.capacity or r.initial_amount or 0.) for r in ir.resources
                if r.active_by_default and r.id != 'health'))
    uncertain = bool(flow['event_gain_uncertain_resources'] or gap or candidate.guarded_action)
    return {'predicted_s': predicted + resource_penalty,
            'uncertainty_s': max(3.0, (.9 if uncertain else .55) * (predicted + resource_penalty)),
            'estimated_damage': direct + delayed,
            'estimated_resource_spent': spent,
            'resource_flow': flow,
            'conditional_continuation_not_modeled_by_l0': bool(candidate.guarded_action),
            'method': 'untrusted_analytic_IR_damage_time_net_resource_flow'}


def _l1_value_evidence(paired):
    """Online, *L2-held-out* ranking evidence for paying for L1 work.

    Absolute L1 error alone is not useful to a scheduler choosing the next
    candidate: a predictor may have a large constant bias yet order candidates
    perfectly. Conversely an apparently accurate predictor may never improve
    candidate ordering. Compare only pairs with distinguishable L2 outcomes.
    """
    samples = [x for x in paired if x.get('l1_predicted_s') is not None]
    l0_mae = sum(abs(x['l0_predicted_s'] - x['actual_s']) for x in samples) / max(1, len(samples))
    l1_mae = sum(abs(x['l1_predicted_s'] - x['actual_s']) for x in samples) / max(1, len(samples))
    comparable = 0
    l0_correct = 0
    l1_correct = 0
    for i, a in enumerate(samples):
        for b in samples[i + 1:]:
            true_diff = a['actual_s'] - b['actual_s']
            if abs(true_diff) < 1e-8:
                continue
            comparable += 1
            l0_correct += int((a['l0_predicted_s'] - b['l0_predicted_s']) * true_diff > 0)
            l1_correct += int((a['l1_predicted_s'] - b['l1_predicted_s']) * true_diff > 0)
    # Require evidence of strictly better *ordering*, not merely calibration.
    useful = (len(samples) >= 4 and comparable >= 2 and
              l1_correct >= l0_correct + 2 and l1_mae <= .9 * l0_mae)
    return {'paired_l2': len(samples), 'comparable_pairs': comparable,
            'l0_correct_pairs': l0_correct, 'l1_correct_pairs': l1_correct,
            'l0_mae_s': l0_mae, 'l1_mae_s': l1_mae,
            'l1_has_observed_ranking_value': useful}


def _condition_from_record(record):
    return PolicyCondition(**record)


def _continuation_key(candidate):
    return (candidate.guarded_action or "",
            tuple(dumps(x.as_dict(), sort_keys=True) for x in candidate.guarded_conditions))


def _continuation_record(candidate):
    return {'guarded_action': candidate.guarded_action,
            'guarded_conditions': [x.as_dict() for x in candidate.guarded_conditions]}


def _guarded_continuations(ir, actions, fillers, *, include_unguarded=False):
    """Reuse canonical policy guards; never synthesize unknown effect rules.

    The unguarded fallback is always kept. Only sourced executable actions
    admitted to this controller may appear as conditional continuations.
    """
    action_map = {a.id: a for a in ir.actions}
    choices = [(None, ())]
    for aid in actions:
        for guards in _rule_options(action_map[aid], ir.resources):
            if not guards and not include_unguarded:
                continue
            if any(guard.kind not in ('aura_missing', 'aura_present',
                                      'resource_threshold','target_control_missing')
                   for guard in guards):
                continue
            if (aid, guards) not in choices:
                choices.append((aid, guards))
    return tuple(choices)


def _make_policy(ir, fallback, *, guarded_action=None, guarded_conditions=()):
    rules = ((PolicyRuleDefinition(id='continuation:guarded', action_id=guarded_action,
                                  conditions=tuple(guarded_conditions)),)
             if guarded_action is not None else ())
    if fallback != AUTO_ONLY_FALLBACK:
        rules += (PolicyRuleDefinition(id='fallback:0', action_id=fallback),)
    return PolicyDefinition(id=f'{ir.id}:stateful:{fallback}',
                            label='Source conditional continuation after ordered opening',
                            rules=rules,
                            provenance={'authority': 'source_stateful_budgeted',
                                        'search_performed': True})


@dataclass
class _Budget:
    max_l2: int
    max_events: int
    l2_attempts: int = 0
    l1_attempts: int = 0
    events: int = 0
    cpu_ns: int = 0
    aborted: int = 0

    def remaining_events(self):
        return max(0, self.max_events - self.events)

    def charge(self, *, tier, events, cpu_ns, aborted=False):
        if tier == 'L2':
            self.l2_attempts += 1
        elif tier == 'L1':
            self.l1_attempts += 1
        self.events += int(events)
        self.cpu_ns += int(cpu_ns)
        if aborted:
            self.aborted += 1
        if self.events > self.max_events or self.l2_attempts > self.max_l2:
            raise AssertionError('hard real-compute budget violated')


def source_execution_context(ir, *, schedule_incoming_attacks: bool = True) -> str:
    """Canonical exact scorer identity for resume/cache validation.

    Engine version, complete source IR, scenario, incoming attacks and fixed
    RNG semantics all participate. Never reuse previous L2 evidence after any
    of these inputs changes.
    """
    from src.shared.leveling.objective import representative_hp
    level = int(ir.actor.metadata['level'])
    return sha256(dumps({'ir': ir.as_dict(), 'engine': SOFTWARE_VERSION,
                         'scenario': 'representative_hp+incoming+combat_recovery_survival',
                         'scenario_target_hp': representative_hp(level),
                         'incoming': schedule_incoming_attacks,
                         'seed': 'deterministic_expected_value'},
                        sort_keys=True, default=str).encode()).hexdigest()


def run_source_stateful_budgeted(*, class_key: str, level: int,
                                  max_l2_attempts: int = 24,
                                  max_event_transitions: int = 15000,
                                  max_cpu_ns: int | None = None,
                                  max_wall_ns: int | None = None,
                                  max_prefix_length: int = 4,
                                  use_l0: bool = True, use_l1: bool = True,
                                  l1_mode: str = 'value_gated',
                                  use_prefix_cache: bool = False,
                                  search_guarded_continuations: bool = False,
                                  search_mode_paths: bool = False,
                                  search_auto_fallback: bool = False,
                                  family_budget_mode: str = 'legacy',
                                  schedule_incoming_attacks: bool = True,
                                  ir_slice=None) -> dict:
    """Online L0/L1/L2 controller with one event + L2-attempt hard budget.

    All candidate scores and observations come from the existing production
    combat/recovery scorer. The scheduler never assumes proxy scores are truth.
    """
    if max_l2_attempts < 1 or max_event_transitions < 1 or max_prefix_length < 2 or (max_cpu_ns is not None and max_cpu_ns < 1) or (max_wall_ns is not None and max_wall_ns < 1):
        raise ValueError('positive budgets and prefix length >=2 required')
    if family_budget_mode not in ('legacy', 'measured_balanced'):
        raise ValueError('unknown family budget mode')
    if l1_mode not in ('value_gated', 'legacy'):
        raise ValueError('l1_mode must be value_gated or legacy')
    run_cpu_start = process_time_ns()
    run_wall_start = monotonic_ns()
    ir = ir_slice if ir_slice is not None else build_game_ir_slice(class_key=class_key, level=level)
    if ir is None or str(ir.actor.metadata.get('class_key','')).lower() != class_key.lower() or int(ir.actor.metadata.get('level', -1)) != level:
        raise ValueError('canonical IR class/level mismatch')
    envelope = source_prefix_envelope(ir, level=level,
        include_auto_fallback=search_auto_fallback)
    action_map = {a.id: a for a in ir.actions}
    sem_blocked = [{'id': a, 'reason': 'BLOCKED_UNMODELED_SOURCE_SEMANTICS',
                    'effects': _unsafe_semantics(action_map[a])}
                   for a in envelope['actions'] if _unsafe_semantics(action_map[a])]
    blocked_ids = {x['id'] for x in sem_blocked}
    actions = tuple(a for a in envelope['actions'] if a not in blocked_ids)
    fillers = tuple(a for a in envelope['fillers'] if a not in blocked_ids)
    context = source_execution_context(ir, schedule_incoming_attacks=schedule_incoming_attacks)
    if (not actions or not fillers) and not (search_mode_paths and envelope.get('mode_paths')):
        return {'status': 'BLOCKED_NO_EXECUTABLE_ACTIONS', 'source_context': context,
                'blocked_source_semantics': sem_blocked, 'attempted_l2': 0}
    controller_start_cpu = process_time_ns()
    controller_start_wall = monotonic_ns()
    continuations = (_guarded_continuations(ir, actions, fillers,
                        include_unguarded=(AUTO_ONLY_FALLBACK in fillers))
                     if search_guarded_continuations or AUTO_ONLY_FALLBACK in fillers
                     else ((None, ()),))
    # Materialize the full ordered-pair frontier only for small action sets.
    # Larger source rank families are admitted in paid, online stages. All
    # pairs (including repeats) remain eligible; none is proxy-pruned.
    staged_pairs = (len(actions) > 6 and not search_mode_paths and
                    not search_guarded_continuations)
    initial_prefixes = [(a,) for a in actions]
    if not staged_pairs:
        initial_prefixes += list(product(actions, repeat=2))
    candidates = [PrefixCandidate(tuple(prefix), fallback, guarded, conditions)
                  for prefix in initial_prefixes
                  for fallback in fillers
                  for guarded, conditions in continuations]
    # Mode-entry actions cannot be selected by initial-mode offensive button
    # discovery. Execute the real entry action as an ordered prefix, then
    # search legal destination-mode attacks and guarded continuations. Never
    # initialize directly in a form for free, or copy a policy between modes.
    mode_paths = tuple(envelope.get('mode_paths', ())) if search_mode_paths else ()
    mode_by_entry = {row['entry']:row for row in mode_paths}
    # Families are source-derived entry transitions, plus the initial-mode
    # family. They are not hardcoded classes, specs or spell names.
    family_ids = (('initial',) if actions and fillers else ()) + tuple(mode_by_entry)
    def family_of(candidate):
        return candidate.prefix[0] if candidate.prefix[0] in mode_by_entry else 'initial'
    mode_candidates = []
    # Source-legal resource-enabler dependencies deserve an early paid probe.
    # Without this, a 0-Rage actor may spend hundreds of L2 attempts trying
    # a downstream sourced action *without* its available generator, even
    # while its legal ordered generator->consumer sequence is in the frontier.
    # Derive pairs solely from action costs and executable resource effects;
    # neither the resource nor class nor spell is special-cased.
    mode_dependency_prefixes = set()
    for row in mode_paths:
        for generator_id in row['actions']:
            generator=action_map[generator_id]
            gains={e.resource_id:float(e.amount) for e in generator.effects
                   if isinstance(e,ResourceChangeEffect) and e.target in ('self','actor')
                   and e.operation=='add' and float(e.amount)>0}
            for consumer_id in row['actions']:
                if generator_id==consumer_id:
                    continue
                consumer=action_map[consumer_id]
                if any(float(c.amount)>0 and gains.get(c.resource_id,0)>=float(c.amount)
                       for c in consumer.costs):
                    mode_dependency_prefixes.add((row['entry'],generator_id,consumer_id))
    for row in mode_paths:
        destination_actions = row['actions']
        destination_guards = (_guarded_continuations(ir, destination_actions, row['fillers'])
                              if search_guarded_continuations else ((None, ()),))
        suffixes = [()]
        if max_prefix_length >= 2:
            suffixes += [(a,) for a in destination_actions]
        if max_prefix_length >= 3:
            suffixes += list(product(destination_actions, repeat=2))
        for suffix in suffixes:
            for fallback in row['fillers']:
                for guarded, conditions in destination_guards:
                    mode_candidates.append(PrefixCandidate(
                        (row['entry'], *suffix), fallback, guarded, conditions))
    candidates.extend(mode_candidates)
    # All candidate identities are sourced and deduplicated before expensive
    # calls. Mode paths get a small explicit exploration reserve below.
    candidates = list(dict.fromkeys(candidates))
    seed_count = len(candidates) + (len(actions)**2 * len(fillers) *
        len(continuations) if staged_pairs else 0)
    pair_heads_unexpanded = list(actions) if staged_pairs else []
    pair_expansion_decisions = []
    all_seen = set(candidates)
    from src.game.runtime.state import ActorState
    proxy_actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    l0 = {c: _l0_proxy(c, action_map, ir, level, actor_state=proxy_actor)
          for c in candidates}
    budget = _Budget(max_l2_attempts, max_event_transitions)
    l0_cpu_ns = process_time_ns() - controller_start_cpu
    budget.cpu_ns += l0_cpu_ns
    cache = {} if use_prefix_cache else None
    pending = list(candidates)
    ready = []
    evaluated = []
    failed = []
    observations = []
    prefix_family_count = {}
    expanded = set()
    prediction_errors = []
    l1_paired = []
    l1_decisions = []
    verification = []
    reserve_verify = 2 if max_l2_attempts >= 6 else (1 if max_l2_attempts >= 3 else 0)
    family_decisions = []

    def family_observations(fid):
        return [x for x in observations if x.get('tier') == 'L2'
                and x.get('prefix') and
                (x['prefix'][0] if x['prefix'][0] in mode_by_entry else 'initial') == fid]

    def family_choice():
        available = [fid for fid in family_ids if any(family_of(c) == fid for c in pending)]
        if not available:
            return None
        counts = {fid: len(family_observations(fid)) for fid in available}
        # Two *paid* attempts per family before comparing any L0 values across
        # families. A small budget reports untested families rather than DONE.
        pilots = [fid for fid in available if counts[fid] < 2]
        if pilots:
            return min(pilots, key=lambda fid: (counts[fid], family_ids.index(fid)))
        # Guaranteed recurrent exploration: no family can be permanently
        # excluded by an overconfident or biased analytic proxy.
        if budget.l2_attempts % 6 == 5:
            return min(available, key=lambda fid: (counts[fid], family_ids.index(fid)))
        global_costs = [max(1, x.get('events', 0)) for x in observations if x.get('tier') == 'L2']
        reference_cost = sum(global_costs) / max(1, len(global_costs))
        def measured_priority(fid):
            rows = family_observations(fid)
            verified = [x['score_s_per_mob'] for x in rows if x['status'] == 'FULL_L2_VERIFIED']
            global_verified = [x['score_s_per_mob'] for x in observations if x.get('tier') == 'L2'
                               and x['status'] == 'FULL_L2_VERIFIED']
            # A failed family is not mathematically dominated: retain the
            # uncertainty bonus and recurring exploration, but do not claim
            # its nonexistent full-cycle score is a good result.
            estimate = min(verified) if verified else (min(global_verified) + 10 if global_verified else 1000.)
            cost = sum(max(1, x.get('events', 0)) for x in rows) / len(rows)
            # Heuristic optimism and measured-compute preference, not a bound.
            return (estimate - 8. / (len(rows) ** .5) +
                    1.5 * (cost / max(1., reference_cost) - 1.),
                    counts[fid], family_ids.index(fid))
        return min(available, key=measured_priority)

    def predicted(candidate):
        base = l0[candidate]['predicted_s']
        if not use_l0:
            return float(len(candidate.prefix))
        related = [x for x in evaluated if x['prefix'][0] == candidate.prefix[0]]
        if not related:
            return base
        # Online calibrated estimate: only prior *L2* observations inform it.
        empirical = sum(x['score_s_per_mob'] for x in related) / len(related)
        return .5 * base + .5 * empirical

    def l1_worth_cost():
        if not use_l1:
            return False, 'disabled'
        if l1_mode == 'legacy':
            paired = [x for x in prediction_errors if x['l1_error_s'] is not None]
            if len(paired) < 4:
                return True, 'legacy_pilot'
            l0_mae = sum(abs(x['l0_error_s']) for x in paired) / len(paired)
            l1_mae = sum(abs(x['l1_error_s']) for x in paired) / len(paired)
            return (l1_mae <= l0_mae or budget.l2_attempts % 5 == 0), 'legacy_mae_gate'
        evidence = _l1_value_evidence(l1_paired)
        if evidence['paired_l2'] < 4 and budget.l2_attempts < 6 and budget.l1_attempts < 6:
            return True, 'calibration_pilot'
        if evidence['l1_has_observed_ranking_value']:
            return True, 'measured_ranking_value'
        # A low-rate, *paid* probe can discover a changed value of information
        # as the prefix frontier expands; never assume a proxy is always bad.
        return budget.l2_attempts > 0 and budget.l2_attempts % 32 == 0, 'no_measured_ranking_value'

    def pick_pending():
        if not pending:
            return None
        # Mode transitions are genuinely different build families. Reserve
        # recurrent exploration, but do not let their often optimistic caster-
        # state L0 proxy consume the whole budget before a single caster L2.
        # This is explicit scheduling, never a declaration of dominance.
        if family_budget_mode == 'measured_balanced':
            chosen = family_choice()
            if chosen is None:
                return None
            pool = [c for c in pending if family_of(c) == chosen]
            rows = family_observations(chosen)
            scored = [x for x in rows if x['status'] == 'FULL_L2_VERIFIED']
            # Family-local calibration; L0 absolute biases across forms must
            # not be compared as if they were terminal full-cycle scores.
            residual = (sum(x['score_s_per_mob'] - x['l0_predicted_s'] for x in scored) /
                        len(scored) if scored else 0.)
            def local_key(c):
                already = sum(x.get('prefix') == list(c.prefix) and x.get('fallback') == c.fallback
                              for x in rows)
                relevant_dependencies={p for p in mode_dependency_prefixes if p[0]==chosen}
                dependency_probed=any(tuple(x.get('prefix',())) in relevant_dependencies
                                     for x in rows)
                # Once per mode family, use a paid L2 probe of a source-derived
                # resource-unlocking sequence. It remains an ordinary search
                # candidate, never a hand-picked winner or free simulation.
                dependency_first=(int(len(rows)>0 and not dependency_probed
                    and bool(relevant_dependencies)
                    and tuple(c.prefix) not in relevant_dependencies))
                # A mode entry followed by an attack is the first meaningful
                # probe; entry-only remains legal and searchable afterwards.
                entry_only = int(chosen != 'initial' and len(c.prefix) == 1)
                return (dependency_first,already, entry_only if len(rows) < 2 else 0,
                        predicted(c) + residual if use_l0 else len(c.prefix),
                        c.prefix, c.fallback, _continuation_key(c))
            c = min(pool, key=local_key)
            family_decisions.append({'l2_attempts_before':budget.l2_attempts,
                'family':chosen,'observed_l2':len(rows),'local_proxy_residual_s':residual,
                'method':'measured_family_optimism_with_exploration_not_dominance'})
            pending.remove(c)
            return c
        mode_pending = [c for c in pending if c.prefix[0] in mode_by_entry]
        initial_pending = [c for c in pending if c.prefix[0] not in mode_by_entry]
        tested_mode_entries = {x['prefix'][0] for x in observations
            if x.get('tier') == 'L2' and x.get('prefix')
            and x['prefix'][0] in mode_by_entry}
        mode_explore = (budget.l2_attempts >= 3 and
            (budget.l2_attempts % 4 == 3 if len(tested_mode_entries) < len(mode_by_entry)
             else budget.l2_attempts % 16 == 15))
        if mode_pending and mode_explore:
            # Prefer one untried entry per source-defined destination mode,
            # then measured refinements; no synthetic free form start.
            attempted_modes = {x['prefix'][0] for x in observations
                if x.get('tier') == 'L2' and x.get('prefix')
                and x['prefix'][0] in mode_by_entry}
            c = min(mode_pending, key=lambda x:(
                x.prefix[0] in attempted_modes,
                x.guarded_action is not None,
                len(x.prefix), predicted(x), x.prefix, x.fallback))
            pending.remove(c)
            return c
        pool = initial_pending if initial_pending else pending
        # One exploration in every four L2 attempts, otherwise predicted cost.
        explore = budget.l2_attempts % 4 == 3
        def key(c):
            novelty = prefix_family_count.get(c.prefix[0], 0)
            return ((novelty, predicted(c), c.prefix, c.fallback, _continuation_key(c)) if explore else
                    (predicted(c) + .4 * novelty, novelty, c.prefix, c.fallback, _continuation_key(c)))
        c = min(pool, key=key)
        pending.remove(c)
        return c

    def verification_event_reserve():
        """Reserve exact scratch replay cost of observed top L2 candidates.

        A cached run may have used fewer *new* events; the full executor event
        count, not cache-discounted work, is needed for a fresh verification.
        This is a reservation, not an estimate of an unobserved candidate.
        """
        if not evaluated or reserve_verify == 0:
            return 0
        best = sorted(evaluated, key=lambda x: (x['score_s_per_mob'], x['prefix'], x['fallback']))
        return sum(int(x['full_executor_events']) for x in best[:reserve_verify])

    def run_tier(candidate, tier, *, force_scratch=False):
        reserved_events = 0 if force_scratch else verification_event_reserve()
        event_allowance = max(0, budget.remaining_events() - reserved_events)
        if event_allowance == 0:
            return {'status': 'BUDGET_EVENTS_EXHAUSTED', 'events': 0, 'cpu_ns': 0}
        start = process_time_ns()
        try:
            result, execution, details = _policy_combat_evaluation(
                ir, level=level, policy_override=_make_policy(
                    ir, candidate.fallback, guarded_action=candidate.guarded_action,
                    guarded_conditions=candidate.guarded_conditions),
                opening_action_ids=candidate.prefix,
                prefix_cache=(None if force_scratch else cache),
                stop_after_opening_actions=(min(2, len(candidate.prefix)) if tier == 'L1' else None),
                max_new_event_transitions=event_allowance,
                cpu_deadline_ns=(run_cpu_start + max_cpu_ns if max_cpu_ns is not None else None),
                wall_deadline_ns=(run_wall_start + max_wall_ns if max_wall_ns is not None else None),
                schedule_incoming_attacks=schedule_incoming_attacks)
            events = int(details.get('event_transitions_new', 0)) if details else 0
            cpu = process_time_ns() - start
            budget.charge(tier=tier, events=events, cpu_ns=cpu)
            # The runtime can continue with auto-attacks after a failed
            # opening and still kill the target. That is NOT an evaluation of
            # the advertised ordered prefix. Charge the work, fail closed.
            required_prefix = (min(2, len(candidate.prefix)) if tier == 'L1'
                               else len(candidate.prefix))
            if not ordered_prefix_executed(execution, candidate.prefix,
                                           first_n=required_prefix):
                return {'status':'BLOCKED_PREFIX_NOT_EXECUTED',
                        'reason':execution.stopped_reason if execution else 'no_execution',
                        'executed_prefix':([x.get('action_id') for x in
                            execution.selected_actions[:required_prefix]] if execution else []),
                        'events':events,'cpu_ns':cpu}
            if tier == 'L1':
                if details['status'] != 'PARTIAL_REAL_EXECUTOR':
                    return {'status': details['status'], 'reason': details['stop_reason'],
                            'events': events, 'cpu_ns': cpu}
                hp = float(details['target_health_remaining'])
                elapsed = max(.05, float(details['actor_time_s']))
                from src.shared.leveling.objective import representative_hp
                start_hp = float(representative_hp(level))
                dealt = max(0.0, start_hp - hp)
                filler = _analytic_fallback(candidate.fallback, action_map, ir,
                    float(ir.actor.base_stats.get('spell_power',0)), proxy_actor)
                rate = max(.01, dealt / elapsed, (filler['damage'] + .25 * filler['delayed_damage']) / filler['seconds'])
                projected = elapsed + hp / rate
                # L1 does not know recovery and queued DoT overkill; uncertain.
                projected += .2 * l0[candidate]['estimated_resource_spent'] / max(1.0, start_hp)
                return {'status': 'PARTIAL_REAL_EXECUTOR', 'predicted_s': projected,
                        'uncertainty_s': max(3.0, .6 * projected),
                        'target_hp': hp, 'actor_time_s': elapsed,
                        'resources': details['actor_resources'],
                        'pending_events': details['remaining_queue_events'],
                        'events': events, 'cpu_ns': cpu,
                        'checkpoint_hit_length': details['checkpoint_hit_length']}
            if result is None or execution is None or not execution.timeline.target_defeated:
                return {'status': 'BLOCKED_NO_KILL', 'reason': details.get('stop_reason') if details else 'no_result',
                        'target_hp_remaining': (execution.timeline.target_end_health if execution else None),
                        'resources_after': (dict(execution.timeline.resources_after) if execution else {}),
                        'selected_action_count': (len(execution.selected_actions) if execution else 0),
                        'events': events, 'cpu_ns': cpu}
            return {'status': 'FULL_L2_VERIFIED', 'score_s_per_mob': float(result.seconds_per_mob),
                    'kill_s': float(execution.timeline.target_death_s),
                    'recovery_s': float(details['recovery']['total_s']),
                    'survived': bool(details['actor_survived']),
                    'events': events, 'cpu_ns': cpu,
                    'checkpoint_hit_length': details['checkpoint_hit_length'],
                    'full_timeline_events': len(execution.timeline.events),
                    'full_executor_events': int(details['event_transitions_total']),
                    'actions': [dict(x) for x in execution.selected_actions]}
        except ComputeDeadlineExceeded as exc:
            cpu = process_time_ns() - start
            budget.charge(tier=tier, events=exc.events_processed, cpu_ns=cpu, aborted=True)
            return {'status': f'BUDGET_{exc.kind}_DEADLINE', 'events': exc.events_processed, 'cpu_ns': cpu}
        except EventTransitionBudgetExceeded as exc:
            cpu = process_time_ns() - start
            budget.charge(tier=tier, events=exc.events_processed, cpu_ns=cpu, aborted=True)
            return {'status': 'BUDGET_EVENT_TRANSITIONS', 'events': exc.events_processed, 'cpu_ns': cpu}
        except (ValueError, RuntimeError) as exc:
            cpu = process_time_ns() - start
            # The attempt is still charged, even if executor failed before
            # dispatching an event. This is not a successful evaluation.
            budget.charge(tier=tier, events=0, cpu_ns=cpu, aborted=True)
            return {'status': 'BLOCKED_EXECUTOR', 'reason': str(exc), 'events': 0, 'cpu_ns': cpu}

    def admit_next_pair_head():
        """Online, budget-aware staged pairs; no rank/family hard-pruning.

        Each head is eventually expanded with EVERY legal ordered second
        action, including itself, and every continuation filler. Observed L2
        successes determine the preferred head; every other admission favors
        an unobserved head to protect exploration. The full theoretical seed
        count is reported even when the compute budget ends early.
        """
        if not pair_heads_unexpanded:
            return
        head_evidence = {a: [x for x in observations if x.get('tier') == 'L2'
            and x.get('prefix') and x['prefix'][0] == a and
            x.get('status') == 'FULL_L2_VERIFIED'] for a in pair_heads_unexpanded}
        expanded_count = len(actions) - len(pair_heads_unexpanded)
        if expanded_count % 2 == 0 and any(head_evidence.values()):
            head = min(pair_heads_unexpanded, key=lambda a: (
                min((x['score_s_per_mob'] for x in head_evidence[a]), default=float('inf')),
                a))
            method = 'observed_L2_head_score'
        else:
            head = min(pair_heads_unexpanded, key=lambda a: (
                len([x for x in observations if x.get('tier') == 'L2' and
                     x.get('prefix') and x['prefix'][0] == a]), a))
            method = 'least_observed_head_exploration'
        pair_heads_unexpanded.remove(head)
        count = 0
        for second in actions:
            for fallback in fillers:
                for guarded, conditions in continuations:
                    c = PrefixCandidate((head, second), fallback, guarded, conditions)
                    if c in all_seen:
                        continue
                    all_seen.add(c)
                    candidates.append(c)
                    pending.append(c)
                    l0[c] = _l0_proxy(c, action_map, ir, level, actor_state=proxy_actor)
                    count += 1
        pair_expansion_decisions.append({'l2_attempts_before':budget.l2_attempts,
            'head':head,'new_pairs':count,'method':method})

    def time_remaining():
        return ((max_cpu_ns is None or process_time_ns() - run_cpu_start < max_cpu_ns) and
                (max_wall_ns is None or monotonic_ns() - run_wall_start < max_wall_ns))

    while (budget.l2_attempts < max_l2_attempts - reserve_verify and
           budget.remaining_events() > verification_event_reserve() and time_remaining()):
        # One new source-rank head per four paid L2 attempts, after the first
        # two pilots. Unspent seeds are retained as unexpanded, NOT dominated.
        if (staged_pairs and pair_heads_unexpanded and budget.l2_attempts >= 2 and
                budget.l2_attempts >= 2 + 4 * len(pair_expansion_decisions)):
            admit_next_pair_head()
        # Two genuine partial rollouts compete before each L2 call. Each
        # observation and its event work is charged to the same global budget.
        while (pending and len(ready) < (1 if family_budget_mode == 'measured_balanced' else (2 if use_l1 else 1)) and
               budget.remaining_events() > verification_event_reserve() and time_remaining()):
            c = pick_pending()
            if c is None:
                break
            current_l1, l1_reason = l1_worth_cost()
            l1_decisions.append({'l2_attempts_so_far': budget.l2_attempts,
                                 'use_l1': current_l1, 'reason': l1_reason})
            if current_l1:
                partial = run_tier(c, 'L1')
                observations.append({'tier': 'L1', 'prefix': list(c.prefix),
                                     'fallback': c.fallback, **_continuation_record(c), **partial})
                if partial['status'] != 'PARTIAL_REAL_EXECUTOR':
                    failed.append({'tier': 'L1', 'prefix': list(c.prefix),
                                   'fallback': c.fallback, **_continuation_record(c), **partial})
                    continue
                prediction = partial['predicted_s']
            else:
                prediction = predicted(c)
                if use_l1:
                    observations.append({'tier': 'L0', 'prefix': list(c.prefix),
                                         'fallback': c.fallback, **_continuation_record(c),
                                         'status': 'L1_SKIPPED_COST_AWARE',
                                         'reason': l1_reason, 'predicted_s': prediction})
            ready.append((c, prediction, current_l1))
        if not ready:
            # Extend only from *measured* L2 candidates, never proxy-only.
            if not pending and evaluated:
                for parent in sorted(evaluated, key=lambda x:x['score_s_per_mob'])[:3]:
                    if len(parent['prefix']) >= max_prefix_length:
                        continue
                    for a in (mode_by_entry[parent['prefix'][0]]['actions']
                              if parent['prefix'][0] in mode_by_entry else actions):
                        c = PrefixCandidate(tuple(parent['prefix']) + (a,), parent['fallback'],
                                            parent.get('guarded_action'),
                                            tuple(_condition_from_record(x) for x in parent.get('guarded_conditions', ())))
                        if c not in all_seen:
                            all_seen.add(c)
                            pending.append(c)
                            l0[c] = _l0_proxy(c, action_map, ir, level, actor_state=proxy_actor)
                if pending:
                    continue
            break
        # Exploit predicted terminal cost, reserve every fifth call for an
        # uncertain/different family; neither proxy is allowed to declare win.
        explore_l2 = budget.l2_attempts % 5 == 4
        untried_mode_ready = [i for i, (candidate, _, _) in enumerate(ready)
            if candidate.prefix[0] in mode_by_entry and
            not any(x.get('tier') == 'L2' and x.get('prefix') and
                    x['prefix'][0] == candidate.prefix[0] for x in observations)]
        pool = (untried_mode_ready if explore_l2 and untried_mode_ready
                else range(len(ready)))
        idx = min(pool, key=lambda i: (
            -l0[ready[i][0]]['uncertainty_s'] if explore_l2 else ready[i][1],
            ready[i][0].prefix, ready[i][0].fallback, _continuation_key(ready[i][0])))
        c, l1_prediction, had_l1 = ready.pop(idx)
        record = run_tier(c, 'L2')
        prefix_family_count[c.prefix[0]] = prefix_family_count.get(c.prefix[0], 0) + 1
        evidence = {'tier': 'L2', 'attempt': budget.l2_attempts, 'prefix': list(c.prefix),
                    'fallback': c.fallback, **_continuation_record(c),
                    'l0_predicted_s': l0[c]['predicted_s'],
                    'l1_predicted_s': l1_prediction if had_l1 else None,
                    **record}
        if record['status'] == 'FULL_L2_VERIFIED':
            evaluated.append(evidence)
            prediction_errors.append({'l0_error_s': l0[c]['predicted_s'] - record['score_s_per_mob'],
                                      'l1_error_s': (l1_prediction - record['score_s_per_mob']) if had_l1 else None})
            if had_l1:
                l1_paired.append({'l0_predicted_s': l0[c]['predicted_s'],
                                  'l1_predicted_s': l1_prediction,
                                  'actual_s': record['score_s_per_mob'],
                                  'prefix': list(c.prefix), 'fallback': c.fallback})
        else:
            failed.append(evidence)
        observations.append(evidence)
        observations.append({'tier': 'progress', 'l2_attempts': budget.l2_attempts,
                             'event_transitions': budget.events,
                             'cpu_ns': budget.cpu_ns,
                             'best_verified_s_per_mob': min((x['score_s_per_mob'] for x in evaluated), default=None)})
        # Extend the search from real scored winners before exhausting the
        # seed pool only after a meaningful exploration tranche.
        if budget.l2_attempts >= min(seed_count, 8) and budget.l2_attempts % 4 == 0:
            for parent in sorted(evaluated, key=lambda x: x['score_s_per_mob'])[:2]:
                if len(parent['prefix']) >= max_prefix_length:
                    continue
                for a in (mode_by_entry[parent['prefix'][0]]['actions']
                          if parent['prefix'][0] in mode_by_entry else actions):
                    c2 = PrefixCandidate(tuple(parent['prefix']) + (a,), parent['fallback'],
                                         parent.get('guarded_action'),
                                         tuple(_condition_from_record(x) for x in parent.get('guarded_conditions', ())))
                    if c2 not in all_seen:
                        all_seen.add(c2)
                        pending.append(c2)
                        l0[c2] = _l0_proxy(c2, action_map, ir, level, actor_state=proxy_actor)
    ordered = sorted(evaluated, key=lambda x: (x['score_s_per_mob'], x['prefix'], x['fallback']))
    # Independent scratch L2 verification, never from a reused checkpoint.
    # Reserve attempt capacity; event budget is still a hard shared guard.
    for candidate_record in ordered[:reserve_verify]:
        if budget.l2_attempts >= max_l2_attempts or budget.remaining_events() == 0 or not time_remaining():
            break
        candidate = PrefixCandidate(tuple(candidate_record['prefix']), candidate_record['fallback'],
                                    candidate_record.get('guarded_action'),
                                    tuple(_condition_from_record(x) for x in candidate_record.get('guarded_conditions', ())))
        check = run_tier(candidate, 'L2', force_scratch=True)
        parity = (check['status'] == 'FULL_L2_VERIFIED' and
                  abs(check['score_s_per_mob'] - candidate_record['score_s_per_mob']) <= 1e-10)
        verification.append({'prefix': list(candidate.prefix), 'fallback': candidate.fallback,
                             **_continuation_record(candidate),
                             'matches_scratch': parity, **check})
    # A budget-aborted scratch replay is not evidence of equality. Report it
    # separately from a genuine mismatch; never silently call an unchecked
    # runner-up "verified" just because the event cap was obeyed.
    required_verification = min(reserve_verify, len(ordered))
    verification_complete = (required_verification > 0 and
                             len(verification) == required_verification and
                             all(x['matches_scratch'] for x in verification))
    verification_failed = any(not x['matches_scratch'] and
                              x['status'] not in ('BUDGET_EVENT_TRANSITIONS',
                                                  'BUDGET_CPU_DEADLINE',
                                                  'BUDGET_WALL_DEADLINE')
                              for x in verification)
    seed_keys = {(c.prefix, c.fallback, _continuation_key(c)) for c in candidates}
    attempted_seed_records = [x for x in observations if x['tier'] == 'L2' and
                              (tuple(x['prefix']), x['fallback'],
                               (x.get('guarded_action'), tuple(dumps(y, sort_keys=True)
                                  for y in x.get('guarded_conditions', ())))) in seed_keys]
    seed_attempted = len(attempted_seed_records)
    seed_evaluated = sum(x['status'] == 'FULL_L2_VERIFIED' for x in attempted_seed_records)
    return {'status': ('BLOCKED_VERIFICATION_MISMATCH' if verification_failed else
                       'BEST_KNOWN_BOUNDED' if ordered and verification_complete else
                       'BEST_KNOWN_BOUNDED_UNVERIFIED' if ordered else 'BLOCKED_NO_L2_KILL'),
            'class_key': class_key, 'level': level, 'source_context': context,
            'source_ir_id': ir.id, 'engine': SOFTWARE_VERSION,
            'source_actions': list(actions), 'source_fillers': list(fillers),
            'auto_fallback_ids':list(envelope.get('auto_fallback_ids', ())),
            'auto_fallback_search_enabled':bool(search_auto_fallback),
            'source_mode_paths':list(mode_paths),
            'source_mode_resource_dependencies': [list(p) for p in sorted(mode_dependency_prefixes)],
            'available_source_mode_paths':list(envelope.get('mode_paths', ())),
            'mode_path_search_enabled':bool(search_mode_paths),
            'family_budget_mode':family_budget_mode,
            'family_decisions':family_decisions,
            'family_l2_counts':{fid:len(family_observations(fid)) for fid in family_ids},
            'family_verified_best':{fid:min((x['score_s_per_mob'] for x in family_observations(fid)
                if x['status']=='FULL_L2_VERIFIED'), default=None) for fid in family_ids},
            'mode_l2_attempts':sum(1 for x in observations if x.get('tier')=='L2'
                and x.get('prefix') and x['prefix'][0] in mode_by_entry),
            'guarded_continuation_options': len(continuations),
            'blocked_source_semantics': sem_blocked,
            'seed_count': seed_count, 'staged_pairs':staged_pairs,
            'unexpanded_pair_heads':list(pair_heads_unexpanded),
            'pair_expansion_decisions':pair_expansion_decisions,
            'seed_attempted_l2': seed_attempted,
            'seed_evaluated_l2': seed_evaluated,
            'seed_blocked_l2': seed_attempted - seed_evaluated,
            'seed_unattempted': seed_count - seed_attempted,
            'l0_candidates_generated': len(l0), 'l1_attempts': budget.l1_attempts,
            'l1_mode': l1_mode, 'l1_value_evidence': _l1_value_evidence(l1_paired),
            'l1_decisions': l1_decisions,
            'l2_attempts': budget.l2_attempts, 'l2_evaluated': len(evaluated),
            'blocked_or_aborted': len(failed), 'event_transitions': budget.events,
            'cpu_ns': budget.cpu_ns, 'l0_cpu_ns': l0_cpu_ns,
            'total_controller_cpu_ns': process_time_ns() - controller_start_cpu,
            'total_wall_ns': monotonic_ns() - controller_start_wall,
            'full_run_cpu_ns': process_time_ns() - run_cpu_start,
            'full_run_wall_ns': monotonic_ns() - run_wall_start,
            'max_l2_attempts': max_l2_attempts,
            'max_event_transitions': max_event_transitions,
            'max_cpu_ns': max_cpu_ns, 'max_wall_ns': max_wall_ns,
            'cache_entries': len(cache) if cache is not None else 0,
            'cache_hits_l2': sum(x.get('checkpoint_hit_length',0) > 0 for x in evaluated),
            'winner': ordered[0] if ordered else None,
            'runner_up': ordered[1] if len(ordered) > 1 else None,
            'predictions': prediction_errors, 'scratch_verification': verification,
            'verification_reserved_attempts': reserve_verify,
            'verification_required': required_verification,
            'verification_completed': sum(x['matches_scratch'] for x in verification),
            'verification_complete': verification_complete,
            'verification_event_reserve_at_finish': verification_event_reserve(),
            'observations': observations,
            'complete_search': False,
            'limitations': ['L0/L1 predictions are not authoritative',
                            'expected-value combat with current source fidelity gaps',
                            'bounded policy prefixes; optional guarded source continuation',
                            'gear/talent configuration fixed for this policy pilot']}
