from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.runtime import ActorState,CombatRuntime,TargetState
from src.game.runtime.simulator import action_eligibility
ir,_=compile_talent_runtime(build_game_ir_slice(class_key='druid',level=20))
for a in ir.actions:
 if a.family_key in ['swipe','claw','wrath','bear_form','cat_form']:
  actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
  for m in ir.modes:
   if m.enabled_action_ids is None or a.id in m.enabled_action_ids:
    if actor.current_mode_id!=m.id: actor.transition_mode(m.id)
    for c in a.costs:
     actor.resource_capacity[c.resource_id]=max(float(c.amount)+500.,float(actor.resource_capacity.get(c.resource_id,0)))
     actor.resources[c.resource_id]=actor.resource_capacity[c.resource_id]
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('t',100000.,armor=0))
    res=action_eligibility(action=a,actor=actor,target=rt.target)
    print('ability',a.id,'mode',m.id,'eligible',res)
