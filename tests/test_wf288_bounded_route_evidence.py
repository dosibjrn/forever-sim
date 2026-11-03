"""Reader integrity for bounded route evidence; legacy spell-acquisition fields are ignored."""
import copy
import json
from pathlib import Path
from hashlib import sha256

from src.v2.source_bounded_route_evidence import (
    EVIDENCE_FILE, checked_source_scenario_routes,
)
from src.game.data.forever.registry import build_game_ir_slice
from src.game.level_legality import (
    LevelState, validate_level_state, validate_level_transition,
)
from src.game.talents import apply_talent_selection
from src.game.data.forever.sqlite_talents import DEFAULT_DB as TALENT_DB
from src.v2.source_stateful_budgeted import (
    _make_policy, _condition_from_record, source_execution_context,
)
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_budgeted_prefix import ordered_prefix_executed
from src.version import SOFTWARE_VERSION

ROOT=Path(__file__).resolve().parents[1]
ITEM=ROOT/'data/forever/catalogue/items_2026-09-29.sqlite'


def checked(root=ROOT):
    return checked_source_scenario_routes(root,version=SOFTWARE_VERSION,
        item_db_sha=sha256(ITEM.read_bytes()).hexdigest())


def staged(tmp_path,data):
    path=tmp_path/EVIDENCE_FILE
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data))
    return checked(tmp_path)


def current_fixture():
    """Build a tiny current-source reader fixture from the historical snapshot.

    The checked-in 97-step artifact is intentionally stale and remains rejected.
    This two-step Druid fixture refreshes only source/talent identities, transition
    records and replay scores so reader integrity can still be tested against the
    current production executor without treating historical coverage as current.
    """
    data=json.loads((ROOT/EVIDENCE_FILE).read_text())
    data['canonical_item_db_sha256']=sha256(ITEM.read_bytes()).hexdigest()
    data['canonical_talent_db_sha256']=sha256(Path(TALENT_DB).read_bytes()).hexdigest()
    total_events=total_attempts=total_steps=0

    for cls,record in data['classes'].items():
        route=copy.deepcopy(record.get('selected_route') or [])[:2] if cls=='druid' else []
        record['selected_route']=route
        record['last_contiguous_level']=route[-1]['level'] if route else None
        record['status']='PARTIAL_BOUNDED_SOURCE_SCENARIO'
        record['full_route_complete']=False
        record['accepted_class_level_checkpoints']=0
        record['compute']={'event_transitions':len(route),'l2_attempts':3*len(route)}
        record['global_budget']={'max_events':100,'max_l2_attempts':100}
        parent=None
        for step in route:
            level=int(step['level'])
            source=build_game_ir_slice(class_key=cls,level=level)
            assert source is not None, (cls,level)
            talented,_=apply_talent_selection(source,step['talents'],level=level)
            step['source_context']=source_execution_context(talented)
            state=LevelState(class_key=cls,level=level,
                race_key=step.get('source_scenario_race'),
                talents=step['talents'],action_ids=tuple(step['source_action_ids']))
            validate_level_state(state)
            legal=validate_level_transition(parent,state) if parent else None
            step['source_legal_transition']=legal

            guard_conditions=tuple(_condition_from_record(x)
                for x in step.get('guarded_conditions',()))
            policy=_make_policy(talented,step['fallback'],
                guarded_action=step.get('guarded_action'),
                guarded_conditions=guard_conditions)
            actual,execution,_=_policy_combat_evaluation(
                talented,level=level,policy_override=policy,
                opening_action_ids=tuple(step['prefix']),
                schedule_incoming_attacks=True)
            assert (actual is not None and execution is not None
                and execution.timeline.target_defeated
                and ordered_prefix_executed(execution,tuple(step['prefix']))), (cls,level)
            step['full_cycle_s_per_mob']=float(actual.seconds_per_mob)
            step['scratch_verification_complete']=True
            step['real_l2_attempts']=3
            step['executor_event_transitions']=1
            step['cpu_ns']=1
            parent=state

        total_events+=len(route)
        total_attempts+=3*len(route)
        total_steps+=len(route)

    summary=data['summary']
    summary['full_bounded_legal_source_scenario_corridors']=0
    summary['source_legal_scratch_verified_steps_in_selected_paths']=total_steps
    summary['total_real_executor_events_all_attempts']=total_events
    summary['total_real_L2_attempts']=total_attempts
    summary['accepted_source_complete_class_level_checkpoints']=0
    summary['validated_full_continuous_leveling_routes']=0
    return data


