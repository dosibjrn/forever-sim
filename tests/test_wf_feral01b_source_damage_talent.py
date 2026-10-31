"""WF-FERAL01b: source-derived action-damage talent, no talent whitelist."""
from dataclasses import replace
import json
import shutil
import sqlite3

import pytest

from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB, load_sqlite_talents, _parse_rank_one_tooltip
from src.game.model.ir import TalentDefinition, TalentModifier, TalentRankDefinition
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.game.talent_search import enumerate_legal_talent_allocations
from src.v2.source_mode_search import evaluate_discovered_mode_search


def test_savage_fury_rank_one_is_sourced_and_changes_both_weapon_and_direct_damage():
    ir = build_source_slice(20)
    talent = next(t for t in ir.talents if t.id == 'savage_fury')
    assert talent.metadata['sqlite_spell_id'] == 16998
    assert talent.tree_key == 'feral'
    assert talent.metadata['rank_cap_verified'] is True
    assert talent.metadata['tree_position_verified'] is False
    assert set(talent.metadata['unavailable_action_targets']) == {'rake', 'shred', 'maul'}
    assert {m.target_id for m in talent.ranks[0].modifiers} == {'claw', 'swipe'}
    assert all(m.kind == 'effect_damage_pct' and m.value == pytest.approx(0.05)
               for m in talent.ranks[0].modifiers)
    # Isolated modifier regression only: the real L20 selection is now illegal
    # until ten Feral points are invested in earlier rows. Test-only row-zero
    # override exercises the generic executor, not a real L20 build.
    ir = replace(ir, talents=tuple(replace(t, metadata={**t.metadata, 'row': 0})
                                     if t.id == 'savage_fury' else t for t in ir.talents))
    modified, application = apply_talent_selection(ir, {'savage_fury': 1}, level=20)
    original = {a.family_key: a for a in ir.actions}
    changed = {a.family_key: a for a in modified.actions}
    original_claw = original['claw'].effects[0]
    changed_claw = changed['claw'].effects[0]
    assert changed_claw.weapon_damage_multiplier == pytest.approx(original_claw.weapon_damage_multiplier * 1.05)
    assert changed_claw.flat_damage == pytest.approx(original_claw.flat_damage * 1.05)
    assert changed['swipe'].effects[0].base_min == pytest.approx(original['swipe'].effects[0].base_min * 1.05)
    assert changed['swipe'].effects[0].base_max == pytest.approx(original['swipe'].effects[0].base_max * 1.05)
    assert len(application.applied_modifiers) == 2
    assert original['claw'].effects[0].flat_damage == pytest.approx(27.0)  # immutable original


def test_source_tooltip_parser_is_not_talent_or_action_whitelist():
    mods, absent, reason = _parse_rank_one_tooltip(
        'Increases the damage caused by your Fire Bolt and Arcane Pulse abilities by 7%.',
        action_families={'fire_bolt'}, source={'provider': 'test'})
    assert reason is None and absent == ('arcane_pulse',)
    assert len(mods) == 1
    assert mods[0].target_id == 'fire_bolt'
    assert mods[0].kind == 'effect_damage_pct'
    assert mods[0].value == pytest.approx(0.07)
    assert mods[0].provenance['all_source_targets'] == ['fire_bolt', 'arcane_pulse']
    assert _parse_rank_one_tooltip('Gain power.', action_families={'fire_bolt'}, source={})[2] == 'unparsed_effect_semantics'


def test_source_sqlite_tooltip_edit_changes_runtime_effect_without_code_edit(tmp_path):
    clone = tmp_path / 'canonical.sqlite'
    shutil.copyfile(DEFAULT_DB, clone)
    con = sqlite3.connect(clone)
    # The primary Wowhead trait-rank capture is now authoritative over the
    # original listview rank-one tooltip for these sourced ranks.
    con.execute("""UPDATE talent_rank_source_facts
        SET raw_tooltip=replace(raw_tooltip,'by 5%.','by 9%.')
        WHERE class_key='druid' AND spell_id=16998 AND rank=1""")
    con.commit(); con.close()
    modified = load_sqlite_talents('druid', action_families={'claw', 'swipe'}, db_path=clone)
    talent = next(t for t in modified.talents if t.id == 'savage_fury')
    assert all(m.value == pytest.approx(0.09) for m in talent.ranks[0].modifiers)


