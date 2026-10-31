"""WF-FERAL01c2a: primary-source trait rank curves, generic SQLite authority."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import shutil
import sqlite3

import pytest

from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB, load_sqlite_talents
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.game.talent_search import enumerate_legal_talent_allocations
from src.v2.source_mode_search import evaluate_discovered_mode_search
from tools.ingest_talent_rank_curves_sqlite import ingest

CAPTURE = Path('data/forever/source_captures/wowhead_druid_trait_ranks_2026-10-10.json')


def test_all_indexed_druid_families_still_present_and_capture_partial():
    ir=build_source_slice(20)
    assert len(ir.talents)==52
    assert ir.provenance['talent_sqlite_coverage']['complete'] is False
    conn=sqlite3.connect(DEFAULT_DB)
    assert conn.execute('select count(distinct spell_id) from talent_rank_source_facts where class_key="druid" and trait_id>0').fetchone()[0] == 4
    assert conn.execute('select count(*) from talent_rank_source_facts where class_key="druid" and trait_id>0').fetchone()[0] == 15
    conn.close()
    assert {t.tree_key for t in ir.talents} == {'balance','feral','restoration'}


def test_ferocity_five_ranks_are_executable_in_real_ir_and_score():
    ir=build_source_slice(20)
    talent=next(t for t in ir.talents if t.id=='ferocity')
    assert talent.max_rank==5 and len(talent.ranks)==5
    assert talent.metadata['rank_cap_verified'] is True
    assert all(len(rank.modifiers)==2 for rank in talent.ranks)
    assert all('primary_wowhead_trait_capture:' in talent.metadata['rank_origin'] for _ in [0])
    changed,application=apply_talent_selection(ir,{'ferocity':5},level=20)
    old_cost={a.family_key:a.costs[0].amount for a in ir.actions if a.family_key in ('claw','swipe')}
    new_cost={a.family_key:a.costs[0].amount for a in changed.actions if a.family_key in ('claw','swipe')}
    assert old_cost=={'claw':45.0,'swipe':20.0}
    assert new_cost=={'claw':40.0,'swipe':15.0}
    assert len(application.applied_modifiers)==2
    before=evaluate_discovered_mode_search(class_key='druid',level=20,ir_slice=ir,max_policies_per_path=24)
    after=evaluate_discovered_mode_search(class_key='druid',level=20,ir_slice=changed,max_policies_per_path=24)
    assert after['winner']['seconds_per_mob'] <= before['winner']['seconds_per_mob'] + 1e-9  # cheaper Claw/Swipe need not win a Bear-dominated global mode search


def test_new_ranks_expand_legal_search_without_unlocking_tier_three():
    ir=build_source_slice(20)
    # Historical .234 five-family candidate universe remains reproducible;
    # new sourced families intentionally expand the live .235 search space.
    historical_ids={'improved_wrath','ferocity','savage_fury','thick_hide','heart_of_the_wild'}
    old_slice=replace(ir,talents=tuple(t for t in ir.talents if t.id in historical_ids))
    candidates,truncated=enumerate_legal_talent_allocations(old_slice,level=20,max_candidates=1000)
    assert not truncated
    assert len(candidates)==417
    assert {'ferocity':5} in candidates
    live,live_truncated=enumerate_legal_talent_allocations(ir,level=20,max_candidates=1000)
    assert live_truncated and len(live)==1000
    assert {'savage_fury':1} not in candidates
    assert {'savage_fury':2} not in candidates
    with pytest.raises(ValueError,match='tier gate'):
        validate_talent_selection(ir,{'savage_fury':2},level=20)


def test_heart_and_thick_have_source_rank_curves_but_are_not_fake_executable():
    ir=build_source_slice(20)
    t=next(t for t in ir.talents if t.id=='heart_of_the_wild')
    assert t.max_rank==5 and len(t.ranks)==5
    assert not t.metadata['unsupported_rank_effects']
    validate_talent_selection(ir,{'heart_of_the_wild':2},level=20)
    assert 'dire_bear_form' in t.metadata['unavailable_mode_targets']
    thick=next(t for t in ir.talents if t.id=='thick_hide')
    assert thick.max_rank==3 and len(thick.ranks)==3
    assert all(rank.modifiers for rank in thick.ranks)
    validate_talent_selection(ir,{'ferocity':5,'heart_of_the_wild':3,'thick_hide':2,'savage_fury':1},level=20)


def test_sqlite_trait_rank_mutation_changes_execution_not_code(tmp_path):
    clone=tmp_path/'modified.sqlite';shutil.copyfile(DEFAULT_DB,clone)
    conn=sqlite3.connect(clone)
    conn.execute("UPDATE talent_rank_source_facts SET raw_tooltip=replace(raw_tooltip,'by 5 Rage','by 8 Rage') WHERE class_key='druid' AND spell_id=16934 AND rank=5")
    conn.commit();conn.close()
    inv=load_sqlite_talents('druid',action_families={'claw','swipe'},db_path=clone)
    ferocity=next(t for t in inv.talents if t.id=='ferocity')
    assert {m.value for m in ferocity.ranks[-1].modifiers}=={-8.0}


def test_importer_rejects_bad_rank_data_atomically(tmp_path):
    clone=tmp_path/'modified.sqlite';shutil.copyfile(DEFAULT_DB,clone)
    capture=json.loads(CAPTURE.read_text())
    capture['capture_id']='malformed_new_batch'
    capture['entries'][0]['ranks'].pop()
    path=tmp_path/'capture.json';path.write_text(json.dumps(capture))
    conn=sqlite3.connect(clone)
    before=conn.execute('select count(*) from talent_rank_source_facts').fetchone()[0];conn.close()
    with pytest.raises(ValueError,match='incomplete'):
        ingest(clone,path)
    conn=sqlite3.connect(clone)
    assert conn.execute('select count(*) from talent_rank_source_facts').fetchone()[0]==before
    assert conn.execute('pragma integrity_check').fetchone()[0]=='ok'
    conn.close()


def test_source_capture_not_talent_whitelist_in_importer(tmp_path):
    clone=tmp_path/'modified.sqlite';shutil.copyfile(DEFAULT_DB,clone)
    payload=json.loads(CAPTURE.read_text())
    payload['capture_id']='test_unlisted_talent'
    # An arbitrary existing indexed talent can use the same generic ingestion.
    conn=sqlite3.connect(clone)
    spell_id,name=conn.execute("SELECT spell_id,name FROM spell_index WHERE class_key='druid' AND kind='talents' AND name='Vengeance'").fetchone()
    conn.close()
    payload['entries']=[{'spell_id':spell_id,'name':name,'trait_id':99999,'max_rank':1,
        'source_url':f'https://www.wowhead.com/forever/spell={spell_id}/vengeance',
        'source_authority':'test_synthetic_not_production',
        'tooltip_source_url':'https://example.org/test',
        'ranks':[{'rank':1,'raw_tooltip':'Unsupported arbitrary effect.'}]}]
    path=tmp_path/'capture.json';path.write_text(json.dumps(payload))
    result=ingest(clone,path)
    assert result['families']==1 and result['ranks']==1
    inventory=load_sqlite_talents('druid',action_families={'claw'},db_path=clone)
    talent=next(t for t in inventory.talents if t.name==name)
    assert talent.max_rank==1 and talent.metadata['unsupported_rank_effects']
