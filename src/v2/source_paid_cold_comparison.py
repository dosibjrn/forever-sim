"""Independent paid 30s/300s source-search comparison on the same live runtime.

A saved search is only a proposal. Its previously measured 100-mob score
must not be used as the comparison score: re-execute each validated winning
full build from its saved source gear, talents, APL and recovery configuration.
"""
from __future__ import annotations

from math import isfinite


_COMMON = ('class_key', 'level', 'source_db_sha256', 'enemy', 'pack_size',
           'spatial_mode', 'bonus_talent_points', 'talent_point_budget',
           'spec_constraint', 'reference_origin', 'screen_evaluator_backend')


def _saved_winner(report, *, expected_budget, source_hash, class_key, level):
    """Fail closed on a missing or unverified 100-mob search finalist."""
    if (report.get('source_db_sha256') != source_hash
            or report.get('class_key') != class_key or report.get('level') != level):
        raise ValueError('COLD_COMPARISON_SOURCE_OR_CHECKPOINT_MISMATCH')
    if (not report.get('search_only') or report.get('complete_100mob_candidates')
            or float(report.get('requested_wall_budget_s') or 0) != expected_budget
            or not 0 < float(report.get('wall_s') or 0) <= expected_budget):
        raise ValueError('COLD_COMPARISON_INVALID_SEARCH_BUDGET_OR_MODE')
    validation = report.get('validation') or {}
    rows = report.get('validation_shortlist') or []
    winner_id = validation.get('validated_winner_id')
    if winner_id is None or not str(winner_id).isdigit():
        raise ValueError('COLD_COMPARISON_NO_VALIDATED_100MOB_WINNER')
    index = int(winner_id)
    if not 0 <= index < len(rows):
        raise ValueError('COLD_COMPARISON_WINNER_OUTSIDE_SAVED_SHORTLIST')
    witnessed = next((row for row in validation.get('rows', ())
                      if str(row.get('id')) == str(index)), None)
    if (witnessed is None or witnessed.get('status') != 'COMPLETE'
            or witnessed.get('count') != 100
            or not isfinite(float(witnessed.get('full_s_per_mob') or float('inf')))):
        raise ValueError('COLD_COMPARISON_WINNER_NOT_100MOB_COMPLETE')
    selected = rows[index]
    required = {'allocation', 'equipped_gear', 'opening_action_ids',
                'policy_ir', 'policy_signature', 'recovery'}
    if required - set(selected):
        raise ValueError('COLD_COMPARISON_INCOMPLETE_SAVED_SOURCE_BUILD')
    return selected


def compare_saved_cold_winners(search30, search300, *, source_ir, seed_stage,
                               class_key, level, source_hash,
                               bonus_talent_points=0, max_per_candidate_wall_s=60.):
    """Independently replay two winners; never turn a diagnostic into P6 PASS.

    The selected source engine is the same retained 2D CombatRuntime used by
    search and the existing independent shortlist replay, not a second scorer.
    """
    for key in _COMMON:
        if search30.get(key) != search300.get(key):
            raise ValueError('COLD_COMPARISON_DIFFERENT_OBJECTIVE:' + key)
    if (search30.get('bonus_talent_points') != bonus_talent_points
            or search30.get('pack_size') is None):
        raise ValueError('COLD_COMPARISON_REPLAY_CONFIGURATION_MISMATCH')
    winner30 = _saved_winner(search30, expected_budget=30,
        source_hash=source_hash, class_key=class_key, level=level)
    winner300 = _saved_winner(search300, expected_budget=300,
        source_hash=source_hash, class_key=class_key, level=level)
    # New reports preserve the exact legal candidate-universe limits. Older
    # reports can be independently replayed but cannot prove same-space P4/P5.
    space30, space300 = search30.get('source_search_space'), search300.get('source_search_space')
    same_space = bool(space30 and space30 == space300)

    from src.v2.source_bounded_joint_frontier import replay_joint_shortlist_100mob
    results = []
    for budget, saved, winner in ((30, search30, winner30),
                                  (300, search300, winner300)):
        replay = replay_joint_shortlist_100mob({
            'search_only': True, 'validation_shortlist': [winner],
            'complete_100mob_candidates': 0, 'wall_s': saved['wall_s'],
            'spec_constraint': saved.get('spec_constraint')},
            source_ir=source_ir, seed_stage=seed_stage,
            class_key=class_key, level=level,
            bonus_talent_points=bonus_talent_points,
            pack_size=int(saved['pack_size']),
            max_per_candidate_wall_s=max_per_candidate_wall_s)
        row = replay['rows'][0]
        results.append({'budget_s': budget, 'status': row['status'],
            'count': row.get('count'), 's_per_mob': row.get('full_s_per_mob'),
            'events': row.get('events'), 'reason': row.get('reason'),
            'failed_pull_index': row.get('failed_pull_index'),
            'replay_wall_s': replay['wall_s_outside_search_budget']})
    complete = all(r['status'] == 'COMPLETE' and r['count'] == 100
                   and r['s_per_mob'] is not None and isfinite(r['s_per_mob'])
                   for r in results)
    ratio = results[0]['s_per_mob'] / results[1]['s_per_mob'] if complete else None
    n30, n300 = (int(s.get('unique_full_builds') or 0)
                 for s in (search30, search300))
    breadth = n30 > 0 and n300 >= 10*n30
    source_coverage = all(s.get('p4_talent_unlock_coverage_pass') is True
                          and s.get('source_legal_gear_universe_verified') is True
                          for s in (search30, search300))
    # The gate is NOT accepted just because numeric P6 looks good: source
    # coverage and source/engine acceptance must be independently certified.
    return {'status': ('INCOMPLETE_INDEPENDENT_100MOB_REPLAY' if not complete
        else 'NUMERIC_P6_SATURATION_FAIL' if ratio > 1.01
        else 'PAID_COMPARISON_COMPLETE_DIAGNOSTIC_NOT_GATE_ACCEPTED'),
        'replays': results, 'T30_s_per_mob': results[0]['s_per_mob'],
        'T300_s_per_mob': results[1]['s_per_mob'],
        'ratio_T30_T300': ratio, 'numeric_p6_within_1pct': bool(complete and ratio <= 1.01),
        'N30_unique_paid': n30, 'N300_unique_paid': n300,
        'p5_10x_breadth': breadth, 'same_source_legal_candidate_space_proven': same_space,
        'p4_p5_source_coverage_proven': source_coverage,
        'eligible_for_checkpoint_acceptance': False}
