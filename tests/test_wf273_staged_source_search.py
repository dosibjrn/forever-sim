"""Real 28-policy search from two SQLite files: never infer source authority."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from tools.compare_staged_ability_search import compare


def _clones(tmp_path):
    old,stage=tmp_path/'canonical.sqlite',tmp_path/'stage.sqlite'
    for target in (old,stage):
        with sqlite3.connect(DEFAULT_DB) as source,sqlite3.connect(target) as copy:
            source.backup(copy)
    return old,stage


def _source_row(db, sid):
    with sqlite3.connect(db) as c:
        return json.loads(c.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=?',(sid,)).fetchone()[0])


def _write_row(db,sid,obj):
    with sqlite3.connect(db) as c:
        c.execute('UPDATE spell_index SET raw_listview_json=? WHERE spell_id=?',
                  (json.dumps(obj),sid))


def _run(old,stage):
    return compare(canonical_db=old,staged_db=stage,class_key='druid',level=27,
                   mode_id='cat',target_health=484,pulls=3,
                   pre_combat_action_ids=('cat_form:768',),
                   post_combat_action_ids=('cancel_mode:cat',),
                   prepared_first_pull_resources={'energy':100,'rage':0},
                   travel_time_s=2.2,max_policies=28)


def test_data_only_source_change_flips_real_optimizer_winner(tmp_path):
    old,stage=_clones(tmp_path)
    before=hashlib.sha256(old.read_bytes()).hexdigest()
    r=_source_row(stage,1082)
    assert 'plus 27.' in r['envChange']['after']['text']
    r['envChange']['after']['text']=r['envChange']['after']['text'].replace('plus 27.','plus 927.')
    _write_row(stage,1082,r)
    original=build_game_ir_slice(class_key='druid',level=27,ability_db_path=old)
    changed=build_game_ir_slice(class_key='druid',level=27,ability_db_path=stage)
    def flat(ir):
        return next(a for a in ir.actions if a.family_key=='claw').effects[0].flat_damage
    assert flat(changed)==flat(original)+900
    result=_run(old,stage)
    assert result['changed_spell_ids']==[1082]
    assert not result['promoted'] and not result['complete_action_coverage']
    assert result['provenance_status']=='NOT_VERIFIED_BY_THIS_GATE'
    a,b=result['arms']['canonical'],result['arms']['staging']
    assert a['candidate_count']==b['candidate_count']==28
    assert a['evaluated_count']==b['evaluated_count']==28
    # WF284: source-backed Regrowth downrank enters the real recovery frontier,
    # changing the full-cycle ranking without changing this staged Claw fact.
    assert a['winner']['actions']==['rake:1822','rip:20','claw:20']
    assert b['winner']['actions']==['claw:20']
    assert a['winner']['seconds_per_mob']==pytest.approx(20.360723933009186)
    assert b['winner']['seconds_per_mob']==pytest.approx(4.590329551593733)
    assert hashlib.sha256(old.read_bytes()).hexdigest()==before


def test_identical_database_is_not_accepted_as_repair(tmp_path):
    old,stage=_clones(tmp_path)
    with pytest.raises(ValueError,match='no indexed ability-source delta'):
        _run(old,stage)


@pytest.mark.parametrize('fault',('wrong_index_url','wrong_semantic_url','wrong_listview_id',
                                  'malformed_tooltip','missing_semantics','unknown_effect'))
def test_bad_source_or_missing_effect_blocks_without_promotion(tmp_path,fault):
    old,stage=_clones(tmp_path)
    original_bytes=old.read_bytes()
    r=_source_row(stage,1082)
    if fault=='wrong_listview_id':
        r['id']=999999
        _write_row(stage,1082,r)
    elif fault=='malformed_tooltip':
        r['envChange']['after']['text']='Unparsed source effect.'
        _write_row(stage,1082,r)
    else:
        with sqlite3.connect(stage) as con:
            if fault=='wrong_index_url':
                con.execute("UPDATE spell_index SET source_url='https://www.wowhead.com/forever/spell=999999' WHERE spell_id=1082")
            elif fault=='wrong_semantic_url':
                con.execute("UPDATE ability_semantic_source_facts SET source_url='https://www.wowhead.com/forever/spell=999999' WHERE spell_id=1082")
            elif fault=='missing_semantics':
                con.execute('DELETE FROM ability_semantic_source_facts WHERE spell_id=1082')
            elif fault=='unknown_effect':
                con.execute("UPDATE ability_semantic_source_facts SET semantic_type='not_supported' WHERE spell_id=1082")
    with pytest.raises(ValueError):
        _run(old,stage)
    assert old.read_bytes()==original_bytes


def test_all_nine_classes_identical_unmodified_stage_regression(tmp_path):
    from src.game.data.forever.registry import registered_class_keys
    old,stage=_clones(tmp_path)
    assert len(registered_class_keys())==9
    for key in registered_class_keys():
        canonical=build_game_ir_slice(class_key=key,level=20,ability_db_path=old)
        staged=build_game_ir_slice(class_key=key,level=20,ability_db_path=stage)
        assert canonical is not None and staged is not None
        # Verifies generic source rebuild; no class exception to the staged DB.
        def facts(ir):
            return sorted((a.id,a.metadata.get('source_semantic_type'),
                           repr(a.costs),repr(a.effects)) for a in ir.actions
                          if a.metadata.get('source_semantic_type') is not None)
        assert facts(canonical)==facts(staged), key
        assert canonical.provenance['indexed_ability_coverage']==staged.provenance['indexed_ability_coverage'],key
