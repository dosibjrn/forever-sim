"""Reproduce WF330 source-stage L0, real paid Maul prefixes and geared 100 mobs.

This is NOT a 30s/300s discovery gate or a complete spell universe.
"""
from __future__ import annotations
import json,os,sqlite3,tempfile
from pathlib import Path
from time import monotonic,process_time
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.game.data.forever.source_queued_swing import ingest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_l0 import action_frontier
from src.game.data.forever.source_db_scope import ability_source_scope
from src.v2.source_budgeted_prefix import run_source_budgeted_prefix
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate

ROOT=Path(__file__).resolve().parents[1]

def run():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    old=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())
    with tempfile.TemporaryDirectory(prefix='wf330_source_') as tmp:
        stage=Path(tmp)/'stage.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as db,sqlite3.connect(stage) as dest:
            db.backup(dest)
        ingest_observations(stage,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(stage,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        ingest(stage,ROOT/'evidence/wf330/druid_l20_maul_observations.json')
        with sqlite3.connect(stage) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        with ability_source_scope(stage):
            ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage)
            scoped=action_frontier(ir,class_key='druid',level=20,db_path=stage)
            started=monotonic();cpu=process_time()
            search=run_source_budgeted_prefix(class_key='druid',level=20,
                max_evaluations=160,ir_slice=ir)
            search_elapsed=monotonic()-started;search_cpu=process_time()-cpu
            maul=[x for x in search['trials'] if any('source_queued_swing:' in a for a in x['prefix'])]
            assert {tuple(a for a in x['prefix'] if a.startswith('source_queued_swing:')) for x in maul}=={
                ('source_queued_swing:6807',),('source_queued_swing:6808',)}
            candidate=prepare_candidate(class_key='druid',level=20,stage=old['finalist']['winner']['stage'])
            replay=evaluate_persistent_candidate(candidate,level=20,mobs=100,max_wall_s=15,max_total_events=100000)
    ref=old['finalist']['winner']['persistent']
    assert replay['status']=='COMPLETE' and abs(replay['mean_s_per_mob']-ref['mean_s_per_mob'])<1e-9
    return {
        'schema':'wf330_source_queued_swing_v1','checkpoint':'druid_L20_unrestricted',
        'source_snapshot':'isolated_WF322_beta_70338_plus_WF321_Bash_plus_WF330_Maul',
        'source_observations_verified_raw_html':False,
        'accepted_checkpoints':0,
        'L0_ranks_potential':scoped['potentially_legal_positive_ranks'],
        'L0_sourced_effect_role_or_IR':scoped['potential_ranks_assessed_by_numeric_ir_or_text_role'],
        'L0_unassessed_or_legal_unknown':scoped['potential_ranks_unknown_role_and_amount'],
        'source_rank_paid_search_admitted':scoped['paid_search_admitted_source_rows'],
        'PASS1':False,'PASS2':False,'PASS3':False,'PASS4':False,'PASS5':False,'PASS6':False,
        'paid_l2_opening_probe':{'attempted':search['attempted'],'evaluated':search['evaluated'],
            'blocked':search['blocked'],'maul_paid_executed_count':len(maul),
            'maul_paid_executed_prefixes':[x['prefix'] for x in maul],
            'elapsed_wall_s':search_elapsed,'elapsed_cpu_s':search_cpu,
            'single_mob_scores_not_comparable_to_geared_100mob':True,
            'not_a_joint_gear_talent_optimization':True},
        'geared_known_winner_100_mob_replay':{
            'status':replay['status'],'s_per_mob':replay['mean_s_per_mob'],
            'mob_count':replay['count'],'events':replay['events'],
            'old_reference_s_per_mob':ref['mean_s_per_mob'],
            'delta_s':replay['mean_s_per_mob']-ref['mean_s_per_mob'],
            'old_winner_was_seeded':True,'independent_joint_search':False},
        'legal_universe_proven_complete':False,
        'strict_hard_30s_and_300s_joint':False,
        'limitations':['miss-resource refund/attack-table details not independently client verified',
                       'remaining source rank acquisition/effects incomplete',
                       'no measured independent 30/300s winner saturation'],
    }

if __name__=='__main__':
    result=run()
    p=ROOT/'evidence/wf330/WF330_DECISION.json'
    p.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,indent=2,sort_keys=True))
