"""Typed, source-hash-bound partial effect observations for every indexed rank.

This module is an evidence *frontier*, not an alternative combat engine.
A matched fragment does not make its spell executable. No class/spell names
or ids select patterns, and all unparsed mechanics remain explicit blockers.
"""
from __future__ import annotations
from hashlib import sha256
import json
import re
import sqlite3
from pathlib import Path
from functools import lru_cache

_NUMBER = r"(\d+(?:\.\d+)?)"
_SCHOOL = r"(Arcane|Fire|Frost|Nature|Shadow|Holy)"
# Higher-priority multi-field observations consume their entire matched span.
GRAMMAR = (
 ("periodic_school_damage", r"\b" + _NUMBER + r"\s+" + _SCHOOL + r"\s+damage over\s+" + _NUMBER + r"\s+sec\b",
  ("amount","school","duration_s")),
 ("school_damage_range", r"\b" + _NUMBER + r"\s+to\s+" + _NUMBER + r"\s+" + _SCHOOL + r"\s+damage\b",
  ("min","max","school")),
 ("periodic_damage", r"\b" + _NUMBER + r"\s+damage over\s+" + _NUMBER + r"\s+sec\b",
  ("amount","duration_s")),
 ("school_damage_fixed", r"\b" + _NUMBER + r"\s+" + _SCHOOL + r"\s+damage\b",
  ("amount","school")),
 ("healing_range", r"\b(?:heals?|restores?)\b.{0,60}?\b" + _NUMBER + r"\s+to\s+" + _NUMBER + r"\b",
  ("min","max")),
 ("weapon_multiplier_plus", r"\b" + _NUMBER + r"%\s+(?:weapon|normal)\s+damage plus\s+" + _NUMBER + r"\b",
  ("percent","amount")),
 ("weapon_damage_plus", r"\bweapon damage plus\s+" + _NUMBER + r"\b",
  ("amount",)),
 ("weapon_damage_multiplier", r"\b" + _NUMBER + r"%\s+(?:weapon|normal)\s+damage\b",
  ("percent",)),
 ("actor_attack_power_increase",
  r"\b(?:increasing (?:the )?melee attack power(?: of all party members within \d+ yards)?|"
  r"increases? the ranged attack power of party members within \d+ yards) by\s+" + _NUMBER + r"\b",
  ("amount",)),
 ("target_armor_reduction", r"\breducing (?:the target['’]s armor|armor|it) by\s+" + _NUMBER + r"\b",
  ("amount",)),
 ("damage_absorption", r"\babsorbing\s+" + _NUMBER + r"\s+damage\b",
  ("amount",)),
 ("movement_slow", r"\b(?:slow(?:s|ed|ing)?(?: movement speed)?(?: by)?|movement speed (?:is )?reduced by)\s+"
    + _NUMBER + r"%\s+for\s+" + _NUMBER + r"\s+sec\b",
  ("percent","duration_s")),
 ("resource_gain", r"\b(?:generate|gains?)\s+" + _NUMBER + r"\s+(Rage|Mana|Energy|Focus)\b",
  ("amount","resource")),
)
_PATTERNS=tuple((kind,re.compile(expr,re.I),fields) for kind,expr,fields in GRAMMAR)
# Older canonical captures were ingested before four additional semantic kinds
# were introduced. Both dialects must remain replayable, never intermingled.
_ENRICHED_ONLY={'weapon_multiplier_plus','weapon_damage_plus',
                'actor_attack_power_increase','target_armor_reduction'}
_LEGACY_PATTERNS=tuple(x for x in _PATTERNS if x[0] not in _ENRICHED_ONLY)
_NUMERIC_FIELDS={'min','max','amount','duration_s','percent'}
_VALID_SCHOOLS={'arcane','fire','frost','nature','shadow','holy'}


