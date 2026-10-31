from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.game.model import (ActorDefinition, ActorLinkModifier, ActionDefinition,
    DamageEffect, TimedSummonDefinition)
from src.game.runtime import ActorState, CombatRuntime, TargetState, ActionNotEligibleError
from src.game.runtime.timed_summon_probe import (
    TREANT_DURATION_S, FOREVER_TREANT_SPELL, create_probe_runtime,
    execute_timed_summon_mechanics_probe)
from src.version import SOFTWARE_VERSION
from src.listener import DECISIONS_HTML


def test_g36_real_forever_timed_lifecycle_with_synthetic_damage_and_split_attribution():
    proof = execute_timed_summon_mechanics_probe()
    assert proof['status'] == 'executed'
    assert proof['source_spell'] == FOREVER_TREANT_SPELL
    assert proof['duration_s'] == TREANT_DURATION_S == 15
    assert [(x['kind'], x['time_s']) for x in proof['lifecycle']] == [
        ('SummonSpawn', 0.0), ('SummonDespawn', 15.0)]
    assert proof['damage_by_role'] == {'player': 40.0, 'pet': 54.0, 'summon': 70.0}
    assert sum(proof['damage_by_actor'].values()) == proof['with_summon_damage'] == 164
    assert proof['baseline_damage'] == 94
    assert proof['summon_added_damage'] == 70
    assert proof['summon_damage_times_s'] == [2, 4, 6, 8, 10, 12, 14]
    assert proof['numeric_authority'] == 'source_duration_and_synthetic_damage'
    assert 'player_spell_availability_unverified' in proof['source_limits']
    assert proof['legacy_fallback'] is False


def test_g36_summon_inactive_before_spawn_and_after_expiry_including_cast_cancellation():
    runtime = create_probe_runtime(with_summon=True, schedule_spawn=False)
    owner = 'g36:treant'
    action = ActionDefinition('g36:spell', 'summon_spell', 'Example spell', owner,
                              (), (), 3, 1.5, 0, (DamageEffect('damage', 'nature', 'enemy', 50, 50),), ())
    assert not runtime.actor_is_active(owner)
    with pytest.raises(ActionNotEligibleError, match='actor inactive'):
        runtime.enqueue_action(action)
    runtime.enqueue_summon('g36:force_of_nature:sample_treant', at_time_s=2)
    assert not runtime.actor_is_active(owner)
    runtime.advance_to(2)
    assert runtime.actor_is_active(owner)
    runtime.advance_to(16)
    runtime.enqueue_action(action)  # 3-second cast completes after t17 despawn
    runtime.advance_to(22)
    assert not runtime.actor_is_active(owner)
    assert not any(e.kind == 'Damage' and e.action_id == action.id and e.payload.get('applied')
                   for e in runtime.trace)
    assert any(e.kind == 'SummonEventSkipped' and e.action_id == action.id
               and e.payload['original_kind'] == 'ActionCompleted' for e in runtime.trace)
    with pytest.raises(ActionNotEligibleError, match='actor inactive'):
        runtime.enqueue_action(action)
    assert runtime.result().damage_by_role['summon'] == pytest.approx(70)


def test_g36_spawn_generation_blocks_old_pending_cast_after_resummon():
    runtime = create_probe_runtime(with_summon=True, schedule_spawn=False)
    sid = 'g36:force_of_nature:sample_treant'
    aid = 'g36:treant'
    delayed = ActionDefinition('g36:delayed', 'probe', 'Slow hit', aid,
                               (), (), 4, 0, 0, (DamageEffect('damage', 'nature', 'enemy', 100, 100),), ())
    runtime.enqueue_summon(sid)
    with pytest.raises(ValueError, match='pending'):
        runtime.enqueue_summon(sid)
    runtime.advance_to(14)
    runtime.enqueue_action(delayed)  # old completion at 18
    runtime.advance_to(15)
    runtime.enqueue_summon(sid, at_time_s=16)
    runtime.advance_to(19)
    assert runtime.actor_is_active(aid)
    assert [(e.kind, e.time_s) for e in runtime.trace if e.kind == 'SummonSpawn'] == [
        ('SummonSpawn', 0), ('SummonSpawn', 16)]
    assert not any(e.kind == 'Damage' and e.action_id == delayed.id for e in runtime.trace)
    assert any(e.kind == 'SummonEventSkipped' and e.payload['reason'] == 'stale_summon_generation'
               for e in runtime.trace)
    # First swing of the re-summoned actor happens at t18; no old swing leaks in.
    assert [e.time_s for e in runtime.trace if e.kind == 'Damage' and e.actor_id == aid
            and e.payload.get('applied')][-2:] == [14, 18]


