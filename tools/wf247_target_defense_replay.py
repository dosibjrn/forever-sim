"""Independent L20 search + exact held-out Feral + separate .246 caster diagnostic.

Both held-out candidates are replayed only after the independent search and
never enter its candidate generator. Same sourced target hit/Armor objective.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from tools.wf244_joint_multi_pull_replay import run
from tools.wf243_joint_multi_pull_replay import frozen_policy
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.target_combat_source import target_combat_metadata
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_multi_pull_joint import replay_exact_challenger


def replay(*,allocations=4,policy_cap=16):
    original=run(allocations=allocations,screen_gears=1,finalists=1,
                 policy_cap=policy_cap,pulls=3,refinement_budget=0)
    source=build_game_ir_slice(class_key='druid',level=20)
    # Frozen .246 winning caster is a diagnostic benchmark, not a seed.
    reference_path=Path(__file__).resolve().parents[1]/'WF246_PRIMARY_STATS_JOINT_REPLAY.json'
    if not reference_path.is_file():
        raise FileNotFoundError('frozen .246 caster reference JSON absent')
    reference=json.loads(reference_path.read_text())['independent_search']['independent_winner']
    gears=_gear_envelope('druid',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=source)
    matching=[g for g in gears if g['id']==reference['gear_id']]
    if len(matching)!=1:raise ValueError('frozen .246 caster gear not unique')
    caster=replay_exact_challenger(class_key='druid',level=20,gear=matching[0],
        allocation=reference['talent_allocation'],policy=frozen_policy(reference['best_policy']['policy']),pulls=3)
    new=original['independent_search']['independent_winner']
    old=original['held_out_frozen_challenger']
    action_ids=sorted({action for row in [new,*original['independent_search']['finalist_summaries']]
                       for action in row.get('executed_action_ids',[])})
    return {'version':'0.11.48.247','status':'EVALUATED_BOUNDED',
        'target_combat':target_combat_metadata(source),
        'source_caveat':'CMaNGOS ordinary class-1 enemy armor is CLASSIC PROXY, not observed Forever server armor',
        'independent_search':original['independent_search'],
        'held_out_frozen_feral':old,
        'held_out_prior_caster_diagnostic':caster,
        'prior_caster_original_s_per_mob':reference['seconds_per_mob'],
        'held_out_not_seeded':True,'same_engine_objective':True,
        'new_vs_feral_pct':100*(old['seconds_per_mob']-new['seconds_per_mob'])/old['seconds_per_mob'],
        'new_vs_prior_caster_s_per_mob':new['seconds_per_mob']-caster['seconds_per_mob'],
        'source_debuff_executed_in_candidate_evaluation':
            'source_spell:770' in action_ids,
        'executed_action_ids_finalists':action_ids,
        'global_optimum_proven':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--allocations',type=int,default=4)
    p.add_argument('--policy-cap',type=int,default=16)
    p.add_argument('--output',default='WF247_TARGET_DEFENSE_REPLAY.json')
    a=p.parse_args()
    out=replay(allocations=a.allocations,policy_cap=a.policy_cap)
    Path(a.output).write_text(json.dumps(out,indent=2))
    print(json.dumps({'winner_s':out['independent_search']['independent_winner']['seconds_per_mob'],
        'feral_s':out['held_out_frozen_feral']['seconds_per_mob'],
        'prior_caster_s':out['held_out_prior_caster_diagnostic']['seconds_per_mob'],
        'faerie_executed':out['source_debuff_executed_in_candidate_evaluation']},indent=2))
