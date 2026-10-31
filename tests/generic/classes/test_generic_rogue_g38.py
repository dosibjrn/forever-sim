from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.class_registry import get_definition, validate_registry
from src.game.data.forever import build_game_ir_slice
from src.game.model import ResourceChangeEffect, ResourceScaledDirectDamageEffect, WeaponDamageEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState, action_eligibility
from src.v2.generic_backend import (_policy_combat_evaluation, _builder_finisher_policy_search_probe,
                                    _searched_policy_combat_evaluation, build_partial_generic_records)
from src.v2.decision_dashboard import _generic_decision_payload
from src.listener import DECISIONS_HTML
from src.version import SOFTWARE_VERSION


def _rogue(level=18):
    ir = build_game_ir_slice(class_key="Rogue", level=level)
    assert ir is not None
    return ir


def test_g38_real_forever_rank_tables_and_bounded_source_adapter():
    assert build_game_ir_slice(class_key="rogue", level=9) is None
    assert build_game_ir_slice(class_key="rogue", level=21) is None
    for level, ss, ev in ((10, 1757, 6760), (14, 1758, 6760), (18, 1758, 6761), (20, 1758, 6761)):
        ir = _rogue(level)
        assert [a.id for a in ir.actions] == [f"sinister_strike:{ss}", f"eviscerate:{ev}"]
        assert [x.id for x in ir.resources] == ["health", "energy", "combo_points"]
        assert ir.resources[1].capacity == 100 and ir.resources[1].regeneration_per_s == 10
        assert ir.resources[2].scope == "target" and ir.resources[2].capacity == 5
        assert isinstance(ir.actions[0].effects[0], WeaponDamageEffect)
        assert isinstance(ir.actions[0].effects[1], ResourceChangeEffect)
        assert isinstance(ir.actions[1].effects[0], ResourceScaledDirectDamageEffect)
        assert ir.actions[1].effects[0].attack_power_coefficient_per_resource == 0  # unresolved Forever server script
        assert isinstance(ir.actions[1].effects[1], ResourceChangeEffect)
        assert all('wowhead.com/forever/' in a.provenance[0]['url'] for a in ir.actions)
        assert not any(a.family_key in ('backstab', 'stealth') for a in ir.actions)
        assert any(x['code']=='stealth_openers_backstab_and_positioning' for x in ir.unsupported_semantics)
    assert get_definition('forever','rogue').proof_only
    assert not get_definition('forever','rogue').ui_visible  # no invented legacy route
    validate_registry()


def test_g38_direct_finisher_snapshot_consumes_cp_and_ladder_damage():
    ir = _rogue(18)
    builder, finisher = ir.actions
    for cp in (1, 2, 5):
        actor = ActorState.from_ir(ir.actor, ir.resources)
        target = TargetState.with_health(f'mob-{cp}', 1000)
        runtime = CombatRuntime(actor=actor, target=target)
        assert not action_eligibility(action=finisher, actor=actor, target=target).eligible
        # Build real CP through the same generic builder, waiting for Energy.
        for n in range(cp):
            at = 1.0 + 4.5*n
            runtime.advance_to(at)
            runtime.enqueue_action(builder)
            runtime.advance_to(at)
        assert target.resource_amount('combo_points') == cp
        at = max(actor.current_time_s, 1.0 + cp*4.5)
        runtime.advance_to(at)
        runtime.enqueue_action(finisher)
        runtime.advance_to(at)
        expected = 13 + 19*cp  # Eviscerate r3 6..20 + 19 per CP
        hit = [e for e in runtime.trace if e.kind=='Damage' and e.action_id==finisher.id]
        assert len(hit) == 1
        assert hit[0].payload['resource_amount_snapshot']==cp
        assert hit[0].payload['amount']==pytest.approx(expected)
        assert target.resource_amount('combo_points') == 0
        consumes = [e for e in runtime.trace if e.kind=='ResourceChanged' and e.action_id==finisher.id]
        assert len(consumes)==1 and consumes[0].payload['after']==0


def test_g38_combo_points_reset_with_new_target_not_actor_energy():
    ir = _rogue()
    actor = ActorState.from_ir(ir.actor, ir.resources)
    old = TargetState.with_health('old', 1000)
    runtime = CombatRuntime(actor=actor, target=old)
    runtime.advance_to(1.0)
    runtime.enqueue_action(ir.actions[0]); runtime.advance_to(1.0)
    assert old.resource_amount('combo_points')==1.0
    remaining_energy = actor.resource_amount('energy')
    # A new target gets its own initialized CP state, not old CP carried over.
    new = TargetState.with_health('new', 1000)
    runtime2 = CombatRuntime(actor=actor, target=new)
    assert new.resource_amount('combo_points')==0
    assert not action_eligibility(action=ir.actions[1], actor=actor, target=new).eligible
    assert actor.resource_amount('energy')==remaining_energy


def test_g38_energy_regen_builder_then_finisher_actual_actions_and_damage():
    ir = _rogue(18)
    evaluation, execution, _ = _policy_combat_evaluation(ir, level=18)
    assert evaluation is not None and execution.timeline.target_defeated
    ids = [str(x['action_id']) for x in execution.selected_actions]
    assert ids[:3] == ['sinister_strike:1758','sinister_strike:1758','eviscerate:6761']
    events = execution.timeline.events
    assert any(e.kind == 'ResourceRegenerated' and e.payload.get('resource_id') == 'energy' for e in events)
    assert any(e.kind == 'AutoAttackSwing' and e.action_id == 'rogue:auto:mainhand' for e in events)
    assert any(e.kind == 'ResourceChanged' and e.payload.get('resource_id')=='combo_points' for e in events)
    assert any(e.kind=='Damage' and e.payload.get('resource_amount_snapshot')==2.0 for e in events)