def test_g36_fail_closed_duplicate_lifecycle_invalid_duration_and_unsupported_links():
    def actor(id): return ActorState.from_ir(ActorDefinition(id, 'pet'), ())
    owner, treant = actor('owner'), actor('treant')
    def summon(duration=15): return TimedSummonDefinition('one', 'owner', 'treant', duration)
    with pytest.raises(ValueError, match='duration'):
        CombatRuntime(actor=owner, companions=(treant,), target=TargetState.with_health('mob',100),
                      timed_summons=(summon(0),))
    with pytest.raises(ValueError, match='duplicate summon'):
        CombatRuntime(actor=owner, companions=(treant,), target=TargetState.with_health('mob',100),
                      timed_summons=(summon(), summon()))
    with pytest.raises(ValueError, match='owner and summoned actor'):
        CombatRuntime(actor=owner, target=TargetState.with_health('mob',100),
                      timed_summons=(summon(),))
    link = ActorLinkModifier('bonus', 'owner', 'owner', ('attack_power',), 'damage_multiplier', 0.1,
                             requires_actor_id='treant')
    with pytest.raises(ValueError, match='dynamic spawn/despawn'):
        CombatRuntime(actor=owner, companions=(treant,), target=TargetState.with_health('mob',100),
                      timed_summons=(summon(),), actor_links=(link,))


def test_g36_existing_permanent_pet_remains_active_and_attribution_is_generic():
    from src.game.runtime.hunter_pet_slice import execute_hunter_pet_policy
    from src.game.runtime.multi_actor_probe import execute_multi_actor_mechanics_probe
    hunter = execute_hunter_pet_policy(policy_names=('claw',))
    assert hunter['kill_s'] is not None
    legacy_two = execute_multi_actor_mechanics_probe()
    assert legacy_two['baseline_kill_s'] == 6
    assert legacy_two['companion_kill_s'] == 3
    rt = create_probe_runtime(with_summon=False)
    rt.advance_to(12)
    result = rt.result()
    assert result.actor_roles == {'g36:player': 'player', 'g36:pet': 'pet'}
    assert result.damage_by_role['summon'] == 0
    assert result.as_dict()['damage_by_actor'] == {'g36:player': 24, 'g36:pet': 36}


def test_g36_backend_and_listener_expose_timed_summon_not_fake_druid_score():
    from src.v2.generic_backend import build_partial_generic_records
    record = build_partial_generic_records(class_names=('Druid',), selected_level=12)[0]
    p = record.provenance['timed_summon_runtime_probe']
    assert record.capability['timed_summon_lifecycle'] is True
    assert record.capability['actor_damage_attribution'] is True
    assert p['damage_by_role']['summon'] == 70
    assert p['scope'] == 'timed_summon_mechanics_not_playable_druid'
    assert 'function genericTimedSummonSummary(r)' in DECISIONS_HTML
    assert 'Generic timed summon &amp; damage attribution' in DECISIONS_HTML
    assert '${eventTriggerHtml}${multiActorHtml}${timedSummonHtml}${hunterPetHtml}' in DECISIONS_HTML
    assert SOFTWARE_VERSION == '0.11.48.157'
    assert 'druid' not in Path('src/game/runtime/simulator.py').read_text().lower()


def test_g36_real_generic_http_response_includes_lifecycle_and_role_contributions(tmp_path):
    from src.service.store import QueueStore
    from src.service.http_api import OptimizerHTTPServer
    from src.service.client import ServiceClient
    store = QueueStore(tmp_path / 'queue.sqlite3')
    server = OptimizerHTTPServer(('127.0.0.1',0), store, project_root=Path.cwd())
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        reply = ServiceClient(f'http://127.0.0.1:{server.server_address[1]}', timeout=60).decisions(level=12, backend_id='generic')
        rec = next(r for r in reply['decisions'] if r['identity']['class_name'].lower()=='druid')
        assert reply['active_backend'] == 'generic'
        assert rec['capability']['timed_summon_lifecycle'] is True
        p = rec['provenance']['timed_summon_runtime_probe']
        assert p['damage_by_role'] == {'player':40.0, 'pet':54.0, 'summon':70.0}
        assert reply['generic_routes']['publication_cache']['status'] == 'validated_release_snapshot'
    finally:
        server.shutdown();server.server_close();th.join(timeout=3)


def test_g36_summon_regen_pauses_and_resummon_starts_fresh_resource_state():
    from src.game.model import ResourceDefinition
    owner = ActorState.from_ir(ActorDefinition('owner', 'player'), ())
    summon_actor = ActorState.from_ir(
        ActorDefinition('summon', 'summon'),
        (ResourceDefinition('focus', 'Focus', 'summon', initial_amount=0,
                            capacity=100, regeneration_per_s=5),))
    definition = TimedSummonDefinition('temporary', 'owner', 'summon', 2)
    rt = CombatRuntime(actor=owner, companions=(summon_actor,),
                       target=TargetState.with_health('mob', 100), timed_summons=(definition,))
    rt.enqueue_summon('temporary', at_time_s=3)
    rt.advance_to(3)
    assert summon_actor.resources['focus'] == 0  # no pre-spawn regen
    rt.advance_to(5)
    assert summon_actor.resources['focus'] == 10
    rt.advance_to(10)
    assert summon_actor.resources['focus'] == 10  # no regen after despawn
    rt.enqueue_summon('temporary', at_time_s=11)
    rt.advance_to(11)
    assert summon_actor.resources['focus'] == 0  # fresh life, no stale resources
    rt.advance_to(12)
    assert summon_actor.resources['focus'] == 5
