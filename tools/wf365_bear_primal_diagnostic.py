"""No hand-tuned build search: diagnose sourced Bear ability feasibility."""
from __future__ import annotations
import copy,hashlib,json,os,sqlite3,tempfile
from pathlib import Path
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.game.recovery_between_pulls import BetweenPullPolicy
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1]


def run(output:Path|None=None):
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    with tempfile.TemporaryDirectory(prefix='wf365_bear_') as temp:
        db=Path(temp)/'s.sqlite'
        with sqlite3.connect(f'file:{(ROOT/"data/forever/staged_druid_l30_talents_70338.sqlite").resolve()}?mode=ro',uri=True) as src,sqlite3.connect(db) as dst:src.backup(dst)
        ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        digest=hashlib.sha256(db.read_bytes()).hexdigest()
        with ability_source_scope(db):
            ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
            stage=json.loads((ROOT/'evidence/wf358/WF358_L30_BEST_JOINT_P3_STAGE.json').read_text())
            results={}
            for ability in ('primal_bite:25','swipe:24'):
                mutated=copy.deepcopy(stage)
                # Use a source-tier-legal L30 allocation that actually buys
                # Primal Bite; no untalented shortcut is allowed.
                mutated['allocation']={'ferocity':5,'heart_of_the_wild':5,
                    'feral_swiftness':2,'savage_fury':2,'sharpened_claws':2,
                    'primal_bite':1}
                policy=mutated['gear_policy_result']['winner']['winner']
                policy.update({'prefix':['bear_form:5487','enrage:5229'],
                    'fallback':ability,'guarded_action':'enrage:5229',
                    'guarded_conditions':[{'kind':'resource_threshold','resource_id':'rage',
                                           'operator':'lt','value':20.0}]})
                candidate=prepare_candidate(class_key='druid',level=30,stage=mutated,
                    source_ir=ir,strict_l2_item_effects=True)
                recovery=BetweenPullPolicy(1.0,1.0,exit_action_id='cancel_mode:bear',
                    reentry_action_id='bear_form:5487')
                results[ability]={}
                for mob_count in (1,2):
                    res=evaluate_persistent_candidate(candidate,level=30,mobs=mob_count,
                        recovery_policy=recovery,max_wall_s=5,max_cpu_s=5,max_total_events=20000)
                    results[ability][str(mob_count)]={k:res.get(k) for k in ('status','mob',
                        'reason','combat_s','recovery_s','mean_s_per_mob','events')}
    report={'schema':'wf365_druid_l30_bear_action_diagnostic_v1',
        'note':'Legal sourced Primal Bite allocation on same fixed gear; one-mob action diagnostic, NOT joint optimum',
        'source_db_sha256':digest,'profiles':results,
        'single_mob_primal_faster_than_swipe':(results['primal_bite:25']['1'].get('status')=='COMPLETE'
            and results['swipe:24']['1'].get('status')=='COMPLETE' and
            results['primal_bite:25']['1']['combat_s']<results['swipe:24']['1']['combat_s']),
        'continuous_bear_2_mob_stable':all(results[a]['2']['status']=='COMPLETE' for a in results)}
    if output:
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    return report

if __name__=='__main__':
    r=run(ROOT/'evidence/wf365/WF365_BEAR_PRIMAL_DIAGNOSTIC.json')
    print(json.dumps(r,sort_keys=True)[:1800])
