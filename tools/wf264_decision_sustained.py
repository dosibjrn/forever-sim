import json,time
from pathlib import Path
from src.rulesets.forever.classes.druid.talents import Talents
from src.rulesets.forever.classes.druid.mechanics import score_external_build
from src.game.data.forever.registry import build_game_ir_slice
from src.rulesets.forever.items.runtime_selection import available_items,item_vector,item_payload,effective_level
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection
from src.game.model import PolicyCondition, PolicyDefinition, PolicyRuleDefinition
from src.v2.generic_backend import _policy_combat_evaluation
from src.game.multi_pull import evaluate_repeated_pulls
from src.shared.leveling.objective import representative_hp

ROOT=Path(__file__).resolve().parents[1]
ref=ROOT/'docs/validation/I15/LISTENER_LOCAL_I15_STATE_v0.11.48.103.json'
row=json.loads(ref.read_text())['cards'][0]['fast_best']
level=20
legacy=score_external_build(level,Talents(**row['talent_ranks']),'feral',row['gear_stats'])
assert abs(legacy['total_s']/100 - row['seconds_per_mob'])<1e-10
pool={x.item_id:x for x in available_items('druid',level,required_level_policy='observed')}
used={slot:pool[v['item_id']] for slot,v in row['gear_stats']['slots'].items() if v['item_id'] in pool}
missing=[(slot,v['item_id']) for slot,v in row['gear_stats']['slots'].items() if v['item_id'] not in pool]
assert not missing,missing
stats={}
for item in used.values():
 for axis,value in item_vector(item).items():stats[axis]=stats.get(axis,0)+float(value)
ir=build_game_ir_slice(class_key='druid',level=level)
geared,gap=apply_gear_selection(ir,aggregate_stats=stats,selected_items=tuple(item_payload(x,display_slot=s,effective_level=effective_level(x)) for s,x in used.items()),source='canonical_sqlite_forever_catalogue')
geared,tapp=apply_talent_selection(geared,row['talent_ranks'],level=level)

def build_policy(rip=True):
 rules=[PolicyRuleDefinition(id='entry',action_id='cat_form:768',conditions=(PolicyCondition(kind='mode_state',value='caster'),))]
 if rip:
  rules.append(PolicyRuleDefinition(id='finisher',action_id='rip:20',conditions=(PolicyCondition(kind='resource_threshold',resource_id='combo_points',operator='gte',value=5.),)))
 rules.append(PolicyRuleDefinition(id='builder',action_id='claw:20'))
 return PolicyDefinition(id='real_legacy_decision_anchor_20261011',label='Decision Claw to 5 CP => Rip',rules=tuple(rules),provenance={'search_performed':True,'authority':'legacy_decision_validation_only'})

out={"scenario":{"legacy_item_ids":{slot: item.item_id for slot,item in used.items()},"talents":row['talent_ranks'],"target_hp":representative_hp(20)},"decision":legacy,"new":{}}
for name,kwargs in [
    ('always_one_pull',dict(count=1,recovery_mode='always',retain_mode_between_pulls=False,travel_time_s=0.0)),
    ('always_15',dict(count=15,recovery_mode='always',retain_mode_between_pulls=False,travel_time_s=2.2)),
    ('sustained_15',dict(count=15,recovery_mode='threshold',retain_mode_between_pulls=True,travel_time_s=2.2)),
]:
 try:
  result=evaluate_repeated_pulls(ir_slice=geared,policy=build_policy(True),level=20,
      target_health=representative_hp(20),pre_combat_action_ids=('cat_form:768',),
      post_combat_action_ids=('cancel_mode:cat',),apply_target_defense=True,
      schedule_incoming_attacks=True,**kwargs)
  out['new'][name]={'seconds_per_mob':result.seconds_per_mob,'pulls':list(result.pulls),
                    'end_resources':dict(result.actor.resources),'end_mode':result.actor.current_mode_id,
                    'elapsed_total_s':result.end_time_s-result.start_time_s}
 except Exception as e:out['new'][name]={'error':str(e),'exception':type(e).__name__}
print(json.dumps({k:(v if k!='new' else {n:{z:(q if z!='pulls' else q[:3]) for z,q in val.items()} for n,val in v.items()}) for k,v in out.items()},indent=2,default=str)[:9000])
(ROOT/'WF264_DECISION_L20_SUSTAINED.json').write_text(json.dumps(out,indent=2,default=str))
