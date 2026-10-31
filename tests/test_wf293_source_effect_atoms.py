"""WF293: source-aware 9-class typed atom frontier, not fake executable actions."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.game.data.forever.source_effect_atoms import (
    ingest,parse_effect_atoms,read_effect_atom_coverage)

DB=Path(__file__).resolve().parents[1]/'data/forever/catalogue/forever_abilities.sqlite'

class EffectAtomsTest(unittest.TestCase):
    def test_full_nine_class_batch_materialized_and_non_executable(self):
        with sqlite3.connect(DB) as db:
            self.assertEqual(db.execute("SELECT count(distinct class_key) FROM ability_effect_atom_coverage").fetchone()[0],9)
            self.assertEqual(db.execute("SELECT count(*) FROM ability_effect_atom_coverage").fetchone()[0],2255)
            count=db.execute("SELECT count(*) FROM ability_effect_atom_observations").fetchone()[0]
            self.assertGreaterEqual(count,650)
            self.assertEqual(db.execute("SELECT count(distinct class_key) FROM ability_effect_atom_observations").fetchone()[0],9)
            self.assertEqual(db.execute("SELECT count(*) FROM ability_effect_atom_coverage WHERE execution_status!='BLOCKED_PARTIAL_EFFECT_EVIDENCE'").fetchone()[0],0)
            evidence=read_effect_atom_coverage(db,class_key='mage',spell_id=133)
            self.assertEqual(evidence['source_authority'],'verified_detail_html')
            self.assertTrue(evidence['not_legal_for_L2'])
            self.assertTrue(any(a['kind']=='school_damage_range' for a in evidence['atoms']))
            self.assertTrue(any(a['kind']=='periodic_school_damage' for a in evidence['atoms']))

    def test_existing_wf292_pipeline_materializes_atom_ledger(self):
        from tools.wf292_batch_verified_source_recovery import typed_ingest_stage
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'fetch.sqlite'
            out=Path(tmp)/'typed.sqlite'
            with sqlite3.connect(DB) as original,sqlite3.connect(src) as dest:
                original.backup(dest)
            data=typed_ingest_stage(source_stage=src,typed_stage=out)
            self.assertGreaterEqual(data['ingested']['source_effect_atoms']['atoms'],650)
            self.assertEqual(data['ingested']['source_effect_atoms']['executable_promotions'],0)
            with sqlite3.connect(out) as db:
                self.assertEqual(db.execute('select count(*) from ability_effect_atom_coverage').fetchone()[0],2255)

    def test_no_partial_fragment_can_legalize_effect(self):
        parsed=parse_effect_atoms('Causes 15 to 18 Fire damage and also summons an unknown actor.')
        self.assertEqual(len(parsed['atoms']),1)
        self.assertIn('summons an unknown actor',parsed['residual_text'])
        self.assertFalse(parsed['full_effect_semantics_verified'])

    def test_bad_order_and_unknown_mechanics_never_executable(self):
        parsed=parse_effect_atoms('Causes 80 to 20 Frost damage, and some unidentified effect.')
        self.assertFalse(parsed['atoms'])
        self.assertEqual(parsed['execution_status'],'BLOCKED_PARTIAL_EFFECT_EVIDENCE')

    def test_source_driven_reingest_and_stale_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.sqlite'
            with sqlite3.connect(DB) as origin,sqlite3.connect(path) as backup:
                origin.backup(backup)
            with sqlite3.connect(path) as db:
                start=read_effect_atom_coverage(db,class_key='druid',spell_id=5176)
                self.assertEqual(start['atoms'][0]['values']['min'],15.0)
                raw=db.execute("SELECT raw_listview_json FROM spell_index WHERE class_key='druid' and spell_id=5176").fetchone()[0]
                obj=json.loads(raw)
                text=obj['envChange']['after']['text']
                self.assertIn('15 to 18',text)
                obj['envChange']['after']['text']=text.replace('15 to 18','17 to 22')
                db.execute("UPDATE spell_index SET raw_listview_json=? WHERE class_key='druid' and spell_id=5176",(json.dumps(obj),))
                db.commit()
                with self.assertRaisesRegex(ValueError,'STALE_ATOM_INDEX'):
                    read_effect_atom_coverage(db,class_key='druid',spell_id=5176)
            report=ingest(path)
            self.assertGreater(report['ranks_with_atoms'],500)
            with sqlite3.connect(path) as db:
                observed=read_effect_atom_coverage(db,class_key='druid',spell_id=5176)
                self.assertEqual(observed['atoms'][0]['values']['min'],17.0)
                # Tamper the derived facts without updating source:
                db.execute("UPDATE ability_effect_atom_observations SET values_json=? WHERE class_key='druid' and spell_id=5176",('{"min":1}',))
                db.commit()
                with self.assertRaisesRegex(ValueError,'TAMPERED_ATOM_ROWS'):
                    read_effect_atom_coverage(db,class_key='druid',spell_id=5176)

if __name__=='__main__':unittest.main()
