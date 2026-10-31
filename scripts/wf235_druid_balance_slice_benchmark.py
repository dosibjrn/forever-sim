"""Diagnostic, *restricted* L20 Balance talent slice; never global optimum."""
from __future__ import annotations
from dataclasses import replace
import json
from pathlib import Path
from src.game.data.forever.druid import build_source_slice
from src.game.talents import apply_talent_selection
from src.v2.source_staged_joint_search import evaluate_staged_joint_search
from src.v2.source_joint_discovery import _gear_envelope, _evaluate_caster_already_talented
from src.v2.source_mode_search import evaluate_discovered_mode_search
from src.game.gear import apply_gear_selection


def run():
    ir=build_source_slice(20)
    # This is an explicit scoped diagnostic of the newly supported Balance
    # mechanics, not the unrestricted optimizer's talent whitelist.
    names={'improved_wrath','genesis','moonglow'}
    restricted=replace(ir,talents=tuple(t for t in ir.talents if t.id in names))
    found=evaluate_staged_joint_search(class_key='druid',level=20,ir_slice=restricted,
        max_gear_candidates=64,screening_gear_count=2,finalist_talent_count=6,
        max_talent_candidates=1000,max_policies_per_path=24,max_caster_policies=24,
        schedule_incoming_attacks=True)
    gears=_gear_envelope('druid',20,max_gear_candidates=64,
        required_level_policy='observed',include_melee_gear=True,ir_slice=ir)
    heldout={'ferocity':5,'heart_of_the_wild':3,'thick_hide':2,'savage_fury':1}
    old=[]
    for i,gear in enumerate(gears):
        equipped,_=apply_gear_selection(ir,aggregate_stats=gear['selection'].aggregate_stats,
            selected_items=tuple(gear['selection'].slots.values()),source='canonical_sqlite_forever_catalogue')
        talented,application=apply_talent_selection(equipped,heldout,level=20)
        candidates=[]
        for branch in ('caster','mode'):
            try:
                result=(_evaluate_caster_already_talented(talented,level=20,max_policies=24,
                        schedule_incoming_attacks=True) if branch=='caster' else
                        evaluate_discovered_mode_search(class_key='druid',level=20,ir_slice=talented,
                        max_policies_per_path=24,schedule_incoming_attacks=True))
                candidates.append((float(result['winner']['seconds_per_mob']),branch,result['winner']))
            except (ValueError,RuntimeError,KeyError):pass
        if candidates:
            score,branch,winner=min(candidates,key=lambda x:x[0])
            old.append({'gear_index':i,'gear_id':gear['id'],'score':score,
                        'branch':branch,'policy':winner})
    old.sort(key=lambda x:x['score'])
    return {'scope':'explicit_three_family_balance_slice_not_global_optimum',
            'source_talent_families':len(ir.talents),
            'new_secondary_rank_families':7,
            'source_restricted_ids':sorted(names),
            'new_independent_winner':found['winner'],
            'restricted_search':{k:v for k,v in found.items() if k not in ('winner','finalists','talent_sqlite_coverage')},
            'heldout_legacy_fully_replayed':bool(old),
            'heldout_legacy_best':old[0] if old else None,
            'heldout_gear_count':len(old),
            'comparison_same_scorer_and_policy_budget':True,
            'global_optimum_claim':False}

if __name__=='__main__':
    result=run()
    path=Path('WF_COVERAGE235_BALANCE_SLICE_EVIDENCE.json')
    path.write_text(json.dumps(result,indent=2,default=str))
    print(json.dumps({'winner':result['new_independent_winner']['seconds_per_mob'],
        'winner_talents':result['new_independent_winner']['talent_allocation'],
        'heldout':result['heldout_legacy_best']['score'],
        'states':result['restricted_search']['evaluated_state_count'],
        'allocations':result['restricted_search']['talent_allocations_enumerated']}))
