from dataclasses import replace
from types import SimpleNamespace
import pytest
from src.v2.source_db_authority import audit_ir_database_authority, require_ir_database_authority


def test_wowhead_url_and_python_transcription_never_count_as_sqlite():
    ir = SimpleNamespace(id='proof', actor=SimpleNamespace(id='player', provenance=()),
       actions=(SimpleNamespace(id='spell', provenance=({'provider': 'wowhead', 'url': 'https://wowhead.com/forever/spell=1', 'source_module': 'some.python.module'},)),), talents=())
    audit = audit_ir_database_authority(ir)
    assert audit['blocker_count'] == 2
    assert audit['complete_optimizer'] is False
    with pytest.raises(ValueError, match='canonical SQLite'):
        require_ir_database_authority(ir)


def test_complete_declared_lineage_is_distinct_from_db_verified():
    lineage = {'authority': 'canonical_sqlite', 'database': 'abilities', 'table': 'spell_details',
               'row_key': '1', 'capture_batch': 'batch01', 'field_lineage': {'cost': 'raw_page_text'}}
    ir = SimpleNamespace(id='proof', actor=SimpleNamespace(id='player', provenance=(lineage,)),
       actions=(SimpleNamespace(id='spell', provenance=(lineage,)),), talents=())
    audit = audit_ir_database_authority(ir)
    assert audit['blocker_count'] == 0
    assert audit['status'] == 'DECLARED_SQLITE_LINEAGE'
    assert not audit['complete_optimizer']


def test_partial_lineage_never_passes():
    incomplete = {'authority': 'canonical_sqlite', 'database': 'abilities', 'table': 'spell_details'}
    ir = SimpleNamespace(id='proof', actor=SimpleNamespace(id='player', provenance=(incomplete,)), actions=(), talents=())
    assert audit_ir_database_authority(ir)['blocker_count'] == 1


def test_real_druid_l20_not_falsely_certified():
    from src.game.data.forever.registry import build_game_ir_slice
    ir = build_game_ir_slice(class_key='druid', level=20)
    audit = audit_ir_database_authority(ir)
    assert audit['blocker_count'] > 0
    assert audit['complete_optimizer'] is False
    assert any(b['kind'] == 'action' and b['id'].startswith('wrath:') for b in audit['blockers'])
