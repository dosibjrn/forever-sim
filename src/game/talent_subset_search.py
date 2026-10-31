"""Class-neutral bounded L2-supported talent allocation × APL 100mob search.

Explores ONLY currently executable ranks. All rejected/unexecuted ranks remain
visible as coverage blockers, so a winner is not a checkpoint optimum.
No class, spell, talent or NPC facts are embedded in this search algorithm.
"""
from __future__ import annotations

from itertools import product
from time import perf_counter, process_time

from src.game.checkpoint_pipeline import checkpoint_enemy, discover_source_damage_seeds
from src.game.multi_pull import evaluate_repeated_pulls
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection, validate_talent_selection


def enumerate_executable_allocations(compiled, *, level: int, bonus_talent_points: int = 0,
                                     max_enumerations: int = 100000):
    """Enumerate all *supported* rank assignments if combinatorics permit.

    A candidate point total is level-9+bonus, per the canonical talent rule.
    Abort/mark non-exhaustive when the finite enumeration budget is exceeded.
    """
    if not 1 <= max_enumerations <= 10000000:
        raise ValueError('INVALID_ALLOCATION_ENUMERATION_BUDGET')
    budget = max(0, level-9) + bonus_talent_points
    rule = compiled.provenance.get('talent_tree_rules') or {}
    per_row = int(rule.get('points_per_row', 5))
    eligible = [t for t in compiled.talents if t.metadata.get('row') is not None
                and int(t.metadata['row'])*per_row < budget
                and any(r.modifiers for r in t.ranks)]
    allowed = [(0, *[r.rank for r in t.ranks if r.modifiers]) for t in eligible]
    combinations = 1
    for choices in allowed:
        combinations *= len(choices)
    if combinations > max_enumerations:
        return [], {'status': 'BLOCKED_EXACT_SUBSPACE_ENUMERATION_BUDGET',
                    'raw_combinations': combinations, 'max_enumerations': max_enumerations,
                    'complete_supported_subspace': False}
    accepted=[]
    for chosen in product(*allowed):
        if sum(chosen) != budget:
            continue
        candidate = {t.id: int(value) for t, value in zip(eligible, chosen) if value}
        try:
            validate_talent_selection(compiled,candidate,level=level,
                                      bonus_talent_points=bonus_talent_points)
        except ValueError:
            continue
        accepted.append(candidate)
    return accepted, {'status': ('COMPLETE_SUPPORTED_SUBSPACE_ENUMERATION' if accepted
                                 else 'NO_EXECUTABLE_LEGAL_ALLOCATION'),
                      'raw_combinations': combinations,
                      'eligible_talent_ids': [t.id for t in eligible],
                      'legal_allocations': len(accepted),
                      'points': budget,
                      'complete_supported_subspace': True,
                      'all_source_talent_ranks_covered': False}


def search_executable_talent_subspace(*, ir, level, bonus_talent_points=0,
                                      max_enumerations=100000,
                                      max_policies=4, max_wall_s=30.0):
    """Pay CombatRuntime for each supported candidate × generic sourced APL.

    Gear, target and recovery are fixed/paid; this is a diagnostic limited
    subspace NOT an exhaustive gear/talent/APL/recovery checkpoint certificate.
    """
    if not 1 <= max_policies <= 16 or not 0 < max_wall_s <= 300:
        raise ValueError('INVALID_TALENT_SEARCH_BUDGET')
    t0,c0=perf_counter(),process_time()
    compiled,coverage=compile_talent_runtime(ir)
    candidates,enumeration=enumerate_executable_allocations(compiled,level=level,
        bonus_talent_points=bonus_talent_points,max_enumerations=max_enumerations)
    enemy=checkpoint_enemy(ir=ir,level=level)
    policies=discover_source_damage_seeds(ir,max_actions=4)[:max_policies]
    results=[]
    expected=len(candidates)*len(policies)
    exhausted=False
    for candidate in candidates:
        if perf_counter()-t0>=max_wall_s:
            exhausted=True
            break
        selected, applied = apply_talent_selection(compiled,candidate,level=level,
            bonus_talent_points=bonus_talent_points)
        for policy in policies:
            if perf_counter()-t0>=max_wall_s:
                exhausted=True
                break
            try:
                run=evaluate_repeated_pulls(ir_slice=selected,policy=policy,
                    level=level,target_health=enemy.hp,count=100,pack_size=1,
                    schedule_incoming_attacks=True,apply_target_defense=True,
                    recovery_mode='always')
                success=sum(int(p['mob_count']) for p in run.pulls if p['pack_all_defeated'])
                result={'allocation':candidate,'policy_id':policy.id,
                    'mobs_killed':success, 'seconds_per_mob':run.seconds_per_mob,
                    'spent_points':applied.spent_points,
                    'events':sum(int(p['event_transitions']) for p in run.pulls),
                    'recovery_s':sum(float(p['recovery_s']) for p in run.pulls)}
            except (ValueError,RuntimeError) as exc:
                result={'allocation':candidate,'policy_id':policy.id,
                        'status':'SOURCE_RUNTIME_EVALUATION_FAILED',
                        'error_type':type(exc).__name__, 'error':str(exc)}
            results.append(result)
        if exhausted:
            break
    success=[r for r in results if r.get('mobs_killed')==100]
    winner=min(success,key=lambda r:(r['seconds_per_mob'],r['policy_id'],
                                      sorted(r['allocation'].items()))) if success else None
    return {'level':level,'class_key':ir.actor.metadata['class_key'],
        'bonus_talent_points':bonus_talent_points,
        'source_enemy':enemy.as_dict(),'coverage':{k:v for k,v in coverage.items() if k!='missing'},
        'enumeration':enumeration,'policies':[p.id for p in policies],
        'expected_100mob_runs':expected,'completed_100mob_runs':len(success),
        'attempted_runs':len(results),'wall_budget_exhausted':exhausted,
        'complete_supported_subspace_evaluated':bool(enumeration['complete_supported_subspace'] and not exhausted and len(results)==expected),
        'winner':winner,'status':('SOURCE_SUPPORTED_SUBSPACE_MEASURED' if winner else
            ('NO_EXECUTABLE_LEGAL_ALLOCATION' if not candidates else 'NO_COMPLETE_100MOB_CANDIDATE')),
        'all_results':results,
        'wall_s':perf_counter()-t0,'cpu_s':process_time()-c0,
        'complete_gear_talent_apl_recovery_optimum':False,
        'eligible_for_checkpoint_acceptance':False}
