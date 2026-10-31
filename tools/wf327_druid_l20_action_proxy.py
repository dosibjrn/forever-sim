"""Druid L20 checkpoint-scoped PASS1 proxy + existing joint L2 smoke evidence.

This tool does not create a new engine, score oracle or checkpoint gate.
"""
from __future__ import annotations
import json,os,sqlite3,tempfile
from pathlib import Path
from time import monotonic,process_time
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_budgeted_prefix import source_prefix_envelope
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from tools.wf321_ingest_control_observations import ingest as ingest_control
from tools.wf297_druid_l20_checkpoint import JOINT_ARGS


def run(*, with_l2=True):
    root=Path(__file__).resolve().parents[1]
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    with tempfile.TemporaryDirectory(prefix='wf327_druid20_') as tmp:
        stage=Path(tmp)/'stage.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as src, sqlite3.connect(stage) as dst:
            src.backup(dst)
        ingest_observations(stage,root/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(stage,root/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(stage):
            ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage)
            envelope=source_prefix_envelope(ir,level=20,include_auto_fallback=True)
            coverage=envelope['l0_action_proxy_coverage']
            t=monotonic();cpu=process_time()
            joint=run_source_budgeted_joint_talents(**JOINT_ARGS,ir_slice=ir) if with_l2 else None
            duration=monotonic()-t;cpu_used=process_time()-cpu
    return {'schema':'wf327_druid20_checkpoint_action_l0_v1',
        'accepted_checkpoints':0,'total_checkpoints':148,
        'source_authority':'canonical SQLite with isolated WF322+WF321 staged web observations',
        'source_stage_unverified_client_html':True,
        'coverage':coverage,
        'search_envelope':{'initial_actions':list(envelope['actions']),
                           'initial_fillers':list(envelope['fillers']),
                           'mode_paths':[{'entry':x['entry'],'mode_id':x['mode_id'],
                                          'actions':list(x['actions']),'fillers':list(x['fillers'])}
                                         for x in envelope['mode_paths']]},
        'l2':None if joint is None else {
            'status':joint.get('status'), 'attempted':joint.get('attempted'),
            'evaluated':joint.get('evaluated'),'blocked':joint.get('blocked'),
            'events':joint.get('event_transitions'),
            'winner_s_per_mob':None if joint.get('winner') is None else joint['winner']['score_s_per_mob'],
            'winner_allocation':None if joint.get('winner') is None else joint['winner']['allocation'],
            'controller_cpu_ns':joint.get('controller_cpu_ns'),
            'measured_wall_s':duration,'measured_cpu_s':cpu_used,
            'scope':'bounded L2 single-mob search, NOT 100-mob prediction or 30/300s saturation'},
        'pass_1':'NOT_YET_ACCEPTED_SOURCE_LEGAL_UNIVERSE_UNCERTAIN',
        'pass_2':'NOT_MEASURED','pass_3':'NOT_MEASURED',
        'pass_4':'NOT_MEASURED','pass_5':'NOT_MEASURED','pass_6':'NOT_MEASURED'}

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    result=run()
    dest=root/'evidence/wf327/WF327_DRUID20_ACTION_PROXY_AND_L2.json'
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,indent=2,sort_keys=True,default=str)+'\n')
    print(json.dumps({'coverage':{k:v for k,v in result['coverage'].items() if not isinstance(v,list)},
                      'l2':result['l2'],'accepted':result['accepted_checkpoints']},indent=2,default=str))
