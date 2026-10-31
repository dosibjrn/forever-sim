"""L0 evidence on authoritative WF331 source stage, no naked-prefix gameplay score."""
from __future__ import annotations
from pathlib import Path
import json,sqlite3,tempfile
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_observed_rank_parity import ingest_observations as ingest_beta
from src.game.data.forever.source_checkpoint_web_l0 import ingest_observations as ingest_web
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.game.data.forever.source_queued_swing import ingest as ingest_maul
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_l0 import action_frontier
from src.game.data.forever.source_db_scope import ability_source_scope
ROOT=Path(__file__).resolve().parents[1]

def run():
    import os
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    with tempfile.TemporaryDirectory(prefix='wf332_runes_') as tmp:
        stage=Path(tmp)/'stage.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as src,sqlite3.connect(stage) as dst:
            src.backup(dst)
        ingest_beta(stage,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(stage,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        ingest_maul(stage,ROOT/'evidence/wf330/druid_l20_maul_observations.json')
        ingested=ingest_web(stage,ROOT/'evidence/wf331/druid20_source_web_index_observations.json')
        with ability_source_scope(stage):
            ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage)
            report=action_frontier(ir,class_key='druid',level=20,db_path=stage)
        with sqlite3.connect(stage) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    return {'schema':'wf332_rune_default_and_l0_gate_v1','accepted_checkpoints':0,
       'checkpoint':'Druid L20 unrestricted','use_runes_default':False,
       'ingested_source_observations':ingested,
       'index_scope_by_type':report['index_scope_by_type'],
       'potentially_legal_positive_ranks':report['potentially_legal_positive_ranks'],
       'assessed_by_numeric_ir_or_text_role':report['potential_ranks_assessed_by_numeric_ir_or_text_role'],
       'paid_search_admitted':report['paid_search_admitted_source_rows'],
       'unknown_effect_roles':report['potential_ranks_unknown_role_and_amount'],
       'rune_engraving_rows_disabled':report['rune_engraving_rows_disabled'],
       'rune_conditional_grants_blocked_without_talent':report['rune_conditional_grants_blocked_without_talent'],
       'auxiliary_nonbuttons_needing_parent_coverage':report['auxiliary_nonbuttons_needing_parent_coverage'],
       'PASS1':False,'PASS2':False,'PASS3':False,'PASS4':False,'PASS5':False,'PASS6':False,
       'no_new_geared_discovery':True,'L0_is_joint_search_score':False,
       'legal_acquisition_and_parent_effect_missing':True}

if __name__=='__main__':
    value=run()
    output=ROOT/'evidence/wf332/WF332_RUNE_POLICY_L0.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in value.items() if k!='ingested_source_observations'},indent=2))
