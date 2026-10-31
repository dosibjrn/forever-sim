"""Source-native Cat/Bear/Caster combat+recovery comparison with incoming hits.

Legacy allocation is a held-out regression, not a seeded optimizer solution.
This reports evaluated grid and does NOT claim unrestricted optimality.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.game.data.forever.druid import build_source_slice
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.v2.source_joint_discovery import _gear_envelope, _evaluate_caster_already_talented
from src.v2.source_mode_search import evaluate_discovered_mode_search
from src.version import SOFTWARE_VERSION


BUILDS={
    'legacy_feral_challenger':{'ferocity':5,'heart_of_the_wild':3,'thick_hide':2,'savage_fury':1},
    'improved_wrath_5':{'improved_wrath':5},
}


def run():
    source=build_source_slice(20)
    for build in BUILDS.values():
        validate_talent_selection(source,build,level=20)
    gears=_gear_envelope('druid',20,ir_slice=source,max_gear_candidates=128,
                         include_melee_gear=True, required_level_policy='observed')
    results=[]
    for entry in gears:
        selection=entry['selection']
        geared,application=apply_gear_selection(source,
            aggregate_stats=selection.aggregate_stats,
            selected_items=tuple(selection.slots.values()))
        builds={}
        for name,allocation in BUILDS.items():
            ir,talent_application=apply_talent_selection(geared,allocation,level=20)
            scores=[]
            try:
                caster=_evaluate_caster_already_talented(ir,level=20,max_policies=24,
                                  schedule_incoming_attacks=True)
                scores.append({'branch':'caster','score_s_per_mob':caster['winner']['seconds_per_mob'],
                    'recovery_s':caster['winner']['recovery_s'],
                    'policy_id':caster['winner']['policy_id'],
                    'selected_actions':caster['winner']['selected_actions']})
            except ValueError as e:
                scores.append({'branch':'caster','rejected':str(e)})
            try:
                mode=evaluate_discovered_mode_search(class_key='druid',level=20,
                    ir_slice=ir,max_policies_per_path=24,schedule_incoming_attacks=True)
                scores.append({'branch':'mode','score_s_per_mob':mode['winner']['seconds_per_mob'],
                    'recovery_s':mode['winner']['recovery_s'],
                    'mode':mode['winner']['path']['combat_mode'],
                    'policy_id':mode['winner']['policy_id'],
                    'selected_actions':mode['winner']['selected_actions']})
            except ValueError as e:
                scores.append({'branch':'mode','rejected':str(e)})
            eligible=[r for r in scores if 'score_s_per_mob' in r]
            builds[name]={'talents':allocation,'winner':min(eligible,key=lambda x:x['score_s_per_mob']) if eligible else None,
                          'branches':scores}
        results.append({'gear_id':entry['id'],'gear_role':entry['gear_role'],
            'weight_vector':entry['weight_vector'],'gear_stats':dict(application.applied_stats),
            'gear_unsupported_stats':dict(application.unsupported_stats),
            'gear_slots':{s:{'item_id':v['item_id'],'name':v.get('name')} for s,v in selection.slots.items()},
            'builds':builds})
    summary={name:min(({'score_s_per_mob':r['builds'][name]['winner']['score_s_per_mob'],
                       'gear_id':r['gear_id'],'gear_role':r['gear_role'],
                       'gear_stats':r['gear_stats'],'gear_slots':r['gear_slots'],
                       'policy':r['builds'][name]['winner']} for r in results if r['builds'][name]['winner']),
                      key=lambda r:r['score_s_per_mob']) for name in BUILDS}
    return {'version':SOFTWARE_VERSION,'scope':'HELD_OUT_TWO_BUILDS_SHARED_SOURCED_INCOMING_SCORER',
            'required_level_policy':'observed','incoming_attacks_scored':True,'source_armor':True,'class_key':'druid','level':20,
            'builds':BUILDS,'gear_candidate_count':len(gears),'evaluated_gear_build_pairs':len(results)*len(BUILDS),
            'best_by_build':summary,'results':results,
            'limitations':['Two held-out talent builds only; NOT independent unrestricted talent search',
             'Talent tree legality and many source effects are not yet complete',
             'Health/Armor secondary mechanics, attack table and item procs not exhaustive',
             'Bounded gear weight vectors, not exhaustive item combinations']}


if __name__=='__main__':
    value=run()
    output=Path(f'WF_COMBAT233_ARMOR_INCOMING_REPLAY_v{SOFTWARE_VERSION}.json')
    output.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in value.items() if k in ('version','gear_candidate_count','evaluated_gear_build_pairs','best_by_build')},indent=2)[:4000])
