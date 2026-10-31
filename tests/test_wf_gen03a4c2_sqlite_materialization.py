import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from src.v2.source_sqlite_spell_facts import materialize_spell_index_fact, MissingVerifiedSpellFact

DB = Path(__file__).resolve().parents[1] / 'data/forever/catalogue/forever_abilities.sqlite'


def test_real_database_identity_is_traced():
    got = materialize_spell_index_fact(DB, batch_id='20261008T145657Z',
         class_key='warrior', kind='abilities', spell_id=71, field='name')
    assert got['value'] == 'Defensive Stance'
    assert got['lineage']['row_key']['spell_id'] == 71
    assert got['scope'].startswith('identity_only')


@pytest.mark.parametrize('field', ['damage', 'cost', 'effect', 'cooldown', 'talent_prerequisites'])
def test_no_unverified_combat_facts(field):
    with pytest.raises(MissingVerifiedSpellFact):
        materialize_spell_index_fact(DB, batch_id='20261008T145657Z',
         class_key='warrior', kind='abilities', spell_id=71, field=field)


def test_wrong_batch_cannot_cross_join():
    with pytest.raises(MissingVerifiedSpellFact):
        materialize_spell_index_fact(DB, batch_id='nonexistent',
         class_key='warrior', kind='abilities', spell_id=71, field='name')
