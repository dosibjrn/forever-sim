"""WF294: generic source-verified class cache, no weakening of provenance."""
from __future__ import annotations
import json
from pathlib import Path
import sqlite3
import tempfile
import os
import unittest

from src.game.data.forever.source_effect_atoms import (
    _verified_class_effect_atoms_cached,
    read_effect_atom_coverage,
    verified_class_effect_atoms,
    source_db_content_identity,
)
from src.game.data.forever.source_indexed_action_coverage import indexed_ability_coverage
from src.game.data.forever.registry import build_game_ir_slice

DB = Path(__file__).resolve().parents[1] / 'data/forever/catalogue/forever_abilities.sqlite'


class VerifiedAtomClassCacheTest(unittest.TestCase):
    def test_all_nine_classes_same_rank_evidence_as_single_source_reads(self):
        with sqlite3.connect(DB) as db:
            for key in ('druid','hunter','mage','paladin','priest','rogue','shaman','warlock','warrior'):
                batch=verified_class_effect_atoms(DB,class_key=key)
                count=db.execute('SELECT count(*) FROM ability_effect_atom_coverage WHERE class_key=?',(key,)).fetchone()[0]
                self.assertEqual(len(batch),count)
                for sid in list(batch)[:3]:
                    self.assertEqual(batch[sid],read_effect_atom_coverage(db,class_key=key,spell_id=sid))
                self.assertTrue(all(e['not_legal_for_L2'] for e in batch.values()))

    def test_cache_reuses_only_exact_source_content(self):
        _verified_class_effect_atoms_cached.cache_clear()
        first=verified_class_effect_atoms(DB,class_key='mage')
        after_first=_verified_class_effect_atoms_cached.cache_info()
        second=verified_class_effect_atoms(DB,class_key='mage')
        after_second=_verified_class_effect_atoms_cached.cache_info()
        self.assertEqual(first,second)
        self.assertIsNot(first,second)
        first[133]['atoms'].clear()
        self.assertTrue(verified_class_effect_atoms(DB,class_key='mage')[133]['atoms'])
        self.assertEqual(after_second.misses,after_first.misses)
        self.assertEqual(after_second.hits,after_first.hits+1)

    def test_same_size_source_mutation_with_restored_mtime_invalidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.sqlite'
            with sqlite3.connect(DB) as source,sqlite3.connect(path) as destination:
                source.backup(destination)
            before=source_db_content_identity(path)
            evidence=verified_class_effect_atoms(path,class_key='druid')
            self.assertTrue(evidence)
            stat=path.stat()
            with sqlite3.connect(path) as db:
                raw=db.execute('SELECT raw_listview_json FROM spell_index WHERE class_key=? AND spell_id=?',('druid',5176)).fetchone()[0]
                self.assertIn('15 to 18',raw)
                modified=raw.replace('15 to 18','17 to 22')
                self.assertEqual(len(raw),len(modified))
                db.execute('UPDATE spell_index SET raw_listview_json=? WHERE class_key=? AND spell_id=?',(modified,'druid',5176))
                db.commit()
            os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
            self.assertEqual(path.stat().st_size,stat.st_size)
            self.assertEqual(path.stat().st_mtime_ns,stat.st_mtime_ns)
            self.assertNotEqual(source_db_content_identity(path),before)
            with self.assertRaisesRegex(ValueError,'STALE_ATOM_INDEX'):
                verified_class_effect_atoms(path,class_key='druid')
            # The untrusted staged GameIR may still evaluate independently
            # sourced executable semantics, but must not reuse stale atoms.
            staged = build_game_ir_slice(class_key='druid',level=20,ability_db_path=path)
            ledger = next(f for f in staged.source_facts
                          if f.get('fact_kind')=='canonical_indexed_ability_coverage')
            record = next(r for r in ledger['records'] if r['spell_id']==5176)
            self.assertEqual(record['source_effect_execution_status'],
                             'STALE_ATOM_INDEX_REINGEST_REQUIRED')
            self.assertNotIn('source_effect_atom_count',record)
            self.assertFalse(staged.provenance['complete_source_action_coverage'])

    def test_coverage_is_still_blocked_not_executable(self):
        ir=build_game_ir_slice(class_key='mage',level=20)
        coverage=indexed_ability_coverage(ir,class_key='mage',level=20)
        self.assertGreater(coverage['source_effect_atom_rank_count'],0)
        self.assertEqual(coverage['source_effect_atom_count'],32)
        self.assertTrue(coverage['source_effect_atoms_not_executable'])
        self.assertTrue(coverage['not_proof_of_legal_action_coverage'])
        self.assertTrue(all(r.get('source_effect_execution_status')=='BLOCKED_PARTIAL_EFFECT_EVIDENCE'
                            for r in coverage['records'] if 'source_effect_execution_status' in r))


if __name__=='__main__': unittest.main()
