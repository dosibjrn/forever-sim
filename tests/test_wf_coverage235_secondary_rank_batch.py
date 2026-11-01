"""Source-versioned secondary rank batch -> generic runtime effects."""
from __future__ import annotations
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3

import pytest
from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB, load_sqlite_talents
from src.game.talents import apply_talent_selection, validate_talent_selection
from tools.ingest_secondary_talent_ranks_sqlite import ingest

CAPTURE=Path('data/forever/source_captures/secondary_druid_rank_batch_2026-10-10.json')


def _action(ir, name):
    return next(a for a in ir.actions if a.family_key==name)


def _effect(action, cls):
    return next(e for e in action.effects if type(e).__name__==cls)


def test_all_seven_secondary_families_29_real_ranks_and_provenance():
    ir=build_source_slice(20)
    payload=json.loads(CAPTURE.read_text())
    assert len(payload['entries'])==7
    assert sum(len(e['ranks']) for e in payload['entries'])==29
    assert len(ir.talents)==52
    for entry in payload['entries']:
        t=next(t for t in ir.talents if t.metadata['sqlite_spell_id']==entry['spell_id'])
        assert t.max_rank==entry['max_rank']
        assert len(t.ranks)==entry['max_rank']
        assert all(r.modifiers for r in t.ranks)
        assert t.metadata['rank_trait_id'] is None
        assert t.metadata['rank_origin'].startswith('secondary_client_rank_capture:')
        assert t.metadata['row']==entry['tree_row']
        assert t.metadata['col']==entry['tree_col']
    assert not ir.provenance['talent_sqlite_coverage']['complete']


def test_genesis_changes_moonfire_rip_and_rejuvenation_periodic_not_direct():
    ir=build_source_slice(20)
    changed, application=apply_talent_selection(ir,{'genesis':5},level=20)
    assert len(application.applied_modifiers)>=3
    assert _effect(_action(changed,'moonfire'),'PeriodicEffect').total_base_damage == pytest.approx(
        _effect(_action(ir,'moonfire'),'PeriodicEffect').total_base_damage*1.05)
    assert _effect(_action(changed,'moonfire'),'DamageEffect').base_min == pytest.approx(
        _effect(_action(ir,'moonfire'),'DamageEffect').base_min)
    assert _effect(_action(changed,'rejuvenation'),'PeriodicHealEffect').total_base_heal == pytest.approx(
        _effect(_action(ir,'rejuvenation'),'PeriodicHealEffect').total_base_heal*1.05)
    assert _effect(_action(changed,'rip'),'ResourceScaledPeriodicEffect').total_base_damage_by_resource_amount[1] == pytest.approx(
        _effect(_action(ir,'rip'),'ResourceScaledPeriodicEffect').total_base_damage_by_resource_amount[1]*1.05)


def test_moonglow_only_damaging_mana_spells_and_tree_gate():
    ir=build_source_slice(20)
    with pytest.raises(ValueError,match='tier gate'):
        apply_talent_selection(ir,{'moonglow':3},level=20)
    changed,_=apply_talent_selection(ir,{'improved_wrath':5,'moonglow':3},level=20)
    for family in ('wrath','moonfire'):
        factor=0.375 if family=='wrath' else 0.75  # Improved Wrath 5 reduces Wrath by 50% first.
        assert _action(changed,family).costs[0].amount == pytest.approx(_action(ir,family).costs[0].amount*factor)
    for family in ('healing_touch','rejuvenation','bear_form','cat_form','claw'):
        assert _action(changed,family).costs==_action(ir,family).costs