def _source_names_armor_before_pronoun(text: str, start: int) -> bool:
    """Never resolve an anaphoric target stat without nearby source context."""
    return bool(re.search(r"\barmor\b", text[max(0, start - 120):start], re.I))


def parse_effect_atoms(description: str, *, grammar_version: str = 'enriched_v2')->dict:
    """Extract independent fragments without inferring spell completeness."""
    if not isinstance(description,str):
        raise TypeError("description must be source text")
    text=" ".join(description.replace("\xa0"," ").split())
    occupied=[False]*len(text)
    invalid=[False]*len(text)
    atoms=[]
    if grammar_version not in ('legacy_v1','enriched_v2'):
        raise ValueError('UNATTESTED_ATOM_GRAMMAR_VERSION')
    patterns=_LEGACY_PATTERNS if grammar_version=='legacy_v1' else _PATTERNS
    for kind,pattern,fields in patterns:
        for match in pattern.finditer(text):
            start,end=match.span()
            # Anaphoric "reducing it" only identifies armor when source text
            # explicitly names armor earlier in the same local clause.
            if (kind == 'target_armor_reduction'
                and match.group(0).lower().startswith('reducing it')
                and not _source_names_armor_before_pronoun(text, start)):
                continue
            if any(occupied[start:end]) or any(invalid[start:end]):
                continue
            vals=dict(zip(fields,match.groups()))
            for k,v in tuple(vals.items()):
                if k in _NUMERIC_FIELDS:
                    vals[k]=float(v)
                elif k in ('school','resource'):
                    vals[k]=v.lower()
            if (('min' in vals and vals['min']>vals['max'])
                or any(k in vals and vals[k]<=0 for k in ('duration_s','percent'))
                or any(k in vals and vals[k]<0 for k in ('amount','min','max'))):
                invalid[start:end]=[True]*(end-start)
                continue
            if vals.get('school','arcane') not in _VALID_SCHOOLS:
                invalid[start:end]=[True]*(end-start)
                continue
            occupied[start:end]=[True]*(end-start)
            atoms.append({'kind':kind,'values':vals,'span':[start,end],
                          'source_text':text[start:end]})
    atoms.sort(key=lambda x:x['span'])
    remainder=" ".join(''.join((' ' if marked else ch)
                 for marked,ch in zip(occupied,text)).split())
    return {'normalized_text':text,'atoms':atoms,'residual_text':remainder,
            'source_text_sha256':sha256(text.encode()).hexdigest(),
            'execution_status':'BLOCKED_PARTIAL_EFFECT_EVIDENCE',
            'independent_mechanics_verified':False,'full_effect_semantics_verified':False}


SCHEMA = """CREATE TABLE IF NOT EXISTS ability_effect_atom_observations (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL,
 atom_ordinal INTEGER NOT NULL,
 kind TEXT NOT NULL, values_json TEXT NOT NULL, source_text TEXT NOT NULL,
 span_json TEXT NOT NULL, normalized_effect_text_sha256 TEXT NOT NULL,
 index_batch_id TEXT NOT NULL, indexed_payload_sha256 TEXT NOT NULL,
 detail_html_sha256 TEXT, source_authority TEXT NOT NULL,
 execution_status TEXT NOT NULL,
 PRIMARY KEY (class_key,spell_id,atom_ordinal)
)"""
LEDGER_SCHEMA="""CREATE TABLE IF NOT EXISTS ability_effect_atom_coverage (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL,
 index_batch_id TEXT NOT NULL, indexed_payload_sha256 TEXT NOT NULL,
 detail_html_sha256 TEXT, normalized_effect_text_sha256 TEXT NOT NULL,
 atom_count INTEGER NOT NULL, residual_text TEXT NOT NULL,
 source_authority TEXT NOT NULL, execution_status TEXT NOT NULL,
 PRIMARY KEY (class_key,spell_id)
)"""


