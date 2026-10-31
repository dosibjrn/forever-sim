"""Compare canonical-source L0 before/after source-identity-bound web-indexed observations.

The additional observations are only L0.  No paid-L2 promotion or proof of
rune acquisition is implied.  The canonical database is read-only.
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

ROOT=Path(__file__).resolve().parents[1]

def run():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    with tempfile.TemporaryDirectory(prefix='wf331_druid20_') as tmp:
        stage=Path(tmp)/'stage.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as src, sqlite3.connect(stage) as dst:
            src.backup(dst)
        ingest_beta(stage,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(stage,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        ingest_maul(stage,ROOT/'evidence/wf330/druid_l20_maul_observations.json')
        with ability_source_scope(stage):
            ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage)
            before=action_frontier(ir,class_key='druid',level=20,db_path=stage)
        ingested=ingest_web(stage,ROOT/'evidence/wf331/druid20_source_web_index_observations.json')
        with sqlite3.connect(stage) as db:
            integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
            assert integrity=='ok'
        with ability_source_scope(stage):
            ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage)
            after=action_frontier(ir,class_key='druid',level=20,db_path=stage)
            started=monotonic();cpu=process_time()
            paid=run_source_budgeted_prefix(class_key='druid',level=20,
                max_evaluations=160,ir_slice=ir)
            wall=monotonic()-started;cpu_s=process_time()-cpu
        unassessed=[{'spell_id':r['spell_id'],'name':r['name'],'source_url':r['source_url']}
            for r in after['records'] if r.get('eligibility')=='POTENTIALLY_LEGAL_RANK_ACQUISITION_UNRESOLVED'
            and not r['ir_action_ids'] and not r['index_features']['source_atom_kinds']
            and not r['source_text_context_evidence']['effect_candidates']
            and not r['sibling_rank_context_only']]
        web=[{'spell_id':r['spell_id'],'name':r['name'],
              'effect_roles':sorted(set(x['kind'] for x in r['source_text_context_evidence']['effect_candidates'])),
              'capture_kind':r['web_indexed_l0_observation']['capture_kind'],
              'flags':r['web_indexed_l0_observation']['source_flags'],
              'legal_acquisition_proven':False,'paid_search_admission':r['paid_search_admission']}
            for r in after['records'] if r.get('web_indexed_l0_observation')]
    assert after['potentially_legal_positive_ranks']<=before['potentially_legal_positive_ranks']
    assert after['paid_search_admitted_source_rows']==before['paid_search_admitted_source_rows']
    return {'checkpoint':'Druid L20 unrestricted','accepted_checkpoints':0,
        'source':'canonical source-index SHA plus web search-indexed text; not raw HTML',
        'before':{'potential_positive_ranks':before['potentially_legal_positive_ranks'],
            'l0_semantic_assessed':before['potential_ranks_assessed_by_numeric_ir_or_text_role'],
            'l0_unassessed':before['potential_ranks_unknown_role_and_amount'],
            'paid_search_admitted':before['paid_search_admitted_source_rows']},
        'after':{'potential_positive_ranks':after['potentially_legal_positive_ranks'],
            'l0_semantic_assessed':after['potential_ranks_assessed_by_numeric_ir_or_text_role'],
            'l0_unassessed':after['potential_ranks_unknown_role_and_amount'],
            'paid_search_admitted':after['paid_search_admitted_source_rows'],
            'web_l0_observation_count':after['web_indexed_observation_rows'],
            'web_semantic_roles_count':after['web_indexed_potential_rank_l0_roles']},
        'ingestion':ingested,'web_scored':web,'remaining_unassessed':unassessed,
        'paid_l2_diagnostic':{'attempts':paid['attempted'],'evaluated':paid['evaluated'],
            'blocked':paid['blocked'],'wall_s':wall,'cpu_s':cpu_s,
            'executor_events_successes':sum(x['event_count'] for x in paid['trials']),
            'best_single_mob_s_per_mob':paid['winner']['score_s_per_mob'] if paid['winner'] else None,
            'best_prefix':paid['winner']['prefix'] if paid['winner'] else None,
            '100_mob_comparison':False},
        'sqlite_integrity':integrity,'canonical_db_unchanged':True,
        'PASS1':False,'PASS2':False,'PASS3':False,'PASS4':False,'PASS5':False,'PASS6':False,
        'L2_promotion':0,'strict_30_300_not_run':True}

if __name__=='__main__':
    result=run()
    out=ROOT/'evidence/wf331/WF331_DECISION.json'
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'before':result['before'],'after':result['after'],
        'unassessed':result['remaining_unassessed'],'L2':result['paid_l2_diagnostic']},indent=2))
