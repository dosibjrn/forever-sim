"""Generate a strict, class-neutral P1 checkpoint certificate from real source stage."""
from __future__ import annotations
import json, os, sqlite3, tempfile
from pathlib import Path
from src.game.data.forever.source_checkpoint_p1_acceptance import CheckpointP1,evaluate_p1,l0_paid_action_priority
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_l0 import action_frontier
from src.game.data.forever.source_checkpoint_web_l0 import ingest_observations as ingest_web
from src.game.data.forever.source_observed_rank_parity import ingest_observations as ingest_beta
from src.game.data.forever.source_queued_swing import ingest as ingest_maul
from src.game.data.forever.source_db_scope import ability_source_scope
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.v2.source_budgeted_prefix import source_prefix_envelope
ROOT=Path(__file__).resolve().parents[1]

def run():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    cp=CheckpointP1('druid',20,use_runes=False)
    with tempfile.TemporaryDirectory(prefix='wf333_p1_') as tmp:
        stage=Path(tmp)/'stage.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as src,sqlite3.connect(stage) as dst:
            src.backup(dst)
        ingest_beta(stage,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(stage,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        ingest_maul(stage,ROOT/'evidence/wf330/druid_l20_maul_observations.json')
        ingest_web(stage,ROOT/'evidence/wf331/druid20_source_web_index_observations.json')
        with ability_source_scope(stage):
            ir=build_game_ir_slice(class_key=cp.class_key,level=cp.level,ability_db_path=stage,use_runes=cp.use_runes)
            frontier=action_frontier(ir,class_key=cp.class_key,level=cp.level,db_path=stage,use_runes=cp.use_runes)
            p1=evaluate_p1(frontier,stage,cp,ir=ir)
            order=l0_paid_action_priority(p1)
            before=source_prefix_envelope(ir,level=cp.level)
            after=source_prefix_envelope(ir,level=cp.level,l0_action_priority=order)
        assert set(before['actions'])==set(after['actions'])
        assert {p['entry'] for p in before['mode_paths']}=={p['entry'] for p in after['mode_paths']}
        assert all(set(x['actions'])==set(y['actions']) for x,y in zip(before['mode_paths'],after['mode_paths']))
        assert sqlite3.connect(stage).execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    p1['l0_paid_action_priority']=order
    p1['source_index_provisional_rank_count']=frontier['potentially_legal_positive_ranks']
    p1['source_context_role_assessed']=frontier['potential_ranks_assessed_by_numeric_ir_or_text_role']
    p1['l2_actions_before_after_identical']=True
    p1['real_paid_source_envelope_path']='src.v2.source_budgeted_prefix.source_prefix_envelope'
    return p1

if __name__=='__main__':
    result=run()
    out=ROOT/'evidence/wf333/WF333_P1_CHECKPOINT_CERTIFICATE.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('records','l0_paid_action_priority')},indent=2))