def ingest(db_path:Path)->dict:
    """Entire 9-class batch, atomic replacement, no executable promotions.

    Re-read and verify immutable HTML whenever available, including its SHA
    and derived header fields. Stale or tampered source causes full rollback.
    """
    from .source_verified_detail_headers import read_current_header
    db=sqlite3.connect(str(db_path));db.row_factory=sqlite3.Row
    try:
        rows=db.execute("""SELECT i.class_key,i.spell_id,i.batch_id,i.raw_listview_json
            FROM spell_index i JOIN capture_lists l ON
            l.batch_id=i.batch_id AND l.class_key=i.class_key AND l.kind=i.kind
            JOIN capture_batches b ON b.batch_id=i.batch_id
            WHERE i.kind='abilities' AND l.complete=1 AND b.status='complete'
            ORDER BY i.class_key,i.spell_id""").fetchall()
        if len({r['class_key'] for r in rows})!=9 or not rows:
            raise ValueError('INCOMPLETE_CANONICAL_NINE_CLASS_INDEX')
        # Parse and check all source facts before altering the SQLite.
        atom_rows=[]; ledger=[]; classes=set()
        for r in rows:
            payload=r['raw_listview_json']
            obj=json.loads(payload)
            detail=read_current_header(db,class_key=r['class_key'],spell_id=r['spell_id'])
            if detail:
                source_text=detail['unparsed_effect_text']
                detail_sha=detail['detail_html_sha256']
                authority='verified_detail_html'
            else:
                after=(obj.get('envChange') or {}).get('after') or {}
                source_text=str(after.get('text') or '')
                detail_sha=None
                authority='source_index_listview'
            parsed=parse_effect_atoms(source_text)
            key=(r['class_key'],int(r['spell_id']))
            classes.add(key[0])
            for idx,atom in enumerate(parsed['atoms']):
                atom_rows.append((*key,idx,atom['kind'],json.dumps(atom['values'],sort_keys=True),
                    atom['source_text'],json.dumps(atom['span']),
                    parsed['source_text_sha256'],r['batch_id'],sha256(payload.encode()).hexdigest(),
                    detail_sha,authority,parsed['execution_status']))
            ledger.append((*key,r['batch_id'],sha256(payload.encode()).hexdigest(),
                detail_sha,parsed['source_text_sha256'],len(parsed['atoms']),
                parsed['residual_text'],authority,parsed['execution_status']))
        db.execute('BEGIN IMMEDIATE')
        db.execute(SCHEMA);db.execute(LEDGER_SCHEMA)
        db.execute('DELETE FROM ability_effect_atom_observations')
        db.execute('DELETE FROM ability_effect_atom_coverage')
        db.executemany('INSERT INTO ability_effect_atom_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',atom_rows)
        db.executemany('INSERT INTO ability_effect_atom_coverage VALUES (?,?,?,?,?,?,?,?,?,?)',ledger)
        db.commit()
        from collections import Counter
        return {'indexed_ranks':len(rows),'classes':len(classes),
            'ranks_with_atoms':len({(r[0],r[1]) for r in atom_rows}),
            'atoms':len(atom_rows),
            'by_effect_kind':dict(Counter(r[3] for r in atom_rows)),
            'by_class':dict(Counter(r[0] for r in atom_rows)),
            'verified_detail_rank_count':sum(r[8]=='verified_detail_html' for r in ledger),
            'executable_promotions':0,'validated_checkpoints':0}
    except Exception:
        db.rollback();raise
    finally:
        db.close()


_ATTESTATION_FILE=(Path(__file__).resolve().parents[4] / 'data/forever/source_observations'
                   / 'atom_ledger_grammar_attestations.json')


