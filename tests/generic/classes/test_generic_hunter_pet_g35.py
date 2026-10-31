from __future__ import annotations

from pathlib import Path
import pytest

from src.game.model import (ActorDefinition, ActorLinkModifier, ActionDefinition, DamageEffect,
                            PolicyDefinition, PolicyRuleDefinition)
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.multi_actor_policy import execute_multi_actor_priority_policies
from src.game.runtime.hunter_pet_slice import (compile_hunter_cat_slice,
        execute_hunter_pet_policy, search_hunter_pet_policy)
from src.rulesets.forever.classes.hunter.pets import modeled_damage_skills
from src.version import SOFTWARE_VERSION


def test_g35_pinned_l24_forever_cat_damage_actions_and_focus_contract():
    owner, pet, focus, links, autos, actions = compile_hunter_cat_slice()
    ranks = modeled_damage_skills('cat', 24)
    assert [(x['skill'], x['damage'], x['focus'], x['cooldown_s']) for x in ranks] == [
        ('bite', 34, 35, 10), ('claw', 19, 25, 0)]
    assert [(a.id, a.costs[0].amount, a.cooldown_s, a.gcd_s) for a in actions] == [
        ('cat:bite', 35, 10, 1.5), ('cat:claw', 25, 0, 1.5)]
    assert focus.regeneration_per_s == 5 and focus.capacity == 100
    assert pet.actor_type == 'pet' and owner.actor_type == 'player'
    assert autos[0].owner_actor_id == owner.id and autos[1].owner_actor_id == pet.id
    assert all(x.provenance for x in actions)
    assert all(x.crit_chance_stat_id == 'critical_strike_chance' for a in actions for x in a.effects)
    with pytest.raises(ValueError, match='L24-L31'):
        compile_hunter_cat_slice(level=23)


def test_g35_actor_link_inheritance_crit_and_focused_fire_apply_to_both_actors():
    owner, pet, focus, links, autos, actions = compile_hunter_cat_slice(focused_fire_rank=2)
    os = ActorState.from_ir(owner, ())
    ps = ActorState.from_ir(pet, (focus,))
    rt = CombatRuntime(actor=os, companions=(ps,), actor_links=links,
                       target=TargetState.with_health('mob', 200), auto_attacks=autos)
    assert ps.stats['attack_power'] == pytest.approx(10.0)
    assert ps.stats['critical_strike_chance'] == pytest.approx(0.1)
    assert ps.stats['damage_multiplier'] == pytest.approx(1.02)
    assert os.stats['damage_multiplier'] == pytest.approx(1.02)
    rt.enqueue_action(actions[0]);rt.advance_to(0)
    bite = [e for e in rt.trace if e.kind == 'Damage']
    assert len(bite) == 1
    assert bite[0].payload['amount'] == pytest.approx(34*1.1*1.02)
    assert bite[0].payload['actor_damage_multiplier'] == pytest.approx(1.02)
    # No companion => active-companion modifier cannot apply, even to owner.
    from src.game.runtime.actor_links import apply_actor_link_modifiers
    solo = ActorState.from_ir(owner, ())
    result = apply_actor_link_modifiers({owner.id: solo}, (links[2],))
    assert result == () and solo.stats['damage_multiplier'] == 1.0
    with pytest.raises(ValueError, match='unknown owner'):
        apply_actor_link_modifiers({owner.id: solo}, (links[0],))


def test_g35_multi_actor_event_policy_damages_same_target_and_consumes_focus():
    p = execute_hunter_pet_policy(policy_names=('bite', 'claw'))
    assert p['kill_s'] is not None
    assert 0 <= p['pet_focus_end'] < 100
    assert p['damage_by_actor']['g35:hunter'] > 0
    assert p['damage_by_actor']['g35:cat'] > 0
    assert any(e['action_id']=='cat:bite' for e in p['action_events'])
    assert any(e['action_id']=='cat:claw' for e in p['action_events'])
    assert all(e['target_id']=='g35:level24_mob' for e in p['damage_events'])
    assert any(e['actor_id']=='g35:cat' and e['action_id']=='cat:auto' for e in p['damage_events'])
    assert any(e['actor_id']=='g35:hunter' and e['action_id']=='hunter:auto_shot' for e in p['damage_events'])
    assert p['legacy_fallback'] is False


