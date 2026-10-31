"""Build-local canonical-item Top-5 per slot: actual 100-mob stat perturbations."""
from __future__ import annotations
import json,os,sqlite3,tempfile
from pathlib import Path
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2.source_persistent_joint_finalists import prepare_candidate
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.game.data.forever.source_checkpoint_p3_weights import measured_stat_weights,ranked_top_items

ROOT=Path(__file__).resolve().parents[1]
def run(*,mobs=100):
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    with tempfile.TemporaryDirectory(prefix='wf339_source_') as tmp:
        staged=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as db, sqlite3.connect(staged) as dest: db.backup(dest)
        ingest_observations(staged,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(staged,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(staged):
            candidate=prepare_candidate(class_key='druid',level=20,stage=stage)
            weights=measured_stat_weights(candidate=candidate,class_key='druid',level=20,mobs=mobs)
            ranking=ranked_top_items(class_key='druid',level=20,stage=stage,weight_evidence=weights,top_n=5)
            return ranking
if __name__=='__main__':
    result=run()
    out=ROOT/'evidence/wf339/WF339_DRUID_L20_WEIGHTED_TOP5_PER_SLOT.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'p3_pass':result['p3_pass'],'legal':result['total_legal_items'],
      'unknown_items':result['unknown_item_count'],'weights':{k:(v['status'],v['weight_s_saved_per_mob_per_unit']) for k,v in result['stat_weights']['weights'].items()},
      'tops':{k:[(r['item_id'],r['name'],round(r['known_score_s_saved_per_mob'],5)) for r in v['top']] for k,v in result['slots'].items()}},ensure_ascii=False,indent=2))
