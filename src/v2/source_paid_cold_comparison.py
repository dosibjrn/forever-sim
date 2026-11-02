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



def source_gear_catalogue_snapshot(class_key, level):
    """Pin the actual gear source separately from the ability/talent SQLite.

    A class/level item frontier is not proven complete merely because its
    current catalogue can be enumerated. Keep membership attestation explicit.
    """
    from hashlib import sha256
    from src.rulesets.forever.items.runtime_selection import (
        available_items, catalogue_path, source_class_item_membership_verified)
    from src.rulesets.forever.items.source_equipment_semantics import ledger_path

    catalogue = catalogue_path()
    semantics = ledger_path()
    rows = available_items(class_key, level, required_level_policy='observed')
    ids = sorted(int(item.item_id) for item in rows)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('COLD_SOURCE_GEAR_EMPTY_OR_DUPLICATE_ITEM_UNIVERSE')
    return {
        'schema': 'source_gear_snapshot_v1',
        'class_key': class_key, 'level': level,
        'catalogue_sha256': sha256(catalogue.read_bytes()).hexdigest(),
        'equipment_semantics_sha256': sha256(semantics.read_bytes()).hexdigest(),
        'observed_eligible_item_ids_sha256': sha256(
            ''.join(f'{item_id}\\n' for item_id in ids).encode()).hexdigest(),
        'observed_eligible_item_count': len(ids),
        'class_membership_verified': source_class_item_membership_verified(
            class_key, catalogue),
    }


def _winner_gear_effect_gaps(winner, *, class_key, level):
    """Check actual equipped source items; partial diagnostics are not P4 L2."""
    from src.game.data.forever.source_checkpoint_p3 import source_item_l0
    from src.rulesets.forever.items.runtime_selection import available_items

    by_id = {int(item.item_id): item for item in available_items(
        class_key, level, required_level_policy='observed')}
    gaps = {}
    for slot, record in winner['equipped_gear']['slots'].items():
        item_id = int(record['item_id'])
        if item_id not in by_id:
            raise ValueError('COLD_COMPARISON_WINNER_ITEM_NOT_IN_SOURCE:' + str(item_id))
        unresolved = source_item_l0(by_id[item_id])['unresolved_effects']
        if unresolved:
            gaps[slot] = {'item_id': item_id, 'unresolved_effects': unresolved}
    return gaps


def _verify_winner_gear_legality(winner, *, class_key, level):
    """Recheck the entire paid finalist against the pinned item catalogue.

    Item membership alone does not validate slot compatibility, the canonical
    simulator stat payload, unique-equipped groups, or a 2H/offhand package.
    This is the same source audit used by the production P3 swap evaluator,
    before either independent 100-mob replay can consume a saved build.
    """
    from src.game.data.forever.source_named_gear_proof import audit_named_gear_source

    gear = winner.get('equipped_gear')
    if not isinstance(gear, dict):
        raise ValueError('COLD_COMPARISON_MISSING_SOURCE_GEAR')
    audit = audit_named_gear_source(class_key=class_key, level=level, gear=gear)
    if not audit['equipment_legality_complete']:
        raise ValueError('COLD_COMPARISON_WINNER_GEAR_NOT_SOURCE_LEGAL')
    return audit


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
    # The ability/talent SQLite hash does NOT pin the separate item catalogue
    # or its typed equipment-effects ledger. Recheck both source snapshots
    # against the current runtime before paying for an independent replay.
    # Legacy reports lacking snapshots remain diagnostic, never same-space proof.
    gear30 = search30.get('source_gear_catalogue_snapshot')
    gear300 = search300.get('source_gear_catalogue_snapshot')
    gear_pinned = bool(gear30 and gear300)
    if gear30 is not None or gear300 is not None:
        if (not gear_pinned or gear30 != gear300
                or gear30 != source_gear_catalogue_snapshot(class_key, level)):
            raise ValueError('COLD_COMPARISON_DIFFERENT_GEAR_SOURCE_SNAPSHOT')
    # The winner may have valid item IDs but illegal slots, duplicate or
    # unique-equipped items, forged stats, or a 2H+offhand combination.
    # Fail before expensive replay, not after a plausible numeric P6 score.
    legal30 = _verify_winner_gear_legality(winner30, class_key=class_key, level=level)
    legal300 = _verify_winner_gear_legality(winner300, class_key=class_key, level=level)
    gaps30 = _winner_gear_effect_gaps(winner30, class_key=class_key, level=level)
    gaps300 = _winner_gear_effect_gaps(winner300, class_key=class_key, level=level)
    space30, space300 = search30.get('source_search_space'), search300.get('source_search_space')
    same_space = bool(gear_pinned and space30 and space30 == space300)

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
        'p4_p5_source_coverage_proven': source_coverage and gear_pinned
            and not gaps30 and not gaps300,
        'same_gear_catalogue_and_semantics_proven': gear_pinned,
        'source_class_gear_membership_attested': bool(gear_pinned
            and gear30['class_membership_verified']),
        'winning_gear_source_legality_verified': True,
        'winning_gear_sourced_acquisition_methods': {
            '30s': legal30['sourced_acquisition_methods'],
            '300s': legal300['sourced_acquisition_methods']},
        'winning_gear_unresolved_effects': {'30s': gaps30, '300s': gaps300},
        'winning_gear_l2_effects_supported': not gaps30 and not gaps300,
        'eligible_for_checkpoint_acceptance': False}
