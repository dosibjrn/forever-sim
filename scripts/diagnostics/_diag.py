from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from tools.wf_gate_p2_live import _action_runtime_probe
ir=build_game_ir_slice(class_key='druid',level=20)
c,_=compile_talent_runtime(ir)
for t in c.talents:
 if t.id in ['ferocity','moonglow','natural_shapeshifter','improved_moonfire','natures_majesty','natures_reach']:
  print('\nTALENT',t.id,[(x.rank,[(m.kind,m.target_type,m.target_id,m.value) for m in x.modifiers]) for x in t.ranks])
for a in c.actions:
 if a.family_key in ['swipe','moonfire','wrath','cat_form','bear_form'] or any(e.__class__.__name__=='ModeChangeEffect' for e in a.effects):
  print('\nACTION',a.id,a.family_key,a.costs,a.effects[:1], 'modes',a.metadata.get("required_mode_ids"),'run',_action_runtime_probe(c,a))
