"""Independent bounded native Hunter/Paladin source search and partial OG replay.

Neither result is a complete class-level optimum. OG Hunter pet/talents/Aimed
Shot cannot be executed in this source IR; the old gear can be evaluated only
as a restricted action-policy counterfactual, explicitly NOT an exact challenger.
"""
from __future__ import annotations
import json
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection
from src.game.model.ir import PolicyCondition, PolicyDefinition, PolicyRuleDefinition
from src.game.multi_pull import evaluate_repeated_pulls
from src.shared.leveling.objective import representative_hp
from src.v2.source_legal_beam import search_source_legal_beam

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'docs/validation/I15/LISTENER_LOCAL_I15_STATE_v0.11.48.103.json'

def run():
    results={}
    for key in ('hunter','paladin'):
        result=search_source_legal_beam(class_key=key,level=20,
            max_allocations=8,screening_gear_count=1,finalists=2,
            policy_cap=8,beam_width=1)
        results[key]={'independent_search':result,
            'full_source_coverage':False,'global_optimum_proven':False}
    old=json.loads(OLD.read_text())['endpoint_paths']['hunter']['targets']['20']['routes']['unconstrained']['path']
    slots=old['gear_stats']['slots']
    aggregate={k:sum(float(x.get(k,0.) or 0.) for x in slots.values())
               for k in ('strength','agility','stamina','intellect','spirit','attack_power',
                         'spell_power','mp5','armor','weapon_dps')}
    source=build_game_ir_slice(class_key='hunter',level=20)
    geared,_=apply_gear_selection(source,aggregate_stats=aggregate,
        selected_items=tuple(slots.values()),source='legacy_i15_named_sqlite_items_replayed')
    sting=next(a for a in geared.actions if a.family_key=='serpent_sting')
    shot=next(a for a in geared.actions if a.family_key=='arcane_shot')
    policy=PolicyDefinition(id='historical_hunter_executable_subset',
        label='Old Serpent + Arcane + Auto subset, NO pet/Aimed/Aspect',
        rules=(PolicyRuleDefinition('sting',sting.id,conditions=(
            PolicyCondition('aura_missing',scope='target',aura_id=sting.effects[0].aura_id),)),
            PolicyRuleDefinition('shot',shot.id)),
        provenance={'status':'translated_subset_not_old_winner'})
    try:
        old_partial=evaluate_repeated_pulls(ir_slice=geared,policy=policy,level=20,
            target_health=representative_hp(20),count=3,
            schedule_incoming_attacks=True,apply_target_defense=True)
        old_score=old_partial.seconds_per_mob
        old_pulls=list(old_partial.pulls)
        old_error=None
    except ValueError as exc:
        old_score=None;old_pulls=[];old_error=str(exc)
    results['hunter']['historical_reference']={
        'old_legacy_reported_s_per_mob':float(old['score_s_per_100'])/100.,
        'old_gear_exact_item_ids':{k:int(v['item_id']) for k,v in slots.items()},
        'old_talent_allocation':old['talent_ranks'],
        'old_policy':old.get('rotation',old.get('policy')),
        'old_partial_source_engine_s_per_mob':old_score,
        'old_partial_source_engine_error':old_error,
        'old_partial_source_engine_pulls':old_pulls,
        'old_gear_ranged_weapon_dps':slots['ranged']['weapon_dps'],
        'old_gear_melee_weapon_dps':slots['weapon']['weapon_dps'],
        'old_gear_executable_ranged_dps':geared.auto_attacks[0].damage_source.flat_dps,
        'full_old_candidate_evaluated':False,
        'comparison_valid':False,
        'why_invalid':['Old Hunter build uses pet attack, Aimed Shot, Aspect of the Hawk and 11 talent points; these source actions/effects are not executable in the new IR.',
                       'Old leveling objective includes route travel and different recovery; new objective is three incoming-inclusive pulls.',
                       'Old named gear is evaluated exactly item-by-item only for the translated action subset, NOT the old complete build.',
                       'Starting HP, mana, weapon speed and ordinary enemy attacks still contain explicit Classic/scenario proxies.']}
    results['paladin']['historical_reference']={'comparison_valid':False,
        'reason':'No reconstructable full old Paladin named gear+talent+policy winner in current baseline; Seal of Righteousness and talent effects remain unexecuted.'}
    return {'version':'0.11.48.251','status':'BOUNDED_PARTIAL_SOURCE_COVERAGE',
            'source_provider_count':9,'results':results}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='WF251_TWO_CLASS_REPLAY.json');a=parser.parse_args()
    r=run();Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:{'winner':v['independent_search']['independent_winner']['seconds_per_mob'],
                          'talents':v['independent_search']['independent_winner']['talent_allocation'],
                          'gear_count':len(v['independent_search']['independent_winner']['gear_slots'])}
                     for k,v in r['results'].items()},indent=2))
