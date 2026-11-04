"""Live stat-feedback -> named gear -> fresh ordered-prefix combat/recovery search.

Every expensive call is charged to one shared budget, including failed probes
and rejected combat evaluations. The previously winning opening is NEVER copied
as a winning policy into a new gear state; each named set starts from singles
and ordered pairs with source legality enforced by the existing runtime.

Source game facts remain in the Forever canonical SQLite and its IR adapter.
This is a bounded *gear-policy* pilot with a fixed talent state, not an optimum.
"""
from __future__ import annotations

from src.game.policy import remove_combat_policy_seeds_preserve_maintenance

from dataclasses import replace
from hashlib import sha256
from json import dumps
from math import isfinite
from time import process_time_ns, monotonic_ns

from src.game.data.forever.gear import available_gear_roles, select_named_gear
from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection, executable_gear_stats
from src.game.model import PolicyDefinition, PolicyRuleDefinition, PolicyCondition
from src.game.stat_sensitivity import measure_stat_sensitivities
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_budgeted_prefix import run_source_budgeted_prefix, ordered_prefix_executed
from src.v2.source_stateful_adapter import stateful_policy_as_prefix
from src.v2.source_stateful_budgeted import _make_policy
from src.game.runtime.simulator import EventTransitionBudgetExceeded, ComputeDeadlineExceeded
from src.version import SOFTWARE_VERSION


def _gear_key(selection):
    return tuple(sorted((str(slot), int(item['item_id'])) for slot, item in selection.slots.items()))


def _fixed_opening_score(ir, record, level, incoming, *, meter=None, max_events=None):
    """A true runtime scorer for the stat-probe *same policy*, not a proxy."""
    # Reuse the controller's exact continuation semantics, including a
    # sourced auto-only fallback with no fabricated Action ID.
    policy = _make_policy(ir,record['fallback'],
        guarded_action=record.get('guarded_action'),
        guarded_conditions=tuple(PolicyCondition(**c)
            for c in record.get('guarded_conditions', ())))
    evaluation, execution, details = _policy_combat_evaluation(
        ir, level=level, policy_override=policy,
        opening_action_ids=tuple(record['prefix']), schedule_incoming_attacks=incoming,
        max_new_event_transitions=max_events)
    if meter is not None:
        meter(int(details.get('event_transitions_new',0)) if details else 0)
    if (evaluation is None or execution is None or
        not ordered_prefix_executed(execution, record['prefix']) or
        not execution.timeline.target_defeated):
        return None
    return float(evaluation.seconds_per_mob)


