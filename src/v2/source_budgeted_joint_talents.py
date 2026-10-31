"""On-demand real combat/recovery gear x talent x ordered-prefix controller.

Every talent allocation invokes a fresh, fully charged gear+policy search. A
source-legal neighbor frontier is expanded from *observed* build scores; it
never enumerates and scores a Cartesian gear x talent grid in advance.
"""
from __future__ import annotations

from src.game.policy import remove_combat_policy_seeds_preserve_maintenance

from collections import Counter
from dataclasses import replace
from hashlib import sha256
from json import dumps
from math import isfinite
from time import process_time_ns

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_frontier import allocation_key, source_legal_talent_neighbors
from src.game.data.forever.source_checkpoint_p2_optimizer import (rank_opportunity_frontier,
    proposal_l0_opportunity)
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.game.gear import apply_gear_selection
from src.game.runtime.simulator import EventTransitionBudgetExceeded, ComputeDeadlineExceeded
from src.game.model.ir import PeriodicEffect, PeriodicHealEffect, ResourceScaledPeriodicEffect
from src.v2.source_budgeted_gear import run_source_budgeted_gear, _fixed_opening_score
from src.v2.source_legal_beam import source_tier_unlock_corridors
from src.version import SOFTWARE_VERSION


def run_source_budgeted_joint_talents(*, class_key: str, level: int,
                                      max_evaluations: int, evaluations_per_talent: int = 72,
                                      initial_search: int = 24, search_per_gear: int = 24,
                                      max_gear_states: int = 3, ir_slice=None,
                                      initial_allocation=None,
                                      talent_l0_certificate: dict | None = None,
                                      schedule_incoming_attacks: bool = True,
                                      policy_search_backend: str = 'prefix',
                                      max_event_transitions: int | None = None,
                                      stateful_use_l1: bool = False,
                             stateful_l1_mode: str = 'value_gated',
                                      stateful_use_prefix_cache: bool = False,
                                      stateful_search_guarded_continuations: bool = False,
                                      measure_parent_fixed_policy: bool = False,
                                      stateful_search_mode_paths: bool = False,
                                      stateful_search_auto_fallback: bool = False,
                                      stateful_family_budget_mode: str = 'legacy',
                                      gear_role_exploration: bool = False,
                                      required_level_policy: str = 'catalogue',
                                      exclude_unknown_item_effects: bool = False,
                                      talent_corridor_reserve: int = 0,
                                      talent_screening_attempts: int = 0,
                                      post_talent_refinement_budget: int = 0,
                                      probe_stats: tuple[str, ...] = ('spell_power', 'intellect', 'spirit', 'mp5', 'stamina'),
                                      probe_deltas: tuple[float, ...] = (5.0, 20.0)) -> dict:
    """Bounded talent frontier; no uncharged combat/recovery evaluations.

    The talent rank/point neighborhood is generated from canonical Game IR.
    Ranking depends on measured objective, observed marginal, and novelty.
    The first candidate is source-empty unless an explicitly provided legal
    initial allocation is requested. Neither OG nor an old winner is seeded.
    """
    if max_evaluations < 1 or evaluations_per_talent < 1 or initial_search < 1 or search_per_gear < 1 or (max_event_transitions is not None and max_event_transitions<1):
        raise ValueError('positive evaluation budgets required')
    if not isinstance(post_talent_refinement_budget,int) or not 0 <= post_talent_refinement_budget < max_evaluations:
        raise ValueError('post_talent_refinement_budget must be less than total budget')
    if not isinstance(talent_corridor_reserve,int) or talent_corridor_reserve < 0:
        raise ValueError('talent_corridor_reserve must be nonnegative integer')
    if (not isinstance(talent_screening_attempts, int) or talent_screening_attempts < 0
            or talent_screening_attempts >= max_evaluations):
        raise ValueError('talent_screening_attempts must be nonnegative and smaller than total budget')
    if required_level_policy not in ('catalogue', 'observed'):
        raise ValueError('required_level_policy must be catalogue or observed')
    if stateful_search_guarded_continuations and policy_search_backend != 'stateful':
        raise ValueError('guarded continuation requires stateful policy backend')
    ir = ir_slice if ir_slice is not None else build_game_ir_slice(class_key=class_key,level=level)
    if (str(ir.actor.metadata.get('class_key','')).lower() != class_key.lower()
            or int(ir.actor.metadata.get('level',-1)) != level):
        raise ValueError('source IR class/level mismatch')
    ir = remove_combat_policy_seeds_preserve_maintenance(ir)
    # L0 rank audit is optional for older checkpoints. When provided it must
    # match the same checkpoint and contains every sourced talent rank delta.
    # It is used for candidate ordering only; never substitutes for paid L2.
    l0_talent_frontier = (rank_opportunity_frontier(talent_l0_certificate,
                         class_key=class_key,level=level)
                         if talent_l0_certificate is not None else None)
    l0_priority_queries = 0
    l0_talent_rank_order = (sorted(l0_talent_frontier['ranks'],
        key=lambda r: (-r['relative_opportunity'],r['conditional'],r['talent_id'],r['rank']))
        if l0_talent_frontier is not None else [])
    initial = dict(initial_allocation or {})
    validate_talent_selection(ir,initial,level=level)
    context = sha256(dumps({'ir':ir.as_dict(), 'version':SOFTWARE_VERSION,
                           'incoming':schedule_incoming_attacks,
                           'objective':'combat_recovery_survival',
                           'required_level_policy':required_level_policy,
                           'exclude_unknown_item_effects':exclude_unknown_item_effects,
                           'gear_role_exploration':gear_role_exploration,
                           'talent_corridor_reserve':talent_corridor_reserve,
                           'talent_screening_attempts':talent_screening_attempts,
                           'post_talent_refinement_budget':post_talent_refinement_budget,
                           'probe_stats':probe_stats, 'probe_deltas':probe_deltas,
                           'talent_l0_rank_count':0 if l0_talent_frontier is None else l0_talent_frontier['rank_count']},sort_keys=True,default=str).encode()).hexdigest()
    pending = {allocation_key(initial): {'parent':None, 'parent_score':None,
                 'operation':'initial', 'changed_ids':()}}
    # REUSE the existing source-tier corridor generator. The original beam's
    # first-N ordering is tree-biased; interleave canonical tree identities
    # and prefer the deepest reachable row in each tree. No held-out allocation,
    # historical gear or policy enters this proposal queue. All corridors are
    # individually source-validated and only scored through the paid L2 path.
    corridors = source_tier_unlock_corridors(ir,level=level,max_corridors=256)
    tree_of = {t.id:t.tree_key for t in ir.talents}
    row_of = {t.id:int(t.metadata.get('row') or 0) for t in ir.talents}
    grouped = {}
    for allocation in corridors:
        key = allocation_key(allocation)
        if key == allocation_key(initial):
            continue
        validate_talent_selection(ir,dict(key),level=level)
        trees = {tree_of[f] for f in allocation}
        if len(trees) != 1:
            raise AssertionError('cross-tree source corridor')
        tree = next(iter(trees))
        grouped.setdefault(tree,[]).append(key)
    for tree in grouped:
        grouped[tree].sort(key=lambda key:(-max(row_of[f] for f,_ in key),
                                              -sum(v for _,v in key),key))
    reserved_corridors = []
    while any(grouped.values()) and len(reserved_corridors) < talent_corridor_reserve:
        for tree in sorted(grouped):
            if grouped[tree] and len(reserved_corridors)<talent_corridor_reserve:
                key = grouped[tree].pop(0)
                if key not in reserved_corridors:
                    reserved_corridors.append(key)
    for key in reserved_corridors:
        pending.setdefault(key,{'parent':None,'parent_score':None,
                'operation':'source_tier_corridor','changed_ids':tuple(f for f,_ in key),
                'allocation':key})
    visited = set()
    stages = []
    attempted = evaluated = blocked = 0
    total_events = total_l1 = 0
    fixed_policy_attempts = fixed_policy_events = fixed_policy_cpu_ns = 0
    stage_by_key = {}
    fixed_policy_challengers = []
    talent_screening = []
    screening_cpu_ns = 0
    screened_keys = set()
    best_curve = []
    rejection_counts = Counter()
    legal_seen = set(pending)
    marginal_by_family = {}
    talent_map = {t.id:t for t in ir.talents}
    action_map = {a.id:a for a in ir.actions}

    def source_l0_relevance(key,row):
        nonlocal l0_priority_queries
        if l0_talent_frontier is None:
            return 0.0
        l0_priority_queries += 1
        parent = dict(row['parent']) if row['parent'] is not None else {}
        return proposal_l0_opportunity(l0_talent_frontier,parent,dict(key))['l0_opportunity']

    def action_relevance(row):
        # Cheap structural proposal prior from source modifiers and actions
        # actually observed in the *parent* combat, never a fake score.
        used = set(row.get('parent_used_actions', ()))
        families = {action_map[aid].family_key for aid in used if aid in action_map}
        relevance = 0.0
        for tid in row['changed_ids']:
            talent = talent_map.get(tid)
            if talent is None:
                continue
            rank = max(1,dict(row['allocation']).get(tid,1))
            definition = next((r for r in talent.ranks if r.rank==rank),None)
            if definition is None:
                continue
            for mod in definition.modifiers:
                if mod.target_type == 'action_family' and mod.target_id in families:
                    relevance += 2.0
                elif mod.target_type == 'actor_stat':
                    relevance += 0.5
                elif mod.target_type == 'action_filter':
                    if mod.target_id == 'periodic':
                        relevant = any(any(isinstance(e,(PeriodicEffect,PeriodicHealEffect,ResourceScaledPeriodicEffect))
                            for e in action_map[aid].effects) for aid in used if aid in action_map)
                    else:
                        relevant = bool(used)
                    if relevant:
                        relevance += 0.6
        return relevance
    selection_trace = []
    best_score = None

    def choose_next():
        # An actual experiment is selected online; reserve one source-legal
        # corridor per canonical tree before local score-based expansion.
        # The empty root is always evaluated first. Unspent reserves are
        # visible, never reported as evaluated or as proven optimal.
        if not stages:
            return allocation_key(initial), pending[allocation_key(initial)]
        # A previously paid full-L2 fixed-gear/policy screening result may
        # guide which talent receives a FRESH joint search. It is not itself
        # a joint winner, and never seeds the historical oracle.
        screened = [(key,row) for key,row in pending.items()
                    if row.get('screened_score') is not None]
        if screened:
            key,row = min(screened, key=lambda entry:
                (entry[1]['screened_score'], entry[0]))
            return key,row
        for key in reserved_corridors:
            if key in pending:
                return key, pending[key]
        # Preserve an early source-family exploration reserve. Without it a
        # locally good first rank can consume the whole budget in transfers
        # before an independently promising other tree is ever simulated.
        root = allocation_key(initial)
        root_families_tried = {family for s in stages
            if s.get('parent_allocation')==dict(root)
            for family in s.get('allocation',{}) if family not in dict(root)}
        exploration_quota = min(3, sum(1 for t in ir.talents if any(r.modifiers for r in t.ranks)))
        if len(root_families_tried)<exploration_quota:
            root_sweeps = [(key,row) for key,row in pending.items()
                if row['parent']==root and row['operation']=='rank_sweep'
                and any(f not in root_families_tried for f in row['changed_ids'])]
            if root_sweeps:
                return min(root_sweeps,key=lambda pair:(-source_l0_relevance(*pair),-action_relevance(pair[1]),pair[0]))
        # Parent predictions are recomputed after each actual simulator result;
        # rank sweep and family novelty are exploration bonuses, not scores.
        options = []
        families_tried = {family for s in stages for family,rank in s['allocation'].items() if rank}
        for key, row in pending.items():
            parent_score = row['parent_score']
            if parent_score is None:
                estimate = 1e6  # first state
            else:
                estimate = parent_score
                parent_alloc = dict(row['parent']) if row['parent'] is not None else {}
                target_alloc = dict(key)
                for family in row['changed_ids']:
                    if family in marginal_by_family:
                        estimate += marginal_by_family[family] * (target_alloc.get(family,0)-parent_alloc.get(family,0))
            new_families = sum(1 for family in row['changed_ids'] if family not in families_tried)
            novelty = new_families + (0.3 if row['operation']=='rank_sweep' else 0.0)
            # 1 in 4 selections explicitly explores an untried family.
            if stages and len(stages)%4==3:
                priority = (-novelty, -source_l0_relevance(key,row), -action_relevance(row), estimate, key)
            else:
                priority = (estimate-0.5*novelty-0.35*action_relevance(row)-0.15*source_l0_relevance(key,row), -novelty, key)
            options.append((priority,key,row))
        _, key, row = min(options, key=lambda x:x[0])
        return key,row

    core_budget=max_evaluations-post_talent_refinement_budget
    while pending and attempted < core_budget and (max_event_transitions is None or total_events < max_event_transitions):
        key, proposal = choose_next()
        pending.pop(key)
        if key in visited:
            raise AssertionError('duplicate talent state evaluation')
        visited.add(key)
        allocation = dict(key)
        remaining = core_budget-attempted
        budget = min(evaluations_per_talent,remaining)
        parent_stage = stage_by_key.get(proposal['parent'])
        # A real fixed-policy marginal is an *additional* paid L2 call, never
        # a free prediction and never a substitute for fresh gear/policy search.
        # Reserve its attempt inside the same talent-stage cap.
        probe_reserved = bool(measure_parent_fixed_policy and parent_stage
                              and parent_stage.get('score_s_per_mob') is not None
                              and budget >= 2)
        search_budget = budget - int(probe_reserved)
        # Source IR talent application is fail-closed. No unsupported no-op
        # state is permitted to enter the expensive scorer.
        try:
            talented, applied = apply_talent_selection(ir,allocation,level=level)
        except (ValueError,RuntimeError) as exc:
            stages.append({'allocation':allocation,'status':'BLOCKED_TALENT_APPLICATION',
                           'reason':str(exc),'attempted':0,'operation':proposal['operation']})
            rejection_counts['talent_application'] += 1
            continue
        try:
            result = run_source_budgeted_gear(class_key=class_key,level=level,
                max_evaluations=search_budget,initial_search=min(initial_search,search_budget),
                search_per_gear=search_per_gear,max_gear_states=max_gear_states,
                schedule_incoming_attacks=schedule_incoming_attacks,ir_slice=talented,
                policy_search_backend=policy_search_backend,
                max_event_transitions=(None if max_event_transitions is None else max_event_transitions-total_events),
                stateful_use_l1=stateful_use_l1,
                stateful_l1_mode=stateful_l1_mode,
                stateful_use_prefix_cache=stateful_use_prefix_cache,
                stateful_search_guarded_continuations=stateful_search_guarded_continuations,
                stateful_search_mode_paths=stateful_search_mode_paths,
                stateful_search_auto_fallback=stateful_search_auto_fallback,
                stateful_family_budget_mode=stateful_family_budget_mode,
                gear_role_exploration=gear_role_exploration,
                required_level_policy=required_level_policy,
                exclude_unknown_item_effects=exclude_unknown_item_effects,
                probe_stats=probe_stats,probe_deltas=probe_deltas)
        except (ValueError,RuntimeError) as exc:
            stages.append({'allocation':allocation,'status':'BLOCKED_GEAR_POLICY_SEARCH',
                           'reason':str(exc),'attempted':0,'operation':proposal['operation']})
            rejection_counts['gear_policy_search'] += 1
            continue
        before = attempted
        attempted += result['attempted']
        total_events += result.get('event_transitions',0)
        total_l1 += result.get('stateful_l1_attempts',0)
        if max_event_transitions is not None and total_events > max_event_transitions:
            raise AssertionError('talent-gear-policy event budget exceeded')
        evaluated += result['evaluated']
        blocked += result['blocked']
        if attempted>max_evaluations or result['attempted']!=result['evaluated']+result['blocked']:
            raise AssertionError('real simulator accounting mismatch')
        # Measure the child allocation under the *parent's actual winning
        # gear and ordered/guarded policy*. This isolates the fixed-policy
        # talent marginal from the separately measured reoptimized marginal.
        # A full executor call (including failures) consumes one shared L2
        # attempt and its real event transitions; cross-talent state is NEVER
        # reused. No legacy or proxy score is substituted.
        fixed_probe = None
        if probe_reserved and attempted < max_evaluations:
            parent_winner = parent_stage['gear_policy_result'].get('winner')
            parent_policy = parent_winner.get('winner') if parent_winner else None
            parent_gear = parent_winner.get('gear') if parent_winner else None
            if parent_policy and (max_event_transitions is None or total_events < max_event_transitions):
                fixed_policy_attempts += 1
                attempted += 1
                observed_events = 0
                started = process_time_ns()
                fixed_score = None
                reason = None
                try:
                    fixed_ir = talented
                    if parent_gear is not None:
                        fixed_ir, _ = apply_gear_selection(talented,
                            aggregate_stats=parent_gear['aggregate_stats'],
                            selected_items=tuple(parent_gear['slots'].values()),
                            source='canonical_sqlite_forever_catalogue')
                    def meter(n):
                        nonlocal observed_events
                        observed_events += int(n)
                    fixed_score = _fixed_opening_score(fixed_ir, parent_policy, level,
                        schedule_incoming_attacks, meter=meter,
                        max_events=(None if max_event_transitions is None
                                    else max_event_transitions-total_events))
                except (EventTransitionBudgetExceeded, ComputeDeadlineExceeded) as exc:
                    observed_events += int(exc.events_processed)
                    reason = type(exc).__name__
                except (ValueError, RuntimeError, KeyError) as exc:
                    reason = f'{type(exc).__name__}: {exc}'
                fixed_policy_cpu_ns += process_time_ns()-started
                total_events += observed_events
                fixed_policy_events += observed_events
                if max_event_transitions is not None and total_events > max_event_transitions:
                    raise AssertionError('fixed-policy talent probe exceeded shared event cap')
                valid = fixed_score is not None and isfinite(fixed_score) and fixed_score > 0
                evaluated += int(valid)
                blocked += int(not valid)
                fixed_probe = {
                    'status':'FULL_L2_VERIFIED' if valid else 'BLOCKED_L2',
                    'score_s_per_mob':float(fixed_score) if valid else None,
                    'parent_score_s_per_mob':parent_stage['score_s_per_mob'],
                    'fixed_policy_delta_s_per_mob':(float(fixed_score)-parent_stage['score_s_per_mob']) if valid else None,
                    'parent_allocation':parent_stage['allocation'],
                    'parent_policy':parent_policy,
                    'parent_named_gear':parent_gear,
                    'event_transitions':observed_events,
                    'reason':reason,
                    'fresh_child_executor_no_cross_talent_cache':True,
                }
        winner = result.get('winner')
        score = None if not winner or not winner.get('winner') else winner['winner']['score_s_per_mob']
        if score is not None and (not isfinite(score) or score<=0):
            raise AssertionError('invalid actual combat/recovery score')
        stage = {'allocation':allocation,'spent_points':sum(allocation.values()),
                 'talent_application':applied.as_dict(), 'operation':proposal['operation'],
                 'parent_allocation':dict(proposal['parent']) if proposal['parent'] is not None else None,
                 'parent_score_s_per_mob':proposal['parent_score'],
                 'status':result['status'], 'score_s_per_mob':score,
                 'attempted':result['attempted']+int(fixed_probe is not None),
                 'evaluated':result['evaluated']+int(fixed_probe is not None and fixed_probe['status']=='FULL_L2_VERIFIED'),
                 'blocked':result['blocked']+int(fixed_probe is not None and fixed_probe['status']!='FULL_L2_VERIFIED'),
                 'budget_start':before,'budget_end':attempted,
                 'source_context_sha256':result['source_context_sha256'],
                 'event_transitions':result.get('event_transitions',0),
                 'gear_policy_result':result,'fresh_gear_and_policy_search':True,
                 'parent_fixed_policy_marginal':fixed_probe,
                 'reoptimized_marginal_s_per_mob':(score-proposal['parent_score']
                     if score is not None and proposal['parent_score'] is not None else None)}
        stages.append(stage)
        stage_by_key[key] = stage
        selection_trace.append({'after_talent_stages':len(stages),'chosen_allocation':allocation,
            'parent_observed_score':proposal['parent_score'],
            'actual_score':score,'operation':proposal['operation']})
        if score is not None:
            # Single-family measured marginal is identifiable; a transfer
            # confounds two talent effects and is not treated as a slope.
            if proposal['parent_score'] is not None and len(proposal['changed_ids'])==1:
                family = proposal['changed_ids'][0]
                previous_rank = dict(proposal['parent']).get(family,0)
                delta_rank = allocation.get(family,0)-previous_rank
                if delta_rank:
                    slope = (score-proposal['parent_score'])/delta_rank
                    marginal_by_family[family] = (marginal_by_family.get(family,slope)+slope)/2
            best_actions = tuple(dict.fromkeys(a['action_id'] for a in
                result['winner']['winner'].get('selected_actions',())))
            neighbors = source_legal_talent_neighbors(ir,allocation,level=level)
            rejection_counts.update(neighbors['rejected_by_reason'])
            for candidate in neighbors['neighbors']:
                child = candidate.allocation
                legal_seen.add(child)
                if child in visited:
                    continue
                new = {'parent':key,'parent_score':score,
                       'operation':candidate.operation,'changed_ids':candidate.changed_ids,
                       'parent_used_actions':best_actions,'allocation':child}
                old = pending.get(child)
                if child in reserved_corridors and old is not None:
                    # Keep source-corridor provenance independent of observed
                    # neighbor scores; only its evaluation updates evidence.
                    continue
                if old is None or old['parent_score'] is None or score<old['parent_score']:
                    pending[child] = new
        for item in result.get('best_vs_budget',()):
            observed = item['best_s_per_mob']
            if observed is not None:
                best_score = observed if best_score is None else min(best_score,observed)
            best_curve.append({'attempt':before+item['attempt'],
                               'best_s_per_mob':best_score,'talent_allocation':allocation,
                               'status':item['status']})
        if fixed_probe is not None:
            if fixed_probe['status']=='FULL_L2_VERIFIED':
                fixed_policy_challengers.append({'allocation':allocation,
                    'score_s_per_mob':fixed_probe['score_s_per_mob'],
                    'parent_allocation':fixed_probe['parent_allocation'],
                    'parent_policy':fixed_probe['parent_policy'],
                    'parent_named_gear':fixed_probe['parent_named_gear'],
                    'source_context_sha256':result['source_context_sha256']})
                best_score = min(best_score, fixed_probe['score_s_per_mob']) if best_score is not None else fixed_probe['score_s_per_mob']
            best_curve.append({'attempt':attempted,'best_s_per_mob':best_score,
                'talent_allocation':allocation,
                'status':'fixed_policy_evaluated' if fixed_probe['status']=='FULL_L2_VERIFIED' else 'fixed_policy_blocked'})
        # Once an actual independent root gear+policy winner exists, probe a
        # diverse SOURCE-LEGAL talent frontier with the SAME real L2 scorer.
        # Every attempt, including illegal or failed continuations, consumes
        # the global attempt/event budget. A probe only prioritizes later
        # fresh gear+policy searches; it can never mark a checkpoint complete.
        if len(stages) == 1 and score is not None and talent_screening_attempts:
            root_winner = result['winner']
            anchor_gear = root_winner.get('gear')
            anchor_policy = root_winner.get('winner')
            if anchor_gear and anchor_policy:
                # Root neighbors and level-legal tier corridors are essential
                # contrasts. Expand their one-point neighbors only to fill
                # remaining exploration space, without Cartesian enumeration.
                candidates = list(dict.fromkeys((*reserved_corridors,*pending.keys())))
                cursor = 0
                upper = min(512, 8 * talent_screening_attempts)
                while cursor < len(candidates) and len(candidates) < upper:
                    parent = candidates[cursor]
                    cursor += 1
                    try:
                        successors = source_legal_talent_neighbors(ir,dict(parent),level=level)
                    except ValueError:
                        continue
                    for nxt in successors['neighbors']:
                        if nxt.allocation not in candidates and nxt.allocation not in visited:
                            candidates.append(nxt.allocation)
                            if len(candidates) >= upper:
                                break
                tree_of_id = {t.id:t.tree_key for t in ir.talents}
                groups = {}
                for proposed in candidates:
                    if proposed in visited:
                        continue
                    family = next((tree_of_id[f] for f,_ in proposed if f in tree_of_id),'unknown')
                    groups.setdefault(family,[]).append(proposed)
                ordered = []
                # Avoid letting one tree exhaust the paid screening budget.
                while any(groups.values()):
                    for tree in sorted(groups):
                        if groups[tree]:
                            ordered.append(groups[tree].pop(0))
                for probe_key in ordered:
                    if (len(talent_screening) >= talent_screening_attempts or
                        attempted >= core_budget or
                        (max_event_transitions is not None and total_events >= max_event_transitions)):
                        break
                    attempted += 1  # charge failed/blocked attempts too
                    observed_events = 0
                    fixed_score = None
                    reason = None
                    t0 = process_time_ns()
                    try:
                        probe_ir,_ = apply_talent_selection(ir,dict(probe_key),level=level)
                        probe_ir,_ = apply_gear_selection(probe_ir,
                            aggregate_stats=anchor_gear['aggregate_stats'],
                            selected_items=tuple(anchor_gear['slots'].values()),
                            source='canonical_sqlite_forever_catalogue')
                        def meter(n):
                            nonlocal observed_events
                            observed_events += int(n)
                        fixed_score = _fixed_opening_score(probe_ir,anchor_policy,level,
                            schedule_incoming_attacks,meter=meter,
                            max_events=(None if max_event_transitions is None
                                        else max_event_transitions-total_events))
                    except (EventTransitionBudgetExceeded,ComputeDeadlineExceeded) as exc:
                        observed_events += int(exc.events_processed)
                        reason = type(exc).__name__
                    except (ValueError,RuntimeError,KeyError) as exc:
                        reason = f'{type(exc).__name__}: {exc}'
                    screening_cpu_ns += process_time_ns()-t0
                    total_events += observed_events
                    if max_event_transitions is not None and total_events>max_event_transitions:
                        raise AssertionError('paid talent-screening event cap exceeded')
                    valid = fixed_score is not None and isfinite(fixed_score) and fixed_score>0
                    evaluated += int(valid)
                    blocked += int(not valid)
                    screened_keys.add(probe_key)
                    talent_screening.append({'allocation':dict(probe_key),
                        'status':'FULL_L2_FIXED_POLICY' if valid else 'BLOCKED_L2',
                        'score_s_per_mob':float(fixed_score) if valid else None,
                        'event_transitions':observed_events,'reason':reason})
                    if valid:
                        legal_seen.add(probe_key)
                        pending.setdefault(probe_key,{
                            'parent':key,'parent_score':score,
                            'operation':'paid_fixed_policy_screening',
                            'changed_ids':tuple(f for f,_ in probe_key),
                            'allocation':probe_key})
                        pending[probe_key]['screened_score']=float(fixed_score)
                        fixed_policy_challengers.append({
                            'allocation':dict(probe_key),'score_s_per_mob':float(fixed_score),
                            'parent_allocation':allocation,'parent_policy':anchor_policy,
                            'parent_named_gear':anchor_gear,
                            'source_context_sha256':context,
                            'scope':'screening_only_not_joint_winner'})
                        best_score = min(best_score,float(fixed_score)) if best_score is not None else float(fixed_score)
                    best_curve.append({'attempt':attempted,'best_s_per_mob':best_score,
                        'talent_allocation':dict(probe_key),'status':
                        'screened_fixed_L2' if valid else 'screened_blocked_L2'})
        # If a nested search cannot spend its allocation, continue to other
        # legal talent states; unspent budget is never silently charged.
    successful = sorted((s for s in stages if s.get('score_s_per_mob') is not None),
                        key=lambda s:(s['score_s_per_mob'],s['spent_points'],allocation_key(s['allocation'])))
    # Recombine the independently found named gear with SOURCE-LEGAL neighboring
    # talent allocations; pay every L2 evaluation and then search a fresh policy.
    # This catches gear x talent interaction missed by nested stat-weight selection.
    refinement=None
    if post_talent_refinement_budget and successful and (
            max_event_transitions is None or total_events < max_event_transitions):
        from src.v2.source_joint_local_refinement import refine_named_gear_talents
        candidate=next((s for s in successful if (s.get('gear_policy_result') or {}).get('winner')
                        and s['gear_policy_result']['winner'].get('gear')),None)
        if candidate is not None:
            refinement=refine_named_gear_talents(ir=ir,class_key=class_key,level=level,
                incumbent=candidate,
                max_l2_attempts=min(post_talent_refinement_budget,max_evaluations-attempted),
                max_event_transitions=(15000 if max_event_transitions is None else max_event_transitions-total_events),
                schedule_incoming_attacks=schedule_incoming_attacks,
                reserve_fresh_policy_attempts=min(10,max(0,min(post_talent_refinement_budget,max_evaluations-attempted)-1)),
                search_guarded_continuations=stateful_search_guarded_continuations,
                search_mode_paths=stateful_search_mode_paths,
                family_budget_mode=stateful_family_budget_mode)
            attempted+=refinement['attempted']
            evaluated+=refinement['evaluated']
            blocked+=refinement['blocked']
            total_events+=refinement['event_transitions']
            if attempted>max_evaluations or (max_event_transitions is not None and total_events>max_event_transitions):
                raise AssertionError('refinement violated shared budget')
            # A fixed-policy replay is a real L2 candidate, even when the
            # separate fresh-policy search cannot improve it. Expose the best
            # ACTUALLY measured configuration as the returned winner rather
            # than silently keeping the older nested-search incumbent.
            fixed_score=refinement['best_fixed_s_per_mob']
            fresh=refinement['fresh_policy_winner']
            use_fresh=bool(fresh and float(fresh['score_s_per_mob'])<=fixed_score+1e-10)
            candidate_score=float(fresh['score_s_per_mob']) if use_fresh else fixed_score
            if candidate_score < candidate['score_s_per_mob']-1e-10:
                chosen_record=fresh if use_fresh else refinement['fixed_policy_record']
                refined_stage={'allocation':refinement['best_fixed_allocation'],
                    'spent_points':sum(refinement['best_fixed_allocation'].values()),
                    'operation':'source_legal_cross_talent_refinement',
                    'status':'EVALUATED_BOUNDED',
                    'score_s_per_mob':candidate_score,
                    'attempted':refinement['attempted'],
                    'evaluated':refinement['evaluated'],
                    'blocked':refinement['blocked'],
                    'event_transitions':refinement['event_transitions'],
                    'source_context_sha256':context,
                    'fresh_gear_and_policy_search':False,
                    'named_gear_reused_from_independent_stage':True,
                    'policy_freshly_searched_after_refinement':use_fresh,
                    'gear_policy_result':{'winner':{
                        'gear':refinement['fixed_named_gear'],
                        'winner':chosen_record,
                        'stage':'cross_talent_fixed_named_gear',
                        'search_is_fresh_from_source_singles_pairs':use_fresh}},
                    'refinement_provenance':'source_legal_talent_neighbors + paid_L2 + stateful_policy_as_prefix'}
                stages.append(refined_stage)
                successful.append(refined_stage)
                successful.sort(key=lambda s:(s['score_s_per_mob'],s['spent_points'],allocation_key(s['allocation'])))
    roster = source_legal_talent_neighbors(ir,initial,level=level)
    best_fixed = min(fixed_policy_challengers,key=lambda x:x['score_s_per_mob']) if fixed_policy_challengers else None
    best_reoptimized = successful[0] if successful else None
    best_observed = ({'kind':'paid_fixed_policy_challenger', **best_fixed}
                     if best_fixed is not None and (best_reoptimized is None or
                         best_fixed['score_s_per_mob'] < best_reoptimized['score_s_per_mob'])
                     else ({'kind':'reoptimized_gear_policy',
                            'allocation':best_reoptimized['allocation'],
                            'score_s_per_mob':best_reoptimized['score_s_per_mob']}
                           if best_reoptimized is not None else None))
    if refinement is not None and refinement['best_fixed_s_per_mob'] < (
            best_observed['score_s_per_mob'] if best_observed else float('inf')):
        best_observed={'kind':'paid_cross_talent_fixed_gear_policy',
            'allocation':refinement['best_fixed_allocation'],
            'score_s_per_mob':refinement['best_fixed_s_per_mob']}
    if refinement is not None and refinement['fresh_policy_winner'] is not None and (
            best_observed is None or refinement['fresh_policy_score_s_per_mob']<best_observed['score_s_per_mob']):
        best_observed={'kind':'paid_cross_talent_fresh_policy',
            'allocation':refinement['best_fixed_allocation'],
            'score_s_per_mob':refinement['fresh_policy_score_s_per_mob']}
    return {'status':'EVALUATED_BOUNDED' if successful else 'BLOCKED_NO_KILL',
            'class_key':class_key,'level':level,'source_ir_id':ir.id,
            'source_context_sha256':context,'budget':max_evaluations,
            'attempted':attempted,'evaluated':evaluated,'blocked':blocked,
            'unspent_budget':max_evaluations-attempted,
            'event_transitions':total_events,
            'stateful_l1_attempts':total_l1, 'stateful_l1_mode':stateful_l1_mode,
            'measure_parent_fixed_policy':measure_parent_fixed_policy,
            'fixed_policy_attempts':fixed_policy_attempts,
            'fixed_policy_event_transitions':fixed_policy_events,
            'fixed_policy_cpu_ns':fixed_policy_cpu_ns,
            'fixed_policy_challengers':fixed_policy_challengers,
            'talent_screening_attempts':len(talent_screening),
            'talent_screening_evidence':talent_screening,
            'talent_screening_cpu_ns':screening_cpu_ns,
            'distinct_talent_allocations_paid_L2':len(visited | screened_keys),
            'post_talent_refinement_budget':post_talent_refinement_budget,
            'post_talent_refinement':refinement,
            'best_verified_fixed_policy_challenger':best_fixed,
            'best_observed_L2':best_observed, 'stateful_use_l1':stateful_use_l1,
            'max_event_transitions':max_event_transitions,
            'policy_search_backend':policy_search_backend,
            'stateful_search_guarded_continuations':stateful_search_guarded_continuations,
            'stateful_search_mode_paths':stateful_search_mode_paths,
            'stateful_search_auto_fallback':stateful_search_auto_fallback,
            'stateful_family_budget_mode':stateful_family_budget_mode,
            'gear_role_exploration':gear_role_exploration,
            'required_level_policy':required_level_policy,
            'talent_corridor_reserve':talent_corridor_reserve,
            'source_corridors_generated':len(corridors),
            'source_corridors_reserved':[dict(key) for key in reserved_corridors],
            'source_corridors_evaluated':sum(1 for key in reserved_corridors if key in visited),
            'source_corridors_unvisited':[dict(key) for key in reserved_corridors if key not in visited],
            'talent_states_evaluated':len(stages),
            'legal_talent_states_discovered':len(legal_seen),
            'pending_legal_talent_states':len(pending),
            'rejected_talent_proposals':dict(rejection_counts),
            'talent_l0_rank_frontier':[{'talent_id':r['talent_id'],'rank':r['rank'],
                'relative_opportunity':r['relative_opportunity'],
                'conditional':r['conditional'],'l2_supported':r['l2_supported']}
                for r in l0_talent_rank_order],
            'talent_l0_source_ranks_scored':0 if l0_talent_frontier is None else l0_talent_frontier['rank_count'],
            'talent_l0_source_only_ranks_scored':0 if l0_talent_frontier is None else l0_talent_frontier['source_only_count'],
            'talent_l0_priority_queries':l0_priority_queries,
            'talent_l0_influenced_candidate_order':l0_priority_queries > 0,
            'source_talent_families':roster['source_talent_families'],
            'executable_talent_families':roster['executable_talent_families'],
            'unsupported_talent_ids':list(roster['unsupported_talent_ids']),
            'winner':successful[0] if successful else None,
            'runner_up':successful[1] if len(successful)>1 else None,
            'stages':stages,'best_vs_budget':best_curve,
            'selection_trace':selection_trace,
            'complete_search':False,
            'limitations':['source executable talents only; missing ranks/effects explicit',
                           'bounded neighbor frontier, not global optimum',
                           'gear selector does not prove item acquisition route',
                           'ordered offensive prefixes and fallback only']}
