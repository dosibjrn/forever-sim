"""Bounded, source-runtime-scored chainpull/recovery schedule frontier.

Each proposal replays the same GameIR / sourced actions / policy on the real
consecutive-mob objective. This chooses a fixed recovery *threshold policy*;
it does not claim optimal per-mob lookahead, talent or gear optimization.
"""
from __future__ import annotations

from math import isfinite
from time import perf_counter

from src.game.multi_pull import evaluate_repeated_pulls


def search_recovery_thresholds(
    *, ir_slice, policy, level: int, target_health: float,
    count: int = 100, pack_size: int = 1,
    health_fractions: tuple[float, ...] = (0.25, 0.5, 0.75),
    mana_fractions: tuple[float, ...] = (0.1, 0.3, 0.6),
    include_always: bool = True,
    schedule_incoming_attacks: bool = True,
    **scenario,
) -> dict:
    """Evaluate source-executed threshold policies, preserving actor carry.

    The evaluator, not a guessed mana-per-mob estimate, performs every kill,
    recovery choice, cooldown progression and final restoration payment.
    """
    if any(key in scenario for key in ('recovery_mode', 'recovery_health_fraction',
                                       'recovery_mana_fraction')):
        raise ValueError('threshold search owns its recovery parameters')
    health = tuple(health_fractions)
    mana = tuple(mana_fractions)
    if any(type(x) not in (float, int) or not isfinite(float(x)) or not 0 <= x <= 1
           for x in health + mana):
        raise ValueError('invalid recovery threshold fraction')
    if len(health) * len(mana) + int(include_always) == 0:
        raise ValueError('at least one recovery candidate required')
    if len(health) * len(mana) + int(include_always) > 100:
        raise ValueError('recovery candidate budget exceeded (100)')
    # Exact duplicate fractions do not earn duplicate expensive paid runs.
    candidates = ([('always', 1.0, 1.0)] if include_always else []) + [
        ('threshold', h, m) for h in dict.fromkeys(health) for m in dict.fromkeys(mana)]
    rows = []
    total_wall_start = perf_counter()
    for mode, hp, mp in candidates:
        wall = perf_counter()
        row = {'recovery_mode': mode, 'health_threshold': hp,
               'mana_threshold': mp, 'status': 'FAILED', 'mobs_killed': 0,
               'seconds_per_mob': None, 'recovery_calls': None,
               'recovery_s': None, 'event_transitions': None}
        try:
            result = evaluate_repeated_pulls(
                ir_slice=ir_slice, policy=policy, level=level,
                target_health=target_health, count=count, pack_size=pack_size,
                schedule_incoming_attacks=schedule_incoming_attacks,
                recovery_mode=mode, recovery_health_fraction=hp,
                recovery_mana_fraction=mp, **scenario)
            kills = sum(int(p['mob_count']) if p['pack_all_defeated'] else 0
                        for p in result.pulls)
            if kills != count or not isfinite(result.seconds_per_mob):
                raise ValueError(f'incomplete or nonfinite 100mob objective: {kills}/{count}')
            row.update(status='COMPLETE', mobs_killed=kills,
                seconds_per_mob=float(result.seconds_per_mob),
                recovery_calls=sum(bool(p['recovery_performed']) for p in result.pulls),
                recovery_s=sum(float(p['recovery_s']) for p in result.pulls),
                event_transitions=sum(int(p['event_transitions']) for p in result.pulls))
        except (ValueError, RuntimeError) as exc:
            row['reason'] = f'{type(exc).__name__}: {exc}'
        row['wall_s'] = perf_counter() - wall
        rows.append(row)
    successful = [r for r in rows if r['status'] == 'COMPLETE']
    best = min(successful, key=lambda row: (row['seconds_per_mob'], row['recovery_calls'],
                                            row['recovery_mode'], row['health_threshold'],
                                            row['mana_threshold'])) if successful else None
    return {'status': 'EVALUATED_BOUNDED' if best is not None else 'NO_SURVIVING_CANDIDATE',
            'objective': 'real GameIR 100-mob kill+recovery+survival, seconds/mob',
            'total_candidates': len(rows), 'evaluated': len(rows),
            'complete': len(successful), 'failed': len(rows)-len(successful),
            'mobs_requested': count, 'pack_size': pack_size,
            'best': best, 'baseline_always': next((r for r in rows if r['recovery_mode']=='always'), None),
            'candidates': rows, 'elapsed_wall_s':perf_counter()-total_wall_start,
            'global_optimum_proven': False,
            'limitations': ['fixed threshold policy candidates only',
                            'no search of talent, gear, mob target selection or movement in this call']}
