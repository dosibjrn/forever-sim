"""Budgeted *contiguous* source-talent / real-executor route, not a 1–60 proof.

Reuse the production stateful combat/recovery/survival scorer, the canonical
legal +1-point frontier and the shared exact path DP. No class-specific spells,
scorers, talent seeds, item acquisition claims or legacy winner fixtures.

The deliberately naked scenario removes the unsourced item acquisition step;
it does NOT establish a complete playable route (training/quest/rune access,
source completeness, world travel and enemy distributions remain unproven).
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from json import dumps
from math import isfinite
from time import process_time_ns, monotonic_ns

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.game.talent_search import talent_candidate_id, executable_talent_definitions
from src.v2.source_legal_beam import legal_point_frontier
from src.v2.source_stateful_budgeted import run_source_stateful_budgeted, source_execution_context
from src.v2.generic_frontier import GenericTalentBuild, GenericTalentRouteModel
from src.v2.path_dp import LevelNode, solve_path_dp


def _talent_tree(ir):
    return {t.id: str(t.tree_key) for t in ir.talents}


def _family(allocation, tree_of):
    points = defaultdict(int)
    for tid, rank in allocation.items():
        points[tree_of[tid]] += rank
    if not points:
        return 'empty'
    return min(points, key=lambda key: (-points[key], key))


def _propose(parent_states, ir, level, *, max_candidates):
    """Fair source-tree admission; parent full-cycle scores are observations.

    Unscored children are NOT pruned by an invented DPS score. A per-tree
    exploration seat is reserved, then cheapest observed parent paths fill the
    remaining slots. This is a bounded beam, not proof of a complete frontier.
    """
    tree_of = _talent_tree(ir)
    pending = {}
    for parent in parent_states:
        for child in legal_point_frontier(ir, parent['allocation'], level=level,
                                          allow_transfers=False):
            cid = talent_candidate_id(child)
            score = float(parent['score_s_per_mob'])
            old = pending.get(cid)
            if old is None or (score, parent['candidate_id']) < (
                    old['parent_score'], old['parent_id']):
                pending[cid] = {'allocation': child, 'candidate_id': cid,
                    'parent_id': parent['candidate_id'], 'parent_score': score,
                    'family': _family(child, tree_of)}
    groups = defaultdict(list)
    for row in pending.values():
        groups[row['family']].append(row)
    for rows in groups.values():
        rows.sort(key=lambda r: (r['parent_score'], r['candidate_id']))
    admitted = []
    # Source-tree diversity is a hard exploration reserve when affordable.
    for family in sorted(groups):
        if len(admitted) < max_candidates and groups[family]:
            admitted.append(groups[family].pop(0))
    # Remaining places use measured *parent* objective, not proxy child score.
    rest = sorted((r for rows in groups.values() for r in rows),
                  key=lambda r: (r['parent_score'], r['candidate_id']))
    admitted.extend(rest[:max(0, max_candidates-len(admitted))])
    return admitted, {'generated_unique':len(pending),
                      'source_tree_families':sorted(groups),
                      'admitted':len(admitted), 'not_evaluated':len(pending)-len(admitted)}


def search_stateful_contiguous_route(*, class_key: str, start_level: int = 10,
        end_level: int = 20, max_candidates_per_level: int = 4,
        beam_width: int = 3, attempts_per_candidate: int = 8,
        events_per_candidate: int = 1200, global_event_cap: int = 65000,
        use_l1: bool = False, max_wall_ns: int | None = None,
        resume_from: dict | None = None):
    """Paid source-legal +1 talent routes, with genuine L2 at *each* level.

    No result is called VALIDATED_CHECKPOINT or ROUTE_COMPLETE. On missing
    source talent or failed L2, return a precise partial route and blocker.
    Every attempted L2/partial/scratch event is charged to the global cap.
    """
    if not (10 <= start_level <= end_level <= 60):
        raise ValueError('contiguous talent route must start at or after L10')
    if min(max_candidates_per_level, beam_width, attempts_per_candidate,
           events_per_candidate, global_event_cap) < 1:
        raise ValueError('budgets must be positive')
    if beam_width > max_candidates_per_level:
        raise ValueError('beam width exceeds per-level candidate budget')
    start_cpu = process_time_ns(); start_wall = monotonic_ns()
    total_events = total_l2 = total_l1 = total_cpu = 0
    pools = {}; reports = []; blocked = None
    resume_verification = None
    if resume_from is not None:
        prior = list(resume_from.get('bounded_route') or [])
        if resume_from.get('class_key') != class_key or not prior or prior[0]['level'] != 10:
            raise ValueError('resume requires same-class sourced L10 prefix')
        if [x['level'] for x in prior] != list(range(10,prior[-1]['level']+1)):
            raise ValueError('resume prefix is not contiguous')
        if start_level != prior[-1]['level']+1:
            raise ValueError('resume must start exactly after previous verified endpoint')
        # Every historical prefix state is rechecked against CURRENT source,
        # engine/scenario hash, source talent rules, and prior scratch evidence.
        # Hashes prevent silently inheriting evidence after any source patch.
        old_reports = {row['level']:row for row in resume_from['level_reports']}
        for step in prior:
            level0 = int(step['level']); allocation = dict(step['talents'])
            ir0 = build_game_ir_slice(class_key=class_key,level=level0)
            if ir0 is None:
                raise ValueError(f'L{level0} previous canonical IR disappeared')
            validate_talent_selection(ir0,allocation,level=level0)
            if sum(allocation.values()) != level0-9:
                raise ValueError('previous route does not spend full legal talent budget')
            talented0,_ = apply_talent_selection(ir0,allocation,level=level0)
            if source_execution_context(talented0) != step['source_context']:
                raise ValueError(f'L{level0} source/engine/scenario fingerprint changed; rerun from scratch')
            cid = talent_candidate_id(allocation)
            evidence = [row for row in old_reports[level0]['evaluations']
                        if row['candidate_id']==cid and row['scratch_verified']]
            if len(evidence)!=1 or evidence[0]['source_context']!=step['source_context']:
                raise ValueError(f'L{level0} no matching scratch-verified L2 evidence')
            build = GenericTalentBuild.from_candidate(
                {'selection':allocation,'candidate_id':cid},
                available_points=level0-9,
                executable_talent_ids=[t.id for t in executable_talent_definitions(ir0)],
                talent_tree_by_id=_talent_tree(ir0))
            pools[level0] = [LevelNode(level=level0,talents=build,
                score_s_per_100=100*float(step['score_s_per_mob']),policy=None,
                source='verified_source_stateful_route_resume',
                details={'score_s_per_mob':float(step['score_s_per_mob']),
                         'source_context':step['source_context'],
                         'winner':{'prefix':step['ordered_prefix'],
                                   'fallback':step['continuation_fallback'],
                                   'guarded_action':step['guarded_action']}})]
        # The DP verifies that ALL previous level transitions were legal.
        previous_path = solve_path_dp(pools,max_respecs=0,model=GenericTalentRouteModel())
        if len(previous_path.steps)!=len(prior):
            raise ValueError('previous route continuity was not proven')
        # One independent fresh production scorer run at the boundary, charged
        # against the new budget; exact score must match prior evidence.
        endpoint = prior[-1]
        ir_end = build_game_ir_slice(class_key=class_key,level=endpoint['level'])
        ir_end,_ = apply_talent_selection(ir_end,endpoint['talents'],level=endpoint['level'])
        checked = run_source_stateful_budgeted(class_key=class_key,
            level=endpoint['level'],ir_slice=ir_end,
            max_l2_attempts=attempts_per_candidate,
            max_event_transitions=min(events_per_candidate,global_event_cap),
            use_l1=use_l1,search_auto_fallback=True,
            search_mode_paths=True,family_budget_mode='measured_balanced',
            max_wall_ns=(None if max_wall_ns is None else max(1,
                max_wall_ns-(monotonic_ns()-start_wall))))
        total_events += int(checked.get('event_transitions',0))
        total_l2 += int(checked.get('l2_attempts',0))
        total_l1 += int(checked.get('l1_attempts',0))
        total_cpu += int(checked.get('full_run_cpu_ns',0))
        winner = checked.get('winner')
        if (not winner or not checked.get('verification_complete') or
            abs(float(winner['score_s_per_mob'])-float(endpoint['score_s_per_mob']))>1e-9):
            raise ValueError('resumed endpoint L2 differs from scratch; invalidate route')
        resume_verification = {'level':endpoint['level'],
            'score_s_per_mob':winner['score_s_per_mob'],
            'events_charged':checked['event_transitions'],
            'l2_attempts_charged':checked['l2_attempts'],
            'source_context_matched':True,'scratch_verified':True}
        reports = list(resume_from['level_reports'])
        parents = [{'allocation':dict(endpoint['talents']),
                    'candidate_id':talent_candidate_id(endpoint['talents']),
                    'score_s_per_mob':float(endpoint['score_s_per_mob'])}]
    else:
        parents = [{'allocation':{},'candidate_id':'talents:none',
                    'score_s_per_mob':0.0}]
    # At L10 the empty L9 parent has zero talents. Never assume a source
    # talent was learned without a validated +1 transition.
    for level in range(start_level, end_level+1):
        ir = build_game_ir_slice(class_key=class_key, level=level)
        if ir is None:
            blocked = {'level':level,'reason':'MISSING_CANONICAL_GAME_IR'}
            break
        if level == start_level and start_level != 10 and resume_from is None:
            blocked = {'level':level,'reason':'START_REQUIRES_VERIFIED_L10_PREFIX'}
            break
        tree_of = _talent_tree(ir)
        proposed, proposal = _propose(parents, ir, level,
                                     max_candidates=max_candidates_per_level)
        report = {'level':level, **proposal, 'source_executable_talent_families':len(
                  executable_talent_definitions(ir)), 'evaluations':[],
                  'scored':0, 'event_transitions':0, 'l2_attempts':0,
                  'l1_attempts':0, 'source_ir_action_count':len(ir.actions)}
        if not proposed:
            blocked = {'level':level,'reason':'NO_SOURCE_EXECUTABLE_LEGAL_NEXT_TALENT_POINT',
                       'source_executable_talent_families':len(executable_talent_definitions(ir))}
            reports.append(report)
            break
        scored = []; nodes = []
        for candidate in proposed:
            remaining = global_event_cap - total_events
            if remaining < 1:
                blocked = {'level':level,'reason':'GLOBAL_EVENT_BUDGET_EXHAUSTED'}
                break
            if max_wall_ns is not None and monotonic_ns()-start_wall >= max_wall_ns:
                blocked = {'level':level,'reason':'GLOBAL_WALL_BUDGET_EXHAUSTED'}
                break
            allocation = candidate['allocation']
            validate_talent_selection(ir,allocation,level=level)
            if sum(allocation.values()) != level-9:
                raise AssertionError('full talent point budget was not spent')
            talented, applied = apply_talent_selection(ir,allocation,level=level)
            r = run_source_stateful_budgeted(class_key=class_key,level=level,
                ir_slice=talented,max_l2_attempts=attempts_per_candidate,
                max_event_transitions=min(events_per_candidate,remaining),
                use_l1=use_l1,search_auto_fallback=True,
                search_mode_paths=True, family_budget_mode='measured_balanced',
                max_wall_ns=(None if max_wall_ns is None else max(1,
                    max_wall_ns-(monotonic_ns()-start_wall))))
            events = int(r.get('event_transitions',0))
            if events > min(events_per_candidate,remaining):
                raise AssertionError('underlying controller violated event cap')
            total_events += events
            total_l2 += int(r.get('l2_attempts',r.get('attempted_l2',0)))
            total_l1 += int(r.get('l1_attempts',0))
            total_cpu += int(r.get('full_run_cpu_ns',0))
            report['event_transitions'] += events
            report['l2_attempts'] += int(r.get('l2_attempts',r.get('attempted_l2',0)))
            report['l1_attempts'] += int(r.get('l1_attempts',0))
            winner = r.get('winner')
            row = {'candidate_id':candidate['candidate_id'],
                   'parent_id':candidate['parent_id'],
                   'talents':dict(allocation), 'family':candidate['family'],
                   'status':r['status'], 'events':events,
                   'l2_attempts':int(r.get('l2_attempts',r.get('attempted_l2',0))),
                   'score_s_per_mob':None if not winner else winner['score_s_per_mob'],
                   'scratch_verified':bool(r.get('verification_complete')),
                   'source_context':r.get('source_context')}
            report['evaluations'].append(row)
            if not winner or not r.get('verification_complete'):
                continue
            score = float(winner['score_s_per_mob'])
            if not isfinite(score) or score <= 0:
                raise AssertionError('nonpositive or nonfinite full-cycle objective')
            build = GenericTalentBuild.from_candidate(
                {'selection':allocation,'candidate_id':candidate['candidate_id']},
                available_points=level-9,
                executable_talent_ids=[t.id for t in executable_talent_definitions(ir)],
                talent_tree_by_id=tree_of)
            nodes.append(LevelNode(level=level,talents=build,
                score_s_per_100=100*score,policy=None,
                source='source_stateful_contiguous_route',
                details={'score_s_per_mob':score,'winner':winner,
                         'source_context':r.get('source_context'),
                         'talent_modifiers_applied':len(applied.applied_modifiers)}))
            scored.append({'allocation':dict(allocation),
                           'candidate_id':candidate['candidate_id'],
                           'score_s_per_mob':score})
        report['scored']=len(scored)
        reports.append(report)
        if blocked:
            break
        if not scored:
            blocked = {'level':level,'reason':'NO_SCRATCH_VERIFIED_FULL_CYCLE_L2'}
            break
        pools[level]=nodes
        # Beam is for NEXT-level proposals only; retain all paid candidates in
        # DP pools. Choose distinct talent-tree families before other scores.
        grouped = defaultdict(list)
        for row in scored:
            grouped[_family(row['allocation'],tree_of)].append(row)
        for rows in grouped.values():
            rows.sort(key=lambda r:(r['score_s_per_mob'],r['candidate_id']))
        parents=[]
        for family in sorted(grouped):
            if len(parents)<beam_width:
                parents.append(grouped[family].pop(0))
        rest = sorted((r for rows in grouped.values() for r in rows),
                      key=lambda r:(r['score_s_per_mob'],r['candidate_id']))
        parents.extend(rest[:max(0,beam_width-len(parents))])
    path = None
    if pools:
        solved=solve_path_dp(pools,max_respecs=0,model=GenericTalentRouteModel())
        if len(solved.steps) != len(pools) or solved.respecs_used:
            raise AssertionError('shared route DP did not prove contiguous no-respec path')
        path=[{'level':step.node.level,'talents':dict(step.node.talents.ranks),
               'talent_added':step.talent_added,
               'score_s_per_mob':step.node.details['score_s_per_mob'],
               'source_context':step.node.details['source_context'],
               'ordered_prefix':step.node.details['winner']['prefix'],
               'continuation_fallback':step.node.details['winner']['fallback'],
               'guarded_action':step.node.details['winner']['guarded_action'],
               'cumulative_weighted_objective_s':step.cumulative_s}
              for step in solved.steps]
    if total_events > global_event_cap:
        raise AssertionError('global real transition budget exceeded')
    return {'class_key':class_key,'requested_levels':[start_level,end_level],
            'status':('EVALUATED_BOUNDED_CONTIGUOUS_NAKED_TALENT_ROUTE'
                      if path and len(path)==end_level-9 and blocked is None
                      else 'BLOCKED_PARTIAL_BOUNDED_ROUTE'),
            'bounded_route':path or [],'blocked':blocked,
            'completed_level_count':len(path or []),
            'full_source_action_coverage':False,
            'fully_validated_class_level_checkpoints':0,
            'legal_complete_leveling_route':False,
            'gear_acquisition_verified':False,
            'trainer_quest_rune_acquisition_verified':False,
            'source_base_stats_complete':False,
            'world_travel_and_quest_transitions_verified':False,
            'scenario':'naked canonical proxy stats, real executor incoming combat+recovery+survival',
            'frontier_policy':'source-legal +1 point; diverse trees then observed parent score; bounded beam',
            'limits':['No item gear, consumables, acquisition or travel',
                      'No source-complete action/rank or trainer/quest/rune proof',
                      'Proxy starting stats and incoming enemy scenario',
                      'Beam and policy exploration bounded; not globally optimal'],
            'resume_verification':resume_verification,
            'level_reports':reports,'budget':{
                'global_event_cap':global_event_cap,
                'charged_event_transitions':total_events,
                'l2_attempts':total_l2,'l1_attempts':total_l1,
                'full_run_cpu_ns_sum':total_cpu,
                'outer_process_cpu_ns':process_time_ns()-start_cpu,
                'outer_wall_ns':monotonic_ns()-start_wall}}


def search_source_pretalent_prefix(*, class_key: str, start_level: int = 1,
        end_level: int = 9, attempts_per_level: int = 8,
        events_per_level: int = 1000, global_event_cap: int = 9000):
    """Actual scratch-verified L2 for contiguous pre-talent levels (no points).

    Fails closed if any class/level lacks a canonical IR or a surviving L2.
    The source actor's starting gear/stats and ability acquisition remain
    proxies, not a fully validated character progression.
    """
    if not (1 <= start_level <= end_level <= 9):
        raise ValueError('pre-talent prefix requires levels 1–9')
    if min(attempts_per_level,events_per_level,global_event_cap)<1:
        raise ValueError('positive budgets required')
    start_cpu=process_time_ns()
    events=attempts=0
    rows=[]; blocked=None
    for level in range(start_level,end_level+1):
        ir=build_game_ir_slice(class_key=class_key,level=level)
        if ir is None:
            blocked={'level':level,'reason':'MISSING_CANONICAL_GAME_IR'}
            break
        if level-9>0:
            raise AssertionError('unexpected pre-talent point')
        remaining=global_event_cap-events
        if remaining<1:
            blocked={'level':level,'reason':'GLOBAL_EVENT_BUDGET_EXHAUSTED'}
            break
        r=run_source_stateful_budgeted(class_key=class_key,level=level,
            ir_slice=ir,max_l2_attempts=attempts_per_level,
            max_event_transitions=min(events_per_level,remaining),
            use_l1=False,search_auto_fallback=True)
        events+=int(r.get('event_transitions',0))
        attempts+=int(r.get('l2_attempts',r.get('attempted_l2',0)))
        if not r.get('winner') or not r.get('verification_complete'):
            blocked={'level':level,'reason':'NO_SCRATCH_VERIFIED_FULL_CYCLE_L2',
                     'controller_status':r['status']}
            break
        w=r['winner']
        rows.append({'level':level,'talents':{},'source_context':r['source_context'],
                     'score_s_per_mob':w['score_s_per_mob'],
                     'ordered_prefix':w['prefix'],
                     'continuation_fallback':w['fallback'],
                     'guarded_action':w['guarded_action'],
                     'scratch_verified':True,
                     'l2_attempts':r['l2_attempts'],
                     'event_transitions':r['event_transitions']})
    return {'class_key':class_key,'status':(
        'EVALUATED_BOUNDED_PRETALENT_PREFIX' if not blocked else 'BLOCKED_PARTIAL_PRETALENT'),
        'bounded_route':rows,'blocked':blocked,
        'complete_source_coverage':False,'legal_complete_leveling_route':False,
        'budget':{'global_event_cap':global_event_cap,
                  'charged_event_transitions':events,'l2_attempts':attempts,
                  'outer_process_cpu_ns':process_time_ns()-start_cpu}}


def join_source_bounded_leveling_route(prefix: dict, talent_route: dict) -> dict:
    """Join independently L2-verified contiguous 1–9 and 10–N evidence.

    This does not turn a naked scenario into a real-world acquisition route.
    Each segment's source context is rechecked against current source/engine,
    preventing a stale source or HP scenario from being relabelled complete.
    """
    if prefix['class_key']!=talent_route['class_key']:
        raise ValueError('cross-class route splice prohibited')
    pre=list(prefix['bounded_route']); post=list(talent_route['bounded_route'])
    if (not post or [r['level'] for r in pre]!=list(range(1,10)) or
        [r['level'] for r in post]!=list(range(10,post[-1]['level']+1))):
        raise ValueError('route segments must cover contiguous L1–9 and L10–N')
    if prefix['blocked'] or talent_route['blocked']:
        raise ValueError('cannot join blocked route')
    combined=pre+post
    for row in combined:
        ir=build_game_ir_slice(class_key=prefix['class_key'],level=row['level'])
        if ir is None:
            raise ValueError('canonical source level disappeared')
        talented = ir if row['level'] < 10 else apply_talent_selection(
            ir,row['talents'],level=row['level'])[0]
        if source_execution_context(talented)!=row['source_context']:
            raise ValueError('source/engine/scenario mismatch in route splice')
    return {'class_key':prefix['class_key'],
            'status':'EVALUATED_BOUNDED_CONTIGUOUS_L1_TO_N',
            'bounded_route':combined,'levels':len(combined),
            'last_level':combined[-1]['level'],
            'fully_validated_class_level_checkpoints':0,
            'legal_complete_leveling_route':False,
            'source_action_coverage_complete':False,
            'gear_acquisition_verified':False,
            'trainer_quest_rune_acquisition_verified':False,
            'travel_and_mob_selection_verified':False,
            'scenario':'source-naked actor proxy, representative classic ordinary mob HP, real L2 incoming+recovery+survival',
            'limitations':['Only source-executable talents and actions',
                          'No named item acquisition, trainer/quest/rune or world movement proof',
                          'Classic mob HP is proxy, not Forever server mob health',
                          'No exhaustive gear/policy/source legality optimum']}