def run_source_budgeted_gear(*, class_key: str, level: int, max_evaluations: int,
                             search_per_gear: int = 24, initial_search: int = 24,
                             max_gear_states: int = 4, probe_stats: tuple[str, ...] = (
                                 'spell_power', 'intellect', 'spirit', 'mp5', 'stamina'),
                             probe_deltas: tuple[float, ...] = (5.0, 20.0),
                             schedule_incoming_attacks: bool = True,
                             required_level_policy: str = 'catalogue', ir_slice=None,
                             policy_search_backend: str = 'prefix',
                             max_event_transitions: int | None = None,
                             stateful_use_l1: bool = False,
                             stateful_l1_mode: str = 'value_gated',
                             stateful_use_prefix_cache: bool = False,
                             stateful_search_guarded_continuations: bool = False,
                             stateful_search_mode_paths: bool = False,
                             stateful_search_auto_fallback: bool = False,
                             stateful_family_budget_mode: str = 'legacy',
                             gear_role_exploration: bool = False,
                             exclude_unknown_item_effects: bool = False) -> dict:
    """Spend a hard shared simulation budget on evidence-led gear/policy changes.

    1. Naked source IR prefix search (actual combat/recovery), not prior winner.
    2. Finite-difference stat sensitivity using the measured opening and real
       objective; every invocation debits the same budget.
    3. Propose sourced named gear with sensitivity-weighted + diverse axes.
    4. FULLY restart prefix exploration for each new named gear selection.
    5. Re-measure derivative at the current best gear and propose again.
    No uncharged scorer replays or cross-gear cache reuse.
    """
    if not isinstance(gear_role_exploration, bool):
        raise ValueError('gear_role_exploration must be bool')
    if max_evaluations < 1 or initial_search < 1 or search_per_gear < 1 or max_gear_states < 1:
        raise ValueError('positive evaluation/search/state budgets required')
    if policy_search_backend not in ('prefix','stateful'):
        raise ValueError('unknown policy search backend')
    if stateful_search_guarded_continuations and policy_search_backend != 'stateful':
        raise ValueError('guarded continuation requires stateful policy backend')
    if max_event_transitions is not None and max_event_transitions < 1:
        raise ValueError('positive event budget required')
    if len(set(probe_stats)) != len(probe_stats):
        raise ValueError('duplicate stat probe axis')
    controller_cpu_started = process_time_ns()
    controller_wall_started = monotonic_ns()
    ir = ir_slice if ir_slice is not None else build_game_ir_slice(class_key=class_key, level=level)
    if ir is None or str(ir.actor.metadata.get('class_key','')).lower() != class_key.lower() or int(ir.actor.metadata.get('level',-1)) != level:
        raise ValueError('Game IR source class/level mismatch')
    # The P3 provider can still use a real source-naked policy and measured
    # stat sensitivities for classes without a named gear-role catalogue.
    # The later proposal loop naturally skips named gear selection when no
    # roles exist; do not invent a role or reject the P3 item-scoring path.
    gear_roles = tuple(available_gear_roles(class_key))
    ir = remove_combat_policy_seeds_preserve_maintenance(ir)  # never trust a historical priority winner
    context = sha256(dumps({'ir':ir.as_dict(),'software':SOFTWARE_VERSION,
                           'objective':'real_incoming_combat_recovery',
                           'required_level_policy':required_level_policy,
                           'exclude_unknown_item_effects':exclude_unknown_item_effects},
                          sort_keys=True,default=str).encode()).hexdigest()
    tried = 0
    successes = 0
    blockers = 0
    stages = []
    best_vs_budget = []
    selections = set()
    evaluated_roles = set()
    role_proposal_trace = []
    gear_results = []
    event_total = 0
    l1_total = 0
    cpu_total = 0
    stat_probe_cpu_ns = 0
    stat_probe_attempts = 0

    def add_events(count):
        nonlocal event_total
        event_total += int(count)
        if max_event_transitions is not None and event_total > max_event_transitions:
            raise AssertionError('shared stateful plus stat-probe event cap exceeded')

    def run_policy_search(search_ir, search_budget):
        nonlocal l1_total,cpu_total
        if policy_search_backend == 'prefix':
            return run_source_budgeted_prefix(class_key=class_key,level=level,
                max_evaluations=search_budget,ir_slice=search_ir,
                schedule_incoming_attacks=schedule_incoming_attacks)
        remaining=(15000 if max_event_transitions is None else max_event_transitions-event_total)
        if remaining<=0:
            return {'attempted':0,'evaluated':0,'blocked':0,'best_vs_budget':[],
                'winner':None,'runner_up':None,'seed_count':0,
                'seed_skipped_by_budget':0,'event_transitions':0,'status':'BUDGET_EVENTS_EXHAUSTED'}
        r=stateful_policy_as_prefix(class_key=class_key,level=level,
            max_evaluations=search_budget,ir_slice=search_ir,
            schedule_incoming_attacks=schedule_incoming_attacks,
            max_event_transitions=remaining,
            use_l1=stateful_use_l1,l1_mode=stateful_l1_mode,
            use_prefix_cache=stateful_use_prefix_cache,
            search_guarded_continuations=stateful_search_guarded_continuations,
            search_mode_paths=stateful_search_mode_paths,
            search_auto_fallback=stateful_search_auto_fallback,
            family_budget_mode=stateful_family_budget_mode)
        add_events(r['event_transitions'])
        l1_total+=r['l1_attempts']
        cpu_total+=r['cpu_ns']
        return r

    def publish_stage(name, result, selection=None, weights=None):
        nonlocal tried, successes, blockers
        if tried + result['attempted'] > max_evaluations:
            raise AssertionError('shared expensive simulation budget overrun')
        start = tried
        tried += result['attempted']
        successes += result['evaluated']
        blockers += result['blocked']
        stage = {'stage':name, 'budget_before':start, 'budget_after':tried,
                 'attempted':result['attempted'], 'evaluated':result['evaluated'],
                 'blocked':result['blocked'], 'seed_total':result.get('seed_count'),
                 'seed_skipped':result.get('seed_skipped_by_budget'),
                 'winner':result.get('winner'), 'runner_up':result.get('runner_up'),
                 'context_sha256':result.get('context_sha256'),
                 'selected_weights':weights or {},
                 'gear':None if selection is None else selection.as_dict(),
                 'search_is_fresh_from_source_singles_pairs':True,
                 'guarded_l2_attempts':result.get('guarded_l2_attempts',0),
                 'guarded_l2_verified':result.get('guarded_l2_verified',0),
                 'mode_l2_attempts':result.get('mode_l2_attempts',0),
                 'family_l2_counts':result.get('family_l2_counts',{}),
                 'guarded_l2_evidence':result.get('guarded_l2_evidence',[])}
        stages.append(stage)
        if stage['winner']:
            gear_results.append((stage['winner']['score_s_per_mob'], stage, selection))
        # An actual source-blocked search has no winner history; preserve the
        # concrete blocker instead of crashing while publishing its stage.
        for record in result.get('best_vs_budget', ()):
            incumbent = min((row[0] for row in gear_results),default=None)
            score = record['best_s_per_mob']
            # The other stages have already been completed when appended; use
            # per-stage minimum plus prior actual winners at this event.
            past = min((x['best_s_per_mob'] for x in best_vs_budget if x['best_s_per_mob'] is not None),default=None)
            current = min(x for x in (past,score) if x is not None) if past is not None or score is not None else None
            best_vs_budget.append({'attempt':start+record['attempt'],
                                   'stage':name, 'best_s_per_mob':current,
                                   'status':record['status']})
        return stage

    # In a small legal action set, allocate enough for all ordered pairs if
    # budget allows. Every scorer call is directly accounted for in W1 runtime.
    naked_budget = min(max_evaluations, initial_search)
    naked = run_policy_search(ir,naked_budget)
    publish_stage('source_naked',naked)
    if not naked.get('winner'):
        return {'status':'BLOCKED_NO_NAKED_SUCCESS', 'budget':max_evaluations,
                'attempted':tried,'evaluated':successes,'blocked':blockers,
                'stages':stages,'source_context_sha256':context,
                'event_transitions':event_total,'policy_search_backend':policy_search_backend}

    current_ir, current_record = ir, naked['winner']
    axis_set = set(executable_gear_stats(ir))
    axes = tuple(x for x in probe_stats if x in axis_set)
    sensitivity_history = []

    def reweight(ir_for_probe, policy_record, label):
        nonlocal tried, successes, blockers, stat_probe_cpu_ns, stat_probe_attempts
        # Existing sensitivity evaluator makes 1 baseline call plus up to
        # #stats x #deltas production evaluations. Reserve them beforehand.
        worst = 1 + len(axes)*len(probe_deltas)
        if not axes or tried+worst > max_evaluations or (
            max_event_transitions is not None and event_total>=max_event_transitions):
            return None
        def score(candidate_ir):
            nonlocal tried, successes, blockers, stat_probe_cpu_ns, stat_probe_attempts
            if tried>=max_evaluations:
                raise AssertionError('stat probe exhausted shared budget')
            tried += 1 # failure also charged
            stat_probe_attempts += 1
            probe_started = process_time_ns()
            try:
                cap=(None if max_event_transitions is None else max_event_transitions-event_total)
                if cap is not None and cap<=0:
                    value=None
                else:
                    value = _fixed_opening_score(candidate_ir,policy_record,level,
                        schedule_incoming_attacks,meter=add_events,max_events=cap)
            except (EventTransitionBudgetExceeded,ComputeDeadlineExceeded) as exc:
                add_events(exc.events_processed)
                value = None
            except (ValueError,RuntimeError):
                value = None
            stat_probe_cpu_ns += process_time_ns() - probe_started
            if value is None or not isfinite(value) or value<=0:
                blockers += 1
                best_vs_budget.append({'attempt':tried,'stage':'stat_probe:'+label,
                    'best_s_per_mob':best_vs_budget[-1]['best_s_per_mob'], 'status':'blocked'})
            else:
                successes += 1
                best_vs_budget.append({'attempt':tried,'stage':'stat_probe:'+label,
                    'best_s_per_mob':best_vs_budget[-1]['best_s_per_mob'], 'status':'evaluated'})
            return value
        try:
            found = measure_stat_sensitivities(ir_for_probe,stats=axes,score=score,
                                                probe_deltas=probe_deltas)
        except ValueError as exc:
            sensitivity_history.append({'stage':label,'reason':str(exc),'status':'blocked'})
            return None
        row = found.as_dict()
        row['stage']=label
        row['evaluation_budget_after']=tried
        sensitivity_history.append(row)
        return row['values']

    weights = reweight(ir,current_record,'source_naked')
    if weights is None:
        return {'status':'EVALUATED_BOUNDED','budget':max_evaluations,
                'attempted':tried,'evaluated':successes,'blocked':blockers,
                'stages':stages,'sensitivity_history':sensitivity_history,
                'event_transitions':event_total,'policy_search_backend':policy_search_backend,
                'source_context_sha256':context,'best_vs_budget':best_vs_budget,
                'winner':stages[0]}

    while len(selections)<max_gear_states and tried<max_evaluations and (
            max_event_transitions is None or event_total<max_event_transitions):
        # The shared hard cap wins: a final gear may have incomplete seed
        # coverage, which the nested controller reports explicitly.
        positives = {axis:max(0.,float(value)) for axis,value in weights.items()}
        ranks = sorted(positives, key=lambda axis:(-positives[axis],axis))
        # First candidate: actual measured stat-weight blend. After that,
        # explore a different measured axis / role, not a lexicographic grid.
        candidates=[]
        proposed_this_round=set()
        weight_vectors = [positives] if any(positives.values()) else []
        for axis in ranks:
            weight_vectors.append({axis:1.0})
        if not weight_vectors:
            weight_vectors=[{axis:1.0} for axis in axes]
        for vector in weight_vectors:
            for role in gear_roles:
                try:
                    gear=select_named_gear(class_key=class_key,level=level,
                        stat_weights=vector,role=role,
                        required_level_policy=required_level_policy,
                        exclude_unknown_item_effects=exclude_unknown_item_effects)
                except ValueError:
                    continue
                key = _gear_key(gear)
                if key in selections or key in proposed_this_round:
                    continue
                proposed_this_round.add(key)
                expected = sum(float(gear.aggregate_stats.get(a,0.))*positives.get(a,0.)
                               for a in positives)
                novelty = min((len(set(key)^set(done))/max(1,len(set(key)|set(done)))
                               for done in selections),default=1.)
                candidates.append((expected,novelty,gear,vector))
        if not candidates:
            break
        # Expected value from *measured* finite differences plus gear diversity.
        # Every proposal is rescored by a new real prefix search; estimates
        # never stand in for combat outcomes.
        # An untrusted stat derivative measured on one combat family must not
        # starve distinct source-legal equipment role families. This optional
        # scheduler spends real L2 calls on as-yet-untried catalogue roles;
        # it never awards a score to a role without running the executor.
        # When role selectors yield identical item IDs, their physical gear is
        # one configuration, not multiple paid evaluations.
        if gear_role_exploration:
            candidates.sort(key=lambda x:(x[2].role in evaluated_roles,
                                          -x[0],-x[1],_gear_key(x[2])))
        else:
            candidates.sort(key=lambda x:(-x[0],-x[1],_gear_key(x[2])))
        expected,novelty,selected,selector_weights = candidates[0]
        role_proposal_trace.append({'role':selected.role,
            'previously_evaluated':selected.role in evaluated_roles,
            'predicted_stat_gain':expected,
            'distinct_gear_candidates':len(candidates),
            'selection':dict(_gear_key(selected))})
        evaluated_roles.add(selected.role)
        selections.add(_gear_key(selected))
        geared, application = apply_gear_selection(ir,
            aggregate_stats=selected.aggregate_stats,
            selected_items=tuple(selected.slots.values()),
            source='canonical_sqlite_forever_catalogue')
        result = run_policy_search(geared,min(search_per_gear, max_evaluations-tried))
        stage=publish_stage('named_gear_'+str(len(selections)),result,
                            selection=selected,weights=selector_weights)
        stage['source_gear_role'] = selected.role
        stage['predicted_improvement_stat_seconds'] = expected
        stage['gear_novelty_fraction']=novelty
        stage['incomplete_seed_coverage']=bool(result['seed_skipped_by_budget'])
        stage['unsupported_stats']=dict(application.unsupported_stats)
        # A better *real* gear result can change which stat axis to pursue.
        if gear_results:
            _, best, best_selection = min(gear_results,key=lambda x:(x[0],x[1]['stage']))
            if best_selection is not None and best['stage']==stage['stage']:
                current_ir,current_record=geared,result['winner']
                updated = reweight(current_ir,current_record,stage['stage'])
                if updated is not None:
                    weights=updated
    ranked = sorted(gear_results,key=lambda x:(x[0],x[1]['stage']))
    if not gear_roles:
        # The naked source policy and paid sensitivity are the meaningful
        # result for P3; there is no named-gear winner to synthesize.
        winner = next((stage for stage in stages
                       if stage.get('stage') == 'source_naked'), None)
        runner_up = None
        final_status = ('EVALUATED_NAKED_ONLY_NO_GEAR_ROLES'
                        if winner is not None else 'BLOCKED_NO_KILL')
    else:
        winner = ranked[0][1] if ranked else None
        runner_up = ranked[1][1] if len(ranked)>1 else None
        final_status = 'EVALUATED_BOUNDED' if winner else 'BLOCKED_NO_KILL'
    return {'status':final_status,
            'class_key':class_key,'level':level,'source_ir_id':ir.id,
            'source_context_sha256':context,'budget':max_evaluations,
            'attempted':tried,'evaluated':successes,'blocked':blockers,
            'unspent_budget':max_evaluations-tried,
            'named_gear_states_evaluated':len(selections),
            'selected_source_gears':len(selections),
            'event_transitions':event_total, 'stateful_l1_attempts':l1_total,
            'stateful_cpu_ns':cpu_total, 'stat_probe_cpu_ns':stat_probe_cpu_ns,
            'stat_probe_attempts':stat_probe_attempts,
            'total_controller_cpu_ns':process_time_ns()-controller_cpu_started,
            'total_wall_ns':monotonic_ns()-controller_wall_started,
            'stateful_l1_mode':stateful_l1_mode, 'stateful_use_l1':stateful_use_l1,
            'max_event_transitions':max_event_transitions,
            'policy_search_backend':policy_search_backend,
            'stateful_search_guarded_continuations':stateful_search_guarded_continuations,
            'stateful_family_budget_mode':stateful_family_budget_mode,
            'gear_role_exploration':gear_role_exploration,
            'gear_role_search_skipped':not bool(gear_roles),
            'source_roles_evaluated':sorted(evaluated_roles),
            'role_proposal_trace':role_proposal_trace,
            'winner':winner,'runner_up':runner_up,
            'stages':stages,'sensitivity_history':sensitivity_history,
            'best_vs_budget':best_vs_budget,'complete_search':False,
            'limitations':['fixed naked talent state, not gear x talent optimum',
                           'named catalogue selector proposals are not exhaustive',
                           'source offensive action subset and ordered-prefix fallback only',
                           'bounded real combat/recovery search, no global optimum']}


