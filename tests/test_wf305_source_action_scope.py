"""Source role separation: never turn index recipe/talent into executable combat."""
import json, sqlite3
from pathlib import Path
import pytest
from src.game.data.forever.source_action_scope import classify_indexed_ability
from tools.wf303_checkpoint_falsifier import source_gap_audit
from tools.wf305_ingest_web_observed_spell_dependencies import ingest
from src.game.data.forever.sqlite_talents import DEFAULT_DB

HERE=Path(__file__).resolve().parents[1]
EVIDENCE=HERE/'data/forever/source_observations/wf305_druid_l20_engraving_grants.json'


def test_l20_inventory_is_complete_and_unmatched_not_silently_dropped():
 r=source_gap_audit('druid',20)
 assert r['raw_indexed_at_or_unknown_level']==124
 assert r['exact_spell_id_matched']==17  # source-ranked Mark added
 assert r['raw_unrepresented']==107
 s=r['role_scope']
 assert s['roles_unmatched']=={
  'UNRESOLVED_POSITIVE_LEVEL_ENTRY':48,
  'ZERO_OR_UNKNOWN_LEVEL_PASSIVE_TALENT_CANDIDATE':17,
  'SOURCE_NAMED_EQUIPMENT_ENGRAVING_SETUP':37,
  'EXPLICITLY_REMOVED_FROM_SOURCE_CHANGESET':5}
 assert s['unmatched_positive_level_nonengraving_count']==48
 assert len(s['records'])==124
 assert not s['all_legal_combat_actions_verified']
 assert not s['full_gameplay_coverage_proven']
 assert not r['full_source_gameplay_coverage_proven']


def test_actual_spell_ids_stay_unmatched_but_role_specific():
 r=source_gap_audit('druid',20)
 by={x['source_spell_id']:x for x in r['role_scope']['records']}
 assert by[410025]['role']=='SOURCE_NAMED_EQUIPMENT_ENGRAVING_SETUP'
 assert by[410025]['slot_hint']=='gloves'
 assert by[16839]['role']=='ZERO_OR_UNKNOWN_LEVEL_PASSIVE_TALENT_CANDIDATE'
 assert by[16836]['role']=='EXPLICITLY_REMOVED_FROM_SOURCE_CHANGESET'
 assert by[5176]['role']=='UNRESOLVED_POSITIVE_LEVEL_ENTRY'
 assert len(r['grant_dependency_targets_absent_from_class_index'])==4
 assert set(r['grant_dependency_targets_absent_from_class_index'])=={407988,407993,407995,409828}
 assert all(d['observation_status'].endswith('NOT_EXECUTABLE') for d in r['source_grant_dependency_edges'])


def test_index_mismatch_fails_closed():
 record={'spell_id':410025,'name':'Engrave Gloves - Mangle','level_hint':1,'source_url':'https://www.wowhead.com/forever/spell=410025'}
 with pytest.raises(ValueError,match='SPELL_ID_MISMATCH'):
  classify_indexed_ability(record,'{"id":410024,"name":"Engrave Gloves - Mangle","level":1}')
 with pytest.raises(ValueError,match='LEVEL_MISMATCH'):
  classify_indexed_ability(record,'{"id":410025,"name":"Engrave Gloves - Mangle","level":20}')


def test_nonsetup_status_not_claimed_action_legal():
 record={'spell_id':123,'name':'Foo','level_hint':1,'source_url':'https://www.wowhead.com/forever/spell=123'}
 role=classify_indexed_ability(record,'{"id":123,"name":"Foo","level":1}')
 assert role['role']=='UNRESOLVED_POSITIVE_LEVEL_ENTRY'
 assert role['gameplay_coverage_complete'] is False
 assert role['source_acquisition_verified'] is False


def test_stage_ingest_idempotent_nonexecutable_and_no_mutation_of_source_rows(tmp_path):
 dest=tmp_path/'stage.sqlite'
 with sqlite3.connect(f'file:{DEFAULT_DB}?mode=ro',uri=True) as old,sqlite3.connect(dest) as new:
  old.backup(new)
 with sqlite3.connect(dest) as db:
  before=db.execute('SELECT COUNT(*),SUM(spell_id) FROM spell_index').fetchone()
 for _ in range(2):
  result=ingest(dest,EVIDENCE)
  assert result['dependency_edges']==4
  assert result['executable_promotions']==0
  assert result['acquisition_promotions']==0
 with sqlite3.connect(dest) as db:
  assert db.execute('SELECT COUNT(*),SUM(spell_id) FROM spell_index').fetchone()==before
  assert db.execute('SELECT COUNT(*) FROM source_spell_dependency_observations WHERE independent_acquisition_verified=1').fetchone()[0]==0
  assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_stage_tampered_acquisition_refused(tmp_path):
 dest=tmp_path/'stage.sqlite'
 with sqlite3.connect(f'file:{DEFAULT_DB}?mode=ro',uri=True) as old,sqlite3.connect(dest) as new:old.backup(new)
 payload=json.loads(EVIDENCE.read_text());payload['observations'][0]['independent_acquisition_verified']=True
 bad=tmp_path/'bad.json';bad.write_text(json.dumps(payload))
 with pytest.raises(ValueError,match='CANNOT_ASSUME_ACQUISITION'):
  ingest(dest,bad)
 with sqlite3.connect(dest) as db:
  assert db.execute('SELECT COUNT(*) FROM source_spell_dependency_observations').fetchone()[0]==4 # existing copied stage unaffected
