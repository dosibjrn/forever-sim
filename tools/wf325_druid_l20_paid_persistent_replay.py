import json,os
from pathlib import Path
from time import process_time,monotonic
from src.game.data.forever.source_db_scope import ability_source_scope
from src.v2.source_persistent_joint_finalists import select_persistent_finalists,persistent_winner_source_manifest
p=Path('/mnt/data/wf325_druid20');joint=json.loads((p/'WF325_BLIND_JOINT.json').read_text()); db=Path('/mnt/data/wf323_druid20/WF323_COMBINED_SOURCE_STAGING_NOT_CANONICAL.sqlite')
os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
with ability_source_scope(db):
 t=monotonic();cpu=process_time()
 r=select_persistent_finalists(class_key='druid',level=20,joint_result=joint,screen_mobs=3,finalist_mobs=100,max_finalists=10,max_screen_candidates=40,max_screen_wall_s=4,max_finalist_wall_s=9,max_shared_evidence_events=150000,max_shared_evidence_cpu_s=60)
 m=persistent_winner_source_manifest(class_key='druid',level=20,winner=r['winner'])
 out={'source':'independent WF325 714 paid L2 joint attempts (blind, no old winner seeded)',
 'search_attempts':joint['attempted'],'search_events':joint['event_transitions'],
 'search_paid_talent_allocations':joint['distinct_talent_allocations_paid_L2'],
 'finalist':r,'winner_source_manifest':m,'cpu_s':process_time()-cpu,'wall_s':monotonic()-t,
 'formal_checkpoint_accepted':False}
 (p/'WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').write_text(json.dumps(out,indent=2,default=str))
 print(json.dumps({'attempts':joint['attempted'],'talents':joint['distinct_talent_allocations_paid_L2'],'joint_events':joint['event_transitions'],
 'screen_evaluated':r['screen_evaluated'],'finalists_evaluated':r['finalists_evaluated'],
 'persistent_events':r['paid_persistent_events'],'persistent_cpu':r['paid_persistent_cpu_s'],
 'winner':r['winner']['persistent']['mean_s_per_mob'],'gear_observed':m['acquisition_evidence']['observed_level_and_identity'],
 'gear_acquired':m['acquisition_evidence']['verified_acquired_items'],'full':False,'cpu':process_time()-cpu},indent=2),flush=True)
