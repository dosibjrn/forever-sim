from pathlib import Path
from src.game.data.forever import build_game_ir_slice
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.v2.generic_backend import _policy_combat_evaluation
from src.listener import DECISIONS_HTML


def test_wand_spellcast_interrupt_and_full_restart_timer():
    ir=build_game_ir_slice(class_key='priest',level=18)
    assert ir.auto_attacks[0].exclusive_with_casts
    r=CombatRuntime(actor=ActorState.from_ir(ir.actor,ir.resources),
        target=TargetState.with_health('mob',10000),auto_attacks=ir.auto_attacks[:1])
    r.enqueue_action(ir.actions[0]);r.advance_to(8.)
    damage_times=[e.time_s for e in r.trace if e.kind=='Damage' and e.action_id==ir.auto_attacks[0].id]
    assert damage_times[:2]==[4.5,6.5],damage_times
    assert any(e.kind=='AutoAttackSwingSkipped' and e.time_s==2. for e in r.trace)


def test_melee_autoattack_remains_independent_of_casts():
    ir=build_game_ir_slice(class_key='shaman',level=16)
    assert not ir.auto_attacks[0].exclusive_with_casts
    r=CombatRuntime(actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes),
        target=TargetState.with_health('mob',10000),auto_attacks=ir.auto_attacks[:1])
    r.enqueue_action(next(a for a in ir.actions if a.family_key=='lightning_bolt'));r.advance_to(6.)
    times=[e.time_s for e in r.trace if e.kind=='Damage' and e.action_id==ir.auto_attacks[0].id]
    assert times[:2]==[2.7,5.4],times


def test_rockbiter_source_ranks_and_ap_semantics():
    assert build_game_ir_slice(class_key='shaman',level=9) is None
    assert build_game_ir_slice(class_key='shaman',level=21) is None
    for level,spell,ap in ((10,8018,79.),(16,8019,118.),(20,8019,118.)):
        ir=build_game_ir_slice(class_key='shaman',level=level)
        assert ir.actions[0].id==f'rockbiter:{spell}'
        a=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
        before=a.stats['attack_power'];a.transition_mode('rockbiter')
        assert a.stats['attack_power'] == before+ap
        assert ir.actions[0].provenance[0]['url'].startswith('https://www.wowhead.com/forever/')


def test_rockbiter_changes_melee_damage_without_new_scorer():
    from src.game.runtime.simulator import expected_auto_attack_swing
    ir=build_game_ir_slice(class_key='shaman',level=16)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    before=expected_auto_attack_swing(ir.auto_attacks[0],actor=actor)['expected_damage']
    actor.transition_mode('rockbiter')
    after=expected_auto_attack_swing(ir.auto_attacks[0],actor=actor)['expected_damage']
    assert after>before
    engine=(Path('src/game/runtime/simulator.py').read_text()+Path('src/game/policy.py').read_text()).lower()
    assert 'shaman' not in engine and 'priest' not in engine


def test_shaman_hybrid_combat_real_effects():
    for level in (10,16,20):
        ir=build_game_ir_slice(class_key='shaman',level=level)
        ev,ex,_=_policy_combat_evaluation(ir,level=level)
        assert ev is not None and ex.timeline.target_defeated
        assert ex.timeline.auto_attack_damage>0 and ex.timeline.direct_damage>0
        ids=[x['action_id'] for x in ex.selected_actions]
        assert any(x.startswith('rockbiter:') for x in ids)
        assert any(x.startswith('lightning_bolt:') for x in ids)


def test_listener_new_cards_and_old_fetch_preserved():
    assert 'function genericShamanSummary(r)' in DECISIONS_HTML
    assert 'function genericPriestSummary(r)' in DECISIONS_HTML
    assert '${shamanHtml}' in DECISIONS_HTML
    assert 'Fetch next 20 tooltips' in DECISIONS_HTML


def test_g41_release_version():
    from src.version import SOFTWARE_VERSION
    assert SOFTWARE_VERSION == "0.11.48.165"
