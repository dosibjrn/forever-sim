from __future__ import annotations
from pathlib import Path
import sqlite3
import pytest
from tools.wf317_first_checkpoint_source_plan import make_plan
from tools.wf317_stage_canonical_verified_effects import build_stage
from tools.capture_forever_abilities_sqlite import load_detail_plan

DB=Path('data/forever/catalogue/forever_abilities.sqlite')


def test_real_checkpoint_source_capture_plan_is_accepted_by_original_fetcher(tmp_path):
    p=make_plan(db_path=DB)
    assert p['class_key']=='druid' and p['level']==20
    assert p['counts']['planned_source_ids']==119
    assert p['counts']['missing_real_html']==118
    assert p['counts']['excluded_removed_for_patch_review']==5
    assert p['counts']['priority_role_counts']['UNRESOLVED_POSITIVE_LEVEL_ENTRY']==48
    assert p['counts']['priority_role_counts']['MATCHED_POSITIVE_LEVEL_ENTRY']==17
    assert p['counts']['priority_role_counts']['SOURCE_NAMED_EQUIPMENT_ENGRAVING_SETUP']==37
    plan=tmp_path/'plan.json'
    import json
    plan.write_text(json.dumps(p['capture_plan']))
    with sqlite3.connect(DB) as db:
        chunks=load_detail_plan(plan,db)
        assert sum(len(c['spell_ids']) for c in chunks)==119


def test_verified_html_can_be_reingested_into_canonical_sqlite_stage_with_no_raw_source_changes(tmp_path):
    path=tmp_path/'staged.sqlite'
    result=build_stage(DB,path)
    assert result['original_canonical_unchanged'] is True
    assert result['full_verified_L1_before']==0
    assert result['full_verified_L1_after']==6
    assert result['full_index_single_L1_after']>=30
    assert result['unique_executable_index_or_detail_L20']>=36
    assert result['verified_detail_pages']==20 and result['verified_effect_slots']==36
    assert result['source_complete_L2_promotions']==0
    assert result['accepted_checkpoints']==0
    with sqlite3.connect(path) as db:
        assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
        assert db.execute('select count(*) from verified_spell_detail_effect_slots').fetchone()[0]==36
    with pytest.raises(ValueError,match='REFUSE_MUTATION_OF_CANONICAL_DB'):
        build_stage(DB,DB)
