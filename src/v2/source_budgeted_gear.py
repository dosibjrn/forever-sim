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
    if not available_gear_roles(class_key):
        raise ValueError('no canonical named gear role for requested class')
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
        for record in result['best_vs_budget']:
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
    axes = tuple(x for x in probe_stats if x in axis_set and x != 'weapon_dps')
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
            for role in available_gear_roles(class_key):
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
    winner = ranked[0][1] if ranked else None
    runner_up = ranked[1][1] if len(ranked)>1 else None
    return {'status':'EVALUATED_BOUNDED' if winner else 'BLOCKED_NO_KILL',
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
            'source_roles_evaluated':sorted(evaluated_roles),
            'role_proposal_trace':role_proposal_trace,
            'winner':winner,'runner_up':runner_up,
            'stages':stages,'sensitivity_history':sensitivity_history,
            'best_vs_budget':best_vs_budget,'complete_search':False,
            'limitations':['fixed naked talent state, not gear x talent optimum',
                           'named catalogue selector proposals are not exhaustive',
                           'source offensive action subset and ordered-prefix fallback only',
                           'bounded real combat/recovery search, no global optimum']}
