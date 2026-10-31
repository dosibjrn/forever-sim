from __future__ import annotations
import json
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import apply_talent_selection
from src.v2.source_mode_search import evaluate_discovered_mode_search
from src.v2.source_joint_discovery import evaluate_bounded_joint_discovery
from src.version import SOFTWARE_VERSION

ir = build_game_ir_slice(class_key='druid', level=20)
feral, app = apply_talent_selection(ir, {'ferocity':1}, level=20)
a = evaluate_discovered_mode_search(class_key='druid', level=20, ir_slice=ir, max_policies_per_path=24)
b = evaluate_discovered_mode_search(class_key='druid', level=20, ir_slice=feral, max_policies_per_path=24)
base = sorted(x['seconds_per_mob'] for x in [a['winner'],*a['alternatives']])
new = sorted(x['seconds_per_mob'] for x in [b['winner'],*b['alternatives']])
joint = evaluate_bounded_joint_discovery(class_key='druid',level=20,max_gear_candidates=8,
    max_talent_candidates=16,max_states=96,max_policies_per_path=24,max_caster_policies=24)
result = {'version':SOFTWARE_VERSION, 'class':'druid', 'level':20,
          'source_talent_index':ir.provenance['talent_sqlite_coverage'],
          'rank1_feral_effect':app.as_dict(),
          'mode_baseline_winner_s':a['winner']['seconds_per_mob'],
          'mode_ferocity1_winner_s':b['winner']['seconds_per_mob'],
          'mode_candidate_count':len(base),
          'mode_improved_alternative_count':sum(y<x-0.001 for x,y in zip(base,new)),
          'mode_best_alternative_delta_s':min(y-x for x,y in zip(base,new)),
          'bounded_joint':{'winner_s':joint['winner']['score_s_per_mob'],
                           'winner_talent':joint['winner']['talent_id'],
                           'gear_count':joint['gear_candidate_count'],
                           'state_count':joint['evaluated_state_count'],
                           'talent_coverage_complete':joint['talent_legality_verified'],
                           'optimizer_ready':joint['optimization_ready']}}
Path('WF_FERAL01_SQLITE_L20_EVIDENCE_v'+SOFTWARE_VERSION+'.json').write_text(json.dumps(result,indent=2))
print(json.dumps({k:v for k,v in result.items() if k!='source_talent_index'},indent=2))
