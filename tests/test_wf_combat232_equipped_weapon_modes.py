"""WF-COMBAT232: official sourced equipped-weapon DPS in generic auto+action execution."""
from dataclasses import replace
import shutil
import sqlite3

import pytest

from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.gear import select_named_gear
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.gear import apply_gear_selection, apply_stat_delta, executable_gear_stats
from src.game.model import ActorDefinition, ModeDefinition
from src.game.runtime import ActorState, expected_auto_attack_swing, expected_weapon_damage
from src.v2.source_mode_search import evaluate_discovered_mode_search


def _mode_actor(ir, mode):
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.transition_mode(mode)
    return actor


def _weapon_effect(ir, family):
    return next(effect for action in ir.actions if action.family_key == family
                for effect in action.effects if effect.effect_type == 'weapon_damage')


def test_source_equipped_weapon_replaces_auto_and_action_without_double_counting():
    source = build_source_slice(20)
    new, report = apply_gear_selection(source, aggregate_stats={'weapon_dps': 28.5})
    assert report.applied_stats == {'weapon_dps': 28.5}
    assert not report.unsupported_stats
    assert 'weapon_dps' not in new.actor.base_stats  # not AP, not an additive actor stat
    assert len(new.provenance['equipped_weapon_dps_application']) == 2
    for mode in ('cat', 'bear'):
        original = next(a for a in source.auto_attacks if a.required_mode_id == mode)
        changed = next(a for a in new.auto_attacks if a.required_mode_id == mode)
        assert changed.damage_source.flat_dps == pytest.approx(28.5)
        assert changed.damage_source.attack_power_stat_id == original.damage_source.attack_power_stat_id
        delta = expected_auto_attack_swing(changed, actor=_mode_actor(new, mode))['expected_damage'] - \
                expected_auto_attack_swing(original, actor=_mode_actor(source, mode))['expected_damage']
        assert delta == pytest.approx((28.5 - original.damage_source.flat_dps) * changed.swing_time_s)
    for family, mode in [('claw', 'cat')]:
        old, fresh = _weapon_effect(source, family), _weapon_effect(new, family)
        assert fresh.damage_source.flat_dps == pytest.approx(28.5)
        old_damage = expected_weapon_damage(old, actor=_mode_actor(source, mode))['expected_damage']
        new_damage = expected_weapon_damage(fresh, actor=_mode_actor(new, mode))['expected_damage']
        assert new_damage > old_damage
    # The L20 Bear weapon ability is not yet trained; test it at a legal higher level.
    later = build_source_slice(30)
    later_equipped, _ = apply_gear_selection(later, aggregate_stats={'weapon_dps': 28.5})
    old_bite, new_bite = _weapon_effect(later, 'primal_bite'), _weapon_effect(later_equipped, 'primal_bite')
    assert new_bite.damage_source.flat_dps == pytest.approx(28.5)
    assert expected_weapon_damage(new_bite, actor=_mode_actor(later_equipped, 'bear'))['expected_damage'] != \
           expected_weapon_damage(old_bite, actor=_mode_actor(later, 'bear'))['expected_damage']
    assert any(p['source_url'].startswith('https://worldofwarcraft.blizzard.com/')
               for a in new.auto_attacks for p in a.provenance if p.get('stage') == 'equipped_weapon_dps_replacement')


def test_real_named_equipped_weapon_changes_sourced_policy_score():
    source = build_source_slice(20)
    gear = select_named_gear(class_key='druid', level=20, role='druid_feral',
                             stat_weights={'weapon_dps': 1})
    assert gear.aggregate_stats['weapon_dps'] > 0
    applied, report = apply_gear_selection(source, aggregate_stats=gear.aggregate_stats,
                                           selected_items=tuple(gear.slots.values()))
    assert report.applied_stats['weapon_dps'] == gear.aggregate_stats['weapon_dps']
    # Isolate the real gear weapon contribution: same actor, only the weapon changes.
    baseline, _ = apply_gear_selection(source, aggregate_stats={'weapon_dps': 8.0})
    high, _ = apply_gear_selection(source, aggregate_stats={'weapon_dps': 28.0})
    low_result = evaluate_discovered_mode_search(class_key='druid', level=20, ir_slice=baseline,
                                                 max_policies_per_path=24)
    high_result = evaluate_discovered_mode_search(class_key='druid', level=20, ir_slice=high,
                                                  max_policies_per_path=24)
    assert high_result['winner']['seconds_per_mob'] < low_result['winner']['seconds_per_mob']
    assert high_result['winner']['auto_attack_damage'] > low_result['winner']['auto_attack_damage']


