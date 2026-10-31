"""WF-FERAL01c2c: full source-rank Heart stats through generic runtime.

The level-20 talent is mechanically executable, but this does NOT verify
current Forever tree legality, missing Dire Bear, gear stamina/strength, or
incoming-attacks in ordinary policy scoring.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import sqlite3

import pytest

from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB, load_sqlite_talents
from src.game.gear import apply_gear_selection
from src.game.runtime import ActorState, expected_auto_attack_swing
from src.game.talent_search import enumerate_legal_talent_allocations
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.v2.source_mode_search import evaluate_discovered_mode_search
from tools.ingest_stat_conversions_sqlite import ingest


def _actor(ir):
    return ActorState.from_ir(ir.actor, ir.resources, ir.modes)


def _inventory_from_clone(ir, db_path):
    return load_sqlite_talents('druid',action_families={a.family_key for a in ir.actions},
        mode_labels={m.label.lower().replace(' ','_'):m.id for m in ir.modes},db_path=db_path)


def test_all_heart_ranks_sqlite_sourced_and_all_active_mode_effects_executable():
    ir=build_source_slice(20)
    heart=next(t for t in ir.talents if t.id=='heart_of_the_wild')
    assert heart.max_rank == 5
    assert [len(rank.modifiers) for rank in heart.ranks] == [5]*5
    assert [next(m.value for m in rank.modifiers if m.kind=='actor_stat_pct')
            for rank in heart.ranks] == pytest.approx([.02,.04,.06,.08,.10])
    assert 'dire_bear_form' in heart.metadata['unavailable_mode_targets']
    assert not heart.metadata['unsupported_rank_effects']
    assert any('dire_bear_form' in b.get('missing_mode_targets',[])
               for b in ir.provenance['talent_sqlite_coverage']['blockers'])
    validate_talent_selection(ir, {'heart_of_the_wild':3}, level=20)
    historical={'ferocity':5,'heart_of_the_wild':3,'thick_hide':2,'savage_fury':1}
    validate_talent_selection(ir,historical,level=20)
    candidates,truncated=enumerate_legal_talent_allocations(_historical_234_talent_slice(ir),level=20)
    assert not truncated and len(candidates)==417
    assert historical in candidates
    assert ir.provenance['talent_sqlite_coverage']['complete'] is False


def test_global_intellect_real_mana_cat_ap_and_bear_health_and_mode_reversibility():
    source=build_source_slice(20)
    changed,application=apply_talent_selection(source,{'heart_of_the_wild':3},level=20)
    assert len(application.applied_modifiers)==5
    assert changed.actor.base_stats['intellect']==pytest.approx(36*1.06)
    assert changed.resources[0].capacity==pytest.approx(614+36*.06*15)
    actor=_actor(changed)
    baseline=_actor(source)
    assert actor.resource_amount('mana') > baseline.resource_amount('mana')
    assert actor.stats['strength']==30
    actor.transition_mode('cat')
    baseline.transition_mode('cat')
    assert actor.stats['strength']==pytest.approx(30*1.06)
    assert actor.stats['attack_power']-baseline.stats['attack_power']==pytest.approx(30*.06*2)
    attack=next(a for a in changed.auto_attacks if a.required_mode_id=='cat')
    assert expected_auto_attack_swing(attack,actor=actor)['expected_damage'] > expected_auto_attack_swing(attack,actor=baseline)['expected_damage']
    actor.transition_mode('bear')
    assert actor.stats['strength']==30
    assert actor.stats['stamina']==pytest.approx(38*1.12)
    assert actor.resource_capacity['health']==pytest.approx(500+38*.12*10)
    assert actor.resource_amount('health')==pytest.approx(actor.resource_capacity['health'])
    actor.deplete('health',100)
    ratio=actor.resource_amount('health')/actor.resource_capacity['health']
    actor.transition_mode('caster')
    assert actor.resource_capacity['health']==pytest.approx(500)
    assert actor.resource_amount('health')==pytest.approx(500*ratio)
    assert actor.stats['stamina']==38
    assert actor.stats.get('attack_power',0)==0
    for _ in range(3):
        actor.transition_mode('bear');actor.transition_mode('caster')
    assert actor.resource_capacity['health']==pytest.approx(500)
    assert actor.resource_amount('health')==pytest.approx(500*ratio)


def test_heart_intellect_scales_gear_when_gear_applied_before_talents():
    source=build_source_slice(20)
    geared,_=apply_gear_selection(source,aggregate_stats={'intellect':10})
    talented,_=apply_talent_selection(geared,{'heart_of_the_wild':3},level=20)
    assert talented.actor.base_stats['intellect']==pytest.approx((36+10)*1.06)
    assert talented.resources[0].capacity==pytest.approx(354+20+((36+10)*1.06-20)*15)


def test_sqlite_mutation_changes_all_three_effects_without_production_code_change(tmp_path):
    clone=tmp_path/'mutated.sqlite';shutil.copyfile(DEFAULT_DB,clone)
    with sqlite3.connect(clone) as db:
        db.execute("""UPDATE talent_rank_source_facts
            SET raw_tooltip=replace(raw_tooltip,'Intellect by 6%','Intellect by 9%')
            WHERE class_key='druid' AND spell_id=17003 AND rank=3""")
        db.execute("""UPDATE stat_conversion_source_facts SET coefficient=3.0
            WHERE class_key='druid' AND source_stat='strength'""")
        db.execute("""UPDATE stat_conversion_source_facts SET coefficient=11.0
            WHERE class_key='druid' AND source_stat='stamina'""")
    source=build_source_slice(20)
    inv=_inventory_from_clone(source,clone)
    changed,_=apply_talent_selection(replace(source,talents=inv.talents),{'heart_of_the_wild':3},level=20)
    assert changed.actor.base_stats['intellect']==pytest.approx(36*1.09)
    actor=_actor(changed);actor.transition_mode('cat')
    assert actor.stats['attack_power']==pytest.approx(36+30*.06*3)
    actor.transition_mode('bear')
    assert actor.resource_capacity['health']==pytest.approx(500+38*.12*11)


def test_missing_stat_conversion_fails_closed_instead_of_stat_only_noop(tmp_path):
    clone=tmp_path/'missing.sqlite';shutil.copyfile(DEFAULT_DB,clone)
    with sqlite3.connect(clone) as db:
        db.execute("DELETE FROM stat_conversion_source_facts WHERE class_key='druid' AND source_stat='strength'")
    source=build_source_slice(20)
    inv=_inventory_from_clone(source,clone)
    heart=next(t for t in inv.talents if t.id=='heart_of_the_wild')
    assert all(not rank.modifiers for rank in heart.ranks)
    assert all(b['reason']=='source_stat_conversion_missing' for b in heart.metadata['unsupported_rank_effects'])
    with pytest.raises(ValueError,match='unsupported talent effect'):
        apply_talent_selection(replace(source,talents=inv.talents),{'heart_of_the_wild':3},level=20)


def test_source_ingestion_rejects_missing_authority_without_modifying_sqlite(tmp_path):
    clone=tmp_path/'clone.sqlite';shutil.copyfile(DEFAULT_DB,clone)
    import json
    capture=json.loads(Path('data/forever/source_captures/forever_inherited_stat_conversions_2026-10-10.json').read_text())
    capture['entries'][0]['source_url']=''
    path=tmp_path/'bad.json';path.write_text(json.dumps(capture))
    with pytest.raises(ValueError,match='missing authority'):
        ingest(clone,path)
    with sqlite3.connect(clone) as db:
        assert db.execute('select count(*) from stat_conversion_source_facts').fetchone()[0]==2
        assert db.execute('pragma integrity_check').fetchone()[0]=='ok'


def test_real_source_mode_policy_reports_heart_ap_damage_without_claiming_optimum():
    source=build_source_slice(20)
    modified,_=apply_talent_selection(source,{'heart_of_the_wild':3},level=20)
    before=evaluate_discovered_mode_search(class_key='druid',level=20,ir_slice=source,max_policies_per_path=24)
    after=evaluate_discovered_mode_search(class_key='druid',level=20,ir_slice=modified,max_policies_per_path=24)
    def first_cat(result):
        return next(r for r in [result['winner'],*result['alternatives']] if r['path']['combat_mode']=='cat')
    assert first_cat(after)['auto_attack_damage'] > first_cat(before)['auto_attack_damage']
    # Discrete swing counts mean damage can improve without changing time/mob.
    assert after['winner']['seconds_per_mob'] <= before['winner']['seconds_per_mob']
    assert not after['optimization_ready']


def test_mode_capacity_modifier_is_generic_for_non_druid_actor():
    from src.game.model import (ActorDefinition, ModeDefinition,
                                ModeResourceCapacityModifier, ResourceDefinition)
    actor_def=ActorDefinition(id='generic',actor_type='generic',base_stats={'resolve':12})
    resources=(ResourceDefinition(id='barrier',name='Barrier',owner_actor_id='generic',
                initial_amount=100,capacity=100),)
    modes=(ModeDefinition(id='normal',label='Normal',initial=True),
           ModeDefinition(id='boost',label='Boost',resource_capacity_modifiers=(
               ModeResourceCapacityModifier(resource_id='barrier',kind='add_stat_scaled',
                                            source_stat='resolve',value=2.0),)))
    actor=ActorState.from_ir(actor_def,resources,modes)
    actor.transition_mode('boost')
    assert actor.resource_capacity['barrier']==124
    assert actor.resource_amount('barrier')==124
    actor.deplete('barrier',62)
    actor.transition_mode('normal')
    assert actor.resource_capacity['barrier']==100
    assert actor.resource_amount('barrier')==50
    assert actor.as_dict()['mode_resource_capacity_adjustments']=={}


def test_held_out_legacy_feral_replay_is_actually_scored_on_same_five_gears():
    from tools.wf_feral01c2c_replay import run
    result=run()
    assert len(result['results'])==5
    assert {r['best_in_this_two_build_comparison'] for r in result['results']} == {
        'old_feral_11_points','improved_wrath_5'}
    assert result['best_over_five_gears_and_two_builds']['build']=='improved_wrath_5'
    assert result['source_coverage_complete'] is False
    assert 'not an independent 417-allocation search' in result['blocking_gaps']


def _historical_234_talent_slice(ir):
    from dataclasses import replace
    old={'improved_wrath','ferocity','savage_fury','thick_hide','heart_of_the_wild'}
    return replace(ir,talents=tuple(t for t in ir.talents if t.id in old))
