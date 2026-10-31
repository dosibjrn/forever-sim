"""Independent canonical Paladin L20 command/weapon-speed search and frozen .254 replay."""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PolicyDefinition,PolicyRuleDefinition,PolicyCondition
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_legal_beam import search_source_legal_beam
from src.v2.source_multi_pull_joint import replay_exact_challenger
from src.game.data.forever.sqlite_talents import DEFAULT_DB
ROOT=Path(__file__).resolve().parents[1]

def run():
    # The old build is loaded only after independent search, never as a seed.
    search=search_source_legal_beam(class_key='paladin',level=20,
        max_allocations=64,screening_gear_count=3,finalists=4,policy_cap=32,beam_width=5)
    prior=json.loads((ROOT/'WF254_PALADIN_TALENT_JOINT_REPLAY.json').read_text())
    old=prior['independent_search']['independent_winner']
    ids={slot:int(row['item_id']) for slot,row in old['gear_slots'].items()}
    source=build_game_ir_slice(class_key='paladin',level=20)
    gears=_gear_envelope('paladin',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=source)
    matched=[g for g in gears if {slot:int(row['item_id']) for slot,row in g['selection'].slots.items()}==ids]
    if len(matched)!=1:raise ValueError('frozen .254 gear not in current legal envelope')
    old_rules=[PolicyRuleDefinition(id=row['id'],action_id=row['action_id'],
        conditions=tuple(PolicyCondition(**cond) for cond in row.get('conditions',[])))
        for row in old['best_policy']['policy']['rules']]
    policy=PolicyDefinition(id='held_out_wf254',label='Frozen .254 Paladin native winner',
        rules=tuple(old_rules),provenance={'version':'0.11.48.254',
        'not_a_complete_historical_OG':True})
    replay=replay_exact_challenger(class_key='paladin',level=20,gear=matched[0],
        allocation=old['talent_allocation'],policy=policy,pulls=3)
    winner=search['independent_winner']
    selected={a['action_id'] for pull in winner['best_policy']['pulls']
              for a in pull['selected_actions']}
    if 'seal_of_command:20375' not in selected:
        raise ValueError('winner did not actually execute source-granted Command')
    if 'judgement:20271' not in selected:
        raise ValueError('winner did not actually execute sourced Judgement')
    # One actual combat execution with the independently discovered winner.
    # Same named gear, talent selection, policy, target defense and incoming
    # attacks as the first scored pull; record proc events, not a paper model.
    from src.game.gear import apply_gear_selection
    from src.game.talents import apply_talent_selection
    from src.game.runtime import ActorState,CombatRuntime,TargetState
    from src.game.policy import execute_priority_policy
    from src.game.data.forever.target_combat_source import target_combat_metadata
    wids={slot:int(row['item_id']) for slot,row in winner['gear_slots'].items()}
    matched_w=[g for g in gears if {slot:int(row['item_id']) for slot,row in g['selection'].slots.items()}==wids]
    if len(matched_w)!=1:raise ValueError('winner named gear cannot be replayed')
    winning_gear_selection=matched_w[0]['selection']
    geared,_=apply_gear_selection(source,aggregate_stats=winning_gear_selection.aggregate_stats,
        selected_items=tuple(winning_gear_selection.slots.values()))
    replay_ir,_=apply_talent_selection(geared,winner['talent_allocation'],level=20)
    wrules=[PolicyRuleDefinition(id=r['id'],action_id=r['action_id'],
        conditions=tuple(PolicyCondition(**cond) for cond in r.get('conditions',[])))
        for r in winner['best_policy']['policy']['rules']]
    wpolicy=PolicyDefinition(id='wf255_winner_trace',label='Independent winner trace',
        rules=tuple(wrules))
    actor=ActorState.from_ir(replay_ir.actor,replay_ir.resources,replay_ir.modes)
    target=TargetState.with_health('wf255-target',search['target_health'],
        **target_combat_metadata(replay_ir))
    runtime=CombatRuntime(actor=actor,target=target,auto_attacks=replay_ir.auto_attacks,
        triggers=replay_ir.triggers,incoming_attacks=replay_ir.incoming_attacks,
        mitigation_rules=replay_ir.mitigation_rules,spell_power=float(actor.stats.get('spell_power',0.)))
    combat=execute_priority_policy(policy=wpolicy,actions=replay_ir.actions,runtime=runtime)
    if not combat.timeline.target_defeated:
        raise ValueError('independent winner first pull failed real trace')
    trace_events=[e.as_dict() for e in combat.timeline.events]
    proc_events=[e for e in trace_events if e['kind']=='TriggerFired'
                 and 'seal_of_command' in str(e.get('action_id'))]
    if not proc_events:raise ValueError('no actual Command proc events in winning combat')
    trace={'first_pull_kill_s':combat.timeline.target_death_s,
           'equipped_weapon_speed_s':replay_ir.auto_attacks[0].swing_time_s,
           'source_proc_events':proc_events[:12],
           'source_proc_event_count':len(proc_events),
           'exclusive_removal_count':sum(e['kind']=='AuraRemovedExclusive' for e in trace_events),
           'selected_actions':list(combat.selected_actions),
           'damage_by_role':combat.timeline.damage_by_role}
    with sqlite3.connect(DEFAULT_DB) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        facts=db.execute("SELECT COUNT(*) FROM verified_talent_granted_action_facts WHERE class_key='paladin'").fetchone()[0]
    if integrity!='ok':raise ValueError('canonical SQLite integrity failure')
    return {'version':'0.11.48.255',
        'status':'EVALUATED_BOUNDED_WITH_CLASSIC_PROC_PROXY_NOT_GLOBAL_OPTIMUM',
        'source_build':'1.60.1.70245',
        'source_capture':'wf255_paladin_command_weapon_speed_20261011',
        'mechanic_limit':'Classic 7 PPM proxy not verified on Forever server',
        'independent_search':search,
        'winner_action_ids_executed':sorted(selected),
        'actual_first_pull_event_trace':trace,
        'held_out_prior_native_winner':{'version':'0.11.48.254','gear_item_ids':ids,
            'talent_allocation':old['talent_allocation'],'policy':policy.as_dict(),
            'previous_s_per_mob':old['seconds_per_mob'],
            'evaluated_as_exact_candidate':True,'used_as_seed':False,'replay':replay},
        'comparison_validity':{'same_scenario_and_objective':True,
            'full_historical_OG':False,'source_complete':False,
            'current_tree_legality_fully_verified':False,
            'note':'.254 frozen candidate evaluated exactly on .255; original OG Paladin still incomplete. Proc PPM is sourced Classic proxy, not Forever server verified.'},
        'coverage_delta':{'new_executable_talent_families':1,'new_rank_rows':1,
            'new_talent_granted_aura':True,'new_triggered_weapon_damage':True,
            'new_exclusive_aura_groups':True,'new_sourced_equipped_weapon_speed':True,
            'new_accepted_9x60_checkpoints':0,
            'indexed_talent_families_missing_executable_ranks':43,
            'remaining_blockers':['current Forever PPM/server proc and Judgement SP coefficient',
                'other seals incl Crusader/Fury','verified current tree and prerequisites',
                'complete player base stats and gear acquisition routes']},
        'canonical_sqlite_integrity':integrity,'talent_grant_rows':facts}

if __name__=='__main__':
    r=run();p=ROOT/'WF255_PALADIN_COMMAND_JOINT_REPLAY.json';p.write_text(json.dumps(r,indent=2)+'\n')
    s=r['independent_search'];w=s['independent_winner'];h=r['held_out_prior_native_winner']
    print(json.dumps({'winner_s_per_mob':w['seconds_per_mob'],
        'winner_talents':w['talent_allocation'],
        'winner_weapon':w['gear_slots']['weapon'],
        'held_out_s_per_mob':h['replay']['seconds_per_mob'],
        'evaluated_allocations':s['total_independent_evaluated_allocations'],
        'policy_evaluations':s['valid_policy_evaluations'],
        'elapsed_s':s['elapsed_s']},indent=2))
