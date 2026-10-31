"""WF328: a sourced mode family must enter the REAL paid prefix search."""
from dataclasses import replace
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_budgeted_prefix import run_source_budgeted_prefix, source_prefix_envelope
from src.game.model import PolicyDefinition, PolicyRuleDefinition
from src.v2.source_persistent_joint_finalists import (
    PreparedCandidate, evaluate_persistent_candidate,
)


def test_small_budget_pays_for_mode_paths_not_only_lists_them():
    ir=build_game_ir_slice(class_key='druid',level=20)
    paths={p['entry'] for p in source_prefix_envelope(ir,level=20)['mode_paths']}
    assert paths
    r=run_source_budgeted_prefix(class_key='druid',level=20,ir_slice=ir,max_evaluations=30)
    assert r['attempted']==30
    assert r['paid_mode_prefix_attempts']>=2
    assert paths <= set(r['paid_distinct_mode_entries'])
    assert any(x['prefix'][0] in paths for x in r['trials'])
    # Source-legal Cat entry is really in the executor trace, not merely a
    # hand-picked gear/policy in the report.
    assert r['winner']['prefix'][0] in paths
    assert r['winner']['score_s_per_mob']<29.9
    assert r['mode_seed_count']>=2


def test_mode_form_requires_actual_source_transition():
    ir=build_game_ir_slice(class_key='druid',level=20)
    absent=replace(ir,actions=tuple(a for a in ir.actions if a.id!='cat_form:768'))
    env=source_prefix_envelope(absent,level=20)
    assert all(p['entry']!='cat_form:768' for p in env['mode_paths'])
    found=run_source_budgeted_prefix(class_key='druid',level=20,ir_slice=absent,max_evaluations=10)
    assert not any(x['prefix'][0]=='cat_form:768' for x in found['trials']+found['failures'])


def test_persistent_replay_same_executor_100_mobs():
    ir=build_game_ir_slice(class_key='druid',level=20)
    r=run_source_budgeted_prefix(class_key='druid',level=20,ir_slice=ir,max_evaluations=30)
    winner=r['winner']
    pol=PolicyDefinition(id='wf328-probe',label='Budgeted original source policy',
        rules=(PolicyRuleDefinition(id='fallback:0',action_id=winner['fallback']),),
        provenance={'authority':'source_budgeted_prefix'})
    candidate=PreparedCandidate(ir=ir,policy=pol,opening=tuple(winner['prefix']),
        source_stage={},allocation={})
    measured=evaluate_persistent_candidate(candidate,level=20,mobs=100,
        max_wall_s=15,max_total_events=100000)
    assert measured['status']=='COMPLETE'
    assert measured['count']==100
    assert measured['continuous_actor_state']
    assert measured['skipped_satisfied_mode_prefixes']>0
    assert 1<measured['mean_s_per_mob']<100
    assert measured['events']>0


def test_checkpoint_l0_source_rank_admission_is_exact_paid_envelope():
    from src.game.data.forever.source_checkpoint_l0 import action_frontier
    ir=build_game_ir_slice(class_key='druid',level=20)
    report=action_frontier(ir,class_key='druid',level=20)
    assert report['paid_mode_entry_count']>=2
    assert report['paid_search_admitted_source_rows']>0
    assert report['positive_level_source_ranks_unadmitted_missing_ir']>0
    assert report['paid_search_admission_is_L2_coverage_proof'] is False
    assert report['PASS1'] is False
    admitted=[r for r in report['records'] if r.get('paid_search_admission')=='PAID_EXECUTABLE_SOURCE_IR']
    env=source_prefix_envelope(ir,level=20)
    ids=set(env['actions'])
    for m in env['mode_paths']:
        ids.add(m['entry']);ids.update(m['actions'])
    assert all(set(r['paid_search_action_ids']) <= ids for r in admitted)