def _ledger_digest(conn: sqlite3.Connection) -> str:
    """Hash the *whole* immutable derived ledger, not a convenient single row."""
    coverage=[list(r) for r in conn.execute(
        'SELECT class_key,spell_id,normalized_effect_text_sha256,atom_count,residual_text '
        'FROM ability_effect_atom_coverage ORDER BY class_key,spell_id')]
    atoms=[list(r) for r in conn.execute(
        'SELECT class_key,spell_id,atom_ordinal,kind,values_json,source_text,span_json '
        'FROM ability_effect_atom_observations ORDER BY class_key,spell_id,atom_ordinal')]
    payload=json.dumps([coverage,atoms],ensure_ascii=False,separators=(',',':'))
    return sha256(payload.encode()).hexdigest()


@lru_cache(maxsize=32)
def _attested_grammar_for_db_file(path: str, file_identity: tuple) -> str:
    # Cache only for one immutable SQLite file identity; modified captures
    # require a fresh whole-ledger attestation and cannot reuse a stale choice.
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
        digest=_ledger_digest(db)
    versions=json.loads(_ATTESTATION_FILE.read_text())['ledgers']
    version=versions.get(digest,{}).get('grammar_version')
    if version not in ('legacy_v1','enriched_v2'):
        raise ValueError('UNATTESTED_ATOM_LEDGER_VERSION')
    return version


def _sqlite_file_identity(path: Path) -> tuple:
    """Invalidate attestation cache on main-file or WAL metadata changes."""
    files=(path,Path(str(path)+'-wal'))
    return tuple((f.stat().st_size,f.stat().st_mtime_ns,f.stat().st_ctime_ns)
                 if f.exists() else None for f in files)


def _attested_grammar(conn: sqlite3.Connection) -> str:
    rows=conn.execute('PRAGMA database_list').fetchall()
    path=next((str(r[2]) for r in rows if r[1]=='main'), '')
    if not path:
        # In-memory sources are not silently treated as the latest grammar.
        digest=_ledger_digest(conn)
        version=json.loads(_ATTESTATION_FILE.read_text())['ledgers'].get(digest,{}).get('grammar_version')
        if version not in ('legacy_v1','enriched_v2'):
            raise ValueError('UNATTESTED_ATOM_LEDGER_VERSION')
        return version
    p=Path(path).resolve()
    return _attested_grammar_for_db_file(str(p),_sqlite_file_identity(p))


def read_effect_atom_coverage(conn:sqlite3.Connection,*,class_key:str,spell_id:int)->dict|None:
    """Fail closed on stale source; the ledger is NEVER action legality proof."""
    conn.row_factory=sqlite3.Row
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ability_effect_atom_coverage'").fetchone():
        return None
    row=conn.execute("""SELECT a.*, i.raw_listview_json,i.batch_id AS live_batch
        FROM ability_effect_atom_coverage a JOIN spell_index i ON
        i.class_key=a.class_key AND i.spell_id=a.spell_id AND i.kind='abilities'
        WHERE a.class_key=? AND a.spell_id=?""",(class_key,spell_id)).fetchone()
    if not row:return None
    if row['indexed_payload_sha256'] != sha256(row['raw_listview_json'].encode()).hexdigest() or row['index_batch_id']!=row['live_batch']:
        raise ValueError('STALE_ATOM_INDEX_REINGEST_REQUIRED')
    if row['detail_html_sha256']:
        from .source_verified_detail_headers import read_current_header
        h=read_current_header(conn,class_key=class_key,spell_id=spell_id)
        if h is None or h['detail_html_sha256']!=row['detail_html_sha256']:
            raise ValueError('STALE_ATOM_DETAIL_REINGEST_REQUIRED')
        text=h['unparsed_effect_text']
    else:
        text=str((json.loads(row['raw_listview_json']).get('envChange') or {}).get('after',{}).get('text') or '')
    current=parse_effect_atoms(text,grammar_version=_attested_grammar(conn))
    if current['source_text_sha256']!=row['normalized_effect_text_sha256'] or len(current['atoms'])!=row['atom_count'] or current['residual_text']!=row['residual_text']:
        raise ValueError('TAMPERED_ATOM_LEDGER_REINGEST_REQUIRED')
    atoms=[dict(a) for a in conn.execute(
        'SELECT * FROM ability_effect_atom_observations WHERE class_key=? AND spell_id=? ORDER BY atom_ordinal',
        (class_key,spell_id))]
    if len(atoms)!=row['atom_count']:
        raise ValueError('INCOMPLETE_ATOM_ROWS')
    for got,expected in zip(atoms,current['atoms']):
        if (got['kind']!=expected['kind'] or json.loads(got['values_json'])!=expected['values']
            or json.loads(got['span_json'])!=expected['span'] or got['source_text']!=expected['source_text']
            or got['normalized_effect_text_sha256']!=current['source_text_sha256']):
            raise ValueError('TAMPERED_ATOM_ROWS_REINGEST_REQUIRED')
    return {'class_key':class_key,'spell_id':spell_id,'atom_count':len(atoms),
        'atoms':[{'kind':a['kind'],'values':json.loads(a['values_json']), 'source_text':a['source_text'], 'span':json.loads(a['span_json'])} for a in atoms],
        'residual_text':row['residual_text'],'source_authority':row['source_authority'],
        'execution_status':'BLOCKED_PARTIAL_EFFECT_EVIDENCE',
        'not_legal_for_L2':True}


