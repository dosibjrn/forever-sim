"""WF-FERAL01c2b: SQLite Thick Hide -> generic mode Armor -> incoming -> recovery.

This does not assert that policy search already schedules incoming mob attacks;
that known score gap is a release blocker, not a synthetic optimum.
"""
from __future__ import annotations

from dataclasses import replace
import shutil
import sqlite3

import pytest

from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB, load_sqlite_talents
from src.game.recovery import recover_actor_to_full
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.talent_search import enumerate_legal_talent_allocations
from src.game.talents import apply_talent_selection, validate_talent_selection


def _mode_actor(ir, *, mode='cat', defense=None):
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    # Canonical base/item Armor is not in the source actor/gear IR yet.
    # A deliberately explicit zero-Armor *probe*, never a player stat claim.
    actor.stats.setdefault('armor', 0.0)
    if defense is not None:
        actor.stats['defense'] = float(defense)
    actor.transition_mode(mode)
    return actor


def _incoming_and_food(ir):
    actor = _mode_actor(ir)
    runtime = CombatRuntime(actor=actor, target=TargetState.with_health('probe', 1000))
    attack = runtime.resolve_incoming_attack(ir.incoming_attacks[0], mitigation_rules=ir.mitigation_rules)
    assert attack['health_damage_applied'] > 0
    actor.transition_mode('caster')
    recovery = recover_actor_to_full(actor=actor, level=20, actions=(), start_time_s=0)
    return attack, recovery


def test_all_thick_hide_ranks_from_sqlite_and_tier_gates():
    ir = build_source_slice(20)
    talent = next(t for t in ir.talents if t.id == 'thick_hide')
    assert talent.max_rank == 3
    assert len(talent.ranks) == 3
    assert all({m.target_id for m in rank.modifiers} == {'cat','bear'} for rank in talent.ranks)
    assert [next(m.value for m in rank.modifiers if m.kind=='mode_armor_per_level' and m.target_id=='cat')
            for rank in talent.ranks] == [1.0,2.0,3.0]
    assert 'dire_bear_form' in talent.metadata['unavailable_mode_targets']
    with pytest.raises(ValueError, match='tier gate'):
        validate_talent_selection(ir, {'thick_hide':1}, level=20)
    validate_talent_selection(ir, {'ferocity':5,'thick_hide':2}, level=20)
    candidates,truncated = enumerate_legal_talent_allocations(_historical_234_talent_slice(ir), level=20, max_candidates=1000)
    assert not truncated and len(candidates)==417
    assert {'ferocity':5,'thick_hide':2} in candidates
    assert {'thick_hide':1} not in candidates
    blockers=ir.provenance['talent_sqlite_coverage']['blockers']
    assert any(b['talent_id']=='thick_hide' and 'incoming_attacks_not_scheduled_in_policy_recovery_score' in b['reasons'] for b in blockers)
    assert not any(b['talent_id']=='thick_hide' and 'form_armor_multiplier_not_executable' in b['reasons'] for b in blockers)


def test_source_mode_armor_changes_actual_damage_and_food_recovery():
    source = build_source_slice(20)
    baseline,_=apply_talent_selection(source, {'ferocity':5}, level=20)
    modified,applied=apply_talent_selection(source, {'ferocity':5,'thick_hide':2}, level=20)
    assert sum(row['talent_id']=='thick_hide' for row in applied.applied_modifiers)==4
    before, recovery_before = _incoming_and_food(baseline)
    after, recovery_after = _incoming_and_food(modified)
    assert before['armor'] == 48.0
    assert after['armor'] == 88.0
    assert after['health_damage_applied'] < before['health_damage_applied']
    assert recovery_after.food_s < recovery_before.food_s
    assert recovery_after.total_s < recovery_before.total_s


def test_defense_above_level_threshold_changes_armor_and_mode_exit_reverts():
    source=build_source_slice(20)
    ir,_=apply_talent_selection(source, {'ferocity':5,'thick_hide':2}, level=20)
    actor=_mode_actor(ir,defense=110)
    assert actor.stats['armor'] == pytest.approx(48+40+1.33*10)
    actor.transition_mode('caster')
    assert actor.stats.get('armor',0.0) == 48.0
    actor.transition_mode('bear')
    assert actor.stats['armor'] == pytest.approx(48+53.3)
    actor.transition_mode('caster')
    assert actor.stats.get('armor',0.0) == 48.0


def test_sqlite_rank_text_mutation_changes_mode_armor_without_code_change(tmp_path):
    clone=tmp_path/'mutated.sqlite';shutil.copyfile(DEFAULT_DB,clone)
    with sqlite3.connect(clone) as db:
        db.execute("""UPDATE talent_rank_source_facts
                      SET raw_tooltip=replace(raw_tooltip,'gain 2 additional base Armor',
                                                   'gain 4 additional base Armor')
                      WHERE class_key='druid' AND spell_id=16929 AND rank=2""")
    source=build_source_slice(20)
    modes={m.label.lower().replace(' ','_'):m.id for m in source.modes}
    inventory=load_sqlite_talents('druid',action_families={a.family_key for a in source.actions},
                                  mode_labels=modes,db_path=clone)
    ir=replace(source,talents=inventory.talents)
    applied,_=apply_talent_selection(ir,{'ferocity':5,'thick_hide':2},level=20)
    assert _mode_actor(applied).stats['armor']==128.0


def test_unknown_source_armor_wording_does_not_become_fake_modifier(tmp_path):
    clone=tmp_path/'unknown.sqlite';shutil.copyfile(DEFAULT_DB,clone)
    with sqlite3.connect(clone) as db:
        db.execute("""UPDATE talent_rank_source_facts SET raw_tooltip='Grants unmodeled armor effect.'
                      WHERE class_key='druid' AND spell_id=16929 AND rank=2""")
    source=build_source_slice(20)
    modes={m.label.lower().replace(' ','_'):m.id for m in source.modes}
    inventory=load_sqlite_talents('druid',action_families={a.family_key for a in source.actions},
                                  mode_labels=modes,db_path=clone)
    ir=replace(source,talents=inventory.talents)
    thick=next(t for t in ir.talents if t.id=='thick_hide')
    assert any(b['rank']==2 for b in thick.metadata['unsupported_rank_effects'])
    with pytest.raises(ValueError,match='unsupported talent effect'):
        apply_talent_selection(ir,{'ferocity':5,'thick_hide':2},level=20)


def test_missing_modes_do_not_become_silent_success():
    ir=build_source_slice(20)
    inv=load_sqlite_talents('druid',action_families={a.family_key for a in ir.actions},mode_labels={})
    t=next(t for t in inv.talents if t.id=='thick_hide')
    assert all(not rank.modifiers for rank in t.ranks)
    assert t.metadata['unsupported_rank_effects']


def _historical_234_talent_slice(ir):
    from dataclasses import replace
    old={'improved_wrath','ferocity','savage_fury','thick_hide','heart_of_the_wild'}
    return replace(ir,talents=tuple(t for t in ir.talents if t.id in old))
