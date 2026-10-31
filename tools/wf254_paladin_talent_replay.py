"""Independent sourced Paladin talent/gear/policy search vs frozen .253 winner."""
from __future__ import annotations
import json
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PolicyDefinition,PolicyRuleDefinition,PolicyCondition
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_legal_beam import search_source_legal_beam
from src.v2.source_multi_pull_joint import replay_exact_challenger
ROOT=Path(__file__).resolve().parents[1]

def run():
    # Source-only independent search; the held-out .253 build is loaded only
    # AFTER candidate discovery, and is never used to seed or tune the beam.
    search=search_source_legal_beam(class_key='paladin',level=20,
        max_allocations=40,screening_gear_count=2,finalists=3,policy_cap=16,beam_width=3)
    prior=json.loads((ROOT/'WF253_PALADIN_SEAL_JOINT_REPLAY.json').read_text())
    old=prior['independent_search']['independent_winner']
    ids={slot:int(row['item_id']) for slot,row in old['gear_slots'].items()}
    source=build_game_ir_slice(class_key='paladin',level=20)
    gear=next(g for g in _gear_envelope('paladin',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=source)
        if {slot:int(row['item_id']) for slot,row in g['selection'].slots.items()}==ids)
    old_rules=[]
    for row in old['best_policy']['policy']['rules']:
        old_rules.append(PolicyRuleDefinition(id=row['id'],action_id=row['action_id'],
            conditions=tuple(PolicyCondition(**cond) for cond in row.get('conditions',[]))))
    policy=PolicyDefinition(id='held_out_wf253',label='Frozen .253 Paladin winner',
        rules=tuple(old_rules),provenance={'version':'0.11.48.253',
        'not_a_complete_historical_OG':True})
    replay=replay_exact_challenger(class_key='paladin',level=20,gear=gear,
        allocation=old['talent_allocation'],policy=policy,pulls=3)
    winner=search['independent_winner']
    return {'version':'0.11.48.254','status':'EVALUATED_BOUNDED_PROVISIONAL_TREE_NOT_GLOBAL_OPTIMUM',
        'client_build_rank_capture':'1.60.1.70009','source_capture':'wf254_paladin_rank_batch_20261011',
        'independent_search':search,
        'held_out_prior_native_winner':{'version':'0.11.48.253','gear_item_ids':ids,
            'talent_allocation':old['talent_allocation'],'policy':policy.as_dict(),
            'previous_s_per_mob':old['seconds_per_mob'],
            'evaluated_as_exact_candidate':True,'used_as_seed':False,'replay':replay},
        'comparison_validity':{'same_scenario_and_objective':True,
            'full_historical_OG':False,'source_complete':False,
            'current_tree_legality_fully_verified':False,
            'note':'Frozen .253 native winner is replayable; complete original Paladin OG and all legal talents/Seals remain unavailable.'},
        'coverage_delta':{'new_executable_talent_families':5,'new_rank_rows':20,
            'new_source_legal_allocation_frontier':True,
            'new_generic_effects':['instant_mana_cost_pct','action_cooldown_delta_s',
                'melee_crit_stat','actor_strength_pct','event_trigger_damage_pct'],
            'new_accepted_9x60_checkpoints':0,
            'tree_row_authority':'mixed explicit 70009 and provisional inherited Classic',
            'remaining_indexed_talent_families_without_executable_rank_curves':44,
            'remaining_source_mechanics':['other Seals including talent-granted Seal of Command',
                'full current talent tree positions/prerequisites','unverified absolute actor stats',
                'verified route and acquisition costs']}}

if __name__=='__main__':
    r=run();out=ROOT/'WF254_PALADIN_TALENT_JOINT_REPLAY.json';out.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({'winner_s_per_mob':r['independent_search']['independent_winner']['seconds_per_mob'],
        'winner_talents':r['independent_search']['independent_winner']['talent_allocation'],
        'held_out_s_per_mob':r['held_out_prior_native_winner']['replay']['seconds_per_mob'],
        'evaluated_allocations':r['independent_search']['total_independent_evaluated_allocations'],
        'policy_evaluations':r['independent_search']['valid_policy_evaluations']},indent=2))