def test_generic_secondary_rank_mutation_changes_runtime(tmp_path):
    clone=tmp_path/'db.sqlite';shutil.copyfile(DEFAULT_DB,clone)
    conn=sqlite3.connect(clone)
    conn.execute("UPDATE talent_rank_source_facts SET raw_tooltip=replace(raw_tooltip,'by 25%.','by 30%.') WHERE class_key='druid' AND spell_id=16845 AND rank=3")
    conn.commit();conn.close()
    inv=load_sqlite_talents('druid',action_families=('wrath','moonfire'),db_path=clone)
    moonglow=next(t for t in inv.talents if t.id=='moonglow')
    assert moonglow.ranks[-1].modifiers[0].value==pytest.approx(-0.30)


def test_generic_healing_shapeshift_and_school_effects_execute_on_ir():
    ir=build_source_slice(20)
    for talent_id,action_name,effect_cls,field,scale in (
        ('gift_of_nature','healing_touch','HealEffect','base_min',1.10),
        ('improved_rejuvenation','rejuvenation','PeriodicHealEffect','total_base_heal',1.15),
        ('moonfury','wrath','DamageEffect','base_min',1.10),
    ):
        talent=next(t for t in ir.talents if t.id==talent_id)
        # Isolate generic executor semantics; this is NOT a legal level-20
        # allocation, and does not claim to unlock the source tree gate.
        synthetic=replace(ir,talents=(replace(talent,metadata={**talent.metadata,'row':0}),))
        changed,_=apply_talent_selection(synthetic,{talent_id:talent.max_rank},level=20)
        before=getattr(_effect(_action(ir,action_name),effect_cls),field)
        after=getattr(_effect(_action(changed,action_name),effect_cls),field)
        assert after==pytest.approx(before*scale)
    talent=next(t for t in ir.talents if t.id=='natural_shapeshifter')
    synthetic=replace(ir,talents=(replace(talent,metadata={**talent.metadata,'row':0}),))
    changed,_=apply_talent_selection(synthetic,{'natural_shapeshifter':3},level=20)
    assert _action(changed,'bear_form').costs[0].amount==pytest.approx(_action(ir,'bear_form').costs[0].amount*0.70)
    assert _action(changed,'cat_form').costs[0].amount==pytest.approx(_action(ir,'cat_form').costs[0].amount*0.70)
    assert _action(changed,'cancel_mode').costs==()


def test_importer_rejects_bad_rank_curve_atomically(tmp_path):
    clone=tmp_path/'db.sqlite';shutil.copyfile(DEFAULT_DB,clone)
    capture=json.loads(CAPTURE.read_text())
    capture['capture_id']='invalid_mutation'
    capture['entries'][0]['ranks'].pop()
    p=tmp_path/'invalid.json';p.write_text(json.dumps(capture))
    conn=sqlite3.connect(clone)
    before=conn.execute('select count(*) from talent_rank_source_facts').fetchone()[0];conn.close()
    with pytest.raises(ValueError,match='incomplete|overwrite'):
        ingest(clone,p)
    conn=sqlite3.connect(clone)
    assert conn.execute('select count(*) from talent_rank_source_facts').fetchone()[0]==before
    assert conn.execute('pragma integrity_check').fetchone()[0]=='ok'
    conn.close()


def test_genesis_reaches_real_combat_timeline_periodic_tick():
    from src.v2.generic_backend import _policy_combat_evaluation
    ir=build_source_slice(20)
    changed,_=apply_talent_selection(ir,{'genesis':5},level=20)
    baseline_result,baseline_execution,_=_policy_combat_evaluation(
        ir,level=20,schedule_incoming_attacks=True)
    changed_result,changed_execution,_=_policy_combat_evaluation(
        changed,level=20,schedule_incoming_attacks=True)
    def moonfire_tick(execution):
        return next(float(e.payload['amount']) for e in execution.timeline.events
            if e.kind=='Damage' and e.payload.get('periodic') and
               str(e.payload.get('aura_id','')).startswith('moonfire:'))
    assert baseline_result.seconds_per_mob>0
    assert changed_result.seconds_per_mob>0
    assert moonfire_tick(changed_execution)==pytest.approx(moonfire_tick(baseline_execution)*1.05)
