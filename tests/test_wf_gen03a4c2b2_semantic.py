import sqlite3
from pathlib import Path
import pytest
from src.v2.source_sqlite_spell_semantics import extract_semantic_observations, extract_verified_semantic_observations

DB = Path(__file__).resolve().parents[1] / 'data/forever/catalogue/forever_abilities.sqlite'
BATCH = '20261008T145657Z'

def get(sid):
    return extract_verified_semantic_observations(DB, batch_id=BATCH, spell_id=sid)

def test_20_source_snapshots_remain_blocked():
    with sqlite3.connect(DB) as con:
        ids = [r[0] for r in con.execute('select spell_id from spell_detail_snapshots')]
    assert len(ids) == 20
    for sid in ids:
        f = get(sid)
        assert f['execution_status'] == 'BLOCKED_UNPARSED_EFFECTS'
        assert not f['semantic_completeness'] and f['executable_effects'] == []
        assert f['source']['html_sha256']

def test_frostbolt_damage_and_slow_not_lost():
    f = get(116)
    assert f['observations'][0]['kind'] == 'direct_school_damage_range'
    assert (f['observations'][0]['min'], f['observations'][0]['max']) == (18.8, 20.8)
    assert any(o['kind'] == 'movement_slow_description' for o in f['observations'])

def test_fireball_dot_remains_blocked():
    f = get(133)
    assert f['observations'][0]['school'] == 'fire'
    assert any(o['kind'] == 'periodic_school_damage_description' for o in f['observations'])

def test_renew_periodic_description_not_pretend_per_tick():
    f = get(139)
    assert f['observations'][0]['kind'] == 'periodic_heal_description'
    assert f['observations'][0]['amount'] == 45
    assert f['observations'][0]['duration_seconds'] == 15
    assert not f['semantic_completeness']

def test_weapon_damage_not_guessed():
    assert not get(53)['observations']

def test_unverified_or_promoted_header_rejected():
    header = {'spell_id': 42, 'unparsed_effect_text': 'causing 10 to 12 Frost damage', 'source': {'html_sha256': 'x'}, 'execution_status': 'EXECUTABLE'}
    with pytest.raises(ValueError): extract_semantic_observations(header)
    header['execution_status'] = 'BLOCKED_UNPARSED_EFFECTS'
    header['source'] = {}
    with pytest.raises(ValueError): extract_semantic_observations(header)

def test_reversed_damage_interval_not_typed():
    h = {'spell_id': 42, 'unparsed_effect_text': 'causing 25 to 10 Frost damage', 'source': {'html_sha256': 'x'}, 'execution_status': 'BLOCKED_UNPARSED_EFFECTS'}
    assert not extract_semantic_observations(h)['observations']