def test_g38_cat_and_rogue_reuse_same_resource_and_policy_executor_not_dispatch():
    from src.game.policy import execute_priority_policy
    druid=build_game_ir_slice(class_key='druid',level=23)
    rogue=_rogue(18)
    assert druid is not None
    assert {r.scope for r in druid.resources if r.id == 'combo_points'} == {'target'}
    assert {r.scope for r in rogue.resources if r.id == 'combo_points'} == {'target'}
    for source in (druid,rogue):
        assert any(a.family_key in ('claw','sinister_strike') for a in source.actions)
        assert any(x.provenance.get('g26_scope') == 'builder_finisher_threshold_seed' for x in source.policies)
    code = (Path('src/game/runtime/simulator.py').read_text()
            +Path('src/game/policy.py').read_text()
            +Path('src/game/policy_search.py').read_text()).lower()
    for text in ('sinister strike','eviscerate','rogue'):
        assert text not in code
    assert callable(execute_priority_policy)


def test_g38_generic_bounded_search_produces_policy_and_cp_threshold():
    ir=_rogue(18)
    structural=_builder_finisher_policy_search_probe(ir,level=18)
    assert structural['status']=='selected'
    assert structural['selected_seconds_per_mob'] is not None
    assert structural['selected_combo_point_threshold'] in {1,2,3,4,5}
    assert structural['legacy_fallback'] is False
    assert len(structural['threshold_results'])>=2
    evaluation, execution, seed, policy_search, threshold_search, efficiency = _searched_policy_combat_evaluation(ir,level=18)
    assert evaluation is not None and execution.timeline.target_defeated
    assert policy_search.search_performed and threshold_search.search_performed
    assert efficiency['legacy_fallback'] is False if 'legacy_fallback' in efficiency else True
    assert any('eviscerate:' in x['action_id'] for x in execution.selected_actions)


def test_g38_generic_record_is_scoped_non_optimization_ready_with_real_finisher():
    r=build_partial_generic_records(class_names=('Rogue',),selected_level=18)[0]
    p=r.provenance['rogue_generic_decision']
    assert r.backend['id']=='generic'
    assert r.capability['rogue_native_generic_decision'] is True
    assert r.capability['combat_evaluation'] is True
    assert r.capability['builder_finisher_policy_search'] is True
    assert r.capability['optimization_ready'] is False
    assert p['status']=='executed' and p['legacy_fallback'] is False
    assert p['selected_seconds_per_mob'] is not None
    assert p['finisher_hit_count']>=1
    assert p['finisher_resource_consumption_events']==p['finisher_hit_count']
    assert p['finisher_resource_snapshots'] and p['selected_combo_point_threshold'] in (1,2,3,4,5)
    assert 'eviscerate_ap_scaling' in p['unsupported']
    assert 'not_final_leveling_score' in p['numeric_authority']


def test_g38_listener_scoped_and_generic_api_without_rogue_legacy_route():
    assert SOFTWARE_VERSION=='0.11.48.157'
    assert 'function genericRogueSummary(r)' in DECISIONS_HTML
    assert '${warriorHtml}${rogueHtml}' in DECISIONS_HTML
    assert 'not final leveling advice' in DECISIONS_HTML
    payload=_generic_decision_payload(18)
    assert 'rogue' in payload['class_metadata']
    assert payload['endpoint_paths']['rogue']['targets']['14']['routes']['unconstrained']['status']=='available'
    assert payload['generic_routes']['publication_cache']['status']=='validated_release_snapshot'
    r=next(x for x in payload['decisions'] if x['identity']['class_name'].lower()=='rogue')
    assert r['provenance']['rogue_generic_decision']['status']=='executed'


def test_g38_real_http_generic_proof_and_preserved_druid_snapshot(tmp_path):
    from src.service.store import QueueStore
    from src.service.http_api import OptimizerHTTPServer
    from src.service.client import ServiceClient
    store=QueueStore(tmp_path/'queue.sqlite3')
    server=OptimizerHTTPServer(('127.0.0.1',0),store,project_root=Path.cwd())
    th=threading.Thread(target=server.serve_forever,daemon=True); th.start()
    try:
        reply=ServiceClient(f'http://127.0.0.1:{server.server_address[1]}',timeout=90).decisions(level=18,backend_id='generic')
        assert reply['active_backend']=='generic'
        assert reply['generic_routes']['publication_cache']['status']=='validated_release_snapshot'
        rogue=next(x for x in reply['decisions'] if x['identity']['class_name'].lower()=='rogue')
        assert rogue['provenance']['rogue_generic_decision']['legacy_fallback'] is False
        assert rogue['capability']['rogue_native_generic_decision'] is True
        druid=next(x for x in reply['decisions'] if x['identity']['class_name'].lower()=='druid')
        assert druid['provenance'].get('rogue_generic_decision') is None
    finally:
        server.shutdown(); server.server_close(); th.join(timeout=3)


def test_g38_optimizer_can_reject_a_finisher_when_white_builder_wins():
    p=build_partial_generic_records(class_names=('Rogue',),selected_level=10)[0].provenance['rogue_generic_decision']
    assert p['seed_seconds_per_mob']==pytest.approx(7.0)
    assert p['selected_seconds_per_mob']==pytest.approx(5.0)
    assert p['improvement_s']==pytest.approx(2.0)
    assert p['selected_combo_point_threshold'] is None  # no finisher in selected policy
    assert p['finisher_hit_count']==0
    assert p['selected_executed_action_ids']==['sinister_strike:1757']*3
    assert p['legacy_fallback'] is False