# Reuse independently source-verified atom ledgers across class levels and
# policy candidates; never key by mutable timestamp or by class alone.
from functools import lru_cache
from copy import deepcopy


def source_db_content_identity(db_path: str | Path) -> str:
    path = Path(db_path).resolve()
    digest = sha256(path.read_bytes())
    wal = Path(str(path) + '-wal')
    if wal.exists():
        digest.update(wal.read_bytes())
    return digest.hexdigest()


def verified_class_effect_atoms(db_path: str | Path, *, class_key: str,
                                allow_stale_index: bool = False) -> dict[int, dict]:
    """Validate every derived rank once per full canonical SQLite identity.

    Fail closed on stale/tampered sources and return isolated per-call values.
    Explicit untrusted stages may quarantine index-stale partial atoms without
    using them as evidence. Tampered derived rows and canonical reads still fail.
    A partial atom is NEVER an acquired or complete executable action.
    """
    path = str(Path(db_path).resolve())
    before = source_db_content_identity(path)
    evidence = _verified_class_effect_atoms_cached(
        path, before, class_key.lower(), allow_stale_index)
    if source_db_content_identity(path) != before:
        raise ValueError('SOURCE_CHANGED_DURING_ATOM_COVERAGE')
    return deepcopy(evidence)


@lru_cache(maxsize=48)
def _verified_class_effect_atoms_cached(path: str, source_sha256: str,
                                       class_key: str,
                                       allow_stale_index: bool = False) -> dict[int, dict]:
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                          "AND name='ability_effect_atom_coverage'").fetchone():
            return {}
        ids = [int(r[0]) for r in db.execute(
            'SELECT spell_id FROM ability_effect_atom_coverage WHERE class_key=? '
            'ORDER BY spell_id', (class_key,))]
        result = {}
        for sid in ids:
            try:
                result[sid] = read_effect_atom_coverage(
                    db, class_key=class_key, spell_id=sid)
            except ValueError as exc:
                # Only a deliberately staged index delta may quarantine an
                # obsolete *partial* atom. Never trust its old values, and
                # never suppress a ledger tamper/grammar/detail failure.
                if not allow_stale_index or str(exc) != 'STALE_ATOM_INDEX_REINGEST_REQUIRED':
                    raise
                result[sid] = {
                    'execution_status': 'STALE_ATOM_INDEX_REINGEST_REQUIRED',
                    'not_legal_for_L2': True,
                }
        if source_db_content_identity(path) != source_sha256:
            raise ValueError('SOURCE_CHANGED_DURING_ATOM_COVERAGE')
        return result
