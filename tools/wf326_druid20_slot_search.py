"""Reproduce blind WF325 seed -> source-only per-slot persistent L2 refinement."""
from __future__ import annotations
import json,os,sqlite3,tempfile
from pathlib import Path
from time import process_time,monotonic
from src.game.data.forever.source_db_scope import ability_source_scope
from src.v2.source_persistent_slot_search import search_persistent_gear_slots
from src.v2.source_persistent_joint_finalists import persistent_winner_source_manifest

def main():
    root=Path(__file__).resolve().parents[1]
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    from src.game.data.forever.source_observed_rank_parity import ingest_observations
    from tools.wf321_ingest_control_observations import ingest as ingest_control
    old=json.loads((root/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())
    seed=old['finalist']['winner']['stage']
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    t=monotonic();c=process_time()
    with tempfile.TemporaryDirectory(prefix='wf326_druid20_') as tmp:
      stage_db=Path(tmp)/'source_stage.sqlite'
      with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as original,sqlite3.connect(stage_db) as dst:
        original.backup(dst)
      ingest_observations(stage_db,root/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
      ingest_control(stage_db,root/'evidence/wf321/druid_l20_control_observations.json')
      with ability_source_scope(stage_db):
        result=search_persistent_gear_slots(class_key='druid',level=20,seed_stage=seed,
            rounds=2,per_slot=3,max_proposals_per_round=48,screen_mobs=8,
            finalist_mobs=100,max_finalists=8,max_cpu_s=48,max_events=220000)
        manifest=persistent_winner_source_manifest(class_key='druid',level=20,
            winner={'stage':result['winner_stage'],
                    'allocation':result['winner_stage']['allocation'],
                    'persistent':result['winner']})
    evidence={'schema':'wf326_source_slot_100mob_v1',
              'origin':'WF325 independently searched 714 paid L2 attempts; no legacy seed',
              'result':result,'winner_manifest':manifest,'elapsed_cpu_s':process_time()-c,
              'elapsed_wall_s':monotonic()-t,'accepted_checkpoints':0,'target_checkpoints':148}
    p=root/'evidence/wf326/WF326_SLOT_SEARCH_EVIDENCE.json';p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(evidence,indent=2,default=str))
    print(json.dumps({'initial':result['initial'].get('mean_s_per_mob'),
        'best':result['winner'].get('mean_s_per_mob'),'rounds':result['rounds'],
        'attempts':result['attempts'],'events':result['events'],
        'cpu_s':result['cpu_s'],'wall_s':result['wall_s'],
        'gear_legal':manifest['acquisition_evidence']['equipment_legality_complete'],
        'availability_methods':manifest['acquisition_evidence']['sourced_acquisition_methods'],
        'accepted':False},indent=2),flush=True)

if __name__=='__main__':main()
