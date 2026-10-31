"""Source-backed all-damage talent and source-family-diverse joint finalists."""
from dataclasses import replace
import json
import sqlite3
from pathlib import Path

import pytest

from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB, _parse_rank_tooltip
from src.game.talents import apply_talent_selection
from src.v2.source_staged_joint_search import _diverse_finalists


def _action(ir, family):
    return next(a for a in ir.actions if a.family_key == family)


def test_naturalist_five_sourced_ranks_and_row_gate():
    ir = build_source_slice(20)
    talent = next(t for t in ir.talents if t.id == 'naturalist')
    assert talent.max_rank == 5
    assert talent.metadata['row'] == 1
    assert talent.metadata['rank_trait_id'] is None
    for rank in talent.ranks:
        assert {(m.kind, m.target_id) for m in rank.modifiers} == {
            ('cast_time_delta_s', 'healing_touch'), ('effect_damage_pct', 'all_damage')}
        assert next(m.value for m in rank.modifiers if m.kind == 'effect_damage_pct') == pytest.approx(rank.rank / 100)
    with pytest.raises(ValueError, match='tier gate'):
        apply_talent_selection(ir, {'naturalist': 5}, level=20)
    with sqlite3.connect(DEFAULT_DB) as conn:
        assert conn.execute(
            "select count(*) from talent_rank_source_facts where class_key='druid' and spell_id=17069"
        ).fetchone()[0] == 5


def test_naturalist_generic_damage_and_healing_cast_time_no_double_count():
    ir = build_source_slice(20)
    talent = next(t for t in ir.talents if t.id == 'naturalist')
    # Isolate runtime effect without falsely declaring its row-2 allocation legal.
    source_effect_probe = replace(ir, talents=(replace(talent, metadata={**talent.metadata, 'row': 0}),))
    changed, application = apply_talent_selection(source_effect_probe, {'naturalist': 5}, level=20)
    assert _action(changed, 'healing_touch').cast_time_s == pytest.approx(
        _action(ir, 'healing_touch').cast_time_s - 0.5)
    assert _action(changed, 'healing_touch').effects == _action(ir, 'healing_touch').effects
    for family in ('wrath', 'moonfire', 'claw'):
        before = _action(ir, family).effects
        after = _action(changed, family).effects
        for e0, e1 in zip(before, after):
            if hasattr(e0, 'base_min'):
                assert e1.base_min == pytest.approx(e0.base_min * 1.05)
            if hasattr(e0, 'total_base_damage'):
                assert e1.total_base_damage == pytest.approx(e0.total_base_damage * 1.05)
            if hasattr(e0, 'weapon_damage_multiplier'):
                assert e1.weapon_damage_multiplier == pytest.approx(e0.weapon_damage_multiplier * 1.05)
    for attack_before, attack_after in zip(ir.auto_attacks, changed.auto_attacks):
        assert attack_after.damage_source.damage_multiplier == pytest.approx(
            attack_before.damage_source.damage_multiplier * 1.05)
    assert len(application.applied_modifiers) > 3


def test_compound_source_parser_fails_closed_without_cast_target():
    raw = 'Reduces the cast time of your Unknown Heal spell by 0.5 sec and increases all damage you deal by 5%.'
    modifiers, missing, reason = _parse_rank_tooltip(
        raw, action_families={'wrath'}, source={'url': 'test'})
    assert not modifiers
    assert missing == ('unknown_heal',)
    assert reason == 'source_cast_target_missing'


def test_diverse_finalists_cover_legal_families_without_legacy_hints():
    screened = [
        {'talent_id': 'none', 'allocation': {}, 'best_screening_s_per_mob': 9.,
         'screening_scores': {0: 9., 1: 12.}},
        {'talent_id': 'a', 'allocation': {'source_a': 1}, 'best_screening_s_per_mob': 10.,
         'screening_scores': {0: 10., 1: 11.}},
        {'talent_id': 'b', 'allocation': {'source_b': 1}, 'best_screening_s_per_mob': 11.,
         'screening_scores': {0: 11., 1: 8.}},
    ]
    rows, coverage = _diverse_finalists(screened, (0, 1), 3)
    assert {r['talent_id'] for r in rows} == {'none', 'a', 'b'}
    assert coverage['finalist_missing_families'] == []
    short, short_coverage = _diverse_finalists(screened, (0, 1), 2)
    assert short[0]['talent_id'] == 'none'
    assert short_coverage['finalist_missing_families'] == ['source_b']
    with pytest.raises(ValueError):
        _diverse_finalists(screened, (0,), 0)


