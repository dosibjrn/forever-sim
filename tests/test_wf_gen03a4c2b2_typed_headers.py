import copy
import sqlite3
import unittest
from pathlib import Path
from src.v2.source_sqlite_typed_spell_facts import extract_header_facts, extract_verified_header_facts, UnverifiedCombatFacts

DB = Path(__file__).resolve().parents[1] / 'data/forever/catalogue/forever_abilities.sqlite'
BATCH = '20261008T145657Z'

class TestTypedHeaders(unittest.TestCase):
    def test_all_captured_snapshots_parse_or_fail_closed(self):
        with sqlite3.connect(DB) as con:
            ids = [r[0] for r in con.execute('select spell_id from spell_detail_snapshots')]
        self.assertEqual(len(ids), 20)
        for sid in ids:
            with self.subTest(sid=sid):
                result = extract_verified_header_facts(DB, batch_id=BATCH, spell_id=sid)
                self.assertEqual(result['spell_id'], sid)
                self.assertEqual(result['execution_status'], 'BLOCKED_UNPARSED_EFFECTS')
                self.assertIn('html_sha256', result['source'])
                self.assertTrue(result['unparsed_effect_text'])

    def test_spell_53_energy(self):
        p=extract_verified_header_facts(DB,batch_id=BATCH,spell_id=53)
        self.assertEqual(p['resource_cost'], {'amount':60.0,'resource':'energy'})
        self.assertEqual(p['required_level'],4)
        self.assertEqual(p['range_text'],'Melee Range')

    def test_wrong_spell_id_rejected(self):
        from src.v2.source_sqlite_detail_snapshots import materialize_spell_detail_snapshot
        snap=materialize_spell_detail_snapshot(DB,batch_id=BATCH,spell_id=53)
        with self.assertRaises(UnverifiedCombatFacts):
            extract_header_facts(snap,spell_id=54)

    def test_conflicting_tooltips_rejected(self):
        from src.v2.source_sqlite_detail_snapshots import materialize_spell_detail_snapshot
        snap=materialize_spell_detail_snapshot(DB,batch_id=BATCH,spell_id=53)
        snap=copy.deepcopy(snap)
        snap['html'] += '<div class="wowhead-tooltip" id="tt53"><a class="whtt-name" href="/forever/spell=53/backstab">Backstab</a></div>'
        with self.assertRaises(UnverifiedCombatFacts):
            extract_header_facts(snap,spell_id=53)

if __name__=='__main__': unittest.main()
