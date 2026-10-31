from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.model import ModeChangeEffect, PeriodicEffect, PeriodicResourceEffect
from src.game.recovery import recover_actor_to_full
from src.game.runtime import ActorState, CombatRuntime, TargetState, action_eligibility
from src.v2.generic_backend import _policy_combat_evaluation, build_partial_generic_records
from src.version import SOFTWARE_VERSION
from src.listener import DECISIONS_HTML


def _warrior(level: int):
    source = build_game_ir_slice(class_key='Warrior', level=level)
    assert source is not None
    return source


def test_g37_registered_l10_to_20_real_warrior_abilities_and_explicit_gaps():
    assert build_game_ir_slice(class_key='Warrior', level=9) is None
    assert build_game_ir_slice(class_key='Warrior', level=21) is None
    for level, rend, thunder in ((10, 'rend:6546', 'thunder_clap:461830'),
                                 (18, 'rend:6546', 'thunder_clap:461829'),
                                 (20, 'rend:6547', 'thunder_clap:461829')):
        ir = _warrior(level)
        assert [m.id for m in ir.modes] == ['battle', 'defensive']
        assert ir.modes[0].initial
        assert {x.id for x in ir.actions if x.family_key in ('rend','thunder_clap')} == {rend, thunder}
        assert any(isinstance(e, PeriodicEffect) for a in ir.actions for e in a.effects)
        assert not any(a.family_key == 'heroic_strike' for a in ir.actions)
        assert ir.resources[-1].id == 'rage'
        assert ir.resources[-1].initial_amount == 0
        assert ir.resources[-1].capacity == 100
        assert ir.auto_attacks[0].attack_type == 'melee'
        assert ir.auto_attacks[0].swing_time_s == pytest.approx(2.8)
        assert all(a.provenance for a in ir.actions)
        assert any(x['code']=='heroic_strike_on_next_swing' for x in ir.unsupported_semantics)
        assert 'scenario_proxy' in ir.actor.state_status


def test_g37_bloodrage_spends_health_and_generates_periodic_rage_without_mana():
    ir = _warrior(18)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    assert actor.current_mode_id == 'battle'
    assert 'mana' not in actor.resources
    runtime = CombatRuntime(actor=actor, target=TargetState.with_health('mob', 1000))
    br = next(a for a in ir.actions if a.family_key=='bloodrage')
    clap = next(a for a in ir.actions if a.family_key=='thunder_clap')
    assert not action_eligibility(action=clap, actor=actor).eligible
    assert any(isinstance(x, PeriodicResourceEffect) for x in br.effects)
    runtime.enqueue_action(br)
    runtime.advance_to(0)
    assert actor.resource_amount('health') == pytest.approx(ir.resources[0].capacity * 0.8)
    assert actor.resource_amount('rage') == pytest.approx(10)
    runtime.advance_to(10)
    assert actor.resource_amount('rage') == pytest.approx(20)
    assert action_eligibility(action=clap, actor=actor).eligible


def test_g37_stances_use_generic_mode_transition_and_modify_melee_damage():
    ir = _warrior(18)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    runtime = CombatRuntime(actor=actor, target=TargetState.with_health('mob',1000))
    defensive = next(a for a in ir.actions if a.family_key=='defensive_stance')
    battle = next(a for a in ir.actions if a.family_key=='battle_stance')
    assert isinstance(defensive.effects[0],ModeChangeEffect)
    runtime.enqueue_action(defensive)
    runtime.advance_to(0)
    assert actor.current_mode_id == 'defensive'
    assert actor.stats['damage_multiplier'] == pytest.approx(0.9)
    runtime.advance_to(1)
    runtime.enqueue_action(battle)
    runtime.advance_to(1)
    assert actor.current_mode_id == 'battle'
    assert actor.stats['damage_multiplier'] == pytest.approx(1.0)
    assert any(e.kind=='ModeChanged' for e in runtime.trace)


def test_g37_source_seed_executes_real_bloodrage_rend_thunder_and_white_rage():
    ir = _warrior(18)
    evaluation, execution, metadata = _policy_combat_evaluation(ir, level=18)
    assert evaluation is not None and execution is not None
    assert evaluation.seconds_per_mob == pytest.approx(20.834782608695654)
    executed = [str(x['action_id']) for x in execution.selected_actions]
    assert 'bloodrage:2687' in executed
    assert 'rend:6546' in executed
    assert 'thunder_clap:461829' in executed
    events = execution.timeline.events
    assert any(e.kind=='Damage' and e.action_id=='warrior:auto:mainhand' for e in events)
    assert any(e.kind=='Damage' and e.action_id=='rend:6546' for e in events)
    gains = [e for e in events if e.kind=='ResourceEventGain' and e.payload.get('resource_id')=='rage']
    assert len(gains) >= 1
    assert all(e.payload['source_payload'].get('auto_attack') is True for e in gains)
    assert all(e.payload['gained'] > 0 for e in gains)
    assert metadata['recovery']['provenance']['resource_profile']=='health_only_no_mana'
    assert metadata['recovery']['water_tier']=='not_applicable'


