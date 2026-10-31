"""Generic paid stat sensitivity across conditional-recovery and pull frontiers.

A fixed-policy 100-mob finite difference can be identically zero for Stamina
while a *reselected* recovery strategy benefits. Reuse the existing
CombatRuntime/100-mob scorer; never hand-wave stamina benefit, invent weights,
or assume the baseline winning policy remains optimal after adding gear.

This is a bounded local search with an explicit finite set of provided legal
recovery policies and pack sizes, not a global 148-checkpoint P3 certificate.
"""
from __future__ import annotations
from dataclasses import replace
from math import isfinite

from src.game.gear import apply_stat_delta
from src.game.data.forever.source_checkpoint_p3_ratings import (
    apply_source_item_stat_delta, source_item_stat_to_combat,
)

_SOURCE_ITEM_CHANCE_STATS = frozenset(('crit', 'hit', 'dodge', 'defense'))
from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate


def _source_stat_perturbation(ir, *, stat: str, delta: float, level: int):
    """Use the existing source chance adapter or the generic gear applicator.

    The returned evidence is None for ordinary stats; no class-specific
    conversion or synthetic positive weight is introduced here.
    """
    if stat in _SOURCE_ITEM_CHANCE_STATS:
        evidence = source_item_stat_to_combat(stat, delta, level=level)
        return apply_source_item_stat_delta(ir, stat, delta, level=level), evidence
    return apply_stat_delta(ir, stat, delta), None


def _best_complete_rows(rows, *, mobs: int, pack_size: int | None = None) -> dict:
    """Select paid finalists within a fixed encounter, varying recovery only."""
    winners = {}
    for context in ('before', 'after'):
        eligible = [row for row in rows if row['context'] == context
                    and (pack_size is None or row['pack_size'] == pack_size)
                    and row['status'] == 'COMPLETE'
                    and row['mob_completed'] == mobs
                    and row['mean_s_per_mob'] is not None
                    and isfinite(float(row['mean_s_per_mob']))]
        if eligible:
            winners[context] = min(eligible, key=lambda row:
                                   (row['mean_s_per_mob'], row['recovery_policy_index'],
                                    row['pack_size']))
    return winners


def reoptimized_stat_sensitivity(*, candidate, stat: str, delta: float, level: int,
                                 recovery_policies: tuple, pack_sizes: tuple[int, ...] = (1,),
                                 mobs: int = 100, max_wall_s_per_eval: float = 10.0) -> dict:
    """Paid, apples-to-apples 100-mob before/after, optimizing recovery each side.

    Returned weight is (best old seconds/mob - best new seconds/mob)/delta.
    Negative or zero slopes are *reported as such*, never clamped to pass a gate.
    No candidate or source metadata is changed, and incomplete runs cannot win.
    """
    if not stat or not isfinite(float(delta)) or delta <= 0 or mobs != 100:
        raise ValueError('INVALID_STAT_SENSITIVITY_REQUEST')
    if not recovery_policies or not pack_sizes or len(set(pack_sizes)) != len(pack_sizes):
        raise ValueError('EMPTY_OR_DUPLICATED_POLICY_FRONTIER')
    if not isfinite(float(max_wall_s_per_eval)) or max_wall_s_per_eval <= 0:
        raise ValueError('INVALID_PAID_SENSITIVITY_WALL_BUDGET')
    after_ir, source_chance_mapping = _source_stat_perturbation(
        candidate.ir, stat=stat, delta=float(delta), level=level,
    )
    after_candidate = replace(candidate, ir=after_ir)
    rows = []
    for key, trial in (('before', candidate), ('after', after_candidate)):
        for index, policy in enumerate(recovery_policies):
            for pack_size in pack_sizes:
                result = evaluate_persistent_candidate(
                    trial, level=level, mobs=mobs, recovery_policy=policy,
                    pack_size=pack_size, max_wall_s=max_wall_s_per_eval,
                    max_total_events=200000)
                row = {
                    'context': key, 'recovery_policy_index': index,
                    'health_fraction': None if policy is None else float(policy.health_fraction),
                    'mana_fraction': None if policy is None else float(policy.mana_fraction),
                    'pack_size': pack_size, 'status': result.get('status'),
                    'mob_completed': result.get('mob_completed', result.get('count')),
                    'mean_s_per_mob': result.get('mean_s_per_mob'),
                    'events': result.get('events'),
                    'recovery_s': result.get('recovery_s'),
                    'between_pull_full_recoveries': result.get('between_pull_full_recoveries'),
                }
                rows.append(row)
    # Encounter geometry is part of the objective, not a decision variable.
    # Never compare pack=1 before to pack=2 after, even if the latter is faster.
    if len(pack_sizes) > 1:
        per_pack = {}
        for pack_size in pack_sizes:
            pack_rows = [row for row in rows if row['pack_size'] == pack_size]
            pack_best = _best_complete_rows(pack_rows, mobs=mobs, pack_size=pack_size)
            complete_pack = set(pack_best) == {'before', 'after'}
            slope = ((float(pack_best['before']['mean_s_per_mob'])
                      - float(pack_best['after']['mean_s_per_mob'])) / float(delta)
                     if complete_pack else None)
            per_pack[pack_size] = {
                'status': ('COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE' if complete_pack
                           else 'BLOCKED_NO_COMPLETE_HUNDRED_MOB_FRONTIER'),
                'stat': stat, 'delta': float(delta), 'mobs': mobs,
                'pack_size': pack_size, 'best': pack_best, 'rows': pack_rows,
                'weight_s_saved_per_mob_per_unit': slope,
                'positive': (slope > 0 if slope is not None else None),
            }
        complete = all(row['status'] == 'COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE'
                       for row in per_pack.values())
        return {
            'status': ('COMPLETE_CONTEXTUAL_100MOB_STAT_PROBE' if complete
                       else 'BLOCKED_CONTEXTUAL_INCOMPLETE_100MOB'),
            'stat': stat, 'delta': float(delta), 'mobs': mobs,
            'pack_sizes': list(pack_sizes), 'by_pack_size': per_pack,
            'weight_s_saved_per_mob_per_unit': None, 'positive': None,
            'best': None, 'rows': rows,
            'method': 'paid_100mob_recovery_reselection_fixed_encounter_per_context',
            'global_optimum_proven': False,
            'source_item_chance_mapping': source_chance_mapping,
        }
    winners = _best_complete_rows(rows, mobs=mobs, pack_size=pack_sizes[0])
    if set(winners) != {'before', 'after'}:
        return {'status':'BLOCKED_NO_COMPLETE_HUNDRED_MOB_FRONTIER',
                'stat':stat,'delta':delta,'mobs':mobs,'rows':rows,'best':winners,
                'weight_s_saved_per_mob_per_unit':None,
                'source_item_chance_mapping':source_chance_mapping}
    slope = (float(winners['before']['mean_s_per_mob'])
             - float(winners['after']['mean_s_per_mob'])) / float(delta)
    return {'status':'COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE',
            'stat':stat,'delta':float(delta),'mobs':mobs,
            'weight_s_saved_per_mob_per_unit':slope,
            'positive':slope > 0, 'best':winners, 'rows':rows,
            'method':'paid_100mob_recovery_and_pull_policy_reselection',
            'global_optimum_proven':False,
            'source_item_chance_mapping':source_chance_mapping}
