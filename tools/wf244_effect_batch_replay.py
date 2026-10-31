"""End-to-end source rank -> shared talent IR -> three-pull objective evidence."""
from __future__ import annotations
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection
from src.game.multi_pull import evaluate_repeated_pulls
from src.game.talents import apply_talent_selection
from src.shared.leveling.objective import representative_hp
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_multi_pull_joint import replay_exact_challenger
from tools.wf243_joint_multi_pull_replay import frozen_policy


def run():
    root=Path(__file__).resolve().parents[1]
    ir=build_game_ir_slice(class_key='druid',level=20)
    baseline={'genesis':5,'improved_wrath':5}
    extended={**baseline,'natures_splendor':1}
    def naked_score(allocation):
        built,_=apply_talent_selection(ir,allocation,level=20)
        result=evaluate_repeated_pulls(ir_slice=built,policy=built.policies[0],
            level=20,target_health=representative_hp(20),count=3,
            schedule_incoming_attacks=True)
        return {'seconds_per_mob':result.seconds_per_mob,'pulls':list(result.pulls)}
    base=naked_score(baseline)
    new=naked_score(extended)
    previous=json.loads((root/'WF243_INDEPENDENT_JOINT_REPEATED_PULL.json').read_text())
    prior=previous['independent_search']['independent_winner']
    gears=_gear_envelope('druid',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=ir)
    matched=[g for g in gears if g['id']==prior['gear_id']]
    if len(matched)!=1:
        raise ValueError('previous winner gear missing from canonical catalogue')
    incumbent=replay_exact_challenger(class_key='druid',level=20,gear=matched[0],
        allocation=prior['talent_allocation'],policy=frozen_policy(prior['best_policy']['policy']),pulls=3)
    if abs(incumbent['seconds_per_mob']-prior['seconds_per_mob'])>1e-9:
        raise ValueError('prior incumbent failed exact replay')
    source_families={t.id for t in ir.talents if any(r.modifiers for r in t.ranks)}
    return {'version':'0.11.48.244', 'scenario':'Druid L20 source IR naked caster priority, three pulls',
        'baseline_talents':baseline,'extended_talents':extended,
        'baseline':base,'extended':new,
        'delta_s_per_mob':new['seconds_per_mob']-base['seconds_per_mob'],
        'percent_improvement':100*(base['seconds_per_mob']-new['seconds_per_mob'])/base['seconds_per_mob'],
        'prior_incumbent_exact_replay':incumbent,
        'prior_incumbent_not_independent_244_candidate':True,
        'executable_talent_families_L20':len(source_families),
        'executable_talent_family_names_L20':sorted(source_families),
        'source_rank_db_unchanged':True,
        'full_global_optimum_proven':False}

if __name__=='__main__':
    out=run()
    Path('WF244_EFFECT_BATCH_E2E.json').write_text(json.dumps(out,indent=2))
    print(json.dumps({k:out[k] for k in ('delta_s_per_mob','percent_improvement',
        'executable_talent_families_L20')},indent=2))
