from __future__ import annotations
import json, sqlite3, tempfile, copy, time
from pathlib import Path
from dataclasses import replace
from collections import Counter
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.v2.source_persistent_joint_finalists import prepare_candidate
from src.game.runtime import ActorState,TargetState,CombatRuntime
from src.game.policy import execute_priority_policy
from src.game.multi_pull import evaluate_repeated_pulls
from src.shared.leveling.spaced_pulls import SpacedPullLayout
from src.shared.leveling.objective import representative_hp
ROOT=Path(__file__).resolve().parents[1]
ALLOCATION={'ferocity':5,'heart_of_the_wild':5,'feral_swiftness':2,
'savage_fury':2,'sharpened_claws':2,'primal_bite':1,'thick_hide':3,'feral_instinct':1}

def run():
 with tempfile.TemporaryDirectory(prefix='wf_l30_compare_') as tmp:
  db=Path(tmp)/'s.sqlite'
  with sqlite3.connect(f'file:{(ROOT/"data/forever/staged_druid_l30_talents_70338.sqlite").resolve()}?mode=ro',uri=True) as src,sqlite3.connect(db) as dst:src.backup(dst)
  ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
  ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
  with ability_source_scope(db):
   base_ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
   stage=json.loads((ROOT/'evidence/wf358/WF358_L30_BEST_JOINT_P3_STAGE.json').read_text())
   layout=SpacedPullLayout(3)
   result={}
   scenarios=[('bear_swipe_only',False,dict(ALLOCATION)),
              ('bear_primal_bite_priority',True,dict(ALLOCATION)),
              ('bear_no_primal_talent',False,{**{k:v for k,v in ALLOCATION.items() if k!='primal_bite'},'feral_instinct':2})]
   for name,guarded,allocation in scenarios:
    one=copy.deepcopy(stage);one['allocation']=allocation
    p=one['gear_policy_result']['winner']['winner']
    p.update({'prefix':['bear_form:5487','enrage:5229'],'fallback':'swipe:24',
              'guarded_action':'primal_bite:25' if guarded else None,'guarded_conditions':[]})
    cand=prepare_candidate(class_key='druid',level=30,stage=one,source_ir=base_ir,strict_l2_item_effects=True)
    ir=cand.ir
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    mobs=[TargetState.with_health(f'l30:m{i}',float(representative_hp(30))) for i in range(3)]
    inc=tuple(replace(ir.incoming_attacks[0],id=f'l30:incoming:{j}',source_actor_id=t.id) for j,t in enumerate(mobs))
    rt=CombatRuntime(actor=actor,target=mobs[0],other_targets=tuple(mobs[1:]),
       spatial_positions_yards={t.id:pos for t,pos in zip(mobs,layout.positions_yards)},
       auto_attacks=ir.auto_attacks,incoming_attacks=inc,mitigation_rules=ir.mitigation_rules,triggers=ir.triggers)
    for t in mobs[1:]:rt.engage_target(t.id)
    result_policy=execute_priority_policy(policy=cand.policy,actions=ir.actions,runtime=rt,
       opening_action_ids=cand.opening,max_actions=256)
    actions=Counter(x['action_id'] for x in result_policy.selected_actions)
    result[name]={'points':sum(allocation.values()),'allocation':allocation,'gear':{k:v['item_id'] for k,v in one['gear_policy_result']['winner']['gear']['slots'].items()},
       'status':'COMPLETE' if rt.pack_summary()['all_defeated'] and result_policy.stopped_reason is None else 'INCOMPLETE',
       'stopped_reason':result_policy.stopped_reason,'total_s':float(actor.current_time_s),
       'kill_seconds_per_mob':float(actor.current_time_s)/3 if rt.pack_summary()['all_defeated'] else None,
       'kills':sum(not t.alive for t in mobs),'remaining_hp':{t.id:t.health for t in mobs},
       'player_hp':actor.resource_amount('health'),'events':rt.event_transitions,'actions':dict(actions),
       'damage':round(rt.total_damage,3),'initial_target_hp':representative_hp(30),
       'spatial_positions':layout.positions_yards}
    started=time.monotonic()
    try:
     long_result=evaluate_repeated_pulls(
      ir_slice=ir,policy=cand.policy,level=30,target_health=representative_hp(30),
      count=100,pack_size=3,opening_action_ids=cand.opening,max_actions=256,
      schedule_incoming_attacks=True,recovery_mode='always')
     from collections import Counter as _Counter
     pack_actions=_Counter(x['action_id'] for pack in long_result.pulls for x in pack['selected_actions'])
     result[name]['repeated_100mob']={
      'status':'COMPLETE','s_per_mob':long_result.seconds_per_mob,
      'total_s':long_result.end_time_s-long_result.start_time_s,
      'mobs':sum(p['mob_count'] for p in long_result.pulls),
      'packs':len(long_result.pulls),
      'recovery_s':sum(p['recovery_s'] for p in long_result.pulls),
      'kill_s':sum(p['kill_s'] for p in long_result.pulls),
      'actions':dict(pack_actions),'wall_s':time.monotonic()-started,
      'last_pack_size':long_result.pulls[-1]['mob_count'],
      'final_health':long_result.actor.resource_amount('health'),
      'final_mana':long_result.actor.resource_amount('mana')}
    except Exception as exc:
     result[name]['repeated_100mob']={
      'status':'FAIL','error':str(exc),
      'error_type':type(exc).__name__,'wall_s':time.monotonic()-started}
   from src.rulesets.forever.classes.druid import Talents
   from src.rulesets.forever.classes.druid.mechanics import _bear_pack
   legacy={}
   for name,allocation in [('bear_swipe_without_primal',scenarios[2][2]),
                            ('bear_primal_bite',dict(ALLOCATION))]:
    old_alloc={k:v for k,v in allocation.items() if k!='primal_bite'}
    old_alloc['mangle']=allocation.get('primal_bite',0)
    old=_bear_pack(30,Talents(**old_alloc),3)
    legacy[name]={'legacy_approx_100mob_s_per_mob':old['total_s']/100,
        'legacy_approx_combat_s_per_pack':old['combat_s_per_pack'],
        'legacy_approx_recovery_s_per_pack':old['recovery_s_per_pack'],
        'rotation':old['rotation'],
        'spatial_fidelity':old['spatial_multi_pull_fidelity'],
        'points':sum(allocation.values())}
   return {'sourced_runtime':result,'legacy_approximation':legacy,
           'source_stage':'evidence/wf358/WF358_L30_BEST_JOINT_P3_STAGE.json',
           'gear_parity_with_legacy':False,
           'metric_warning':'Single 3-pack is combat-only; repeated_100mob includes recovery and 100 kills; legacy is an approximate 100-mob model with different gear and mob exposure. Absolute cross-engine values not directly comparable.',
           'primal_bite_targeting':'single enemy at L30, Swipe can hit max 3 targets'}
if __name__=='__main__':
 print(json.dumps(run(),sort_keys=True,indent=2))
