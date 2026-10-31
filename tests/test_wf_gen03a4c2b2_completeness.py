import copy
import unittest

from src.v2.source_sqlite_spell_semantics import extract_semantic_observations
from src.v2.source_sqlite_semantic_audit import audit_semantic_completeness


def header(text, spell_id=123):
    return {'spell_id': spell_id, 'source': {'html_sha256': 'source-checksum'},
            'unparsed_effect_text': text, 'execution_status': 'BLOCKED_UNPARSED_EFFECTS'}


class SourceCompletenessAuditTest(unittest.TestCase):
    def test_known_effect_does_not_imply_executable(self):
        h = header('Causes 20 to 30 Frost damage')
        a = audit_semantic_completeness(h, extract_semantic_observations(h))
        self.assertTrue(a['source_clause_coverage_complete'])
        self.assertEqual(a['observations'][0]['candidate_execution_kind'], 'direct_damage')
        self.assertTrue(a['observations'][0]['executor_kind_registered'])
        self.assertFalse(a['ir_promotion_allowed'])
        self.assertFalse(a['semantic_completeness'])
        self.assertEqual(a['executable_effects'], [])
        self.assertIn('TARGETING_AND_PREREQUISITES_UNVERIFIED', [b['code'] for b in a['blockers']])

    def test_unparsed_effect_is_explicit_blocker(self):
        h = header('Causes 20 to 30 Frost damage and summons five dragons')
        a = audit_semantic_completeness(h, extract_semantic_observations(h))
        self.assertFalse(a['source_clause_coverage_complete'])
        self.assertIn('and summons five dragons', [b['text'] for b in a['blockers'] if b['code']=='UNPARSED_SOURCE_CLAUSES'][0])

    def test_no_observations(self):
        h = header('Turns into a dragon')
        a = audit_semantic_completeness(h, extract_semantic_observations(h))
        self.assertIn('NO_TYPED_OBSERVATIONS', [b['code'] for b in a['blockers']])

    def test_lineage_tamper_fails(self):
        h = header('Causes 20 to 30 Frost damage')
        s = extract_semantic_observations(h)
        s['source'] = {'html_sha256': 'tampered'}
        with self.assertRaises(ValueError): audit_semantic_completeness(h,s)

    def test_source_span_tamper_fails(self):
        h = header('Causes 20 to 30 Frost damage')
        s = extract_semantic_observations(h)
        s['observations'][0]['source_text'] = 'fake'
        with self.assertRaises(ValueError): audit_semantic_completeness(h,s)

    def test_unknown_observation_kind_fails_closed(self):
        h = header('Turns into a dragon')
        s = extract_semantic_observations(h)
        s['observations'] = [{'kind': 'transmogrify', 'text_span': [0,len(h['unparsed_effect_text'])],
                              'source_text': h['unparsed_effect_text']}]
        s['unparsed_text'] = ''
        a = audit_semantic_completeness(h,s)
        self.assertIn('UNKNOWN_OBSERVATION_KIND', [b['code'] for b in a['blockers']])
        self.assertFalse(a['ir_promotion_allowed'])

    def test_mismatched_spell_id_fails(self):
        h = header('Causes 20 to 30 Frost damage')
        s = extract_semantic_observations(h)
        s['spell_id'] = 456
        with self.assertRaises(ValueError): audit_semantic_completeness(h,s)

    def test_premature_execution_flag_fails(self):
        h = header('Causes 20 to 30 Frost damage')
        s = extract_semantic_observations(h)
        s['execution_status'] = 'READY'
        with self.assertRaises(ValueError): audit_semantic_completeness(h,s)


if __name__ == '__main__': unittest.main()

class RealSnapshotIntegration(unittest.TestCase):
    def test_all_20_verified_snapshots_fail_closed(self):
        import sqlite3
        from pathlib import Path
        from src.v2.source_sqlite_semantic_audit import audit_verified_spell
        db = Path(__file__).resolve().parents[1] / 'data/forever/catalogue/forever_abilities.sqlite'
        with sqlite3.connect(db) as con:
            ids = [x[0] for x in con.execute('select spell_id from spell_detail_snapshots order by spell_id')]
        self.assertEqual(len(ids), 20)
        for sid in ids:
            with self.subTest(spell_id=sid):
                a = audit_verified_spell(db,batch_id='20261008T145657Z',spell_id=sid)
                self.assertFalse(a['ir_promotion_allowed'])
                self.assertEqual(a['executable_effects'], [])
                self.assertTrue(a['blockers'])
