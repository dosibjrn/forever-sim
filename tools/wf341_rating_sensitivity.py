"""WF341: reuse SOURCE-MATCHED verified WF339 100-mob baseline weights.

Only new Crit/Hit/Dodge probability sensitivities are run; never truncate
expensive already validated stat probes or infer new provenance.
"""
from __future__ import annotations
import json, os, sqlite3, tempfile
from pathlib import Path
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2.source_persistent_joint_finalists import prepare_candidate
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.game.data.forever.source_checkpoint_p3_weights import measured_stat_weights, ranked_top_items
ROOT=Path(__file__).resolve().parents[1]

def run():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    prior=json.loads((ROOT/'evidence/wf339/WF339_DRUID_L20_WEIGHTED_TOP5_PER_SLOT.json').read_text())['stat_weights']
    stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    with tempfile.TemporaryDirectory(prefix='wf341_') as d:
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as db, sqlite3.connect(Path(d)/'source.sqlite') as dst:db.backup(dst)
        src=Path(d)/'source.sqlite'
        ingest_observations(src,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(src,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(src):
            candidate=prepare_candidate(class_key='druid',level=20,stage=stage)
            weights=measured_stat_weights(candidate=candidate,class_key='druid',level=20,mobs=100,prior_weights=prior)
            report=ranked_top_items(class_key='druid',level=20,stage=stage,weight_evidence=weights,top_n=5)
            out=ROOT/'evidence/wf341/WF341_DRUID_L20_CHANCE_SENSITIVITY_TOP5.json'
            out.parent.mkdir(parents=True,exist_ok=True)
            out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
            return report
if __name__=='__main__':
    r=run()
    print(json.dumps({'p3_pass':r['p3_pass'],'uncertain':r['unknown_item_count'],
      'chance':r['stat_weights']['chance_sensitivities'],
      'tops_diff':{s:{'known':[x['item_id'] for x in b['top']],
        'historical_sensitivity':b['historical_rating_sensitivity_top_ids']}
        for s,b in r['slots'].items() if [x['item_id'] for x in b['top']]!=b['historical_rating_sensitivity_top_ids']}}
      ,indent=2))
