"""WF-FERAL01c: SQLite-sourced tier gates change actual candidate legality."""
from dataclasses import replace
import json
import shutil
import sqlite3

import pytest

from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB, load_sqlite_talents
from src.game.model.ir import TalentDefinition, TalentModifier, TalentRankDefinition
from src.game.talents import validate_talent_selection
from src.game.talent_search import enumerate_legal_talent_allocations
from tools.ingest_talent_tree_rows_sqlite import ingest

CAPTURE = 'data/forever/source_captures/wowhead_druid_tree_rows_2026-10-10.json'


def test_actual_source_row_gates_change_level20_candidate_set():
    ir = build_source_slice(20)
    assert len(ir.talents) == 52
    assert sum(t.metadata['tree_row_known'] for t in ir.talents) == 33  # includes 11 source-ranked low-tier families, seven newly positioned
    assert sum(t.metadata['tree_row_explicit_announcement'] for t in ir.talents) == 14
    by_id = {t.id:t for t in ir.talents}
    assert by_id['savage_fury'].metadata['row'] == 2
    assert by_id['savage_fury'].metadata['tree_row_explicit_announcement'] is True
    assert by_id['heart_of_the_wild'].metadata['row'] == 0
    assert by_id['thick_hide'].metadata['row'] == 1
    assert by_id['thick_hide'].metadata['tree_row_verified'] is False
    assert by_id['ferocity'].metadata['row'] == 0
    with pytest.raises(ValueError, match='tier gate not met.*10'):
        validate_talent_selection(ir, {'savage_fury':1}, level=20)
    with pytest.raises(ValueError, match='tier gate'):
        validate_talent_selection(ir, {'thick_hide':1}, level=20)
    # The tier gate itself is separately exercised with executable synthetic ranks.
    selections, truncated = enumerate_legal_talent_allocations(_historical_234_talent_slice(ir),level=20)
    assert not truncated and len(selections) == 417
    assert {'savage_fury':1} not in selections
    assert any('savage_fury' in row for row in selections)  # 10 earlier Feral points now executable
    assert {'ferocity':1} in selections
    assert {'improved_wrath':5} in selections
    assert ir.provenance['talent_sqlite_coverage']['complete'] is False


def test_sqlite_row_edit_changes_actual_search_without_code_change(tmp_path):
    clone=tmp_path/'canonical.sqlite'
    shutil.copyfile(DEFAULT_DB,clone)
    with sqlite3.connect(clone) as c:
        c.execute("UPDATE talent_tree_row_facts SET tree_row=0 WHERE class_key='druid' AND spell_id=16998")
    original=build_source_slice(20)
    # Use same real production IR except source-derived talents from cloned DB.
    from src.game.data.forever.sqlite_talents import load_sqlite_talents
    cloned=load_sqlite_talents('druid',action_families={a.family_key for a in original.actions},
                                   mode_labels={m.label.lower().replace(' ', '_'):m.id for m in original.modes},db_path=clone)
    modified=replace(original,talents=cloned.talents)
    before,_=enumerate_legal_talent_allocations(_historical_234_talent_slice(original),level=20,max_candidates=2000)
    after,_=enumerate_legal_talent_allocations(_historical_234_talent_slice(modified),level=20,max_candidates=2000)
    assert len(before)==417 and len(after)==1194
    assert {'savage_fury':1} in after


def test_generic_tier_gate_uses_only_earlier_same_tree_points():
    def t(name,tree,row,cap):
        return TalentDefinition(id=name,name=name,tree_key=tree,max_rank=cap,
            ranks=tuple(TalentRankDefinition(rank=i,modifiers=(TalentModifier(
                kind='resource_cost_flat',target_type='action_family',target_id='some_action',value=-i),))
                for i in range(1,cap+1)),metadata={'row':row})
    ir=replace(build_source_slice(20),talents=(t('low','a',0,5),t('same','a',1,5),
                                              t('deep','a',2,1),t('other','b',0,5)))
    with pytest.raises(ValueError,match='tier gate not met'):
        validate_talent_selection(ir,{'low':5,'other':5,'deep':1},level=20)
    with pytest.raises(ValueError,match='tier gate not met'):
        validate_talent_selection(ir,{'low':5,'same':4,'deep':1},level=20)
    validate_talent_selection(ir,{'low':5,'same':5,'deep':1},level=20)
    with pytest.raises(ValueError,match='level budget'):
        validate_talent_selection(ir,{'low':5,'same':5,'deep':1,'other':1},level=20)


