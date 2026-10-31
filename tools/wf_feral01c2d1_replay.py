"""Held-out diagnostic: same gear sets and scorer, including STR/AGI/AP.

This is not an unrestricted talent search or verified Forever optimum.
"""
from __future__ import annotations

import json
from pathlib import Path
from src.version import SOFTWARE_VERSION
from src.game.data.forever.druid import build_source_slice
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_mode_search import evaluate_discovered_mode_search
from src.v2.source_policy_search import evaluate_discovered_policy_search


def run():
    source = build_source_slice(20)
    held_out = {
        'old_feral_11_points': {'ferocity':5,'heart_of_the_wild':3,'thick_hide':2,'savage_fury':1},
        'improved_wrath_5': {'improved_wrath':5},
    }
    for allocation in held_out.values():
        validate_talent_selection(source, allocation, level=20)
    gear_rows = _gear_envelope('druid',20,max_gear_candidates=128,
                                include_melee_gear=True, ir_slice=source)
    results = []
    for gear in gear_rows:
        selection = gear['selection']
        geared, application = apply_gear_selection(
            source, aggregate_stats=selection.aggregate_stats,
            selected_items=tuple(selection.slots.values()))
        row = {
            'gear_id': gear['id'], 'gear_role': gear['gear_role'],
            'weight_vector': gear['weight_vector'],
            'aggregate_stats': dict(selection.aggregate_stats),
            'applied_stats': dict(application.applied_stats),
            'unsupported_stats': dict(application.unsupported_stats),
            'builds': {},
        }
        for name, allocation in held_out.items():
            talented, _ = apply_talent_selection(geared, allocation, level=20)
            mode = evaluate_discovered_mode_search(class_key='druid',level=20,
                    ir_slice=talented,max_policies_per_path=24)
            caster = evaluate_discovered_policy_search(class_key='druid',level=20,
                    ir_slice=geared,talent_selection=allocation,max_policies=24)
            branches = [('mode',mode['winner']),('caster',caster['winner'])]
            best_branch, best = min(branches,key=lambda pair:float(pair[1]['seconds_per_mob']))
            row['builds'][name] = {
                'mode_score_s_per_mob':mode['winner']['seconds_per_mob'],
                'caster_score_s_per_mob':caster['winner']['seconds_per_mob'],
                'best_branch':best_branch,
                'best_score_s_per_mob':best['seconds_per_mob'],
                'mode_auto_attack_damage':mode['winner']['auto_attack_damage'],
            }
        pair = sorted(((name, float(details['best_score_s_per_mob']))
                       for name, details in row['builds'].items()), key=lambda x: x[1])
        row['pairwise_winner'] = ('tie' if abs(pair[0][1] - pair[1][1]) <= 1e-9
                                  else pair[0][0])
        results.append(row)
    best_by_build = {name: min(
        ({'gear_id':row['gear_id'],'gear_role':row['gear_role'],
          'weight_vector':row['weight_vector'],
          'score_s_per_mob':row['builds'][name]['best_score_s_per_mob'],
          'best_branch':row['builds'][name]['best_branch']}
         for row in results),key=lambda x:x['score_s_per_mob'])
        for name in held_out}
    return {
        'version': SOFTWARE_VERSION, 'scope':'HELD_OUT_TWO_BUILDS_SOURCE_GEAR_WITH_STR_AGI_AP',
        'class_key':'druid','level':20,'gear_candidates':len(gear_rows),
        'builds':held_out,'policy_caps':{'caster':24,'mode_per_path':24},
        'best_by_build':best_by_build,
        'pairwise_wins':{name:sum(row['pairwise_winner']==name for row in results) for name in held_out},
        'pairwise_ties':sum(row['pairwise_winner']=='tie' for row in results),
        'blocking_gaps':[
            'not an unrestricted 417-allocation search',
            'not a complete per-slot or mixed-ratio gear search; 7 single-stat axes plus combined seeds',
            'source tree legality provisional',
            'Stamina/Armor item effects unsupported in production policy score',
            'ordinary incoming mob attacks absent from production policy score',
            'base Strength -> AP and base Stamina -> HP not fully represented',
            'selected item weapon_dps is retained as unsupported in this generic scorer',
            'Dire Bear missing; bear armor multiplier absent',
            'Classic inherited conversion coefficient not Forever-verified',
        ],
        'source_coverage_complete':False,
        'results':results,
    }

if __name__=='__main__':
    out = Path(f'WF_FERAL01C2D1_STRENGTH_GEAR_REPLAY_v{SOFTWARE_VERSION}.json')
    result = run()
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'gear_candidates':result['gear_candidates'],
        'pairwise_wins':result['pairwise_wins'], 'pairwise_ties':result['pairwise_ties'],
        'best_by_build':result['best_by_build']},indent=2))
