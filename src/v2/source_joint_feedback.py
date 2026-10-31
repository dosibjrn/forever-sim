"""Generic coordinate feedback on a genuinely evaluated joint-state grid.

Does not claim a global optimizer: uses pre-evaluated policy optimum for each
gear/talent pair and reports incomplete/non-cartesian coverage explicitly.
"""
from __future__ import annotations


def trace_joint_feedback(states, *, start_gear_id=None, start_talent_id=None, max_sweeps=32):
    if not states or max_sweeps < 1:
        raise ValueError('nonempty evaluated grid and positive sweep limit required')
    indexed = {}
    gears, talents = set(), set()
    for row in states:
        gear, talent = row['gear_id'], row['talent_id']
        score = float(row['score_s_per_mob'])
        if not (score > 0 and score < float('inf')) or (gear, talent) in indexed:
            raise ValueError('duplicate or invalid scored state')
        if not row.get('best_policy'):
            raise ValueError('missing executed policy evaluation')
        indexed[(gear, talent)] = row
        gears.add(gear)
        talents.add(talent)
    if len(indexed) != len(gears) * len(talents):
        raise ValueError('feedback requires a complete evaluated Cartesian grid')
    gear = start_gear_id if start_gear_id is not None else sorted(gears)[0]
    talent = start_talent_id if start_talent_id is not None else sorted(talents)[0]
    if (gear, talent) not in indexed:
        raise ValueError('initial state not in evaluated grid')
    def step(g, t, axis):
        choices = ([(x, t) for x in gears] if axis == 'gear' else
                   [(g, x) for x in talents])
        return min(choices, key=lambda key: (float(indexed[key]['score_s_per_mob']), key))
    def snapshot(g, t, axis):
        row = indexed[(g,t)]
        p = row['best_policy']
        return {'axis': axis, 'gear_id': g, 'talent_id': t,
                'policy_id': p['policy_id'], 'branch': p['branch'],
                'score_s_per_mob': float(row['score_s_per_mob'])}
    trace = [snapshot(gear, talent, 'initial')]
    seen = {(gear, talent)}
    for sweep in range(max_sweeps):
        previous = (gear, talent)
        for axis in ('gear', 'talents'):
            next_gear, next_talent = step(gear, talent, axis)
            old_score = float(indexed[(gear, talent)]['score_s_per_mob'])
            new_score = float(indexed[(next_gear, next_talent)]['score_s_per_mob'])
            if new_score < old_score - 1e-10:
                gear, talent = next_gear, next_talent
                trace.append(snapshot(gear, talent, axis))
        if (gear, talent) == previous:
            return {'status': 'COORDINATE_STABLE_BOUNDED_GRID', 'converged': True,
                    'sweeps': sweep+1, 'trace': trace, 'winner': indexed[(gear,talent)],
                    'global_grid_winner': min(indexed.values(),key=lambda r:(r['score_s_per_mob'],r['gear_id'],r['talent_id'])),
                    'global_optimum_proven': False,
                    'scope': 'evaluated_cartesian_grid_only'}
        if (gear, talent) in seen:
            raise ValueError('coordinate feedback cycle detected')
        seen.add((gear, talent))
    raise ValueError('coordinate feedback exceeded explicit sweep bound')
