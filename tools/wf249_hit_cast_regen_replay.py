"""One scorer, real source-backed combat and recovery, independent joint search.

A bounded search result is NOT a global optimum; the frozen challenger is
excluded from the beam and replayed separately by the same engine.
"""
import argparse
import json
from pathlib import Path
import sqlite3

from tools.wf248_source_legal_beam_replay import replay as independent_replay
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection
from src.game.runtime import ActorState,CombatRuntime,TargetState
from src.game.data.forever.target_combat_source import target_combat_metadata
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_multi_pull_joint import _score_state
from src.shared.leveling.objective import representative_hp


def _gear(level):
    source=build_game_ir_slice(class_key='druid',level=level)
    return source,_gear_envelope('druid',level,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=source)[0]


def _damage_probe(ir,gear,allocation):
    geared,_=apply_gear_selection(ir,aggregate_stats=gear['selection'].aggregate_stats,
        selected_items=tuple(gear['selection'].slots.values()),source='canonical_sqlite_forever_catalogue')
    changed,_=apply_talent_selection(geared,allocation,level=20)
    action=next(a for a in changed.actions if a.family_key=='wrath')
    actor=ActorState.from_ir(changed.actor,changed.resources,changed.modes)
    target=TargetState.with_health('hit_probe',100000.,**target_combat_metadata(changed))
    runtime=CombatRuntime(actor=actor,target=target)
    runtime.schedule_action(action)
    runtime.advance_to(actor.current_time_s+action.cast_time_s)
    event=next(e for e in runtime.result().events if e.kind=='Damage' and e.payload.get('applied'))
    return {'amount':event.payload['amount'],'base_hit':event.payload['source_base_hit'],
            'bonus':event.payload['source_hit_bonus'],
            'effective_hit':event.payload['effective_hit_chance']}


def run(max_allocations=24,screen_gears=1,finalists=1,policy_cap=4):
    with sqlite3.connect(DEFAULT_DB) as conn:
        fact=conn.execute('''SELECT class_key,spell_id,scope_filter,authority,source_url,capture_id
            FROM talent_effect_scope_source_facts WHERE class_key='druid' AND spell_id=16819''').fetchone()
        if fact is None:raise ValueError('sourced offensive spell scope absent')
    independent=independent_replay(max_allocations=max_allocations,screen_gears=screen_gears,
        finalists=finalists,policy_cap=policy_cap)
    source20,gear20=_gear(20)
    hit_before=_damage_probe(source20,gear20,{'improved_wrath':5})
    hit_after=_damage_probe(source20,gear20,{'improved_wrath':5,'natures_reach':2})
    source24,gear24=_gear(24)
    baseline={'furor':5,'naturalist':5}
    # Same gear, three pulls, same incoming-inclusive combat/recovery objective.
    scores=[]
    for ranks in (0,1,3):
        allocation={**baseline,**({'reflection':ranks} if ranks else {})}
        row=_score_state(source24,level=24,gear=gear24,allocation=allocation,
            pulls=3,policy_cap=8,target_health=representative_hp(24))
        scores.append({'allocation':allocation,'seconds_per_mob':row['seconds_per_mob'],
            'policy':row['best_policy']['policy'] if row['best_policy'] else None,
            'gear_id':row['gear_id'],'policy_evaluated':row['policy_evaluated']})
    return {'version':'0.11.48.249','status':'EVALUATED_BOUNDED',
        'scope_source':dict(zip(('class_key','spell_id','scope_filter','authority','source_url','capture_id'),fact)),
        'independent_l20_joint_and_frozen_feral':independent,
        'l20_sourced_hit_same_gear':{'gear_id':gear20['id'],'without':hit_before,'with_rank_2':hit_after},
        'l24_reflection_same_gear_and_objective':scores,
        'notes':['Hit chance improves expected per-cast damage; discrete kill thresholds may leave s/mob unchanged.',
                 'Reflection uses qualified shared Classic mana-regeneration proxy during casts.',
                 'Range bonus is not yet modeled as travel/pull-distance improvement.',
                 'Talent positions remain provisional, no global optimum claim.']}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--max-allocations',type=int,default=24)
    p.add_argument('--screen-gears',type=int,default=1)
    p.add_argument('--policy-cap',type=int,default=4)
    p.add_argument('--output',default='WF249_HIT_CAST_REGEN_REPLAY.json')
    a=p.parse_args()
    result=run(max_allocations=a.max_allocations,screen_gears=a.screen_gears,policy_cap=a.policy_cap)
    Path(a.output).write_text(json.dumps(result,indent=2))
    best=result['independent_l20_joint_and_frozen_feral']['independent_search']['independent_winner']
    print(json.dumps({'winner':best['seconds_per_mob'],'talents':best['talent_allocation'],
        'old_feral':result['independent_l20_joint_and_frozen_feral']['held_out_frozen_feral']['seconds_per_mob'],
        'l20_hit':result['l20_sourced_hit_same_gear'],
        'l24_reflection':[(x['allocation'],x['seconds_per_mob']) for x in result['l24_reflection_same_gear_and_objective']]},indent=2))
