"""Independent cross-class and negative-source coverage acceptance tests."""
import pytest
from src.v2.source_sqlite_spell_semantics import extract_semantic_observations, extract_verified_semantic_observations
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / 'data/forever/catalogue/forever_abilities.sqlite'
BATCH = '20261008T145657Z'


def get(spell_id):
    return extract_verified_semantic_observations(DB, batch_id=BATCH, spell_id=spell_id)


def test_real_frostbolt_two_distinct_effects_and_unknown_context():
    f = get(116)
    assert [o['kind'] for o in f['observations']] == ['direct_school_damage_range', 'movement_slow_description']
    assert f['observations'][1]['percent'] == 40
    assert f['observations'][1]['duration_seconds'] == 5
    assert f['unparsed_characters'] > 0


def test_real_fireball_two_distinct_effects():
    f = get(133)
    assert [o['kind'] for o in f['observations']] == ['direct_school_damage_range', 'periodic_school_damage_description']
    assert f['observations'][1]['amount'] == 2
    assert f['observations'][1]['duration_seconds'] == 4


def test_real_warrior_resource_and_interrupt():
    assert [(o['kind'], o['resource'], o['amount']) for o in get(100)['observations'] if o['kind'] == 'resource_gain_description'] == [('resource_gain_description', 'rage', 9)]
    assert get(72)['observations'][0]['kind'] == 'school_interrupt_lockout_description'
    assert get(72)['observations'][0]['duration_seconds'] == 6


def test_real_aoe_dot_and_pet_heal():
    assert get(10)['observations'][0]['kind'] == 'periodic_school_damage_description'
    assert get(10)['observations'][0]['amount'] == 196
    assert get(136)['observations'][0]['kind'] == 'periodic_heal_description'
    assert get(136)['observations'][0]['duration_seconds'] is None


def test_all_spans_verbatim_nonoverlapping_and_nonexecutable():
    import sqlite3
    from src.v2.source_sqlite_typed_spell_facts import extract_verified_header_facts
    with sqlite3.connect(DB) as con:
        ids = [r[0] for r in con.execute('select spell_id from spell_detail_snapshots')]
    assert len(ids) == 20
    for sid in ids:
        f = get(sid)
        description = extract_verified_header_facts(DB, batch_id=BATCH, spell_id=sid)['unparsed_effect_text']
        last = 0
        for o in f['observations']:
            lo, hi = o['text_span']
            assert lo >= last and hi > lo
            assert description[lo:hi] == o['source_text']
            last = hi
        assert f['execution_status'] == 'BLOCKED_UNPARSED_EFFECTS'
        assert not f['semantic_completeness'] and not f['executable_effects']


def fake(text):
    return {'spell_id': 42, 'unparsed_effect_text': text,
            'source': {'html_sha256': 'verified-in-test'}, 'execution_status': 'BLOCKED_UNPARSED_EFFECTS'}


@pytest.mark.parametrize('text', [
    'are slowed by 140% for 6 sec',
    'are slowed by 40% for 0 sec',
    'doing 10 Frost damage over 0 sec',
    'interrupts spellcasting and prevents any spell in that school from being cast for 0 sec',
])
def test_invalid_quantities_never_typed(text):
    f = extract_semantic_observations(fake(text))
    assert not f['observations']
    assert f['unparsed_characters'] > 0
    assert not f['semantic_completeness']


def test_resource_ambiguous_context_not_assumed_executable():
    f = extract_semantic_observations(fake('generate 9 Rage, and Stun it for 1 sec. Cannot be used in combat.'))
    assert f['observations'][0]['kind'] == 'resource_gain_description'
    assert 'Stun' in f['unparsed_text']
    assert f['executable_effects'] == []
