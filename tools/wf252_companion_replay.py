"""W252 sourced Hunter pet independent joint search and matched counterfactuals.

Historical Hunter remains non-comparable: its 11 talent points, Aimed Shot,
Aspect and pet build are not source-complete in this Game IR.
"""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import json
from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection
from src.game.model import PolicyCondition,PolicyDefinition,PolicyRuleDefinition
from src.game.multi_pull import evaluate_repeated_pulls
from src.shared.leveling.objective import representative_hp
from src.v2.source_legal_beam import search_source_legal_beam
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_multi_pull_joint import _source_policy_envelope
from src.v2.source_companion_policy_search import companion_policy_envelope
ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'docs/validation/I15/LISTENER_LOCAL_I15_STATE_v0.11.48.103.json'


def _without_companions(ir):
    return replace(ir,companions=(),actor_links=(),
        actions=tuple(a for a in ir.actions if a.owner_actor_id==ir.actor.id),
        auto_attacks=tuple(a for a in ir.auto_attacks if a.owner_actor_id==ir.actor.id),
        policies=tuple(p for p in ir.policies if not p.provenance.get('companion_policy')))


def run():
    result=search_source_legal_beam(class_key='hunter',level=20,
        max_allocations=8,screening_gear_count=2,finalists=2,policy_cap=8,beam_width=1)
    winner=result['independent_winner']
    source=build_game_ir_slice(class_key='hunter',level=20)
    gears=_gear_envelope('hunter',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=source)
    selected=next(x['selection'] for x in gears if x['id']==winner['gear_id'])
    equipped,_=apply_gear_selection(source,aggregate_stats=selected.aggregate_stats,
        selected_items=tuple(selected.slots.values()),source='same_named_gear_counterfactual')
    # Rehydrate the actual source-generated winner, not a new approximating
    # policy; talent application changes IR id but not these action IDs.
    original=winner['best_policy']['policy']
    owner_policy=PolicyDefinition(id=original['id'],label=original['label'],
        rules=tuple(PolicyRuleDefinition(r['id'],r['action_id'],
            conditions=tuple(PolicyCondition(**c) for c in r['conditions']),
            phase=r['phase'],provenance=r['provenance']) for r in original['rules']),
        provenance=original['provenance'])
    without=_without_companions(equipped)
    no_pet=evaluate_repeated_pulls(ir_slice=without,policy=owner_policy,
        level=20,target_health=representative_hp(20),count=3,apply_target_defense=True)
    historical=json.loads(OLD.read_text())['endpoint_paths']['hunter']['targets']['20']['routes']['unconstrained']['path']
    slots=historical['gear_stats']['slots']
    aggregate={k:sum(float(x.get(k,0.) or 0.) for x in slots.values())
               for k in ('strength','agility','stamina','intellect','spirit','attack_power',
                         'spell_power','mp5','armor','weapon_dps')}
    historical_geared,_=apply_gear_selection(source,aggregate_stats=aggregate,
        selected_items=tuple(slots.values()),source='historical_named_gear_exact')
    sting=next(a for a in historical_geared.actions if a.family_key=='serpent_sting')
    shot=next(a for a in historical_geared.actions if a.family_key=='arcane_shot')
    partial_policy=PolicyDefinition(id='historical_executable_subset',
        label='Historical Serpent Arcane Auto subset, no Aimed Aspect or talents',
        rules=(PolicyRuleDefinition('sting',sting.id,conditions=(
            PolicyCondition('aura_missing',scope='target',aura_id=sting.effects[0].aura_id),)),
            PolicyRuleDefinition('shot',shot.id)))
    pet_options,_=companion_policy_envelope(historical_geared)
    subset=[]
    for option in pet_options:
        try:
            scored=evaluate_repeated_pulls(ir_slice=historical_geared,
                policy=partial_policy,level=20,target_health=representative_hp(20),
                count=3,apply_target_defense=True,companion_policy_override=option)
            subset.append({'seconds_per_mob':scored.seconds_per_mob,
                           'pet_policy':{k:[r.action_id for r in p.rules] for k,p in option.items()},
                           'damage_by_role':[x['damage_by_role'] for x in scored.pulls]})
        except ValueError as exc:
            subset.append({'error':str(exc)})
    valid=[x for x in subset if 'seconds_per_mob' in x]
    return {'version':'0.11.48.252','status':'EVALUATED_BOUNDED_SOURCE_INCOMPLETE',
            'independent_search':result,
            'matched_winner_gear_owner_policy_without_pet':{
                'seconds_per_mob':no_pet.seconds_per_mob,'pulls':list(no_pet.pulls),
                'gear_ids':{slot:int(item['item_id']) for slot,item in selected.slots.items()},
                'owner_policy':owner_policy.as_dict()},
            'historical_hunter':{'legacy_score_s_per_mob':float(historical['score_s_per_100'])/100.,
                'old_exact_named_gear_ids':{k:int(v['item_id']) for k,v in slots.items()},
                'old_talent_ranks':historical['talent_ranks'],
                'source_replay_partial_pet_policy_candidates':subset,
                'best_partial_s_per_mob':min(x['seconds_per_mob'] for x in valid) if valid else None,
                'full_old_candidate_evaluated':False,'comparison_valid':False,
                'reason':'Historical 11 talent points, Aspect, Aimed Shot and full pet build cannot be reconstructed/executed in canonical source Game IR. Legacy objective includes route travel and differs from incoming-inclusive repeated pulls.'},
            'limits':['Only sourced Cat pet family is executable at L10-20.',
                'Pet white DPS, inheritance and focus regeneration are explicitly qualified G35 proxies.',
                'Pet acquisition, positioning, threat, survivability and feed/revive costs not represented.',
                'Hunter talent ranks, Aimed Shot and Aspect of the Hawk remain source gaps.',
                'No global optimum or complete class-level acceptance.']}

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--output',default='WF252_HUNTER_PET_JOINT_REPLAY.json');args=ap.parse_args()
    data=run();Path(args.output).write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps({'winner':data['independent_search']['independent_winner']['seconds_per_mob'],
        'no_pet_same_gear':data['matched_winner_gear_owner_policy_without_pet']['seconds_per_mob'],
        'historical_partial':data['historical_hunter']['best_partial_s_per_mob']},indent=2))