def test_importer_uses_source_names_not_hardcoded_ids_and_refuses_missing(tmp_path):
    clone=tmp_path/'canonical.sqlite'
    shutil.copyfile(DEFAULT_DB,clone)
    capture=json.load(open(CAPTURE))
    capture['facts']=capture['facts'][:1]
    capture['facts'][0]['name']='Not a canonical talent'
    bad=tmp_path/'bad.json';bad.write_text(json.dumps(capture))
    with pytest.raises(ValueError,match='absent from canonical SQLite'):
        ingest(clone,bad)
    with sqlite3.connect(clone) as c:
        assert c.execute('select count(*) from talent_tree_row_facts').fetchone()[0]==33  # source-backed low-tier position coverage expanded


def test_importer_rejects_downgrade_of_primary_position(tmp_path):
    clone=tmp_path/'canonical.sqlite';shutil.copyfile(DEFAULT_DB,clone)
    capture=json.load(open(CAPTURE))
    capture['facts']=[dict(capture['facts'][0],authority='secondary_provisional_row',
                           source_url='https://wowforever.gg/en/talents/druid/')]
    bad=tmp_path/'bad.json';bad.write_text(json.dumps(capture))
    with pytest.raises(ValueError,match='cannot downgrade'):
        ingest(clone,bad)


def test_historical_11_point_feral_row_layout_consistent_but_not_fully_verified():
    ir = build_source_slice(20)
    historical = {'ferocity':5,'heart_of_the_wild':3,'thick_hide':2,'savage_fury':1}
    validate_talent_selection(ir,historical,level=20)
    # Structurally legal under *provisional* row evidence, not source-verified.

    # Isolate only the *structural* row check using test-only dummy rank effects;
    # this is NOT an executable production replay or verification of rank caps.
    synthetic=[]
    for t in ir.talents:
        if t.id in historical:
            synthetic.append(replace(t,max_rank=historical[t.id],
                ranks=tuple(TalentRankDefinition(rank=r,modifiers=(TalentModifier(
                    kind='resource_cost_flat',target_type='action_family',
                    target_id='test_only',value=-r),))
                    for r in range(1,historical[t.id]+1))))
        else:
            synthetic.append(t)
    validate_talent_selection(replace(ir,talents=tuple(synthetic)),historical,level=20)
    assert sum(historical.values())==11
    assert all(next(t for t in ir.talents if t.id==k).metadata['row'] is not None
               for k in historical)
    assert not all(next(t for t in ir.talents if t.id==k).metadata['tree_row_verified']
                   for k in historical)


def test_tier_point_rule_is_from_sqlite_not_engine_constant():
    base=build_source_slice(20)
    def talent(tid,row,cap):
        return TalentDefinition(id=tid,name=tid,tree_key='source_tree',max_rank=cap,
            ranks=tuple(TalentRankDefinition(rank=i,modifiers=(TalentModifier(
                kind='resource_cost_flat',target_type='action_family',target_id='test_only',value=-i),))
                for i in range(1,cap+1)),metadata={'row':row})
    ir=replace(base,talents=(talent('first',0,5),talent('second',1,1)))
    with pytest.raises(ValueError,match='tier gate not met'):
        validate_talent_selection(ir,{'first':4,'second':1},level=20)
    rule=dict(ir.provenance['talent_tree_rules'])
    modified=replace(ir,provenance={**ir.provenance,'talent_tree_rules':{**rule,'points_per_row':4}})
    validate_talent_selection(modified,{'first':4,'second':1},level=20)
    missing=replace(ir,provenance={**ir.provenance,'talent_tree_rules':None})
    with pytest.raises(ValueError,match='tier rule missing'):
        validate_talent_selection(missing,{'first':5,'second':1},level=20)


def _historical_234_talent_slice(ir):
    from dataclasses import replace
    old={'improved_wrath','ferocity','savage_fury','thick_hide','heart_of_the_wild'}
    return replace(ir,talents=tuple(t for t in ir.talents if t.id in old))
