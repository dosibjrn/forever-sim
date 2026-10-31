"""WF256 independently searched source-legal Paladin L20 and frozen .255 replay.

Search is produced separately by `search_source_legal_beam`; this tool does
not rerun it or use the old answer to seed it. Replays only exact candidates.
"""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_multi_pull_joint import replay_exact_challenger
from src.v2.source_policy_search import synthesize_source_policies
from src.game.model import PolicyDefinition,PolicyRuleDefinition,PolicyCondition
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection
from src.game.runtime import ActorState,CombatRuntime,TargetState
from src.game.policy import execute_priority_policy
from src.game.data.forever.target_combat_source import target_combat_metadata
ROOT=Path(__file__).resolve().parents[1]

def as_policy(row,name):
    return PolicyDefinition(id=name,label=name,rules=tuple(
        PolicyRuleDefinition(id=r['id'],action_id=r['action_id'],
            conditions=tuple(PolicyCondition(**c) for c in r.get('conditions',[])))
        for r in row['rules']))

def run():
    search=json.loads((ROOT/'WF256_SEARCH.json').read_text())
    prior=json.loads((ROOT/'WF255_PALADIN_COMMAND_JOINT_REPLAY.json').read_text())
    old=prior['independent_search']['independent_winner']
    source=build_game_ir_slice(class_key='paladin',level=20)
    gears=_gear_envelope('paladin',20,max_gear_candidates=256,required_level_policy='observed',
        include_melee_gear=True,ir_slice=source)
    def match(ids):
        found=[g for g in gears if {s:int(i['item_id']) for s,i in g['selection'].slots.items()}==ids]
        if len(found)!=1:raise ValueError('exact named gear not in source legal envelope')
        return found[0]
    old_ids={s:int(i['item_id']) for s,i in old['gear_slots'].items()}
    old_policy=as_policy(old['best_policy']['policy'],'frozen_wf255_native')
    old_replay=replay_exact_challenger(class_key='paladin',level=20,gear=match(old_ids),
        allocation=old['talent_allocation'],policy=old_policy)
    winner=search['independent_winner']
    win_ids={s:int(i['item_id']) for s,i in winner['gear_slots'].items()}
    win_policy=as_policy(winner['best_policy']['policy'],'wf256_independent_winner_trace')
    exact_winner=replay_exact_challenger(class_key='paladin',level=20,gear=match(win_ids),
        allocation=winner['talent_allocation'],policy=win_policy)
    if abs(exact_winner['seconds_per_mob']-winner['seconds_per_mob'])>1e-8:
        raise ValueError('independent search stale against final executor: rerun source beam')
    geared,_=apply_gear_selection(source,aggregate_stats=match(win_ids)['selection'].aggregate_stats,
        selected_items=tuple(match(win_ids)['selection'].slots.values()))
    ir,_=apply_talent_selection(geared,winner['talent_allocation'],level=20)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    target=TargetState.with_health('wf256-target',search['target_health'],**target_combat_metadata(ir))
    runtime=CombatRuntime(actor=actor,target=target,auto_attacks=ir.auto_attacks,
        triggers=ir.triggers,incoming_attacks=ir.incoming_attacks,
        mitigation_rules=ir.mitigation_rules,spell_power=float(actor.stats.get('spell_power',0.0)))
    combat=execute_priority_policy(policy=win_policy,actions=ir.actions,runtime=runtime)
    if not combat.timeline.target_defeated:raise ValueError('winner failed independent real first-pull trace')
    events=[e.as_dict() for e in combat.timeline.events]
    # Source graph candidates (not hand-curated spell rankings) are replayed
    # exactly on a fixed shield-bearing named gear set for policy comparison.
    env=synthesize_source_policies(source,level=20,max_policies=32,
        include_auto_resource_fallback=True,budget_mode='balanced_frontier')
    tank=next((g for g in gears if g['gear_role']=='paladin_tank' and
               any(i.get('armor_type')=='shield' for i in g['selection'].slots.values())),None)
    if tank is None:raise ValueError('source legal shield gear not in frontier')
    def linked_case(families):
        matches=[p for p in env['policies'] if tuple(r.action_id.split(':')[0] for r in p.rules)==families]
        if not matches:raise ValueError(f'linked policy missing: {families}')
        return matches[0]
    cases={
        'fury_shield':('holy_strike','judgement','seal_of_fury'),
        'righteousness_same_shield':('holy_strike','judgement','seal_of_righteousness'),
        'crusader_to_righteousness':('holy_strike','judgement','seal_of_the_crusader','seal_of_righteousness'),
    }
    comparisons={}
    for label,ids in cases.items():
        policy=linked_case(ids)
        comparisons[label]=replay_exact_challenger(class_key='paladin',level=20,
            gear=tank,allocation={},policy=policy)
    # Direct runtime event witnesses for both new families, on *named* shield
    # gear, with real incoming enemy swings rather than a synthetic DPS delta.
    tank_geared,_=apply_gear_selection(source,aggregate_stats=tank['selection'].aggregate_stats,
        selected_items=tuple(tank['selection'].slots.values()))
    def event_witness():
        actor=ActorState.from_ir(tank_geared.actor,tank_geared.resources,tank_geared.modes)
        rt=CombatRuntime(actor=actor,target=TargetState.with_health('fury-witness',10000,
            **target_combat_metadata(tank_geared)),auto_attacks=tank_geared.auto_attacks,
            triggers=tank_geared.triggers,incoming_attacks=tank_geared.incoming_attacks,
            mitigation_rules=tank_geared.mitigation_rules)
        fury=next(a for a in tank_geared.actions if a.family_key=='seal_of_fury')
        rt.schedule_action(fury);rt.advance_to(7.0)
        fury_events=[e.as_dict() for e in rt.trace if e.kind in ('TriggerFired','AbsorbShieldGranted','IncomingAttackResolved')]
        actor2=ActorState.from_ir(tank_geared.actor,tank_geared.resources,tank_geared.modes)
        rt2=CombatRuntime(actor=actor2,target=TargetState.with_health('crusader-witness',10000,
            **target_combat_metadata(tank_geared)),auto_attacks=tank_geared.auto_attacks,
            triggers=tank_geared.triggers)
        cru=next(a for a in tank_geared.actions if a.family_key=='seal_of_the_crusader')
        right=next(a for a in tank_geared.actions if a.family_key=='seal_of_righteousness')
        judge=next(a for a in tank_geared.actions if a.family_key=='judgement')
        rt2.schedule_action(cru);rt2.advance_to(1.5);rt2.schedule_action(judge)
        rt2.schedule_action(right);rt2.advance_to(6)
        cru_events=[e.as_dict() for e in rt2.trace if e.kind in ('SchoolPowerDebuffApplied','Damage','AuraRemovedExclusive')
                    and (e.kind!='Damage' or 'seal_of_righteousness' in str(e.action_id))]
        return {'shield_gear_ids':{k:int(v['item_id']) for k,v in tank['selection'].slots.items()},
            'fury_events':fury_events,'crusader_events':cru_events,
            'fury_absorb_grants':sum(e['kind']=='AbsorbShieldGranted' for e in fury_events),
            'fury_absorbed_enemy_attacks':sum(e['kind']=='IncomingAttackResolved' and e['payload'].get('absorbed_damage',0)>0 for e in fury_events),
            'crusader_school_power_procs':sum(e['kind']=='Damage' and e['payload'].get('target_school_power_applied',0)>0 for e in cru_events)}
    mechanics=event_witness()
    if not all(mechanics[k]>0 for k in ('fury_absorb_grants','fury_absorbed_enemy_attacks','crusader_school_power_procs')):
        raise ValueError('new source family did not execute actual event witnesses')
    with sqlite3.connect(DEFAULT_DB) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        ranks=[{'family':f,'ranks':n,'build':b} for f,n,b in db.execute('''SELECT family_key,COUNT(*),MAX(client_build)
             FROM sourced_timed_aura_actions GROUP BY family_key''')]
        foreign=db.execute('PRAGMA foreign_key_check').fetchall()
    if integrity!='ok' or foreign:raise ValueError('SQLite integrity failure')
    trace={'first_pull_kill_s':combat.timeline.target_death_s,
           'selected_actions':list(combat.selected_actions),
           'command_proc_count':sum(e['kind']=='TriggerFired' and 'seal_of_command:swing' in str(e.get('action_id')) for e in events),
           'first_events':events[:35]}
    return {'version':'0.11.48.256','status':'EVALUATED_BOUNDED_NOT_SOURCE_COMPLETE',
            'current_capture_build':'1.60.1.70338','capture_id':'wf256_paladin_crusader_fury_20261011',
            'independent_search':search,'winner_exact_replay':exact_winner,'winner_first_pull_trace':trace,
            'frozen_previous_native_winner':{'version':'0.11.48.255','gear_ids':old_ids,
                'allocation':old['talent_allocation'],'policy':old_policy.as_dict(),
                'previous_score':old['seconds_per_mob'],'replayed_as_exact_candidate':True,
                'used_as_seed':False,'replay':old_replay},
            'new_source_graph_policy_comparisons':comparisons,
            'new_mechanic_event_witnesses':mechanics,
            'new_source_graph_policy_frontier':{k:v for k,v in env.items() if k!='policies'},
            'source_rank_coverage':ranks,'canonical_sqlite_integrity':integrity,
            'comparison_limits':['Old .255 native winner is not full OG','Command PPM Classic proxy',
                'Crusader Holy vulnerability as spell-power-coefficient proxy',
                'Fury shield replace semantics and taunt behavior server unverified',
                '44? Paladin talent identities still incomplete: verify canonical ledger',
                'source provider only supports levels 10-20','no legal continuous leveling route']}
if __name__=='__main__':
    r=run();(ROOT/'WF256_PALADIN_SEALS_REPLAY.json').write_text(json.dumps(r,indent=2)+'\n')
    w=r['independent_search']['independent_winner'];print(json.dumps({
        'winner':w['seconds_per_mob'],'talents':w['talent_allocation'],
        'old':r['frozen_previous_native_winner']['replay']['seconds_per_mob'],
        'alternatives':{k:v['seconds_per_mob'] for k,v in r['new_source_graph_policy_comparisons'].items()},
        'source_graph_admitted':r['new_source_graph_policy_frontier']['source_graph_linked_candidates_admitted']},indent=2))