def paid_search_winner_baseline(preferred_policy, baseline_record, opening_action_ids):
    """Return a paid search score only when its exact policy execution matches.

    The source-naked winner is reusable only for the same ordered opening,
    fallback, guarded continuation and selected-action prefix. A score from a
    different policy is not a baseline for this policy's stat perturbations.
    """
    from src.v2.source_budgeted_prefix import AUTO_ONLY_FALLBACK

    if preferred_policy is None or not isinstance(baseline_record, dict):
        return None
    provenance = getattr(preferred_policy, 'provenance', None)
    if (not isinstance(provenance, dict)
            or provenance.get('authority') != 'source_stateful_budgeted'
            or provenance.get('search_performed') is not True):
        return None

    try:
        if baseline_record.get('status') != 'evaluated':
            return None
        score = float(baseline_record.get('score_s_per_mob'))
        if not isfinite(score) or score <= 0.:
            return None

        raw_prefix = baseline_record.get('prefix', ())
        if (not isinstance(raw_prefix, (list, tuple))
                or any(not isinstance(action_id, str) or not action_id
                       for action_id in raw_prefix)):
            return None
        record_prefix = tuple(raw_prefix)
        if record_prefix != tuple(str(x) for x in opening_action_ids):
            return None
        if record_prefix:
            selected = baseline_record.get('selected_actions')
            if not isinstance(selected, (list, tuple)) or len(selected) < len(record_prefix):
                return None
            selected_prefix = tuple(
                row.get('action_id') if isinstance(row, dict) else None
                for row in selected[:len(record_prefix)])
            if selected_prefix != record_prefix:
                return None

        record_fallback = baseline_record.get('fallback')
        if not isinstance(record_fallback, str) or not record_fallback:
            return None
        guarded_action = baseline_record.get('guarded_action')
        if guarded_action is not None and not isinstance(guarded_action, str):
            return None
        raw_guarded_conditions = baseline_record.get('guarded_conditions') or ()
        if (not isinstance(raw_guarded_conditions, (list, tuple))
                or any(not isinstance(condition, dict)
                       for condition in raw_guarded_conditions)):
            return None
        expected_guarded_conditions = tuple(
            dict(condition) for condition in raw_guarded_conditions)

        rules = tuple(getattr(preferred_policy, 'rules', ()) or ())
        fallback_rules = tuple(
            rule for rule in rules if getattr(rule, 'id', None) == 'fallback:0')
        guarded_rules = tuple(
            rule for rule in rules
            if getattr(rule, 'id', None) == 'continuation:guarded')
        expected_rule_count = (
            (0 if record_fallback == AUTO_ONLY_FALLBACK else 1)
            + (0 if guarded_action is None else 1))
        if len(rules) != expected_rule_count:
            return None
        if record_fallback == AUTO_ONLY_FALLBACK:
            if fallback_rules:
                return None
        elif (len(fallback_rules) != 1
              or getattr(fallback_rules[0], 'action_id', None) != record_fallback):
            return None

        if guarded_action is None:
            if guarded_rules or expected_guarded_conditions:
                return None
        else:
            if (len(guarded_rules) != 1
                    or getattr(guarded_rules[0], 'action_id', None) != guarded_action):
                return None
            actual_guarded_conditions = []
            for condition in tuple(getattr(guarded_rules[0], 'conditions', ()) or ()):
                as_dict = getattr(condition, 'as_dict', None)
                if callable(as_dict):
                    payload = as_dict()
                elif isinstance(condition, dict):
                    payload = dict(condition)
                else:
                    return None
                if not isinstance(payload, dict):
                    return None
                actual_guarded_conditions.append(payload)
            if tuple(actual_guarded_conditions) != expected_guarded_conditions:
                return None

        if not isinstance(getattr(preferred_policy, 'id', None), str):
            return None
        return score
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def paid_source_policy_stat_witness(ir, *, stat: str, level: int,
                                   probe_deltas: tuple[float, ...] = (5., 20.),
                                   max_evaluations: int = 4,
                                   schedule_incoming_attacks: bool = True,
                                   baseline_cache: dict | None = None,
                                   opening_action_ids: tuple[str, ...] = (),
                                   preferred_policy=None,
                                   baseline_record: dict | None = None,
                                   allow_paid_winner_after_nonpositive: bool = False) -> dict:
    """Find a measured beneficial stat delta on an executable source policy.

    Keep source-IR policies first. On the Mage L30 native-item path, use the
    exact winning opening prefix as the source-policy baseline attempt; the
    empty-prefix attempt is known not to establish the kill objective. The
    selected paid winner normally remains a baseline fallback only. When its
    exact fallback action has been enriched from native PreparedV2 spell data,
    permit one largest native item-sized probe after a nonpositive source-policy
    result. Reuse the exact already-paid winner baseline; do not spend another
    baseline evaluation. Every perturbation still runs through the real
    executor; no synthetic policy, epsilon, or inferred stat weight is used.
    """
    from src.game.gear import apply_stat_delta
    from src.v2.source_budgeted_prefix import ordered_prefix_executed

    if not stat or max_evaluations < 0 or any(
        not isfinite(float(delta)) or float(delta) <= 0. for delta in probe_deltas
    ):
        raise ValueError('INVALID_SOURCE_POLICY_STAT_WITNESS_REQUEST')
    used = 0
    attempted_policies = []
    attempted_policy_sources = []
    attempted_policy_opening_action_ids = []
    baseline_failures = []
    baseline_reused_any = False
    opening_action_ids = tuple(str(x) for x in opening_action_ids)
    prefix_options = (
        (opening_action_ids,) if opening_action_ids and preferred_policy is not None
        else (((), opening_action_ids) if opening_action_ids else ((),))
    )
    cache_prefix = (id(ir), int(level), bool(schedule_incoming_attacks))
    baseline_cache = {} if baseline_cache is None else baseline_cache

    # This is a genuinely paid source-search score, not a free replay. Reuse it
    # only after exact policy/record identity has been established above.
    preferred_score = paid_search_winner_baseline(
        preferred_policy, baseline_record, opening_action_ids)
    preferred_prefix = None
    if preferred_score is not None:
        preferred_prefix = opening_action_ids
        baseline_cache[(*cache_prefix, str(preferred_policy.id),
                        preferred_prefix)] = preferred_score

    candidate_policies = []
    for policy in ir.policies:
        if not getattr(policy, 'provenance', None):
            continue
        if (preferred_policy is not None and
                str(policy.id) == str(getattr(preferred_policy, 'id', ''))):
            continue
        candidate_policies.append((policy, 'source_ir_policy'))
    # Only spend the remaining budget on the already-paid search winner after
    # the source policy probes have had their chance to reproduce the positive
    # native item-sized derivative (Mage L30 Intellect in #825).
    if preferred_policy is not None and getattr(preferred_policy, 'provenance', None):
        candidate_policies.append((preferred_policy, 'paid_search_winner'))

    # With only one paid evaluation left, a fresh baseline cannot establish a
    # stat slope. Reserve that last evaluation for a previously paid baseline.
    reusable_cached_baseline = any(
        isinstance(key, tuple) and key[:3] == cache_prefix
        and type(value) in (int, float) and isfinite(value) and value > 0
        for key, value in baseline_cache.items()
    )

    source_policy_baseline_established = False
    for policy, policy_source in candidate_policies:
        if (policy_source == 'paid_search_winner'
                and source_policy_baseline_established
                and not allow_paid_winner_after_nonpositive):
            # Without a native coefficient-backed action, the paid winner is
            # only a baseline fallback, not a second policy after a source
            # baseline has been established.
            continue
        policy_probe_deltas = tuple(probe_deltas)
        if (policy_source == 'paid_search_winner'
                and source_policy_baseline_established
                and allow_paid_winner_after_nonpositive):
            # The selected winner already has a paid baseline. One largest
            # native item-sized perturbation is the bounded alternative probe.
            policy_probe_deltas = tuple(probe_deltas[:1])
        baseline = None
        baseline_source = None
        policy_baseline_reused = False
        active_prefix = None
        if policy_source == 'paid_search_winner':
            candidate_prefixes = (
                (preferred_prefix,) if preferred_prefix is not None
                else ((opening_action_ids, ()) if opening_action_ids else ((),)))
        else:
            candidate_prefixes = prefix_options

        for candidate_prefix in candidate_prefixes:
            cache_key = (*cache_prefix, str(policy.id), tuple(candidate_prefix))
            cached_baseline = baseline_cache.get(cache_key)
            if isinstance(cached_baseline, dict) and cached_baseline.get('status') == 'FAILED':
                baseline_failures.append({
                    'policy_id': str(policy.id),
                    'opening_action_ids': list(candidate_prefix),
                    'reason': 'CACHED_' + str(cached_baseline.get('reason', 'BASELINE_FAILED')),
                })
                continue
            if cached_baseline is not None:
                try:
                    cached_value = float(cached_baseline)
                except (TypeError, ValueError):
                    cached_value = float('nan')
                if isfinite(cached_value) and cached_value > 0.:
                    baseline = cached_value
                    baseline_source = (
                        'paid_search_winner_record'
                        if policy_source == 'paid_search_winner'
                        and preferred_prefix is not None
                        and tuple(candidate_prefix) == preferred_prefix
                        else 'source_policy_baseline_cache')
                    policy_baseline_reused = True
                    baseline_reused_any = True
                    active_prefix = tuple(candidate_prefix)
                    if policy_source == 'source_ir_policy':
                        source_policy_baseline_established = True
                    break

            if used >= max_evaluations:
                break
            if reusable_cached_baseline and max_evaluations - used == 1:
                continue
            used += 1
            try:
                before, execution, details = _policy_combat_evaluation(
                    ir, level=level, policy_override=policy,
                    opening_action_ids=tuple(candidate_prefix),
                    schedule_incoming_attacks=schedule_incoming_attacks)
            except (ValueError, RuntimeError, EventTransitionBudgetExceeded,
                    ComputeDeadlineExceeded) as exc:
                reason = f'BASELINE_EVALUATION_ERROR:{type(exc).__name__}:{exc}'
                baseline_failures.append({
                    'policy_id': str(policy.id),
                    'opening_action_ids': list(candidate_prefix),
                    'reason': reason,
                })
                baseline_cache[cache_key] = {'status': 'FAILED', 'reason': reason}
                continue
            if before is None or execution is None:
                reason = 'BASELINE_NO_EVALUATION'
            elif (candidate_prefix and
                  not ordered_prefix_executed(execution, candidate_prefix)):
                reason = 'BLOCKED_PREFIX_NOT_EXECUTED'
            elif not execution.timeline.target_defeated:
                reason = 'BASELINE_TARGET_NOT_DEFEATED'
            else:
                try:
                    baseline_value = float(before.seconds_per_mob)
                except (TypeError, ValueError):
                    baseline_value = float('nan')
                reason = (None if isfinite(baseline_value) and baseline_value > 0.
                          else 'BASELINE_NONPOSITIVE_OR_NONFINITE_OBJECTIVE')
            if reason is not None:
                baseline_failures.append({
                    'policy_id': str(policy.id),
                    'opening_action_ids': list(candidate_prefix),
                    'reason': reason,
                })
                baseline_cache[cache_key] = {'status': 'FAILED', 'reason': reason}
                continue

            baseline = baseline_value
            baseline_source = 'paid_policy_baseline'
            active_prefix = tuple(candidate_prefix)
            baseline_cache[cache_key] = baseline
            if policy_source == 'source_ir_policy':
                source_policy_baseline_established = True
            break

        if baseline is None:
            if used >= max_evaluations:
                break
            continue

        attempted_policies.append(str(policy.id))
        attempted_policy_sources.append(policy_source)
        attempted_policy_opening_action_ids.append(list(active_prefix))
        for delta in policy_probe_deltas:
            if used >= max_evaluations:
                break
            used += 1
            try:
                changed = apply_stat_delta(ir, stat, float(delta))
                after, execution, details = _policy_combat_evaluation(
                    changed, level=level, policy_override=policy,
                    opening_action_ids=active_prefix,
                    schedule_incoming_attacks=schedule_incoming_attacks)
            except (ValueError, RuntimeError, EventTransitionBudgetExceeded,
                    ComputeDeadlineExceeded):
                continue
            if (after is None or execution is None or
                    (active_prefix and
                     not ordered_prefix_executed(execution, active_prefix)) or
                    not execution.timeline.target_defeated or
                    not isfinite(float(after.seconds_per_mob)) or
                    after.seconds_per_mob <= 0):
                continue
            improvement = baseline - float(after.seconds_per_mob)
            if improvement > 1e-12:
                return {
                    'status': 'MEASURED_POSITIVE_SOURCE_POLICY_WITNESS',
                    'stat': stat, 'policy_id': str(policy.id),
                    'policy_source': policy_source,
                    'weight_s_saved_per_mob_per_unit': improvement / float(delta),
                    'baseline_seconds_per_mob': baseline,
                    'perturbed_seconds_per_mob': float(after.seconds_per_mob),
                    'delta': float(delta),
                    'probe_deltas': [float(x) for x in policy_probe_deltas],
                    'requested_probe_deltas': [float(x) for x in probe_deltas],
                    'paid_winner_fallback_after_nonpositive_source': bool(
                        policy_source == 'paid_search_winner'
                        and source_policy_baseline_established
                        and allow_paid_winner_after_nonpositive),
                    'paid_evaluations': used,
                    'baseline_reused': policy_baseline_reused,
                    'baseline_source': baseline_source,
                    'opening_action_ids': list(active_prefix),
                    'attempted_policies': attempted_policies,
                    'attempted_policy_sources': attempted_policy_sources,
                    'attempted_policy_opening_action_ids': attempted_policy_opening_action_ids,
                    'baseline_failures': baseline_failures,
                    'source_ir_id': str(ir.id),
                    'engine': 'gsim_CombatRuntime',
                    'method': 'same_paid_source_policy_real_combat_and_recovery_before_after',
                }
    return {
        'status': 'NO_POSITIVE_SOURCE_POLICY_WITNESS',
        'stat': stat, 'probe_deltas': [float(x) for x in probe_deltas],
        'paid_evaluations': used,
        'baseline_reused': baseline_reused_any,
        'opening_action_ids': list(opening_action_ids),
        'attempted_policies': attempted_policies,
        'attempted_policy_sources': attempted_policy_sources,
        'attempted_policy_opening_action_ids': attempted_policy_opening_action_ids,
        'baseline_failures': baseline_failures,
    }

