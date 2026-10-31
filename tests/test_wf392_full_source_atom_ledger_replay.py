"""All indexed rank effects must replay byte-for-byte from canonical SQLite evidence.

The existing ledger is immutable source evidence, never permission to execute an
unsupported spell.  Any parser change must reproduce its spans, values and
residual text or fail closed instead of silently losing mechanics.
"""
from pathlib import Path
import sqlite3
import pytest
from src.game.data.forever.source_effect_atoms import parse_effect_atoms, read_effect_atom_coverage

ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'


def test_all_nine_class_2255_canonical_rank_effect_ledgers_replay():
    with sqlite3.connect(STAGE) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute('SELECT class_key,spell_id FROM ability_effect_atom_coverage ORDER BY class_key,spell_id').fetchall()
        assert len(rows)==2255
        assert len({r['class_key'] for r in rows})==9
        for row in rows:
            observed=read_effect_atom_coverage(db,class_key=row['class_key'],spell_id=row['spell_id'])
            assert observed is not None
            assert observed['execution_status']=='BLOCKED_PARTIAL_EFFECT_EVIDENCE'
            assert observed['not_legal_for_L2']


@pytest.mark.parametrize('source,kind,values',[
    ('Deals 150% weapon damage plus 32 to the target.', 'weapon_multiplier_plus',{'percent':150.0,'amount':32.0}),
    ('Strike for weapon damage plus 43.', 'weapon_damage_plus',{'amount':43.0}),
    ('The shout is increasing the melee attack power of all party members within 20 yards by 24.', 'actor_attack_power_increase',{'amount':24.0}),
    ("Sunders the target's armor, reducing it by 90 per stack.", 'target_armor_reduction',{'amount':90.0}),
])
def test_compound_source_effect_atoms_are_not_silently_discarded(source,kind,values):
    got=parse_effect_atoms(source)
    assert got['atoms']==[{'kind':kind,'values':values,'span':list(_span(source,kind)),'source_text':source[slice(*_span(source,kind))]}]
    assert got['execution_status']=='BLOCKED_PARTIAL_EFFECT_EVIDENCE'
    assert not got['full_effect_semantics_verified']


def _span(source,kind):
    import re
    patterns={
        'weapon_multiplier_plus':r'150% weapon damage plus 32',
        'weapon_damage_plus':r'weapon damage plus 43',
        'actor_attack_power_increase':r'increasing the melee attack power of all party members within 20 yards by 24',
        'target_armor_reduction':r'reducing it by 90',
    }
    return re.search(patterns[kind],source).span()


def test_ambiguous_pronoun_does_not_invent_armor_effect():
    assert all(x['kind']!='target_armor_reduction' for x in parse_effect_atoms('Reducing it by 90 does not identify a stat.')['atoms'])


def test_legacy_and_enriched_ledgers_both_replay_with_verified_dialects():
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    for db_path,expected_atoms in ((DEFAULT_DB,685),(STAGE,742)):
        with sqlite3.connect(db_path) as db:
            db.row_factory=sqlite3.Row
            rows=db.execute('SELECT class_key,spell_id FROM ability_effect_atom_coverage ORDER BY class_key,spell_id').fetchall()
            assert len(rows)==2255
            assert db.execute('SELECT COUNT(*) FROM ability_effect_atom_observations').fetchone()[0]==expected_atoms
            for r in rows:
                evidence=read_effect_atom_coverage(db,class_key=r['class_key'],spell_id=r['spell_id'])
                assert evidence is not None
                assert evidence['not_legal_for_L2']


def test_one_row_tamper_cannot_choose_a_convenient_grammar(tmp_path):
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    import shutil
    copy=tmp_path/'tampered.sqlite'
    shutil.copyfile(DEFAULT_DB,copy)
    with sqlite3.connect(copy) as db:
        db.execute("UPDATE ability_effect_atom_coverage SET residual_text='FORGED' WHERE class_key='druid' AND spell_id=1082")
        db.commit()
        with pytest.raises(ValueError,match='(UNATTESTED|TAMPERED)'):
            read_effect_atom_coverage(db,class_key='druid',spell_id=1082)