def test_g35_policy_search_is_actual_numeric_selection_not_fake_policy_legend():
    result = search_hunter_pet_policy()
    candidates = result['pet_policy_candidates']
    assert len(candidates) == 5
    assert [x['policy'] for x in candidates] == [[], ['bite'], ['claw'], ['bite','claw'], ['claw','bite']]
    assert result['selected_policy'] == ['claw']
    assert result['owner_only_kill_s'] == pytest.approx(17.5)
    assert result['owner_plus_pet_auto_kill_s'] == pytest.approx(10)
    assert result['owner_plus_pet_policy_kill_s'] == pytest.approx(7.5)
    assert result['improvement_vs_owner_only_s'] == pytest.approx(10)
    assert all(x['kill_s'] is not None for x in candidates)
    assert 'exact_pet_white_damage_baseline' in result['unsupported']
    assert 'source_pet_spells' in result['numeric_authority']
    # Two talent modifiers are also executable, not cosmetic metadata.
    buff = execute_hunter_pet_policy(policy_names=('claw',),focused_fire_rank=2,
                                     bestial_discipline_rank=2)
    assert buff['stats']['g35:hunter']['damage_multiplier'] == pytest.approx(1.02)
    assert buff['pet_focus_regen_per_s'] == pytest.approx(6.0)
    assert buff['stats']['g35:cat']['critical_strike_chance'] == pytest.approx(0.1)


def test_g35_multi_actor_policy_fails_closed_foreign_action_and_unknown_owner():
    primary = ActorState.from_ir(ActorDefinition('a','player'), ())
    pet = ActorState.from_ir(ActorDefinition('b','pet'), ())
    rt = CombatRuntime(actor=primary,companions=(pet,),target=TargetState.with_health('m',10))
    a = ActionDefinition('a:hit','hit','hit','a',(),(),0,1.5,0,
                         (DamageEffect('damage','arcane','enemy',10,10),), ())
    policy = PolicyDefinition(id='bad',label='bad',rules=(PolicyRuleDefinition('bad','a:hit'),))
    with pytest.raises(ValueError,match='not owned'):
        execute_multi_actor_priority_policies(runtime=rt,policies={'b':policy},actions=(a,))
    with pytest.raises(ValueError,match='unregistered actor'):
        execute_multi_actor_priority_policies(runtime=rt,policies={'missing':policy},actions=(a,))


def test_g35_backend_and_listener_checkpoint_g31_to_g35():
    from src.v2.generic_backend import build_partial_generic_records
    from src.listener import DECISIONS_HTML
    hunter=build_partial_generic_records(class_names=('Hunter',),selected_level=24)[0]
    p=hunter.provenance['hunter_pet_policy_probe']
    assert hunter.capability['class_pet_policy_modifiers'] is True
    assert hunter.capability['multi_actor_event_queue'] is True
    assert 'class_pet_policy_modifiers' not in hunter.unsupported_mechanics
    assert p['legacy_fallback'] is False
    assert hunter.provenance['multi_actor_runtime_probe']['numeric_authority']=='synthetic_not_forever_pet_tuning'
    assert 'genericHunterPetSummary' in DECISIONS_HTML
    assert 'hunterPetHtml' in DECISIONS_HTML
    assert 'Bounded scenario, not a complete leveling score' in DECISIONS_HTML
    assert SOFTWARE_VERSION == '0.11.48.157'
    druid=build_partial_generic_records(class_names=('Druid',),selected_level=12)[0]
    assert druid.capability['class_pet_policy_modifiers'] is False
    assert druid.provenance['hunter_pet_policy_probe'] is None
    assert 'class_pet_policy_modifiers' in druid.unsupported_mechanics


def test_g35_http_api_real_generic_hunter_pet_checkpoint(tmp_path):
    import threading
    from src.service.store import QueueStore
    from src.service.http_api import OptimizerHTTPServer
    from src.service.client import ServiceClient
    store=QueueStore(tmp_path / 'queue.sqlite3')
    server=OptimizerHTTPServer(('127.0.0.1',0),store,project_root=Path.cwd())
    worker=threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    try:
        response=ServiceClient(f'http://127.0.0.1:{server.server_address[1]}',timeout=40).decisions(
                 level=24,backend_id='generic')
        hunter=next(x for x in response['decisions'] if x['identity']['class_name'].lower()=='hunter')
        assert response['active_backend']=='generic'
        assert response['generic_routes']['publication_cache']['status']=='validated_release_snapshot'
        assert hunter['capability']['class_pet_policy_modifiers'] is True
        assert hunter['capability']['multi_actor_event_queue'] is True
        assert hunter['provenance']['hunter_pet_policy_probe']['selected_policy']==['claw']
        assert hunter['provenance']['hunter_pet_policy_probe']['owner_plus_pet_policy_kill_s']==pytest.approx(7.5)
        assert hunter['provenance']['hunter_pet_policy_probe']['legacy_fallback'] is False
        druid=next(x for x in response['decisions'] if x['identity']['class_name'].lower()=='druid')
        assert druid['capability']['class_pet_policy_modifiers'] is False
        assert druid['provenance']['hunter_pet_policy_probe'] is None
    finally:
        server.shutdown();server.server_close();worker.join(timeout=3)
