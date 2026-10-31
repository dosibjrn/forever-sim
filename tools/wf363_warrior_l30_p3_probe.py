"""Run existing P3 L0 on provisional Warrior staging, FAIL closed on membership.

This is a source ingestion/proficiency smoke probe, not a P3 acceptance and
not an independent 30/300-second gear×talent×rotation search.
"""
from __future__ import annotations
import json,os,time,hashlib,sqlite3
from pathlib import Path
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
from src.rulesets.forever.items.runtime_selection import _AVAILABLE_ITEMS_CACHE
from tools.wf363_warrior_l30_gear_stage import warrior_source_membership_verified

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_warrior_l30_gear_provisional.sqlite'
OUT=ROOT/'evidence/wf363/WF363_WARRIOR_L30_P3_PROBE.json'

def run():
    os.environ['FOREVER_ITEM_CATALOGUE']=str(DB)
    _AVAILABLE_ITEMS_CACHE.clear()
    wall=time.perf_counter();cpu=time.process_time()
    cert=checkpoint_item_l0(class_key='warrior',level=30)
    elapsed_wall=time.perf_counter()-wall;elapsed_cpu=time.process_time()-cpu
    with sqlite3.connect(DB) as db:
        count=db.execute('SELECT COUNT(*) FROM item_class_eligibility WHERE class_id=1').fetchone()[0]
        statuses=db.execute('SELECT provenance,COUNT(*) FROM item_class_eligibility WHERE class_id=1 GROUP BY provenance').fetchall()
    result={'schema':'wf363_warrior_l30_p3_fail_closed_v1','checkpoint':'warrior:L30:unrestricted',
        'accepted_checkpoints':'2/148','p1':{'status':'PASS','coverage':'54/54','inherited_from':'WF361'},
        'p2':{'status':'PASS','coverage':'117/117','inherited_from':'WF362'},
        'p3':{'status':'FAIL','reason':'CANONICAL_WARRIOR_CLASS_1_ITEM_MEMBERSHIP_NOT_INGESTED',
            'verified_legal_item_denominator':None,'verified_legal_item_numerator':0,
            'provisional_item_l0_assessed':cert['l0_assessed_count'],
            'provisional_item_count':cert['legal_item_count'],
            'provisional_fillable_slots':len(cert['slot_frontiers']),
            'provisional_required_slots':18,
            'provisional_unresolved_effect_items':cert['unknown_effect_item_count'],
            'source_membership_verified':warrior_source_membership_verified(DB),
            'provisional_membership_rows':count,'provenance_counts':statuses,
            'source_contextual_top5':'NOT_MEASURED_UNVERIFIED_MEMBERSHIP',
            'required_slot_counts':{k:v['legal_item_count'] for k,v in cert['slot_frontiers'].items()},
            'missing_required_slots':cert['missing_required_slots'],
            'probe_wall_s':elapsed_wall,'probe_cpu_s':elapsed_cpu},
        'p4':{'status':'NOT_RUN'},'p5':{'status':'NOT_RUN'},'p6':{'status':'NOT_RUN'},
        'p4_p5_wall_cpu_events_attempts_unique_forecast_actual':'NOT_MEASURED',
        'provisional_sqlite_sha256':hashlib.sha256(DB.read_bytes()).hexdigest(),
        'limitations':['Provisional item set is not a legal Warrior denominator',
            'Other class listview intersections can include class-restricted items and miss Warrior-only items',
            'No 100-mob build evaluation or Top5 claim until class-1 source membership is ingested']}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result

if __name__=='__main__':
    print(json.dumps(run(),indent=2))
