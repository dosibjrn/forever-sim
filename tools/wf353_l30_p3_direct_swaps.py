"""Druid L30 P3: source-legal item-scale swaps on one independently discovered build.

The proposal frontier uses only canonical item stat domains; every tested
change uses the exact same 100-mob CombatRuntime, not a linear extrapolation.
This is calibration, not an additional checkpoint gate or P4/P5 seeding.
"""
from pathlib import Path
from time import monotonic,process_time
from hashlib import sha256
import json,os,sqlite3,tempfile
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0,source_item_slots,source_item_l0
from src.game.data.forever.source_checkpoint_p3_weights import _features
from src.game.data.forever.source_checkpoint_p3_swaps import subprocess_stage_100mob,substituted_stage,source_context_fingerprint
from src.rulesets.forever.items.runtime_selection import available_items
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/wf353';OUT.mkdir(parents=True,exist_ok=True)
AXES=('agility','strength','weapon_dps','attack_power','health_regeneration_per_5s','stamina','spirit','mp5','armor')
SLOTS=('weapon','chest','shoulder','legs','hands','feet','back','ring1','waist','head','wrist','neck','trinket1','ring2','trinket2','relic','shirt')

def proposals(stage,inventory,limit=14):
    items=available_items('druid',30,required_level_policy='observed')
    known={int(x.item_id):x for x in items}
    current={k:int(v['item_id']) for k,v in stage['gear_policy_result']['winner']['gear']['slots'].items()}
    output=[];seen=set()
    for slot in SLOTS:
        if slot not in current:continue
        eligible=[known[int(r['item_id'])] for r in inventory['source_items']
                  if slot in r['slots'] and int(r['item_id'])!=current[slot]]
        local=[]
        for axis in AXES:
            ranked=sorted((x for x in eligible if float(_features(x).get(axis,0.))>0),
                key=lambda x:(-float(_features(x).get(axis,0.)),-int(x.item_level or 0),int(x.item_id)))
            if ranked:
                item=ranked[0];key=(slot,int(item.item_id))
                if key not in seen and key not in local:
                    local.append(key)
        # Two contrasting sourced item axes per slot, no handpicked item IDs.
        for key in local[:2]:
            if key not in seen:output.append(key);seen.add(key)
    return output[:limit]

def run(limit=14,timeout_s=9.,start_index=0):
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    stage=json.loads((OUT/'WF353_L30_BEST_INDEPENDENT_P3_STAGE.json').read_text())
    inventory=checkpoint_item_l0(class_key='druid',level=30)
    assert inventory['legal_item_count']==1974 and inventory['l0_assessed_count']==1974
    trials=proposals(stage,inventory,limit=limit)
    started=monotonic();cpu=process_time();rows=[]
    with tempfile.TemporaryDirectory(prefix='wf353_p3_direct_') as tmp:
        db=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(db) as b:a.backup(b)
        ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        context=source_context_fingerprint(stage=stage,class_key='druid',level=30,
                 source_db_sha256=sha256(db.read_bytes()).hexdigest())
        baseline=subprocess_stage_100mob(stage=stage,source_db_path=db,timeout_s=timeout_s)
        if baseline['status']!='COMPLETE':raise RuntimeError('P3_BASELINE_NOT_COMPLETE:'+str(baseline))
        existing_path=OUT/'WF353_L30_P3_DIRECT_SWAP_EVIDENCE.json'
        previous=json.loads(existing_path.read_text()) if existing_path.exists() else {}
        if previous and (previous.get('context_sha256')!=context or
                         abs(previous.get('baseline_s_per_mob',0.)-baseline['mean_s_per_mob'])>1e-8):
            raise ValueError('P3_STALE_DIRECT_SWAP_CACHE')
        rows=list(previous.get('trials',[]))
        best=baseline['mean_s_per_mob'];best_stage=stage
        for r in rows:
            if r.get('status')=='COMPLETE' and r['mean_s_per_mob']<best:
                best=r['mean_s_per_mob']
                best_stage=substituted_stage(stage=stage,class_key='druid',level=30,
                            slot=r['slot'],item_id=r['item_id'])
        done={(r['slot'],r['item_id']) for r in rows}
        known={int(x.item_id):x for x in available_items('druid',30,required_level_policy='observed')}
        for slot,iid in trials[start_index:]:
            if (slot,iid) in done:continue
            print("START_SWAP",slot,iid,flush=True)
            item=known[iid];l0=source_item_l0(item)
            if l0['unresolved_effects']:
                result={'status':'L0_ONLY_UNRESOLVED_EFFECT','unresolved_effects':l0['unresolved_effects']}
            else:
                result=subprocess_stage_100mob(stage=stage,source_db_path=db,
                    slot=slot,item_id=iid,timeout_s=timeout_s)
            row={'slot':slot,'item_id':iid,'name':item.name,'source_url':item.source_url,
                 'numeric_source_domains':l0['numeric_source_domains'],
                 'improvement_s_per_mob':baseline['mean_s_per_mob']-result['mean_s_per_mob']
                      if result['status']=='COMPLETE' else None,**result}
            rows.append(row)
            if result['status']=='COMPLETE' and result['mean_s_per_mob']<best:
                best=result['mean_s_per_mob'];best_stage=substituted_stage(stage=stage,class_key='druid',level=30,
                                             slot=slot,item_id=iid)
                (OUT/'WF353_L30_P3_BEST_DIRECT_SWAP_STAGE.json').write_text(json.dumps(best_stage,indent=2,sort_keys=True,default=str)+'\n')
            summary={'checkpoint':'druid:L30:unrestricted','context_sha256':context,
                'catalogue_sha256':inventory['catalogue_sha256'],'legal_items_l0':1974,
                'baseline_s_per_mob':baseline['mean_s_per_mob'],'baseline_events':baseline.get('events'),
                'trials':rows,'best_s_per_mob':best,'wall_s':monotonic()-started,'cpu_s':process_time()-cpu,
                'status':'P3_DIRECT_ITEM_SCALE_PARTIAL_NO_ACCEPTANCE','accepted_checkpoints':'1/148'}
            (OUT/'WF353_L30_P3_DIRECT_SWAP_EVIDENCE.json').write_text(json.dumps(summary,indent=2,sort_keys=True,default=str)+'\n')
            print(slot,iid,result['status'],result.get('mean_s_per_mob'),flush=True)
    if best<baseline['mean_s_per_mob']:
        (OUT/'WF353_L30_P3_BEST_DIRECT_SWAP_STAGE.json').write_text(json.dumps(best_stage,indent=2,sort_keys=True,default=str)+'\n')
    return {'baseline':baseline['mean_s_per_mob'],'best':best,'tested':len(rows),
            'complete':sum(r['status']=='COMPLETE' for r in rows),'wall_s':monotonic()-started}
if __name__=='__main__':print(json.dumps(run(),indent=2),flush=True)