def test_g37_mana_free_generic_recovery_keeps_rage_and_heals_health():
    ir = _warrior(18)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.spend('health', 75)
    actor.restore('rage', 40)
    recovery = recover_actor_to_full(actor=actor,level=18,actions=ir.actions,start_time_s=0)
    assert recovery.total_s > 0
    assert recovery.method=='food'
    assert recovery.mana_missing_before==0
    assert recovery.water_tier=='not_applicable'
    assert recovery.provenance['resource_profile']=='health_only_no_mana'
    assert actor.resource_amount('health')==pytest.approx(ir.resources[0].capacity)
    assert actor.resource_amount('rage')==pytest.approx(40)
    assert 'mana' not in actor.resources


def test_g37_bounded_warrior_generic_policy_search_selects_execution_not_rule_labels():
    record = build_partial_generic_records(class_names=('Warrior',),selected_level=18)[0]
    p=record.provenance['warrior_generic_decision']
    assert record.backend['id']=='generic'
    assert record.capability['warrior_native_generic_decision'] is True
    assert record.capability['combat_evaluation'] is True
    assert record.capability['recovery_evaluation'] is True
    assert record.capability['auto_attack_runtime'] is True
    assert record.capability['policy_search'] is True
    assert record.capability['optimization_ready'] is False
    assert p['legacy_fallback'] is False
    assert p['selected_seconds_per_mob']==pytest.approx(19.6)
    assert p['seed_seconds_per_mob']==pytest.approx(20.834782608695654)
    assert p['improvement_s'] > 1
    assert p['selected_auto_attack_only'] is True
    assert p['selected_executed_action_ids']==[]
    assert p['selected_declared_rule_action_ids'] != p['selected_executed_action_ids']
    assert {'bloodrage:2687','rend:6546','thunder_clap:461829'}.issubset(set(p['seed_executed_action_ids']))
    assert p['selected_rage_gain_events'] > 0
    assert 'not_final_leveling_score' in p['numeric_authority']
    assert 'full_talent_and_level_route' in p['unsupported']


def test_g37_listener_and_no_warrior_class_simulator_dispatch():
    assert 'function genericWarriorSummary(r)' in DECISIONS_HTML
    assert 'selected_executed_action_ids' in DECISIONS_HTML
    assert 'Policy priorities (not necessarily executed)' in DECISIONS_HTML
    assert '${hunterPetHtml}${warriorHtml}' in DECISIONS_HTML
    assert 'not final leveling advice' in DECISIONS_HTML
    assert SOFTWARE_VERSION=='0.11.48.157'
    for path in ('src/game/runtime/simulator.py','src/game/policy.py'):
        if Path(path).exists():
            source = Path(path).read_text().lower()
            assert 'warrior' not in source


def test_g37_real_http_generic_warrior_and_preserved_druid_cache(tmp_path):
    from src.service.store import QueueStore
    from src.service.http_api import OptimizerHTTPServer
    from src.service.client import ServiceClient
    store=QueueStore(tmp_path/'queue.sqlite3')
    server=OptimizerHTTPServer(('127.0.0.1',0),store,project_root=Path.cwd())
    th=threading.Thread(target=server.serve_forever,daemon=True)
    th.start()
    try:
        reply=ServiceClient(f'http://127.0.0.1:{server.server_address[1]}',timeout=75).decisions(level=18,backend_id='generic')
        assert reply['active_backend']=='generic'
        assert reply['generic_routes']['publication_cache']['status']=='validated_release_snapshot'
        warrior=next(x for x in reply['decisions'] if x['identity']['class_name'].lower()=='warrior')
        proof=warrior['provenance']['warrior_generic_decision']
        assert proof['status']=='executed'
        assert proof['selected_auto_attack_only'] is True
        assert proof['selected_seconds_per_mob']==pytest.approx(19.6)
        assert proof['legacy_fallback'] is False
        assert warrior['capability']['warrior_native_generic_decision'] is True
        druid=next(x for x in reply['decisions'] if x['identity']['class_name'].lower()=='druid')
        assert druid['provenance'].get('warrior_generic_decision') is None
    finally:
        server.shutdown();server.server_close();th.join(timeout=3)
