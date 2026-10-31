"""Diagnostic same-scorer replay, NOT a certified Druid L20 optimum."""
from __future__ import annotations
import json
from pathlib import Path
from src.game.data.forever.druid import build_source_slice
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_mode_search import evaluate_discovered_mode_search
from src.v2.source_policy_search import evaluate_discovered_policy_search


def run():
    source=build_source_slice(20)
    builds={
        'old_feral_11_points': {'ferocity':5,'heart_of_the_wild':3,'thick_hide':2,'savage_fury':1},
        'improved_wrath_5': {'improved_wrath':5},
    }
    for selection in builds.values():
        validate_talent_selection(source,selection,level=20)
    result={'version':'0.11.48.228','scope':'DIAGNOSTIC_HELD_OUT_TWO_BUILDS',
            'class_key':'druid','level':20,
            'candidate_origin':'old Feral held-out; Wrath reference from prior new optimizer',
            'current_talent_families':len(source.talents),
            'current_executable_allocations':417,
            'source_tree_positions_verified':False,
            'source_coverage_complete':False,
            'policy_caps':{'caster':24,'mode_per_path':24},
            'gear_candidates':[],
            'blocking_gaps':['provisional talent tree legality',
                'gear Strength/Stamina/Armor not fully executable',
                'incoming enemy hits absent from ordinary production policy scorer',
                'Dire Bear missing from IR',
                'base primary stat to AP and HP source conversions incomplete',
                'inherited Classic conversion proxies not Forever-verified',
                'not an independent 417-allocation search',
                'not a full gear search; only five caster weight vectors'],
            'results':[]}
    gear_rows=_gear_envelope('druid',20,max_gear_candidates=8)
    for gear in gear_rows:
        row={'gear_id':gear['id'],'weight_vector':gear['weight_vector'],'builds':{}}
        geared,_=apply_gear_selection(source,aggregate_stats=gear['selection'].aggregate_stats,
                                      selected_items=tuple(gear['selection'].slots.values()))
        for key,allocation in builds.items():
            talented,_=apply_talent_selection(geared,allocation,level=20)
            mode=evaluate_discovered_mode_search(class_key='druid',level=20,ir_slice=talented,
                                                 max_policies_per_path=24)
            caster=evaluate_discovered_policy_search(class_key='druid',level=20,ir_slice=geared,
                                                      talent_selection=allocation,max_policies=24)
            candidates=[('mode',mode['winner']),('caster',caster['winner'])]
            best=min(candidates,key=lambda x:float(x[1]['seconds_per_mob']))
            row['builds'][key]={'mode_score_s_per_mob':mode['winner']['seconds_per_mob'],
                                'caster_score_s_per_mob':caster['winner']['seconds_per_mob'],
                                'best_branch':best[0], 'best_score_s_per_mob':best[1]['seconds_per_mob'],
                                'mode_auto_attack_damage':mode['winner']['auto_attack_damage']}
        row['best_in_this_two_build_comparison']=min(row['builds'],key=lambda k:row['builds'][k]['best_score_s_per_mob'])
        result['results'].append(row)
    result['best_over_five_gears_and_two_builds']=min(
        ({'gear_id':row['gear_id'],'build':name,'score_s_per_mob':build['best_score_s_per_mob']}
         for row in result['results'] for name,build in row['builds'].items()),
        key=lambda x:x['score_s_per_mob'])
    return result

if __name__=='__main__':
    output=Path('WF_FERAL01C2C_HEART_REPLAY_EVIDENCE_v0.11.48.228.json')
    result=run()
    output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result['best_over_five_gears_and_two_builds'],indent=2))