def test_rank_two_and_old_full_feral_allocation_still_blocked():
    ir = build_source_slice(20)
    with pytest.raises(ValueError, match='tier gate'):
        validate_talent_selection(ir, {'savage_fury': 2}, level=20)
    validate_talent_selection(ir, {'ferocity': 5, 'heart_of_the_wild': 3,
                                   'thick_hide': 2, 'savage_fury': 1}, level=20)
    allocations, truncated = enumerate_legal_talent_allocations(_historical_234_talent_slice(ir), level=20, max_candidates=500)
    assert not truncated
    assert {'savage_fury': 1} not in allocations
    assert {'savage_fury': 1, 'ferocity': 1} not in allocations
    assert len(allocations) == 417


def test_savage_fury_changes_real_combat_recovery_score_but_not_claimed_winner():
    ir = build_source_slice(20)
    # Hypothetical effect isolation; not a legal L20 talent allocation.
    ir = replace(ir, talents=tuple(replace(t, metadata={**t.metadata, 'row': 0})
                                     if t.id == 'savage_fury' else t for t in ir.talents))
    changed, _ = apply_talent_selection(ir, {'savage_fury': 1}, level=20)
    baseline = evaluate_discovered_mode_search(class_key='druid', level=20, ir_slice=ir,
                                               max_policies_per_path=24)
    enhanced = evaluate_discovered_mode_search(class_key='druid', level=20, ir_slice=changed,
                                               max_policies_per_path=24)
    base_scores = [baseline['winner']['seconds_per_mob'], *[a['seconds_per_mob'] for a in baseline['alternatives']]]
    new_scores = [enhanced['winner']['seconds_per_mob'], *[a['seconds_per_mob'] for a in enhanced['alternatives']]]
    # Different damage can change which bounded policies remain executable;
    # the number of survivors is not a fixed source fact. Nor is total
    # combat+recovery monotone in one ability's damage at discrete kill gates.
    assert base_scores and new_scores
    assert (len(base_scores) != len(new_scores) or
            any(abs(b-a) > .001 for b,a in zip(base_scores,new_scores)))
    assert enhanced['winner']['seconds_per_mob'] > 0


def test_generic_damage_modifier_executes_for_non_druid_direct_damage():
    from src.game.data.forever.mage import build_source_slice as mage_slice
    mage = mage_slice(20)
    damaging = next(a for a in mage.actions if any(type(e).__name__ == 'DamageEffect' for e in a.effects))
    synthetic = TalentDefinition(id='test_damage', name='Test Damage', tree_key='test', max_rank=1,
        ranks=(TalentRankDefinition(rank=1, modifiers=(TalentModifier(kind='effect_damage_pct',
            target_type='action_family', target_id=damaging.family_key, value=0.07),)),))
    ir = replace(mage, talents=(synthetic,))
    result, _ = apply_talent_selection(ir, {'test_damage': 1}, level=20)
    old = next(a for a in ir.actions if a.id == damaging.id)
    new = next(a for a in result.actions if a.id == damaging.id)
    old_effect = next(e for e in old.effects if type(e).__name__ == 'DamageEffect')
    new_effect = next(e for e in new.effects if type(e).__name__ == 'DamageEffect')
    assert new_effect.base_min == pytest.approx(old_effect.base_min * 1.07)


def test_generic_damage_modifier_refuses_non_damage_target_instead_of_noop():
    from src.game.data.forever.mage import build_source_slice as mage_slice
    mage = mage_slice(20)
    nondamaging = next(a for a in mage.actions if not any(type(e).__name__ in
        {'DamageEffect', 'WeaponDamageEffect', 'PeriodicEffect', 'ResourceScaledDirectDamageEffect'}
        for e in a.effects))
    synthetic = TalentDefinition(id='test_bad_target', name='Test Bad Target', tree_key='test', max_rank=1,
        ranks=(TalentRankDefinition(rank=1, modifiers=(TalentModifier(kind='effect_damage_pct',
            target_type='action_family', target_id=nondamaging.family_key, value=0.07),)),))
    with pytest.raises(ValueError, match='no supported damage effect'):
        apply_talent_selection(replace(mage, talents=(synthetic,)), {'test_bad_target': 1}, level=20)


def _historical_234_talent_slice(ir):
    from dataclasses import replace
    old={'improved_wrath','ferocity','savage_fury','thick_hide','heart_of_the_wild'}
    return replace(ir,talents=tuple(t for t in ir.talents if t.id in old))
