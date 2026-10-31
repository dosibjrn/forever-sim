"""WF270: every indexed rank is visible, executable only with proof."""
from __future__ import annotations
from dataclasses import replace
import json
import shutil
import sqlite3

from src.game.data.forever.registry import build_game_ir_slice, registered_class_keys
from src.game.data.forever.source_indexed_action_coverage import indexed_ability_coverage
from src.game.data.forever.source_ability_semantics import source_ability_actions
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2.source_action_coverage import audit_source_action_coverage
from src.v2.source_policy_search import synthesize_source_policies
from src.v2.source_button_discovery import discover_source_combat_buttons


def _ledger(ir):
    result = [x for x in ir.source_facts if x.get('fact_kind')=='canonical_indexed_ability_coverage']
    assert len(result)==1
    return result[0]


def test_all_nine_classes_have_index_rank_to_ir_audit_without_false_legality():
    assert len(registered_class_keys())==9
    for class_key in registered_class_keys():
        ir=build_game_ir_slice(class_key=class_key,level=20)
        assert ir is not None
        record=_ledger(ir)
        summary=record['summary']
        assert summary['not_proof_of_legal_action_coverage']
        assert summary['exact_source_rank_in_ir_count']+summary['unrepresented_rank_count']==summary['at_or_unknown_below_level_count']
        assert summary['unrepresented_rank_count']>0  # no fabricated COMPLETE
        ids=[x['spell_id'] for x in record['records']]
        assert len(ids)==len(set(ids))
        assert all(x['batch_id'] and x['source_url'] for x in record['records'])
        assert any(x['status']=='BLOCKED_INDEX_ONLY_NO_EXECUTABLE_SEMANTICS' for x in record['records'])
        audit=audit_source_action_coverage(ir,level=20)
        assert audit['source_indexed_unrepresented_rank_count']==summary['unrepresented_rank_count']
        assert audit['status']=='INCOMPLETE' and not audit['complete_optimizer']


def test_druid_rake_indexed_but_ir_never_claims_all_source_actions():
    ir=build_game_ir_slice(class_key='druid',level=27)
    records=_ledger(ir)['records']
    rake=next(x for x in records if x['spell_id']==1822)
    assert rake['matched_action_ids']  # source URL lineage matches exact rank, not just name
    assert any(x['spell_id']==3029 for x in _ledger(build_game_ir_slice(class_key='druid',level=30))['records'])
    # Source index contains rune engravings; level hints do NOT prove equipped/learned.
    assert any(x['name'].startswith('Engrave ') and not x['matched_action_ids'] for x in records)


def test_all_downranks_remain_visible_in_index_even_if_older_rank_uncompiled():
    ir=build_game_ir_slice(class_key='druid',level=30)
    rows=[r for r in _ledger(ir)['records'] if r['name']=='Wrath']
    assert len(rows)>=5
    assert len({r['spell_id'] for r in rows})==len(rows)
    assert any(not r['matched_action_ids'] for r in rows)


def test_new_verified_source_semantic_row_compiles_without_class_code_changes(tmp_path):
    # Existing sourced Starfire rank not present at L10.  The generic source
    # compiler must synthesize the L20 action from SQLite alone.
    base=build_game_ir_slice(class_key='druid',level=20)
    assert any(a.family_key=='starfire' for a in base.actions)
    star=next(a for a in base.actions if a.family_key=='starfire')
    assert star.id.startswith('source_spell:')
    available=discover_source_combat_buttons(base,level=20)
    assert star.id in available['action_ids']
    # Mutating the canonical source entry changes the executable action without
    # editing a class-specific spell table or a policy whitelist.
    db=tmp_path/'capture.sqlite'
    with sqlite3.connect(DEFAULT_DB) as source,sqlite3.connect(db) as dest:
        source.backup(dest)
    with sqlite3.connect(db) as con:
        raw=con.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=?',(2912,)).fetchone()[0]
        obj=json.loads(raw)
        original=obj['envChange']['after']['text']
        import re
        obj['envChange']['after']['text']=re.sub(r'(\d+) to (\d+)',
            lambda m:f'{int(m.group(1))+100} to {int(m.group(2))+100}',original,count=1)
        assert obj['envChange']['after']['text'] != original
        con.execute('UPDATE spell_index SET raw_listview_json=? WHERE spell_id=?',(json.dumps(obj),2912))
    # Remove the already compiled Starfire action to reingest it using the
    # generic compiler against the updated database.
    stripped=replace(base,actions=tuple(a for a in base.actions if a.family_key!='starfire'),
        modes=tuple(replace(m,enabled_action_ids=(None if m.enabled_action_ids is None else tuple(i for i in m.enabled_action_ids if i!=star.id))) for m in base.modes))
    newer=source_ability_actions(stripped,class_key='druid',level=20,db_path=db)
    after=next(a for a in newer.actions if a.family_key=='starfire')
    assert after.effects[0].base_min != star.effects[0].base_min
    assert after.effects[0].base_min>star.effects[0].base_min


def test_missing_semantics_is_blocked_not_no_op_or_synthetic_fallback(tmp_path):
    ir=build_game_ir_slice(class_key='druid',level=20)
    db=tmp_path/'deleted.sqlite'
    with sqlite3.connect(DEFAULT_DB) as source,sqlite3.connect(db) as dest:source.backup(dest)
    with sqlite3.connect(db) as con:
        con.execute('DELETE FROM ability_semantic_source_facts WHERE spell_id=2912')
    star=next(a for a in ir.actions if a.family_key=='starfire')
    base=replace(ir, actions=tuple(a for a in ir.actions if a.family_key!='starfire'),
        modes=tuple(replace(m,enabled_action_ids=(None if m.enabled_action_ids is None else tuple(i for i in m.enabled_action_ids if i!=star.id))) for m in ir.modes))
    rebuilt=source_ability_actions(base,class_key='druid',level=20,db_path=db)
    assert not any(a.family_key=='starfire' for a in rebuilt.actions)
    ledger=indexed_ability_coverage(rebuilt,class_key='druid',level=20,db_path=db)
    row=next(x for x in ledger['records'] if x['spell_id']==2912)
    assert row['status']=='BLOCKED_INDEX_ONLY_NO_EXECUTABLE_SEMANTICS'


def test_missing_ability_semantic_schema_fails_closed(tmp_path):
    ir=build_game_ir_slice(class_key='druid',level=20)
    db=tmp_path/'missing_schema.sqlite'
    with sqlite3.connect(DEFAULT_DB) as source,sqlite3.connect(db) as dest:
        source.backup(dest)
    with sqlite3.connect(db) as con:
        con.execute('DROP TABLE ability_semantic_source_facts')
    import pytest
    with pytest.raises(ValueError,match='ability semantics schema unavailable'):
        source_ability_actions(ir,class_key='druid',level=20,db_path=db)
