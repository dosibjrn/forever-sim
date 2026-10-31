import json,sys,time
from pathlib import Path
from time import process_time
from src.game.data.forever.source_db_scope import ability_source_scope
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.v2.source_persistent_joint_finalists import select_persistent_finalists
from tools.wf297_druid_l20_checkpoint import JOINT_ARGS

db=Path('/mnt/data/wf323_druid20/WF323_COMBINED_SOURCE_STAGING_NOT_CANONICAL.sqlite')
outdir=Path('/mnt/data/wf325_druid20')
options={**JOINT_ARGS, 'max_evaluations':800,'evaluations_per_talent':52,'initial_search':10,'search_per_gear':16,'max_gear_states':4,'max_event_transitions':115000,'post_talent_refinement_budget':130,'talent_corridor_reserve':9,'talent_screening_attempts':95, 'probe_stats':('agility','strength','stamina','spirit','armor','dodge_rating')}
with ability_source_scope(db):
 t=time.monotonic(); c=process_time(); search=run_source_budgeted_joint_talents(**options);print('joint',search['winner']['score_s_per_mob'] if search['winner'] else None,'attempt',search['attempted'],'events',search['event_transitions'],'talents',search.get('distinct_talent_allocations_paid_L2'),'time',process_time()-c,flush=True)
 # Keep trace separate from old held-out data; search never reads it.
 (outdir/'WF325_BLIND_JOINT.json').write_text(json.dumps(search,indent=2,default=str))
 c=process_time();fin=select_persistent_finalists(class_key='druid',level=20,joint_result=search,screen_mobs=3,finalist_mobs=100,max_finalists=10,max_screen_candidates=40,max_screen_wall_s=3,max_finalist_wall_s=8)
 print('persistent',fin['status'],'winner',fin['winner']['persistent']['mean_s_per_mob'] if fin['winner'] else None,'scr',fin['screen_evaluated'],'fin',fin['finalists_evaluated'],'time',process_time()-c,flush=True)
 (outdir/'WF325_BLIND_PERSISTENT.json').write_text(json.dumps(fin,indent=2,default=str))
