from pathlib import Path
from src.game.data.forever import build_game_ir_slice
from src.game.model import DamageEffect, PeriodicEffect, HealEffect, PeriodicHealEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.v2.generic_backend import _policy_combat_evaluation, build_partial_generic_records
from src.listener import DECISIONS_HTML
from src.version import SOFTWARE_VERSION

def test_g40_source_rank_adapter_and_registry():
    from src.class_registry import get_definition
    assert get_definition('forever','priest').proof_only
    assert build_game_ir_slice(class_key='Priest',level=9) is None
    assert build_game_ir_slice(class_key='Priest',level=21) is None
    for level,smite,pain in ((10,591,594),(14,598,594),(18,598,970),(20,598,970)):
        ir=build_game_ir_slice(class_key='priest',level=level)
        assert ir is not None
        assert ir.actions[0].id==f'smite:{smite}' and ir.actions[1].id==f'shadow_word_pain:{pain}'
        assert isinstance(ir.actions[0].effects[0],DamageEffect)
        assert isinstance(ir.actions[1].effects[0],PeriodicEffect)
        assert ir.auto_attacks[0].attack_type=='ranged'
        assert ir.auto_attacks[0].damage_source.attack_power_stat_id is None
        assert all('wowhead.com/forever/' in action.provenance[0]['url'] for action in ir.actions)
        assert not any(x['code']=='wand_channel_interruption_on_cast' for x in ir.unsupported_semantics)
        assert ir.auto_attacks[0].exclusive_with_casts
    assert isinstance(build_game_ir_slice(class_key='priest',level=14).actions[2].effects[0],PeriodicHealEffect)
    assert isinstance(build_game_ir_slice(class_key='priest',level=18).actions[3].effects[0],HealEffect)

def test_g40_wand_real_ranged_event_and_casts_not_dispatch():
    ir=build_game_ir_slice(class_key='priest',level=18)
    ev,ex,_=_policy_combat_evaluation(ir,level=18)
    assert ev is not None and ex.timeline.target_defeated
    events=ex.timeline.events
    assert any(e.kind=='AutoAttackSwing' and e.action_id=='priest:auto:wand' for e in events)
    assert any(e.kind=='Damage' and e.action_id=='priest:auto:wand' for e in events)
    assert ex.timeline.auto_attack_damage>0
    assert any(e.kind=='Damage' and str(e.action_id).startswith('smite:') for e in events)
    code=(Path('src/game/runtime/simulator.py').read_text()+Path('src/game/policy.py').read_text()).lower()
    assert 'priest' not in code and 'shadow word: pain' not in code

def test_g40_dot_and_heals_executable_through_generic_runtime():
    ir=build_game_ir_slice(class_key='priest',level=20)
    actor=ActorState.from_ir(ir.actor,ir.resources)
    runtime=CombatRuntime(actor=actor,target=TargetState.with_health('mob',1000))
    runtime.enqueue_action(ir.actions[1]);runtime.advance_to(18.)
    assert any(e.kind=='Damage' and e.action_id==ir.actions[1].id for e in runtime.trace)
    assert runtime.result().periodic_damage>0
    actor2=ActorState.from_ir(ir.actor,ir.resources)
    actor2.spend('health',150)
    r2=CombatRuntime(actor=actor2,target=TargetState.with_health('mob',1000))
    r2.enqueue_action(ir.actions[2]);r2.advance_to(15.)
    assert actor2.resource_amount('health')>float(ir.resources[0].capacity)-150
    assert any(e.kind in ('Heal','Healing') for e in r2.trace) or any('Heal' in e.kind for e in r2.trace)

def test_g40_generic_record_has_real_priest_contribution():
    r=build_partial_generic_records(class_names=('Priest',),selected_level=18)[0]
    p=r.provenance['priest_generic_decision']
    assert r.backend['id']=='generic' and r.capability['priest_native_generic_decision']
    assert not r.capability['optimization_ready']
    assert p['legacy_fallback'] is False
    assert p['wand_swing_count']>0 and p['wand_damage']>0 and p['smite_damage']>0
    assert p['source_spell_ids'][:2]==[598,970]
    assert p['unsupported']

def test_g40_listener_and_version():
    assert SOFTWARE_VERSION=='0.11.48.157'
    assert 'function genericPriestSummary(r)' in DECISIONS_HTML
    assert '${warriorHtml}${rogueHtml}${priestHtml}' in DECISIONS_HTML
    assert 'Spell resists' in DECISIONS_HTML
