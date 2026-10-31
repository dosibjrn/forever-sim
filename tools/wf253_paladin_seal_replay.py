"""Independent source joint search + exact prior native winner replay.

The prior native L20 winner is NOT the full historical Paladin OG build;
no complete named historical Paladin challenger is reconstructable here.
"""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import replace
from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection
from src.game.model import PolicyDefinition,PolicyRuleDefinition
from src.game.multi_pull import evaluate_repeated_pulls
from src.shared.leveling.objective import representative_hp
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_legal_beam import search_source_legal_beam
from src.v2.source_multi_pull_joint import replay_exact_challenger

ROOT=Path(__file__).resolve().parents[1]
PRIOR=ROOT/'WF251_TWO_CLASS_REPLAY.json'

def run():
    # No old winner, gear ID or policy enters this search.
    search=search_source_legal_beam(class_key='paladin',level=20,
        max_allocations=6,screening_gear_count=2,finalists=2,policy_cap=16,beam_width=2)
    old=json.loads(PRIOR.read_text())['results']['paladin']['independent_search']['independent_winner']
    ids={slot:int(item['item_id']) for slot,item in old['gear_slots'].items()}
    source=build_game_ir_slice(class_key='paladin',level=20)
    gear=next(g for g in _gear_envelope('paladin',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=source)
        if {slot:int(item['item_id']) for slot,item in g['selection'].slots.items()}==ids)
    policy=PolicyDefinition(id='held_out_prior_native_L20',label='Exact prior native source policy',
        rules=tuple(PolicyRuleDefinition(f'old:{i}',row['action_id']) for i,row in
            enumerate(old['best_policy']['policy']['rules'])),
        provenance={'authority':'frozen_prior_native_winner','version':'0.11.48.251',
                    'not_a_full_historical_paladin_OG':True})
    replay=replay_exact_challenger(class_key='paladin',level=20,gear=gear,
        allocation=old['talent_allocation'],policy=policy,pulls=3)
    winner=search['independent_winner']
    # Matched gear, one frozen old policy, same objective; isolate new
    # Seal/Judgement actions from the improvement due to gear selection.
    candidate=next(g for g in _gear_envelope('paladin',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=source)
        if g['id']==winner['gear_id'])
    geared,_=apply_gear_selection(source,aggregate_stats=candidate['selection'].aggregate_stats,
        selected_items=tuple(candidate['selection'].slots.values()),source='canonical_sqlite_forever_catalogue')
    no_seal=evaluate_repeated_pulls(ir_slice=geared,policy=policy,level=20,
        target_health=representative_hp(20),count=3,schedule_incoming_attacks=True,
        apply_target_defense=True)
    return {'version':'0.11.48.253','status':'EVALUATED_BOUNDED_NOT_GLOBAL_OPTIMUM',
        'source_client_build':'1.60.1.70338','capture_id':'wf253_paladin_seal_20261011',
        'independent_search':search,
        'held_out_prior_native_winner':{
            'origin':'0.11.48.251 native Paladin L20 source joint search',
            'gear_item_ids':ids,'talent_allocation':old['talent_allocation'],
            'prior_reported_s_per_mob':old['seconds_per_mob'],
            'evaluated_as_exact_candidate':True,'replay':replay,
            'same_objective':True,'used_as_new_search_seed':False},
        'matched_winner_gear_prior_holy_strike_policy':{
            'seconds_per_mob':no_seal.seconds_per_mob,
            'pulls':list(no_seal.pulls),'gear_item_ids':{s:x['item_id'] for s,x in winner['gear_slots'].items()},
            'talent_allocation':{},'policy':policy.as_dict()},
        'complete_historical_OG_comparison':{
            'valid':False,'evaluated':False,
            'reason':'Historical Paladin full gear+talent+policy winner is not reconstructable from existing reference fixture. Prior native source winner has zero executable talents and is not the full OG. Other seals, Paladin talents and route are not source executable.'},
        'coverage_delta':{'new_sourced_rank_rows':3,'new_sourced_consumer_rows':1,
            'new_executable_action_families':['seal_of_righteousness','judgement'],
            'new_generic_effect_types':['status_aura','event_emit'],
            'new_generic_trigger_filters':['required_actor_aura','swing_speed_scaling'],
            'paladin_L20_source_talent_families_executable':0,
            'remaining_blockers':['Paladin L20 source talent tree/rank/effects incomplete',
                'Other legal Seal families unexecuted','Absolute base stats and server-side Seal proc formula qualified proxies',
                'No validated continuous leveling route']}}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',default='WF253_PALADIN_SEAL_JOINT_REPLAY.json');a=p.parse_args()
    r=run();Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({'winner_s_per_mob':r['independent_search']['independent_winner']['seconds_per_mob'],
        'old_native_replay_s_per_mob':r['held_out_prior_native_winner']['replay']['seconds_per_mob'],
        'matched_no_seal_s_per_mob':r['matched_winner_gear_prior_holy_strike_policy']['seconds_per_mob'],
        'valid_policy_evaluations':r['independent_search']['valid_policy_evaluations']},indent=2))
