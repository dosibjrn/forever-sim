"""WF275: deterministic, zero-network replay of previously stored HTML evidence.

The HTML in this file is SYNTHETIC TEST EVIDENCE, not a Forever claim.
"""
import hashlib
import sqlite3
import zlib
from pathlib import Path

import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from tools.parse_verified_detail_to_staging import (
    SourceRepairBlocked, _verified_visible_text, parse_into_staging)
from tools.run_forever_ability_repair import execute
from test_wf274_verified_source_auto_repair import _synthetic_detail, _text, SEARCH_SCENARIO


def clone(db):
    with sqlite3.connect(DEFAULT_DB) as src, sqlite3.connect(db) as dst:
        src.backup(dst)
    return db


def forbidden_runner(*args, **kwargs):
    raise AssertionError('offline mode must never invoke a fetch subprocess')


def test_offline_reuses_verified_capture_then_real_bounded_search(tmp_path):
    canonical=clone(tmp_path/'canonical.sqlite')
    with sqlite3.connect(canonical) as db:
        _synthetic_detail(db,1822,_text(1822,145))
    original=hashlib.sha256(canonical.read_bytes()).hexdigest()
    result=execute(class_key='druid',level=27,canonical=canonical,
        staging=tmp_path/'staging.sqlite',spell_ids=(1822,),
        runner=forbidden_runner,offline=True,runtime_scenario=SEARCH_SCENARIO)
    assert result['status']=='STAGING_REAL_POLICY_SEARCH_VALIDATED_NOT_PROMOTED'
    assert result['offline'] and result['command'] is None
    assert result['fetch_exit_code'] is None
    assert result['typed_repairs'][0]['changed']
    assert result['runtime_gate']['changed_spell_ids']==[1822]
    assert result['runtime_gate']['arms']['canonical']['evaluated_count']==28
    assert result['runtime_gate']['arms']['staging']['evaluated_count']==28
    assert not result['promoted']
    assert hashlib.sha256(canonical.read_bytes()).hexdigest()==original


def test_offline_fails_closed_if_no_html_snapshot(tmp_path):
    canonical=clone(tmp_path/'canonical.sqlite')
    original=hashlib.sha256(canonical.read_bytes()).hexdigest()
    result=execute(class_key='druid',level=27,canonical=canonical,
        staging=tmp_path/'staging.sqlite',spell_ids=(1822,),
        runner=forbidden_runner,offline=True,runtime_scenario=SEARCH_SCENARIO)
    assert result['status']=='OFFLINE_VERIFIED_HTML_MISSING'
    assert result['missing_ids']==[1822]
    assert 'runtime_gate' not in result
    assert not result['promoted']
    assert hashlib.sha256(canonical.read_bytes()).hexdigest()==original


@pytest.mark.parametrize('markup',[
    '<span hidden>Rake the target for 123 damage</span>',
    '<div style="display: none">Rake the target for 123 damage</div>',
    '<div style=" visibility : hidden ">Rake the target for 123 damage</div>',
    '<span aria-hidden="true">Rake the target for 123 damage</span>',
    '<script>Rake the target for 123 damage</script>',
    '<template>Rake the target for 123 damage</template>',
    '<style>Rake the target for 123 damage</style>',
])
def test_hidden_markup_cannot_impersonate_visible_source(markup):
    assert 'Rake the target' not in _verified_visible_text('<body>'+markup+'</body>')
    assert 'Rake the target' in _verified_visible_text('<body><p>Rake the target for 123 damage</p></body>')


def test_hidden_html_cannot_override_typed_fact_even_when_digest_matches(tmp_path):
    staging=clone(tmp_path/'staging.sqlite')
    text=_text(1822,123)
    with sqlite3.connect(staging) as db:
        _synthetic_detail(db,1822,text)
        body=f'Rake - Spell - Forever Rank 1 Requires level 24 40 Energy Instant {text}'
        html=(f'<html><body>Rake - Spell - Forever Rank 1 Requires level 24 '
              f'40 Energy Instant <span hidden>{text}</span></body></html>').encode()
        digest=hashlib.sha256(html).hexdigest()
        db.execute('UPDATE spell_details SET raw_page_text=?,html_sha256=? WHERE spell_id=1822',
                   (body,digest))
        db.execute('UPDATE spell_detail_snapshots SET html_sha256=?,html_bytes=?,html_zlib=? WHERE spell_id=1822',
                   (digest,len(html),zlib.compress(html)))
    with pytest.raises(SourceRepairBlocked,match='DETAIL_GRAMMAR_UNIQUE_MATCH_REQUIRED'):
        parse_into_staging(staging,spell_ids=(1822,))
    with sqlite3.connect(staging) as db:
        row=db.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=1822').fetchone()[0]
        assert 'for 123 damage' not in row


def test_offline_resume_existing_fetched_staging_without_fetch(tmp_path):
    canonical=clone(tmp_path/'canonical.sqlite')
    stage=clone(tmp_path/'already_fetched.sqlite')
    with sqlite3.connect(stage) as db:
        _synthetic_detail(db,1822,_text(1822,160))
    result=execute(class_key='druid',level=27,canonical=canonical,
        staging=stage,spell_ids=(1822,),offline=True,reuse_staging=True,
        runner=forbidden_runner,runtime_scenario=SEARCH_SCENARIO)
    assert result['status']=='STAGING_REAL_POLICY_SEARCH_VALIDATED_NOT_PROMOTED'
    assert result['reused_staging'] and result['command'] is None
    assert result['runtime_gate']['arms']['staging']['evaluated_count']==28
    assert not result['promoted']


def test_existing_stage_drift_blocks_without_mutation(tmp_path):
    canonical=clone(tmp_path/'canonical.sqlite')
    stage=clone(tmp_path/'already_fetched.sqlite')
    with sqlite3.connect(stage) as db:
        _synthetic_detail(db,1822,_text(1822,160))
        db.execute("UPDATE spell_index SET name='tampered' WHERE spell_id=1822")
    before=hashlib.sha256(stage.read_bytes()).hexdigest()
    result=execute(class_key='druid',level=27,canonical=canonical,
        staging=stage,spell_ids=(1822,),offline=True,reuse_staging=True,
        runner=forbidden_runner,runtime_scenario=SEARCH_SCENARIO)
    assert result['status']=='STAGING_LINEAGE_MISMATCH'
    assert 'STAGING_LINEAGE_DATA_DRIFT:spell_index' in result['blocker']
    assert hashlib.sha256(stage.read_bytes()).hexdigest()==before


def test_reuse_staging_requires_offline(tmp_path):
    canonical=clone(tmp_path/'canonical.sqlite')
    stage=clone(tmp_path/'already_fetched.sqlite')
    with pytest.raises(ValueError,match='reuse_staging requires offline'):
        execute(class_key='druid',level=27,canonical=canonical,
            staging=stage,spell_ids=(1822,),offline=False,reuse_staging=True,
            runner=forbidden_runner)
