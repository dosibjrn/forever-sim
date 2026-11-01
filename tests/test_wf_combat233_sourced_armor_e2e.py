"""WF-COMBAT233: canonical source Armor through named gear, modes, incoming hits and joint scoring."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from src.game.data.forever.armor_conversions import source_enrich_armor, load_armor_rules
from src.game.data.forever.druid import build_source_slice
from src.game.gear import apply_gear_selection, apply_stat_delta
from src.game.model.ir import ActorDefinition, GameIRSlice, ModeDefinition
from src.game.runtime import ActorState
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_mode_search import evaluate_discovered_mode_search
from src.v2.source_joint_discovery import _evaluate_caster_already_talented
from tools.ingest_armor_conversions_sqlite import ingest, DEFAULT_CAPTURE


def actor(ir):
    return ActorState.from_ir(ir.actor, ir.resources, ir.modes)


def test_source_level20_naked_has_nonzero_agility_armor_and_mitigation():
    source = build_source_slice(20)
    assert source.actor.base_stats['agility'] == 24
    assert source.actor.base_stats['armor'] == 48
    assert source.actor.metadata['canonical_armor_source_rules'][0]['source_url'].startswith('https://')
    evaluation, timeline, detail = _policy_combat_evaluation(source,level=20,schedule_incoming_attacks=True)
    assert evaluation is not None and detail['incoming_hit_count'] >= 1
    incoming = [e for e in timeline.timeline.events if e.kind == 'IncomingAttackResolved']
    assert incoming
    assert incoming[0].payload['armor'] == pytest.approx(48)


def test_equipped_item_armor_only_multiplied_in_bear_and_agi_never_multiplied():
    source=build_source_slice(20)
    geared, report=apply_gear_selection(source,aggregate_stats={'agility':5,'armor':100})
    assert report.applied_stats['armor']==100
    a=actor(geared)
    assert a.stats['armor']==pytest.approx(2*(24+5)+100)
    a.transition_mode('cat'); assert a.stats['armor']==pytest.approx(158)
    a.transition_mode('bear'); assert a.stats['armor']==pytest.approx(2*29+2.8*100)
    a.transition_mode('caster'); assert a.stats['armor']==pytest.approx(158)
    for _ in range(4):
        a.transition_mode('bear');a.transition_mode('caster')
    assert a.stats['armor']==pytest.approx(158)
    assert len(next(m for m in geared.modes if m.id=='bear').stat_modifiers)==1


def test_repeated_gear_and_agility_sensitivity_recompute_without_double_counting():
    source=build_source_slice(20)
    first,_=apply_gear_selection(source,aggregate_stats={'armor':100,'agility':5})
    second=apply_stat_delta(first,'armor',50)
    third=apply_stat_delta(second,'agility',3)
    a=actor(third)
    assert a.stats['armor']==pytest.approx(2*(24+8)+150)
    a.transition_mode('bear')
    assert a.stats['armor']==pytest.approx(2*(24+8)+2.8*150)


def test_source_coefficient_mutation_changes_runtime_without_code_changes(tmp_path):
    source=build_source_slice(20)
    clone=tmp_path/'changed.sqlite'
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    shutil.copyfile(DEFAULT_DB,clone)
    with sqlite3.connect(clone) as db:
        db.execute("UPDATE armor_conversion_source_facts SET coefficient=3 WHERE scope='actor'")
        db.execute("UPDATE armor_conversion_source_facts SET coefficient=2 WHERE scope='mode'")
    synthetic=replace(source,actor=replace(source.actor,base_stats={'agility':10},
                        metadata={'class_key':'druid','level':20}),
                      modes=(ModeDefinition(id='caster',label='Caster',initial=True),
                             ModeDefinition(id='bear',label='Bear Form')))
    ir=source_enrich_armor(synthetic,db_path=clone)
    geared,_=apply_gear_selection(ir,aggregate_stats={'agility':5,'armor':10},db_path=clone)
    a=actor(geared)
    assert a.stats['armor']==55
    a.transition_mode('bear')
    assert a.stats['armor']==75


def test_missing_canonical_actor_rule_cannot_fabricate_naked_mitigation(tmp_path):
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    clone=tmp_path/'missing.sqlite';shutil.copyfile(DEFAULT_DB,clone)
    with sqlite3.connect(clone) as db:
        db.execute("DELETE FROM armor_conversion_source_facts WHERE scope='actor'")
    source=build_source_slice(20)
    synthetic=replace(source,actor=replace(source.actor,base_stats={'agility':10},
                        metadata={'class_key':'druid','level':20}),
                      modes=(ModeDefinition(id='caster',label='Caster',initial=True),
                             ModeDefinition(id='bear',label='Bear Form')))
    enriched=source_enrich_armor(synthetic,db_path=clone)
    assert 'armor' not in enriched.actor.base_stats
    assert 'armor' not in actor(enriched).stats


def test_ingest_rejects_unknown_source_without_committing(tmp_path):
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    clone=tmp_path/'copy.sqlite';shutil.copyfile(DEFAULT_DB,clone)
    payload=json.loads(DEFAULT_CAPTURE.read_text())
    payload['entries'][0]['source_url']=''
    invalid=tmp_path/'invalid.json';invalid.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='missing source facts'):
        ingest(clone,invalid)
    with sqlite3.connect(clone) as db:
        assert db.execute('SELECT COUNT(*) FROM armor_conversion_source_facts').fetchone()[0]==2
    with sqlite3.connect(clone) as db:
        db.execute("UPDATE armor_conversion_source_facts SET coefficient=-1 WHERE scope='mode'")
    with pytest.raises(ValueError,match='invalid canonical armor source fact'):
        load_armor_rules('druid',db_path=clone)


def test_non_druid_actor_can_use_same_source_rule_with_generic_engine():
    source=build_source_slice(20)
    synthetic=replace(source,actor=ActorDefinition(id='synthetic',actor_type='player',
                          base_stats={'agility':7},metadata={'class_key':'synthetic','level':20}),
                      modes=(ModeDefinition(id='normal',label='Normal',initial=True),))
    enriched=source_enrich_armor(synthetic)
    assert enriched.actor.base_stats['armor']==14
    geared,_=apply_gear_selection(enriched,aggregate_stats={'agility':3,'armor':5})
    assert actor(geared).stats['armor']==25


def test_incoming_mitigation_changes_real_mode_policy_and_recovery():
    source=build_source_slice(20)
    low,_=apply_gear_selection(source,aggregate_stats={'armor':50,'mp5':200})
    high,_=apply_gear_selection(source,aggregate_stats={'armor':350,'mp5':200})
    low_result=evaluate_discovered_mode_search(class_key='druid',level=20,ir_slice=low,
                                max_policies_per_path=24,schedule_incoming_attacks=True)
    high_result=evaluate_discovered_mode_search(class_key='druid',level=20,ir_slice=high,
                                max_policies_per_path=24,schedule_incoming_attacks=True)
    assert low_result['evaluated_count'] and high_result['evaluated_count']
    lo=min((r for r in [low_result['winner'],*low_result['alternatives']]
            if r['path']['combat_mode']=='cat'),key=lambda r:r['seconds_per_mob'])
    hi=min((r for r in [high_result['winner'],*high_result['alternatives']]
            if r['path']['combat_mode']=='cat'),key=lambda r:r['seconds_per_mob'])
    # With the sourced Cat-entry Energy reset, Mana is the binding recovery
    # resource for this policy; Armor still saves HP, but need not change the
    # max(Health, Mana) recovery or a discrete kill-time threshold.
    assert hi['resources_after_combat']['health'] > lo['resources_after_combat']['health']
    assert hi['recovery_s'] <= lo['recovery_s']
    assert hi['seconds_per_mob'] <= lo['seconds_per_mob']


def test_joint_caster_policy_search_uses_same_actual_incoming_scorer():
    source=build_source_slice(20)
    low,_=apply_gear_selection(source,aggregate_stats={'armor':50,'mp5':200})
    high,_=apply_gear_selection(source,aggregate_stats={'armor':350,'mp5':200})
    lo=_evaluate_caster_already_talented(low,level=20,max_policies=24,schedule_incoming_attacks=True)
    hi=_evaluate_caster_already_talented(high,level=20,max_policies=24,schedule_incoming_attacks=True)
    assert hi['winner']['recovery_s'] < lo['winner']['recovery_s']
