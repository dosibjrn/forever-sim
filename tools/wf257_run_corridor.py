"""Run actual 21-level Paladin source gear×talent×policy×recovery corridor."""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2.source_legal_level_corridor import search_source_legal_level_corridor
from src.v2.source_multi_pull_joint import replay_exact_challenger
from src.v2.source_joint_discovery import _gear_envelope
from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PolicyDefinition,PolicyRuleDefinition,PolicyCondition

ROOT=Path(__file__).resolve().parents[1]


def _policy(p):
    return PolicyDefinition(id='wf257_frozen_wf256',label='Frozen old L20 candidate',
        rules=tuple(PolicyRuleDefinition(r['id'],r['action_id'],
            conditions=tuple(PolicyCondition(**c) for c in r.get('conditions',())))
            for r in p['rules']))


def run():
    result=search_source_legal_level_corridor(class_key='paladin',start_level=10,end_level=30,
        gear_screen_count=2,policy_cap=8,pulls=3)
    old=json.loads((ROOT/'WF256_PALADIN_SEALS_REPLAY.json').read_text())['winner_exact_replay']
    ir=build_game_ir_slice(class_key='paladin',level=20)
    gears=_gear_envelope('paladin',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=ir)
    ids={s:int(x['item_id']) for s,x in old['gear_slots'].items()} if 'gear_slots' in old else {
        s:int(v) for s,v in json.loads((ROOT/'WF256_PALADIN_SEALS_REPLAY.json').read_text())['frozen_previous_native_winner']['gear_ids'].items()}
    matching=[g for g in gears if {s:int(i['item_id']) for s,i in g['selection'].slots.items()}==ids]
    if len(matching)!=1:raise ValueError('frozen old gear not in L20 legal source envelope')
    frozen=replay_exact_challenger(class_key='paladin',level=20,gear=matching[0],
        allocation=old['talent_allocation'],policy=_policy(old['policy']),pulls=3,
        recovery_action_ids=('holy_light:647',))
    # Exact old gear/talents/policy are replayed, not seeded. A changed
    # score is legitimate when new executable recovery or source weapon
    # semantics change the current shared engine.
    result['held_out_previous_l20_candidate']={
        'status':'SAME_ENGINE_EXACT_REPLAY_NOT_SEARCH_SEED',
        'version':'0.11.48.256','previous_published_seconds_per_mob':old['seconds_per_mob'],
        'seconds_per_mob':frozen['seconds_per_mob'],
        'talents':frozen['talent_allocation'],'gear_id':frozen['gear_id'],
        'policy':old['policy'],'recovery_action_ids':['holy_light:647'],
        'first_pull':frozen['pulls'][0]}
    result['historical_l30_full_og_comparable']=False
    result['historical_l30_blocker']='No named, fully executable L30 OG build with identical rules/scenario; .256 challenger is only L20.'
    with sqlite3.connect(DEFAULT_DB) as db:
        result['sqlite_integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]
    return result

if __name__=='__main__':
    result=run()
    (ROOT/'WF257_PALADIN_L10_30_ROUTE_REPLAY.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'route_levels':len(result['route']),
        'L20':result['route'][10]['seconds_per_mob'],
        'L30':result['route'][-1]['seconds_per_mob'],
        'L30_talents':result['route'][-1]['talents'],
        'screened_states':result['gear_policy_screened_states'],
        'policy_evaluations':result['policy_evaluations'],
        'elapsed_s':result['elapsed_s']},indent=2))
