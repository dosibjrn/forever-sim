"""Measured fixed-policy HP5 sensitivity on the existing 100-mob scorer.

This is diagnostic, not independent gear/talent/policy discovery or P4 PASS.
"""
from pathlib import Path
from time import monotonic,process_time
from hashlib import sha256
import copy,json,sqlite3,tempfile
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.rulesets.forever.items.runtime_selection import available_items,catalogue_path
from src.v2.source_persistent_slot_search import _gear_replace
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1]

def run():
    stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    with tempfile.TemporaryDirectory(prefix='wf347_hp5_') as tmp:
        source=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as db,sqlite3.connect(source) as dst:db.backup(dst)
        ingest_observations(source,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(source,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(source):
            by_id={x.item_id:x for x in available_items('druid',20,required_level_policy='observed')}
            cases=[('baseline',None,None),('shoulder_hp5','shoulder',6461),('chest_hp5','chest',6226),('back_hp5','back',14149),('legs_hp5','legs',284192)]
            rows=[]
            for name,slot,iid in cases:
                s=copy.deepcopy(stage)
                if iid is not None:
                    s['gear_policy_result']['winner']['gear']=_gear_replace(s['gear_policy_result']['winner']['gear'],slot,by_id[iid])
                begin=monotonic();cpu=process_time()
                try:
                    candidate=prepare_candidate(class_key='druid',level=20,stage=s,strict_l2_item_effects=True)
                    r=evaluate_persistent_candidate(candidate,level=20,mobs=100,max_total_events=200000,max_wall_s=20.,max_cpu_s=20.)
                    rows.append({'case':name,'slot':slot,'item_id':iid,'status':r['status'],
                        'actual_100mob_s_per_mob':r.get('mean_s_per_mob'),
                        'events':r.get('events'),'mob_completed':r.get('mob_completed'),
                        'cpu_s':process_time()-cpu,'wall_s':monotonic()-begin,
                        'actor_health_regeneration_per_5s':candidate.ir.actor.base_stats.get('health_regeneration_per_5s',0.)})
                except Exception as exc:
                    rows.append({'case':name,'slot':slot,'item_id':iid,'status':'FAIL','error':str(exc),
                        'cpu_s':process_time()-cpu,'wall_s':monotonic()-begin})
            return {'checkpoint':'druid:L20:unrestricted','source_sha256':sha256(source.read_bytes()).hexdigest(),
                    'item_catalogue_sha256':sha256(catalogue_path().read_bytes()).hexdigest(),
                    'oracle_seeded':False,'fixed_policy_not_independent_search':True,'rows':rows}
if __name__=='__main__':
    out=run();p=ROOT/'evidence/wf347/WF347_FIXED_POLICY_HP5_100MOB.json';p.write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
