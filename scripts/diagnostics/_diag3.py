from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.data.forever.checkpoint_p2_execution_gate import _executable_filler_witness
from src.game.talents import available_talent_points,talented_bonus_for_level
from tools.wf_gate_p2_live import _action_runtime_probe
ir,_=compile_talent_runtime(build_game_ir_slice(class_key='druid',level=20))
for t in ir.talents:
 if t.id not in ['ferocity','moonglow','natural_shapeshifter','improved_moonfire','natures_majesty']:continue
 rank=1;w=_executable_filler_witness(t,rank,ir.talents,points=available_talent_points(20,bonus_talent_points=talented_bonus_for_level(20)),step=5)
 if w is None: w={t.id:1}
 x={**w};x.pop(t.id,None)
 try: before,_=apply_talent_selection(ir,x,level=20,bonus_talent_points=talented_bonus_for_level(20)); after,_=apply_talent_selection(ir,w,level=20,bonus_talent_points=talented_bonus_for_level(20))
 except Exception as ex:print('oops',t.id,ex);continue
 print('\n===',t.id,w)
 bmap={a.id:a for a in before.actions}
 for a in after.actions:
  older=bmap.get(a.id)
  if older!=a and older is not None:
   print('DIFF',a.id,a.family_key,'cost',older.costs,a.costs,'effects_change',older.effects!=a.effects)
   print('run',_action_runtime_probe(before,older), _action_runtime_probe(after,a))
   print('provenance',a.provenance[-1:] if a.provenance else None)