def test_naturalist_reaches_real_combat_damage_events_not_just_ir():
    from src.v2.generic_backend import _policy_combat_evaluation
    ir = build_source_slice(20)
    talent = next(t for t in ir.talents if t.id == 'naturalist')
    probe = replace(ir, talents=(replace(talent, metadata={**talent.metadata, 'row': 0}),))
    changed, _ = apply_talent_selection(probe, {'naturalist': 5}, level=20)
    _, before, _ = _policy_combat_evaluation(probe, level=20, schedule_incoming_attacks=True)
    _, after, _ = _policy_combat_evaluation(changed, level=20, schedule_incoming_attacks=True)
    before_damage = next(float(e.payload['amount']) for e in before.timeline.events
                         if e.kind == 'Damage' and e.action_id.startswith('wrath:'))
    after_damage = next(float(e.payload['amount']) for e in after.timeline.events
                        if e.kind == 'Damage' and e.action_id.startswith('wrath:'))
    assert after_damage == pytest.approx(before_damage * 1.05)


def test_all_damage_modifier_does_not_buff_companion_auto_attacks():
    ir = build_source_slice(20)
    talent = next(t for t in ir.talents if t.id == 'naturalist')
    assert ir.auto_attacks
    pet = replace(ir.auto_attacks[0], id='synthetic_companion_auto',
                  owner_actor_id='synthetic_companion')
    probe = replace(ir, auto_attacks=ir.auto_attacks + (pet,),
                    talents=(replace(talent, metadata={**talent.metadata, 'row': 0}),))
    changed, _ = apply_talent_selection(probe, {'naturalist': 1}, level=20)
    assert changed.auto_attacks[-1].damage_source == pet.damage_source
    assert changed.auto_attacks[0].damage_source.damage_multiplier == pytest.approx(
        ir.auto_attacks[0].damage_source.damage_multiplier * 1.01)


def test_naturalist_changes_real_mode_combat_recovery_score():
    from src.v2.source_mode_search import evaluate_discovered_mode_search
    ir = build_source_slice(20)
    talent = next(t for t in ir.talents if t.id == 'naturalist')
    probe = replace(ir, talents=(replace(talent, metadata={**talent.metadata, 'row': 0}),))
    changed, _ = apply_talent_selection(probe, {'naturalist': 5}, level=20)
    base = evaluate_discovered_mode_search(class_key='druid', level=20,
        ir_slice=probe, max_policies_per_path=16, schedule_incoming_attacks=True)
    boosted = evaluate_discovered_mode_search(class_key='druid', level=20,
        ir_slice=changed, max_policies_per_path=16, schedule_incoming_attacks=True)
    assert boosted['winner']['seconds_per_mob'] < base['winner']['seconds_per_mob']
    assert boosted['winner']['auto_attack_damage'] > 0
    # This is a deliberately isolated mechanic probe, not a legal L20
    # Restoration allocation (row-1 prerequisite coverage is still missing).


def test_all_damage_modifier_does_not_buff_companion_actions():
    ir = build_source_slice(20)
    talent = next(t for t in ir.talents if t.id == 'naturalist')
    pet_action = replace(_action(ir, 'wrath'), id='synthetic_pet_spell',
                         owner_actor_id='synthetic_companion')
    probe = replace(ir, actions=ir.actions + (pet_action,),
                    talents=(replace(talent, metadata={**talent.metadata, 'row': 0}),))
    changed, _ = apply_talent_selection(probe, {'naturalist': 1}, level=20)
    assert changed.actions[-1] == pet_action

def test_restoration_row_one_source_ranks_preserved_and_furor_now_executable():
    ir = build_source_slice(20)
    by_id = {t.id: t for t in ir.talents}
    for talent_id, cap in (('furor', 5), ('natures_focus', 5)):
        talent = by_id[talent_id]
        assert talent.max_rank == cap
        assert talent.metadata['row'] == 0
        assert len(talent.ranks) == cap
    assert all(rank.modifiers for rank in by_id['furor'].ranks)
    assert all(not rank.modifiers for rank in by_id['natures_focus'].ranks)
    changed, app = apply_talent_selection(ir, {'furor': 1}, level=20)
    assert app.applied_modifiers
    assert next(m for m in changed.modes if m.id == 'cat').entry_resource_modifiers
    with pytest.raises(ValueError, match='unsupported talent effect'):
        apply_talent_selection(ir, {'natures_focus': 1}, level=20)
    with sqlite3.connect(DEFAULT_DB) as conn:
        assert conn.execute("select count(*) from talent_rank_source_facts where class_key='druid' and spell_id in (17056,17063)").fetchone()[0] == 10
