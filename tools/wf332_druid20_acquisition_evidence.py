"""WF332: replay checkpoint-scoped acquisition and exact source-rank bindings.

No new 30/300-second joint search; do not promote to checkpoint PASS.
"""
from __future__ import annotations
import json,os,sqlite3,tempfile
from pathlib import Path
from time import monotonic,process_time
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_observed_rank_parity import ingest_observations as ingest_beta
from src.game.data.forever.source_checkpoint_web_l0 import ingest_observations as ingest_web
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.game.data.forever.source_queued_swing import ingest as ingest_maul
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_l0 import action_frontier
from src.game.data.forever.source_db_scope import ability_source_scope
from src.v2.source_budgeted_prefix import run_source_budgeted_prefix
from src.v2.source_persistent_joint_finalists import prepare_candidate, evaluate_persistent_candidate

ROOT=Path(__file__).resolve().parents[1]


def run():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    with tempfile.TemporaryDirectory(prefix='wf332_druid20_') as tmp:
        stage=Path(tmp)/'stage.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as src, sqlite3.connect(stage) as dst:
            src.backup(dst)
        ingest_beta(stage,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(stage,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        ingest_maul(stage,ROOT/'evidence/wf330/druid_l20_maul_observations.json')
        ingest_web(stage,ROOT/'evidence/wf331/druid20_source_web_index_observations.json')
        with ability_source_scope(stage):
            ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage)
            frontier=action_frontier(ir,class_key='druid',level=20,db_path=stage)
            started=monotonic();cpu=process_time()
            paid=run_source_budgeted_prefix(class_key='druid',level=20,
                max_evaluations=160,ir_slice=ir)
            wall=monotonic()-started;cpu_s=process_time()-cpu
            previous=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())
            candidate=prepare_candidate(class_key='druid',level=20,stage=previous['finalist']['winner']['stage'])
            replay_start=monotonic();replay_cpu_start=process_time()
            replay=evaluate_persistent_candidate(candidate,level=20,mobs=100,max_wall_s=15,max_total_events=100000)
            replay_wall=monotonic()-replay_start;replay_cpu=process_time()-replay_cpu_start
        with sqlite3.connect(stage) as db:
            integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
    matched=[r for r in frontier['records'] if r.get('spell_id') is not None and r['ir_action_ids']]
    acquisition=frontier['source_acquisition_frontier']
    return {'checkpoint':'druid_L20_unrestricted','accepted_checkpoints':0,
        'source_snapshot':'canonical Oct8 plus isolated WF322/WF321/WF330/WF331 evidence',
        'index_rows':frontier['source_index_rows_all_levels'],
        'exact_ir_index_matches':len(matched),
        'exact_ir_source_spell_ids':sorted(r['spell_id'] for r in matched),
        'new_exact_bindings':[r['spell_id'] for r in matched if r['spell_id'] in (5188,1430)],
        'positive_nonengraving_potential':frontier['potentially_legal_positive_ranks'],
        'semantically_assessed':frontier['potential_ranks_assessed_by_numeric_ir_or_text_role'],
        'source_acquisition':acquisition,
        'source_rank_paid_search_admitted':frontier['paid_search_admitted_source_rows'],
        'full_L2_legal_action_set_proven':False,
        'paid_L2_single_mob_diagnostic':{
            'attempts':paid['attempted'],'evaluated':paid['evaluated'],
            'blocked':paid['blocked'],'events':sum(x['event_count'] for x in paid['trials']),
            'wall_s':wall,'cpu_s':cpu_s,
            'best_s_per_mob':paid['winner']['score_s_per_mob'] if paid['winner'] else None,
            'best_prefix':paid['winner']['prefix'] if paid['winner'] else None,
            'NOT_100_MOB_AND_NOT_JOINT':True},
        'known_winner_100_mob_replay':{
            's_per_mob':replay['mean_s_per_mob'],'mobs':replay['count'],
            'events':replay['events'],'status':replay['status'],
            'cpu_s':replay_cpu,'wall_s':replay_wall,
            'known_prior_winner_seeded':True,'independent_joint_search':False},
        'source_acquisition_proof_gap':True,'sqlite_integrity':integrity,
        'PASS1':False,'PASS2':False,'PASS3':False,'PASS4':False,'PASS5':False,'PASS6':False,
        'strict_30s_300s_saturation_not_run':True}

if __name__=='__main__':
    result=run()
    p=ROOT/'evidence/wf332/WF332_DECISION.json';p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k in ('exact_ir_index_matches','new_exact_bindings','positive_nonengraving_potential','semantically_assessed','source_rank_paid_search_admitted','source_acquisition','paid_L2_single_mob_diagnostic','known_winner_100_mob_replay')},indent=2))