def test_current_source_fixture_replays_and_ignores_legacy_spell_metadata(tmp_path):
    fixture=current_fixture()
    # Old metadata is neither proof nor a veto. The reader must use only the
    # current source context, legal talent transition and independently replayed score.
    fixture['all_route_acquisitions_verified']=True
    fixture['classes']['druid']['ability_trainer_quest_rune_acquisition_verified']=True
    fixture['classes']['druid']['selected_route'][0]['world_acquisition_verified']=True
    fixture['classes']['druid']['selected_route'][1]['source_consistent_acquisition']=True
    fixture['classes']['druid']['selected_route'][1]['source_acquisition_events']=[{'kind':'trainer_purchase'}]
    info,rows=staged(tmp_path,fixture)
    assert info['valid'], info['failures']
    assert info['full_bounded_corridors']==0
    assert len(rows)==2 and info['scratch_verified_source_scenario_steps']==2
    assert rows['druid',10]['seconds_per_mob']>0
    assert rows['druid',11]['seconds_per_mob']>0
    assert all('route_complete' not in row for row in rows.values())


def test_reader_does_not_repeat_source_state_check_after_transition(monkeypatch, tmp_path):
    from src.v2 import source_bounded_route_evidence as reader

    fixture = current_fixture()
    checked_levels = []
    original = reader.validate_level_state

    def count_initial_state_checks(state):
        checked_levels.append(state.level)
        return original(state)

    monkeypatch.setattr(reader, 'validate_level_state', count_initial_state_checks)
    info, rows = staged(tmp_path, fixture)
    assert info['valid'], info['failures']
    assert len(rows) == 2
    # Continuations already validate parent+child through the transition
    # check; the standalone state check is only needed for the root.
    assert checked_levels == [10]


def test_historical_snapshot_is_rejected_when_talent_database_changes():
    info,rows=checked()
    assert not info['valid'], info['failures']
    assert any(failure.endswith('talent_database_mismatch') for failure in info['failures'])
    assert rows=={}


def test_historical_snapshot_is_rejected_when_source_context_changes(tmp_path):
    original=json.loads((ROOT/EVIDENCE_FILE).read_text())
    original['canonical_item_db_sha256']=sha256(ITEM.read_bytes()).hexdigest()
    original['canonical_talent_db_sha256']=sha256(Path(TALENT_DB).read_bytes()).hexdigest()
    info,rows=staged(tmp_path,original)
    assert not info['valid'], info['failures']
    assert any('source_or_engine_context_mismatch' in failure
               for failure in info['failures'])
    assert rows=={}


def test_bad_version_source_and_legality_do_not_promote(tmp_path):
    original=current_fixture()
    cases=[]
    def case(modify):
        d=copy.deepcopy(original);modify(d);cases.append(d)
    case(lambda d:d.__setitem__('software_version','0.11.48.0'))
    case(lambda d:d.__setitem__('canonical_item_db_sha256','0'*64))
    case(lambda d:d.__setitem__('canonical_talent_db_sha256','0'*64))
    case(lambda d:d['classes']['druid']['selected_route'][0].__setitem__('source_context','0'*64))
    case(lambda d:d['classes']['druid']['selected_route'][0].__setitem__('full_cycle_s_per_mob',999.0))
    case(lambda d:d['classes']['druid']['selected_route'][1].__setitem__('level',42))
    case(lambda d:d['classes']['druid']['selected_route'][1].__setitem__('talents',{'improved_wrath':999}))
    case(lambda d:d['classes']['druid']['selected_route'][1].__setitem__('talents',{}))
    case(lambda d:d['classes']['druid']['selected_route'][1].__setitem__('scratch_verification_complete',False))
    case(lambda d:d['classes']['hunter'].__setitem__('named_gear_acquisition_verified',True))
    case(lambda d:d['classes']['druid']['compute'].__setitem__('event_transitions',999999))
    case(lambda d:d['classes']['druid']['compute'].__setitem__('l2_attempts',999999))
    case(lambda d:d['classes']['druid']['global_budget'].__setitem__('max_events',0))
    case(lambda d:d['classes']['druid']['global_budget'].__setitem__('max_l2_attempts',0))
    case(lambda d:d['summary'].__setitem__('total_real_executor_events_all_attempts',0))
    case(lambda d:d['summary'].__setitem__('total_real_L2_attempts',0))
    case(lambda d:d['summary'].__setitem__('full_bounded_legal_source_scenario_corridors',9))
    for value in cases:
        info,rows=staged(tmp_path,value)
        assert not info['valid'] and not rows and info['failures']


def test_route_benchmark_does_not_emit_retired_acquisition_claim(monkeypatch):
    from tools import wf288_real_contiguous_route_benchmark as benchmark

    def partial_route(**_):
        return {
            'status':'PARTIAL_BOUNDED_SOURCE_SCENARIO',
            'selected_route':[],
            'compute':{
                'event_transitions':0,'l2_attempts':0,
                'scorer_cpu_ns':0,'total_cpu_ns':0,
            },
        }

    monkeypatch.setattr(benchmark,'search_source_bounded_level_route',partial_route)
    report=benchmark.benchmark(end_level=10)
    assert 'all_route_acquisitions_verified' not in report['summary']


def test_missing_evidence_cannot_claim_route(tmp_path):
    info,rows=checked(tmp_path)
    assert not info['valid'] and rows=={}