def test_source_removed_is_explicit_unsupported_and_never_replaces(tmp_path):
    source = build_source_slice(20)
    clone = tmp_path / 'missing.sqlite'
    shutil.copyfile(DEFAULT_DB, clone)
    with sqlite3.connect(clone) as db:
        db.execute("DELETE FROM equipped_weapon_mode_source_facts WHERE class_key='druid'")
    assert 'weapon_dps' not in executable_gear_stats(source, db_path=clone)
    no_source, report = apply_gear_selection(source, aggregate_stats={'weapon_dps': 28}, db_path=clone)
    assert report.unsupported_stats == {'weapon_dps': 28}
    assert no_source.auto_attacks == source.auto_attacks
    assert _weapon_effect(no_source, 'claw') == _weapon_effect(source, 'claw')
    with pytest.raises(ValueError, match='absolute equipped-weapon replacement'):
        apply_stat_delta(source, 'weapon_dps', 1)


def test_invalid_source_fact_fails_closed_and_missing_mode_cannot_silently_pass(tmp_path):
    source = build_source_slice(20)
    clone = tmp_path / 'invalid.sqlite'
    shutil.copyfile(DEFAULT_DB, clone)
    with sqlite3.connect(clone) as db:
        db.execute("UPDATE equipped_weapon_mode_source_facts SET source_url='' WHERE class_key='druid'")
    with pytest.raises(ValueError, match='invalid canonical equipped weapon mode source fact'):
        apply_gear_selection(source, aggregate_stats={'weapon_dps': 28}, db_path=clone)
    with sqlite3.connect(clone) as db:
        db.execute("UPDATE equipped_weapon_mode_source_facts SET source_url='https://worldofwarcraft.blizzard.com/en-us/news/24301515/' WHERE class_key='druid'")
        db.execute("UPDATE equipped_weapon_mode_source_facts SET damage_source_kind='wrong_kind' WHERE mode_label='Bear Form'")
    with pytest.raises(ValueError, match='no executable damage source: bear'):
        apply_gear_selection(source, aggregate_stats={'weapon_dps': 28}, db_path=clone)


def test_synthetic_class_uses_same_canonical_mode_rule_without_class_branch(tmp_path):
    source = build_source_slice(20)
    clone = tmp_path / 'synthetic.sqlite'
    shutil.copyfile(DEFAULT_DB, clone)
    with sqlite3.connect(clone) as db:
        db.execute('''INSERT INTO equipped_weapon_mode_source_facts
            SELECT 'synthetic','Wolf Form','weapon_dps',damage_source_kind,operation,applies_to,
                   'synthetic_test',source_url,source_date,evidence,'test' FROM equipped_weapon_mode_source_facts
            WHERE class_key='druid' AND mode_label='Cat Form' ''')
    cat_attack = next(a for a in source.auto_attacks if a.required_mode_id == 'cat')
    synthetic = replace(source,
        actor=replace(source.actor, metadata={**source.actor.metadata,'class_key':'synthetic'}),
        modes=(ModeDefinition(id='normal',label='Normal',initial=True),
               ModeDefinition(id='wolf',label='Wolf Form')),
        auto_attacks=(replace(cat_attack,required_mode_id='wolf'),), actions=())
    changed, report = apply_gear_selection(synthetic, aggregate_stats={'weapon_dps': 41}, db_path=clone)
    assert report.applied_stats['weapon_dps'] == 41
    assert changed.auto_attacks[0].damage_source.flat_dps == 41
    assert changed.auto_attacks[0].required_mode_id == 'wolf'


def test_invalid_nonpositive_or_nonfinite_weapon_dps_is_rejected():
    source = build_source_slice(20)
    for value in (-3, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            apply_gear_selection(source, aggregate_stats={'weapon_dps': value})
