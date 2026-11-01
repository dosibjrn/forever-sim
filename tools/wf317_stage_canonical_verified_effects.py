"""Rebuild a SAFE canonical-source SQLite stage from independent SHA-verified HTML.

No new alternate source database: SQLite backup of the real canonical data;
re-run the EXISTING verified-detail effect ingester and atom ingester.
Neither artifact nor ingester promotes incomplete actions to L2 eligibility.
"""
from __future__ import annotations
import hashlib,json,sqlite3
from pathlib import Path
import sys

# Direct CLI execution starts with tools/ on sys.path, not the repository root.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from time import process_time
from src.game.data.forever.source_verified_detail_effects import ingest as ingest_effects
from src.game.data.forever.source_effect_atoms import ingest as ingest_atoms
from tools.wf316_verified_full_cast_canary import audit as audited_full_l1
from tools.wf317_source_index_single_batch import measure as measured_index_l1


def _table_digest(db:sqlite3.Connection,table:str)->str:
    # Exact row-order and raw BLOB bytes retained; table schema is invariant.
    h=hashlib.sha256()
    for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid'):
        for cell in row:
            v=(cell if isinstance(cell,bytes) else str(cell).encode('utf-8'))
            h.update(len(v).to_bytes(8,'big'));h.update(v)
    return h.hexdigest()


def build_stage(source:Path,stage:Path)->dict:
    source=source.resolve();stage=stage.resolve()
    if source==stage:raise ValueError('REFUSE_MUTATION_OF_CANONICAL_DB')
    if stage.exists():raise ValueError('STAGE_EXISTS_NO_OVERWRITE')
    before=audited_full_l1(source)
    started=process_time()
    with sqlite3.connect(f'file:{source}?mode=ro',uri=True) as origin:
        if origin.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('BAD_SOURCE_INTEGRITY')
        with sqlite3.connect(stage) as clone:origin.backup(clone)
        immutable_tables=['spell_index','spell_detail_snapshots','spell_details','capture_batches','capture_lists']
        fingerprints={t:_table_digest(origin,t) for t in immutable_tables}
    effects=ingest_effects(stage,quarantine_structural_errors=True)
    atoms=ingest_atoms(stage)
    after=audited_full_l1(stage)
    index=measured_index_l1(stage,level=20)
    existing={(r['class_key'],int(r['spell_id'])) for r in after['records']
              if r['status']=='EXECUTED_FULL_TYPED_L1_CAST_NOT_L2'}
    new={(r['class_key'],int(r['spell_id'])) for r in index['sample_executions']}
    with sqlite3.connect(stage) as staged:
        if staged.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('BAD_STAGE_INTEGRITY')
        for table in immutable_tables:
            if fingerprints[table]!=_table_digest(staged,table):
                raise ValueError('IMMUTABLE_SOURCE_TABLE_CHANGED:'+table)
    if before['full_typed_L1_casts']>after['full_typed_L1_casts']:
        raise ValueError('STAGING_LOST_EXISTING_VERIFIED_L1_CASTS')
    if len(new)!=index['index_single_L1_casts']:
        raise ValueError('INDEX_CANARY_SAMPLES_NOT_COMPLETE')
    return {'schema':'wf317_canonical_verified_detail_stage_v1',
            'canonical_source':str(source),'stage':str(stage),
            'original_canonical_unchanged':True,'immutable_source_tables_sha256':fingerprints,
            'full_verified_L1_before':before['full_typed_L1_casts'],
            'full_verified_L1_after':after['full_typed_L1_casts'],
            'full_index_single_L1_after':index['index_single_L1_casts'],
            'unique_executable_index_or_detail_L20':len(existing|new),
            'verified_detail_pages':effects['verified_pages'],
            'verified_effect_slots':effects['effect_slots'],
            'verified_effect_typed_by_kind':effects['by_kind'],
            'atom_rows':atoms['atoms'],'source_index_count':atoms['indexed_ranks'],
            'verified_canary_events':after['runtime_events'],
            'full_verified_L1_failures':after['blockers'],
            'CPU_s':round(process_time()-started,6),
            'checkpoint_target':148,'accepted_checkpoints':0,
            'source_complete_L2_promotions':0,'sqlite_integrity':'ok',
            'provenance':'pre-existing verified snapshot SHA checked by production source reader; no invented source records'}

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('--source',type=Path,default=Path('data/forever/catalogue/forever_abilities.sqlite'))
    ap.add_argument('--stage',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();r=build_stage(a.source,a.stage)
    a.output.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:r[k] for k in ('full_verified_L1_before','full_verified_L1_after',
       'full_index_single_L1_after','unique_executable_index_or_detail_L20',
       'verified_detail_pages','verified_effect_slots','CPU_s')},indent=2))
