from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import pickle
import queue
import sqlite3
import struct
import sys
import threading
import time
import atexit
from pathlib import Path

from src.engine_registry import eng
from src import game_context
from src import policy_codec
from src import presentation
from src.forever_build import current as current_forever_build

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = game_context.state_root(ROOT) / 'cache'
DB_PATH = CACHE_DIR / 'pnp.sqlite3'
CACHE_SCHEMA = 'pnp_head_metrics_v5_metadata_landscape'
SIM_SEMANTICS_VERSION = 'pnp_chain_v1'
PRECISION_LADDER = (1, 2, 4, 8, 16, 32, 64, 100)
SEED_SCHEME = 'common_level_stream_v1'
_SIM_HASH = None
_SIM_HASH_KEY = None
_STALE_STATUS = (0.0, False)
_CACHE_STATS_STATUS = (0.0, None)
_TLS = threading.local()
_DB_READY = set()
_INIT_LOCK = threading.Lock()
_WRITE_QUEUE = None
_WRITE_THREAD = None
_WRITE_LOCK = threading.Lock()
_WRITE_ERROR = None
_WRITE_BATCH_ROWS = 2048
_WRITE_BATCH_WAIT_S = 0.025

_METRICS_MAGIC = b'PNM4'
_STATE_MAGIC = b'PNS4'
_METRIC_BASE_KEYS = ('total_s','kill_s','recovery_s','mana','pushback_s','swings','total_sq_s')
_CAST_IDS = {name:i for i,name in enumerate(('frostbolt','fireball','scorch','arcane_missiles','fire_blast','frost_nova','blink','move'))}
_CAST_NAMES = {v:k for k,v in _CAST_IDS.items()}


def _sha256_bytes(parts) -> str:
    h = hashlib.sha256()
    for part in parts:
        if isinstance(part, str):
            part = part.encode('utf-8')
        h.update(part); h.update(b'\0')
    return h.hexdigest()[:20]


def current_sim_hash() -> str:
    """Hash numeric simulator semantics, including moving Forever build identity."""
    global _SIM_HASH, _SIM_HASH_KEY
    build_token = (current_forever_build().build_id if getattr(eng, 'RULESET', None) == 'forever' else 'non-forever')
    key = (str(Path(eng.__file__).resolve()), build_token, sys.version.split()[0])
    if _SIM_HASH is None or _SIM_HASH_KEY != key:
        engine_path = Path(eng.__file__).resolve()
        _SIM_HASH = _sha256_bytes([SIM_SEMANTICS_VERSION, engine_path.read_bytes(), sys.version.split()[0], build_token])
        _SIM_HASH_KEY = key
    return _SIM_HASH


def _canon(v):
    if dataclasses.is_dataclass(v):
        return {f.name: _canon(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, dict):
        return {str(k): _canon(v[k]) for k in sorted(v)}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    return v


def canonical_seed(level: int) -> int:
    return 730201 + int(level) * 104729


def scenario_payload(level, talents, policy, cfg, seed, hp_mult=1.0):
    cfg_payload = _canon(cfg)
    if isinstance(cfg_payload, dict):
        cfg_payload.pop('seed', None)
    return {
        'level': int(level), 'talents': _canon(talents),
        'policy': policy_codec.canonical_policy_payload(policy, int(level)),
        'cfg': cfg_payload, 'seed_scheme': SEED_SCHEME, 'seed': int(seed),
        'hp_mult': float(hp_mult),
    }


def scenario_key(level, talents, policy, cfg, seed, hp_mult=1.0) -> str:
    payload = json.dumps(scenario_payload(level, talents, policy, cfg, seed, hp_mult),
                         sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()



def _encode_casts(casts: dict) -> bytes:
    out = bytearray()
    items = [(str(k), int(round(v))) for k, v in (casts or {}).items() if v]
    if len(items) > 255:
        raise ValueError('too many cast counters')
    out += struct.pack('<B', len(items))
    for name, count in sorted(items):
        cid = _CAST_IDS.get(name)
        if cid is not None:
            out += struct.pack('<BI', cid, max(0, count))
        else:
            raw = name.encode('utf-8')
            if len(raw) > 255:
                raise ValueError('cast counter name too long')
            out += struct.pack('<BB', 255, len(raw)) + raw + struct.pack('<I', max(0, count))
    return bytes(out)


def _decode_casts(buf, offset: int):
    count = struct.unpack_from('<B', buf, offset)[0]; offset += 1
    casts = {}
    for _ in range(count):
        cid = struct.unpack_from('<B', buf, offset)[0]; offset += 1
        if cid == 255:
            ln = struct.unpack_from('<B', buf, offset)[0]; offset += 1
            name = bytes(buf[offset:offset+ln]).decode('utf-8'); offset += ln
        else:
            name = _CAST_NAMES.get(cid, f'unknown_{cid}')
        value = struct.unpack_from('<I', buf, offset)[0]; offset += 4
        casts[name] = int(value)
    return casts, offset


def _metrics_from_cumulative(n: int, vals, casts: dict) -> dict:
    total, kill, recovery, mana, pushback, swings, total_sq = map(float, vals)
    mean = total / n if n else 0.0
    if n > 1:
        var = max(0.0, (total_sq - total * total / n) / (n - 1))
        stderr = (var / n) ** 0.5
    else:
        stderr = float('inf')
    out = {
        'total_s': total, 'kill_s': kill, 'recovery_s': recovery, 'mana': mana,
        'pushback_s': pushback, 'swings': swings, 'total_sq_s': total_sq,
        'mean_s_per_mob': mean, 'stderr_s_per_mob': stderr,
    }
    for name, value in casts.items():
        out['casts_' + name] = value
    return out


def encode_metrics_history(hist: dict) -> bytes:
    """Compact cumulative metrics history; numeric binary, no JSON field names."""
    rows = []
    for key, metrics in (hist or {}).items():
        n = int(key)
        casts = {k[6:]: v for k, v in metrics.items() if str(k).startswith('casts_')}
        vals = [float(metrics.get(k, 0.0)) for k in _METRIC_BASE_KEYS]
        rows.append((n, vals, casts))
    rows.sort(key=lambda x: x[0])
    if len(rows) > 255:
        raise ValueError('metrics history too long')
    out = bytearray(_METRICS_MAGIC)
    out += struct.pack('<B', len(rows))
    for n, vals, casts in rows:
        out += struct.pack('<H7d', n, *vals)
        out += _encode_casts(casts)
    return bytes(out)


def decode_metrics_history(blob, legacy_json=None) -> dict:
    if blob:
        raw = bytes(blob)
        if raw.startswith(_METRICS_MAGIC):
            mv = memoryview(raw); off = len(_METRICS_MAGIC)
            count = struct.unpack_from('<B', mv, off)[0]; off += 1
            hist = {}
            for _ in range(count):
                unpacked = struct.unpack_from('<H7d', mv, off); off += struct.calcsize('<H7d')
                n, vals = int(unpacked[0]), unpacked[1:]
                casts, off = _decode_casts(mv, off)
                hist[n] = _metrics_from_cumulative(n, vals, casts)
            return hist
        # Transitional binary formats may simply be pickled dicts.
        try:
            obj = pickle.loads(raw)
            return {int(k): dict(v) for k, v in obj.items()}
        except Exception:
            pass
    if legacy_json:
        obj = json.loads(legacy_json)
        return {int(k): dict(v) for k, v in obj.items()}
    return {}


def encode_chain_state(state: dict | None) -> bytes:
    if not state:
        return b''
    # Compatibility for synthetic tests/legacy rows that predate resumable RNG
    # continuations. Real simulator states take the compact numeric path below.
    if 'rng_state' not in state:
        return pickle.dumps(state, pickle.HIGHEST_PROTOCOL)
    rng = state['rng_state']
    version = int(rng[0]); internal = tuple(int(x) & 0xffffffff for x in rng[1]); gauss = rng[2]
    if len(internal) > 65535:
        raise ValueError('RNG state unexpectedly large')
    out = bytearray(_STATE_MAGIC)
    out += struct.pack('<HBH', int(state.get('n', 0)), version, len(internal))
    out += struct.pack('<' + 'I' * len(internal), *internal)
    if gauss is None:
        out += struct.pack('<B', 0)
    else:
        out += struct.pack('<Bd', 1, float(gauss))
    cds = tuple(float(x) for x in state.get('cooldowns', (0.0, 0.0, 0.0)))
    if len(cds) > 255:
        raise ValueError('too many cooldowns')
    out += struct.pack('<B', len(cds))
    if cds:
        out += struct.pack('<' + 'd' * len(cds), *cds)
    vals = [float(state.get(k, 0.0)) for k in _METRIC_BASE_KEYS]
    out += struct.pack('<7d', *vals)
    out += _encode_casts(state.get('casts', {}))
    return bytes(out)


def decode_chain_state(blob):
    if not blob:
        return None
    raw = bytes(blob)
    if not raw.startswith(_STATE_MAGIC):
        return pickle.loads(raw)
    mv = memoryview(raw); off = len(_STATE_MAGIC)
    n, version, ln = struct.unpack_from('<HBH', mv, off); off += struct.calcsize('<HBH')
    internal = struct.unpack_from('<' + 'I' * ln, mv, off); off += 4 * ln
    has_gauss = struct.unpack_from('<B', mv, off)[0]; off += 1
    gauss = None
    if has_gauss:
        gauss = struct.unpack_from('<d', mv, off)[0]; off += 8
    cdn = struct.unpack_from('<B', mv, off)[0]; off += 1
    cooldowns = struct.unpack_from('<' + 'd' * cdn, mv, off) if cdn else ()
    off += 8 * cdn
    vals = struct.unpack_from('<7d', mv, off); off += struct.calcsize('<7d')
    casts, off = _decode_casts(mv, off)
    return {
        'n': int(n), 'rng_state': (int(version), tuple(int(x) for x in internal), gauss),
        'cooldowns': tuple(cooldowns),
        'total_s': vals[0], 'kill_s': vals[1], 'recovery_s': vals[2], 'mana': vals[3],
        'pushback_s': vals[4], 'swings': vals[5], 'total_sq_s': vals[6], 'casts': casts,
    }


def _terminal_precision(n: int) -> bool:
    return int(n) >= int(max(PRECISION_LADDER))


def ensure_db():
    key = (os.getpid(), str(DB_PATH.resolve()))
    if key in _DB_READY:
        return
    with _INIT_LOCK:
        if key in _DB_READY:
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(DB_PATH, timeout=30.0)
        try:
            con.execute('PRAGMA busy_timeout=30000')
            con.execute('PRAGMA journal_mode=WAL')
            con.execute('PRAGMA synchronous=NORMAL')
            con.execute('PRAGMA temp_store=MEMORY')
            try: con.execute('PRAGMA mmap_size=268435456')
            except Exception: pass
            con.execute("""CREATE TABLE IF NOT EXISTS chains (
                code_hash TEXT NOT NULL, scenario_key TEXT NOT NULL, n INTEGER NOT NULL,
                level INTEGER NOT NULL, water_mode TEXT NOT NULL, metrics_json TEXT NOT NULL,
                chain_state BLOB NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY(code_hash, scenario_key, n))""")
            con.execute("""CREATE TABLE IF NOT EXISTS scenario_heads (
                code_hash TEXT NOT NULL, scenario_key TEXT NOT NULL,
                level INTEGER NOT NULL, water_mode TEXT NOT NULL,
                max_n INTEGER NOT NULL, metrics_history_json TEXT NOT NULL,
                chain_state BLOB NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(code_hash, scenario_key))""")
            cols = {r[1] for r in con.execute('PRAGMA table_info(scenario_heads)').fetchall()}
            if 'metrics_blob' not in cols:
                con.execute('ALTER TABLE scenario_heads ADD COLUMN metrics_blob BLOB')
            con.execute('CREATE INDEX IF NOT EXISTS idx_heads_hash ON scenario_heads(code_hash,max_n)')
            con.execute('CREATE INDEX IF NOT EXISTS idx_heads_scenario ON scenario_heads(scenario_key,code_hash)')
            con.execute('CREATE INDEX IF NOT EXISTS idx_chains_scenario ON chains(scenario_key,code_hash,n)')
            con.execute("""CREATE TABLE IF NOT EXISTS builds (
                build_id TEXT PRIMARY KEY, talents_json TEXT NOT NULL, allocation TEXT NOT NULL,
                school TEXT NOT NULL, family TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS policies (
                policy_id TEXT PRIMARY KEY, policy_json TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS scenario_meta (
                code_hash TEXT NOT NULL, scenario_key TEXT NOT NULL, build_id TEXT NOT NULL,
                policy_id TEXT NOT NULL, policy_desc TEXT NOT NULL, seed INTEGER NOT NULL,
                hp_mult REAL NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(code_hash,scenario_key))""")
            con.execute('CREATE INDEX IF NOT EXISTS idx_meta_recent ON scenario_meta(code_hash,updated_at DESC)')
            con.execute("""CREATE TABLE IF NOT EXISTS path_observations (
                code_hash TEXT NOT NULL, water_mode TEXT NOT NULL, talent_path_id TEXT NOT NULL,
                candidate_path_id TEXT, source TEXT NOT NULL, school TEXT NOT NULL, family TEXT NOT NULL,
                search_hours REAL, validated_hours REAL, precision_mobs INTEGER NOT NULL, validated INTEGER NOT NULL,
                respec_levels_json TEXT NOT NULL, final_allocation TEXT NOT NULL, replay_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(code_hash,water_mode,talent_path_id))""")
            con.execute('CREATE INDEX IF NOT EXISTS idx_path_obs_recent ON path_observations(code_hash,water_mode,updated_at DESC)')
            con.commit()
            _DB_READY.add(key)
        finally:
            con.close()


def _new_connection():
    con = sqlite3.connect(DB_PATH, timeout=30.0)
    con.execute('PRAGMA busy_timeout=30000')
    con.execute('PRAGMA synchronous=NORMAL')
    con.execute('PRAGMA temp_store=MEMORY')
    try: con.execute('PRAGMA mmap_size=268435456')
    except Exception: pass
    return con


def _connect():
    ensure_db()
    key = (os.getpid(), str(DB_PATH.resolve()))
    if getattr(_TLS, 'key', None) != key or getattr(_TLS, 'con', None) is None:
        old = getattr(_TLS, 'con', None)
        if old is not None:
            try: old.close()
            except Exception: pass
        _TLS.con = _new_connection(); _TLS.key = key
    return _TLS.con


def close_connection():
    con = getattr(_TLS, 'con', None)
    if con is not None:
        try: con.close()
        except Exception: pass
    _TLS.con = None; _TLS.key = None


def _talent_school_family(talents):
    return presentation.school_family(talents)


def _scenario_metadata(level, talents, policy, seed, hp_mult, code_hash, skey):
    tj=json.dumps(_canon(talents),sort_keys=True,separators=(',',':'),ensure_ascii=True)
    pj=json.dumps(policy_codec.canonical_policy_payload(policy,int(level)),sort_keys=True,separators=(',',':'),ensure_ascii=True)
    build_id=hashlib.sha1(tj.encode('utf-8')).hexdigest()[:20]
    policy_id=hashlib.sha1(pj.encode('utf-8')).hexdigest()[:20]
    school,family=_talent_school_family(talents)
    return {
        '_kind':'meta','code_hash':code_hash,'scenario_key':skey,'build_id':build_id,'policy_id':policy_id,
        'talents_json':tj,'allocation':eng.final_allocation(talents),'school':school,'family':family,
        'policy_json':pj,'policy_desc':eng.policy_desc(policy,int(level)),'seed':int(seed),'hp_mult':float(hp_mult),
    }


def _has_scenario_metadata(code_hash: str, skey: str) -> bool:
    return _connect().execute('SELECT 1 FROM scenario_meta WHERE code_hash=? AND scenario_key=? LIMIT 1',(code_hash,skey)).fetchone() is not None


def _write_meta_tx(records, *, connection=None):
    records=[r for r in (records or []) if isinstance(r,dict) and r.get('_kind')=='meta']
    if not records: return
    con=connection or _connect(); now=time.time()
    builds={r['build_id']:(r['build_id'],r['talents_json'],r['allocation'],r['school'],r['family']) for r in records}
    policies={r['policy_id']:(r['policy_id'],r['policy_json']) for r in records}
    metas={(r['code_hash'],r['scenario_key']):(r['code_hash'],r['scenario_key'],r['build_id'],r['policy_id'],r['policy_desc'],r['seed'],r['hp_mult'],now) for r in records}
    for attempt in range(9):
        try:
            con.execute('BEGIN IMMEDIATE')
            con.executemany('INSERT OR IGNORE INTO builds(build_id,talents_json,allocation,school,family) VALUES(?,?,?,?,?)',builds.values())
            con.executemany('INSERT OR IGNORE INTO policies(policy_id,policy_json) VALUES(?,?)',policies.values())
            con.executemany("""INSERT INTO scenario_meta(code_hash,scenario_key,build_id,policy_id,policy_desc,seed,hp_mult,updated_at)
                               VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(code_hash,scenario_key) DO UPDATE SET
                               build_id=excluded.build_id,policy_id=excluded.policy_id,policy_desc=excluded.policy_desc,
                               seed=excluded.seed,hp_mult=excluded.hp_mult,updated_at=excluded.updated_at""",metas.values())
            con.commit(); return
        except sqlite3.OperationalError:
            try: con.rollback()
            except Exception: pass
            if attempt==8: raise
            time.sleep(0.02*(2**attempt))
        except Exception:
            try: con.rollback()
            except Exception: pass
            raise


def _water_mode(cfg) -> str:
    return 'buy_water' if bool(getattr(cfg, 'use_best_water', True)) else 'conjured_water'


def _migrate_legacy_chain_head(code_hash: str, skey: str):
    """Lazy compatibility import from old per-precision `chains` rows."""
    con = _connect()
    rows = con.execute("""SELECT n,level,water_mode,metrics_json,chain_state,created_at
                          FROM chains WHERE code_hash=? AND scenario_key=? ORDER BY n""",
                       (code_hash, skey)).fetchall()
    if not rows:
        return False
    hist = {int(r[0]): json.loads(r[3]) for r in rows}
    last = rows[-1]
    state = None if _terminal_precision(int(last[0])) else pickle.loads(last[4])
    _write_rows_tx([(code_hash, skey, int(last[0]), int(last[1]), last[2], hist[int(last[0])], state)],
                   seed_history=hist)
    return True


def _head_row(code_hash: str, skey: str, migrate=True):
    con = _connect()
    row = con.execute("""SELECT level,water_mode,max_n,metrics_blob,metrics_history_json,chain_state,updated_at
                         FROM scenario_heads WHERE code_hash=? AND scenario_key=?""",
                      (code_hash, skey)).fetchone()
    if row is not None or not migrate:
        return row
    if _migrate_legacy_chain_head(code_hash, skey):
        return _head_row(code_hash, skey, migrate=False)
    return None


def lookup_target(code_hash: str, skey: str, target_n: int, *, migration_sink=None, level=None, water_mode=None):
    """One cheap head lookup; fetch the multi-kB continuation blob only for extension.

    Legacy JSON terminal rows are opportunistically queued for binary compaction
    through the worker's deferred-write result; the worker itself never writes.
    """
    con = _connect()
    row = con.execute("""SELECT max_n,metrics_blob,metrics_history_json
                         FROM scenario_heads WHERE code_hash=? AND scenario_key=?""",
                      (code_hash, skey)).fetchone()
    if row is None:
        if _migrate_legacy_chain_head(code_hash, skey):
            return lookup_target(code_hash, skey, target_n, migration_sink=migration_sink, level=level, water_mode=water_mode)
        return None, None
    max_n = int(row[0])
    hist = decode_metrics_history(row[1], row[2])
    exact = hist.get(int(target_n))
    if exact is not None:
        return 'exact', (exact, None)
    if 0 < max_n < int(target_n):
        metrics = hist.get(max_n)
        if metrics is not None:
            state_row = con.execute("""SELECT chain_state FROM scenario_heads
                                       WHERE code_hash=? AND scenario_key=?""",
                                    (code_hash, skey)).fetchone()
            state = decode_chain_state(state_row[0]) if state_row else None
            if state is not None:
                return 'prefix', (max_n, metrics, state)
    return None, None


def get_exact(code_hash: str, skey: str, n: int):
    kind, val = lookup_target(code_hash, skey, int(n))
    return val if kind == 'exact' else None


def get_prefix(code_hash: str, skey: str, target_n: int):
    kind, val = lookup_target(code_hash, skey, int(target_n))
    return val if kind == 'prefix' else None


def _group_pending_rows(rows):
    groups = {}
    for code_hash, skey, n, level, water_mode, metrics, chain_state in rows:
        key = (code_hash, skey)
        groups.setdefault(key, []).append((int(n), int(level), water_mode, dict(metrics), chain_state))
    return groups


def _write_rows_tx(rows, *, connection=None, seed_history=None):
    """Merge many milestones with one SELECT+UPSERT per scenario, not per precision."""
    rows = list(rows or [])
    if not rows:
        return
    con = connection or _connect()
    groups = _group_pending_rows(rows)
    for attempt in range(9):
        try:
            con.execute('BEGIN IMMEDIATE')
            updates = []
            now = time.time()
            for (code_hash, skey), vals in groups.items():
                old = con.execute("""SELECT level,water_mode,max_n,metrics_blob,metrics_history_json,chain_state
                                     FROM scenario_heads WHERE code_hash=? AND scenario_key=?""",
                                  (code_hash, skey)).fetchone()
                if old:
                    old_max = int(old[2])
                    hist = decode_metrics_history(old[3], old[4])
                    state_blob = old[5]
                    level, water_mode = int(old[0]), old[1]
                else:
                    old_max = 0
                    hist = dict(seed_history or {})
                    state_blob = b''
                    level, water_mode = vals[-1][1], vals[-1][2]
                vals.sort(key=lambda x: x[0])
                max_n = old_max
                for n, lvl, wm, metrics, state in vals:
                    hist[n] = metrics
                    if n >= max_n:
                        max_n = n; level = lvl; water_mode = wm
                        if _terminal_precision(n):
                            state_blob = b''
                        elif state is not None:
                            state_blob = bytes(state) if isinstance(state, (bytes, bytearray, memoryview)) else encode_chain_state(state)
                if _terminal_precision(max_n):
                    state_blob = b''
                updates.append((code_hash, skey, int(level), water_mode, int(max_n),
                                '', state_blob or b'', now, encode_metrics_history(hist)))
            con.executemany("""INSERT INTO scenario_heads
                (code_hash,scenario_key,level,water_mode,max_n,metrics_history_json,chain_state,updated_at,metrics_blob)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(code_hash,scenario_key) DO UPDATE SET
                  level=excluded.level, water_mode=excluded.water_mode, max_n=excluded.max_n,
                  metrics_history_json=excluded.metrics_history_json, chain_state=excluded.chain_state,
                  updated_at=excluded.updated_at, metrics_blob=excluded.metrics_blob""", updates)
            con.commit()
            return
        except sqlite3.OperationalError:
            try: con.rollback()
            except Exception: pass
            if attempt == 8: raise
            time.sleep(0.02 * (2 ** attempt))
        except Exception:
            try: con.rollback()
            except Exception: pass
            raise


def put(code_hash: str, skey: str, n: int, level: int, water_mode: str, metrics: dict, chain_state: dict):
    _write_rows_tx([(code_hash, skey, n, level, water_mode, metrics, chain_state)])


def put_many(rows, chunk_size: int = 4096):
    items=list(rows or [])
    data_rows=[x for x in items if not (isinstance(x,dict) and x.get('_kind')=='meta')]
    meta_rows=[x for x in items if isinstance(x,dict) and x.get('_kind')=='meta']
    step=max(1,int(chunk_size))
    for off in range(0,len(data_rows),step): _write_rows_tx(data_rows[off:off+step])
    for off in range(0,len(meta_rows),step): _write_meta_tx(meta_rows[off:off+step])


def _writer_loop(q):
    global _WRITE_ERROR
    con = None
    try:
        ensure_db()
        con = _new_connection()
        while True:
            kind, payload = q.get()
            if kind == 'stop':
                return
            if kind == 'flush':
                payload.set(); continue
            if kind == 'meta':
                _write_meta_tx(payload, connection=con); continue
            if kind != 'rows':
                continue
            rows = list(payload)
            while len(rows) < _WRITE_BATCH_ROWS:
                try:
                    nkind, npayload = q.get_nowait()
                except queue.Empty:
                    break
                if nkind == 'rows':
                    rows.extend(npayload)
                elif nkind == 'flush':
                    if rows: _write_rows_tx(rows, connection=con)
                    rows = []
                    npayload.set()
                elif nkind == 'stop':
                    if rows: _write_rows_tx(rows, connection=con)
                    return
            if rows:
                _write_rows_tx(rows, connection=con)
    except BaseException as e:
        _WRITE_ERROR = e
    finally:
        if con is not None:
            try: con.close()
            except Exception: pass


def _ensure_writer():
    global _WRITE_QUEUE, _WRITE_THREAD
    if _WRITE_ERROR is not None:
        raise RuntimeError('cache writer failed') from _WRITE_ERROR
    if _WRITE_THREAD is not None and _WRITE_THREAD.is_alive():
        return
    with _WRITE_LOCK:
        if _WRITE_THREAD is not None and _WRITE_THREAD.is_alive():
            return
        _WRITE_QUEUE = queue.Queue()
        _WRITE_THREAD = threading.Thread(target=_writer_loop, args=(_WRITE_QUEUE,),
                                         name='pnp-cache-writer', daemon=True)
        _WRITE_THREAD.start()


def enqueue_writes(rows):
    items=list(rows or [])
    if not items:
        return
    data_rows=[x for x in items if not (isinstance(x,dict) and x.get('_kind')=='meta')]
    meta_rows=[x for x in items if isinstance(x,dict) and x.get('_kind')=='meta']
    _ensure_writer()
    if _WRITE_ERROR is not None:
        raise RuntimeError('cache writer failed') from _WRITE_ERROR
    if data_rows: _WRITE_QUEUE.put(('rows',data_rows))
    if meta_rows: _WRITE_QUEUE.put(('meta',meta_rows))


def flush_writes(timeout: float = 120.0):
    if _WRITE_THREAD is None:
        return
    if _WRITE_ERROR is not None:
        raise RuntimeError('cache writer failed') from _WRITE_ERROR
    ev = threading.Event()
    _WRITE_QUEUE.put(('flush', ev))
    if not ev.wait(timeout):
        raise TimeoutError('cache writer flush timed out')
    if _WRITE_ERROR is not None:
        raise RuntimeError('cache writer failed') from _WRITE_ERROR


def shutdown_writer():
    global _WRITE_THREAD, _WRITE_QUEUE
    if _WRITE_THREAD is None:
        return
    try:
        flush_writes()
        _WRITE_QUEUE.put(('stop', None))
        _WRITE_THREAD.join(timeout=5.0)
    finally:
        _WRITE_THREAD = None; _WRITE_QUEUE = None


atexit.register(shutdown_writer)


def _milestones(start_n: int, target_n: int):
    vals = [n for n in PRECISION_LADDER if start_n < n <= target_n]
    if target_n > start_n and target_n not in vals:
        vals.append(int(target_n))
    return sorted(set(vals))


def evaluate_policy(level, talents, policy, cfg, target_n: int, seed: int, hp_mult: float = 1.0,
                    deferred_writes: list | None = None):
    target_n = int(target_n); code_hash = current_sim_hash()
    skey = scenario_key(level, talents, policy, cfg, seed, hp_mult)
    kind, cached = lookup_target(code_hash, skey, target_n, migration_sink=deferred_writes,
                                 level=level, water_mode=_water_mode(cfg))
    if not _has_scenario_metadata(code_hash,skey):
        meta=_scenario_metadata(level,talents,policy,seed,hp_mult,code_hash,skey)
        if deferred_writes is None: _write_meta_tx([meta])
        else: deferred_writes.append(meta)
    if kind == 'exact':
        metrics = dict(cached[0]); metrics.update(_cache='hit',_sim_code_hash=code_hash,_scenario_key=skey,
                                                _extended_from_n=target_n,_simulated_new_mobs=0)
        return metrics
    prefix = cached if kind == 'prefix' else None
    continuation = prefix[2] if prefix else None
    start_n = prefix[0] if prefix else 0
    last_metrics = None
    for stop_n in _milestones(start_n, target_n):
        last_metrics, continuation = eng.simulate_chain_incremental(
            level,talents,policy,cfg,target_n=stop_n,seed=seed,hp_mult=hp_mult,continuation=continuation)
        if deferred_writes is None:
            put(code_hash, skey, stop_n, level, _water_mode(cfg), last_metrics, continuation)
        else:
            # Metrics from every ladder milestone are useful; only the highest
            # requested continuation can ever be used for a future extension.
            state_payload = (b'' if _terminal_precision(stop_n) else encode_chain_state(continuation)) if stop_n == target_n else None
            deferred_writes.append((code_hash, skey, stop_n, level, _water_mode(cfg), last_metrics, state_payload))
    if last_metrics is None:
        # Only possible for an off-ladder lower precision beneath an existing head.
        last_metrics, continuation = eng.simulate_chain_incremental(
            level,talents,policy,cfg,target_n=target_n,seed=seed,hp_mult=hp_mult,continuation=None)
        if deferred_writes is None:
            put(code_hash, skey, target_n, level, _water_mode(cfg), last_metrics, continuation)
        else:
            state_payload = b'' if _terminal_precision(target_n) else encode_chain_state(continuation)
            deferred_writes.append((code_hash, skey, target_n, level, _water_mode(cfg), last_metrics, state_payload))
        start_n = 0
    metrics = dict(last_metrics)
    metrics.update(_cache='extend' if start_n else 'miss',_extended_from_n=start_n,
                   _simulated_new_mobs=target_n-start_n,_sim_code_hash=code_hash,_scenario_key=skey)
    return metrics


def stale_hint(level, talents, policy, cfg, target_n: int, seed: int, hp_mult: float = 1.0):
    skey=scenario_key(level,talents,policy,cfg,seed,hp_mult); cur=current_sim_hash(); con=_connect()
    candidates=[]
    for ch,maxn,mblob,hjson,ts in con.execute('''SELECT code_hash,max_n,metrics_blob,metrics_history_json,updated_at
                                                  FROM scenario_heads WHERE scenario_key=? AND code_hash<>?''',(skey,cur)).fetchall():
        hist=decode_metrics_history(mblob,hjson); eligible=[n for n in hist if n<=int(target_n)]
        if eligible:
            n=max(eligible); candidates.append((ts,n,ch,hist[n]))
    for ch,n,m,ts in con.execute('''SELECT code_hash,n,metrics_json,created_at FROM chains
                                    WHERE scenario_key=? AND code_hash<>? AND n<=?''',(skey,cur,int(target_n))).fetchall():
        candidates.append((ts,int(n),ch,json.loads(m)))
    if not candidates: return None
    _ts,n,ch,m=max(candidates,key=lambda x:(x[0],x[1]))
    return {'code_hash':ch,'n':n,'metrics':m}


def has_stale_cache() -> bool:
    global _STALE_STATUS
    now=time.monotonic()
    if now-_STALE_STATUS[0] < 60.0: return _STALE_STATUS[1]
    if not DB_PATH.exists(): _STALE_STATUS=(now,False); return False
    cur=current_sim_hash(); con=_connect()
    yes=(con.execute('SELECT 1 FROM scenario_heads WHERE code_hash<>? LIMIT 1',(cur,)).fetchone() is not None or
         con.execute('SELECT 1 FROM chains WHERE code_hash<>? LIMIT 1',(cur,)).fetchone() is not None)
    _STALE_STATUS=(now,yes); return yes


def _policy_behavior_key(p):
    return tuple(getattr(p,f) for f in p.__dataclass_fields__ if f != 'name')


def _candidate_policies(level: int, talents, coarse: bool):
    policies = eng.candidate_policies_coarse(level) if coarse else eng.candidate_policies(level)
    policies = eng.with_ice_barrier_policy_variants(policies,level,talents)
    # Primary-school mode constrains rotations, never talent-tree spend.  Read
    # from the inherited environment here so Windows spawned worker processes
    # apply the exact same policy filter as the parent optimizer.
    policies = eng.filter_policies_by_primary_school(policies)
    policies=[p for p in policies if (not p.pyro_opener or talents.pyroblast>0)]
    if coarse:
        policies=[p for p in policies if p.primary!='arcane_missiles' or talents.imp_arcane_missiles>0 or talents.arcane_concentration>0]
    else:
        policies=[p for p in policies if (not p.clearcast_am or talents.arcane_concentration>0)
                  and (not p.scorch_to_stacks or talents.imp_scorch>0)]
    return policies


def optimize_policy_cached(level, talents, cfg, n: int, seed: int, coarse: bool=False,
                           defer_writes: bool=False):
    policies=_candidate_policies(level,talents,coarse)
    # Coarse mode starts from the compact cross-school basis, then performs a
    # focused Fire sequence search.  This keeps talent exploration tractable
    # while still allowing phase-shifted FBa/Sc cycles plus optimizer-selected
    # Nova/Pyro insertions. Importantly this refinement is result/search driven,
    # not gated by Improved Scorch rank or by Fire-tree point count.
    if not coarse and has_stale_cache():
        hinted=[]; counts={}
        for p in policies:
            h=stale_hint(level,talents,p,cfg,n,seed)
            if h: counts[h['code_hash']]=counts.get(h['code_hash'],0)+1
            hinted.append((p,h))
        cohort=max(counts,key=lambda k:(counts[k],k)) if counts else None
        head=sorted([(h['metrics'].get('total_s',float('inf')),p) for p,h in hinted if h and h['code_hash']==cohort],
                    key=lambda x:(x[0],repr(x[1])))
        used={repr(p) for _,p in head}; tail=sorted([p for p,_ in hinted if repr(p) not in used],key=repr)
        policies=[p for _,p in head]+tail

    best=None
    pending=[] if defer_writes else None
    seen=set()
    scored=[]

    def score_policy(p):
        nonlocal best
        k=_policy_behavior_key(p)
        if k in seen:
            return None
        seen.add(k)
        r=evaluate_policy(level,talents,p,cfg,n,seed,deferred_writes=pending)
        scored.append((p,r))
        if best is None or r['total_s']<best[1]['total_s']:
            best=(p,r)
        return r

    for p in policies:
        score_policy(p)

    if coarse and eng.configured_primary_school() in ('all','fire') and eng.latest(eng.SCORCH, level) is not None:
        # Broad sequence exploration is proposal-only: run exact 1-mob probes
        # directly in memory, then materialize/cache only the finalists at the
        # requested precision. This prevents phase/Nova/Pyro exploration from
        # exploding the multi-GB SQLite cache or multiplying high-m precision.
        probe_seed=canonical_seed(level)
        probe_n=1

        def probe(p):
            return eng.simulate_chain(level,talents,p,cfg,n=probe_n,seed=probe_seed)

        cadence_probe=[]
        for p in eng.candidate_fire_cadence_policies(level):
            cadence_probe.append((p,probe(p)))

        # Keep several phases per block shape before testing every Nova slot.
        # This preserves phase diversity rather than taking one global top lane.
        by_shape={}
        for p,r in cadence_probe:
            by_shape.setdefault((p.fireball_block,p.scorch_block),[]).append((p,r))
        nova_parents=[]
        for vals in by_shape.values():
            vals.sort(key=lambda pr:(pr[1]['total_s'],pr[0].fire_cycle_phase))
            nova_parents.extend(vals[:3])

        nova_probe=[]
        for p,_r in nova_parents:
            cycle=p.fireball_block+p.scorch_block
            for pos in range(cycle):
                q=dataclasses.replace(p,name=p.name+f'+FN@{pos}',nova_cycle_pos=pos)
                nova_probe.append((q,probe(q)))

        proposals=cadence_probe+nova_probe
        proposals.sort(key=lambda pr:pr[1]['total_s'])

        # Probe utility Frostbolt and Pyro only around the strongest sequence
        # proposals. Pyro is talent-gated; the underlying Fire cadence is not.
        utility_probe=[]
        for p,_r in proposals[:6]:
            q=dataclasses.replace(p,name=p.name+'+FBoR1-maint',fbo_r1_mode='maintain')
            utility_probe.append((q,probe(q)))
        pyro_probe=[]
        if talents.pyroblast>0:
            for p,_r in proposals[:12]:
                q=dataclasses.replace(p,name=p.name+'+PyroOpen',pyro_opener=True)
                pyro_probe.append((q,probe(q)))

        proposals=(proposals+utility_probe+pyro_probe)
        proposals.sort(key=lambda pr:pr[1]['total_s'])

        # Cache/score a compact finalist set at the requested PnP precision. Add
        # one leader per block shape so a noisy 1-mob probe cannot collapse all
        # sequence diversity into one cadence family.
        finalists=[]; fseen=set()
        def add_final(p):
            k=_policy_behavior_key(p)
            if k not in fseen:
                fseen.add(k); finalists.append(p)
        for p,_r in proposals[:12]:
            add_final(p)
        for vals in by_shape.values():
            vals.sort(key=lambda pr:pr[1]['total_s'])
            if vals: add_final(vals[0][0])
        for p in finalists:
            score_policy(p)

    return (best, pending) if defer_writes else best


def cache_stats_fast():
    """O(1) live/UI cache stats. Never scans the multi-GB SQLite tables.

    Deep row counts belong in the offline/read-only analyzer. The listener must
    remain responsive even when the cache is tens of gigabytes.
    """
    cur = current_sim_hash()
    try:
        db_bytes = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    except OSError:
        db_bytes = 0
    wal_path = Path(str(DB_PATH) + '-wal')
    try:
        wal_bytes = wal_path.stat().st_size if wal_path.exists() else 0
    except OSError:
        wal_bytes = 0
    return {
        'sim_code_hash': cur,
        'db_bytes': int(db_bytes),
        'wal_bytes': int(wal_bytes),
        'cache_schema': CACHE_SCHEMA,
        'stats_mode': 'fast_no_table_scan',
    }


def cache_stats(force: bool = False):
    global _CACHE_STATS_STATUS
    cur=current_sim_hash(); now=time.monotonic()
    if not force and _CACHE_STATS_STATUS[1] is not None and now-_CACHE_STATS_STATUS[0] < 30.0:
        return dict(_CACHE_STATS_STATUS[1])
    if not DB_PATH.exists():
        out={'sim_code_hash':cur,'rows_current':0,'rows_stale':0,'db_bytes':0,'cache_schema':CACHE_SCHEMA}
        _CACHE_STATS_STATUS=(now,out); return dict(out)
    con=_connect()
    # These are UI/diagnostic stats, not optimizer-critical. Cache the full-table
    # aggregate so browser polling cannot repeatedly scan a 600k+ row cache.
    current=con.execute('SELECT COUNT(*) FROM scenario_heads WHERE code_hash=?',(cur,)).fetchone()[0]
    stale=con.execute('SELECT COUNT(*) FROM scenario_heads WHERE code_hash<>?',(cur,)).fetchone()[0]
    maxn=con.execute('SELECT MAX(max_n) FROM scenario_heads WHERE code_hash=?',(cur,)).fetchone()[0]
    legacy=con.execute('SELECT COUNT(*) FROM chains WHERE code_hash=?',(cur,)).fetchone()[0]
    binary=con.execute('SELECT COUNT(*) FROM scenario_heads WHERE code_hash=? AND metrics_blob IS NOT NULL',(cur,)).fetchone()[0]
    out={'sim_code_hash':cur,'rows_current':int(current),'rows_stale':int(stale),
         'rows_binary':int(binary),'max_current_n':int(maxn or 0),'legacy_precision_rows':int(legacy),
         'db_bytes':DB_PATH.stat().st_size,'cache_schema':CACHE_SCHEMA}
    _CACHE_STATS_STATUS=(now,out)
    return dict(out)


def record_path_candidates(candidates, water_mode: str='buy_water'):
    """Persist full 10->60 leveling talent trajectories for the landscape.

    One row represents one *talent trajectory*, not one level/scenario and not
    one rotation variant. If the same talent path is seen with multiple policy
    paths, prefer validated data; otherwise prefer higher precision, then the
    lower full-path hour estimate at equal precision.
    """
    ensure_db(); con=_connect(); cur=current_sim_hash(); wm=str(water_mode); now=time.time()
    vals=[]
    for raw in candidates or []:
        if not isinstance(raw,dict) or not raw.get('full_arc') or not raw.get('replay'):
            continue
        tid=str(raw.get('talent_path_id') or '').strip()
        if not tid:
            continue
        validated_h=raw.get('validated_hours'); search_h=raw.get('search_hours')
        try: validated_h=None if validated_h is None else float(validated_h)
        except Exception: validated_h=None
        try: search_h=None if search_h is None else float(search_h)
        except Exception: search_h=None
        precision=int(raw.get('validation_mobs') or raw.get('search_precision_mobs') or 0)
        is_valid=1 if validated_h is not None and raw.get('sim_code_hash')==cur else 0
        vals.append((
            cur,wm,tid,str(raw.get('path_id') or raw.get('id') or ''),str(raw.get('source') or ''),
            str(raw.get('school') or 'unknown'),str(raw.get('family') or raw.get('school') or 'unknown'),
            search_h,validated_h if is_valid else None,precision,is_valid,
            json.dumps(raw.get('respec_levels') or [],separators=(',',':')),
            str(raw.get('final_allocation') or ''),
            json.dumps(raw.get('replay') or [],ensure_ascii=False,separators=(',',':')),now,
        ))
    if not vals:
        return 0
    for attempt in range(9):
        try:
            con.execute('BEGIN IMMEDIATE')
            for row in vals:
                old=con.execute("""SELECT search_hours,validated_hours,precision_mobs,validated
                                   FROM path_observations
                                   WHERE code_hash=? AND water_mode=? AND talent_path_id=?""",row[:3]).fetchone()
                replace=False
                if old is None:
                    replace=True
                else:
                    old_search,old_valid_h,old_m,old_valid=old
                    new_search,new_valid_h,new_m,new_valid=row[7],row[8],row[9],row[10]
                    if new_valid and not old_valid:
                        replace=True
                    elif new_valid and old_valid:
                        replace=(new_valid_h is not None and (old_valid_h is None or new_valid_h < old_valid_h))
                    elif not old_valid:
                        if new_m > int(old_m or 0):
                            replace=True
                        elif new_m == int(old_m or 0) and new_search is not None and (old_search is None or new_search < old_search):
                            replace=True
                if replace:
                    con.execute("""INSERT OR REPLACE INTO path_observations(
                                   code_hash,water_mode,talent_path_id,candidate_path_id,source,school,family,
                                   search_hours,validated_hours,precision_mobs,validated,respec_levels_json,
                                   final_allocation,replay_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",row)
            con.commit()
            return len(vals)
        except sqlite3.OperationalError:
            try: con.rollback()
            except Exception: pass
            if attempt==8:
                raise
            time.sleep(0.02*(2**attempt))
        except Exception:
            try: con.rollback()
            except Exception: pass
            raise
    return 0


def landscape_points(water_mode: str='buy_water', limit: int=1200):
    """Current-hash full-path talent trajectories for the interactive PCA view."""
    ensure_db(); con=_connect(); cur=current_sim_hash(); limit=max(50,min(4000,int(limit)))
    rows=con.execute("""SELECT talent_path_id,candidate_path_id,source,school,family,
                               search_hours,validated_hours,precision_mobs,validated,
                               respec_levels_json,final_allocation,replay_json,updated_at
                        FROM path_observations
                        WHERE code_hash=? AND water_mode=?
                        ORDER BY validated DESC, precision_mobs DESC, updated_at DESC LIMIT ?""",
                     (cur,str(water_mode),limit)).fetchall()
    out=[]
    for tid,pid,source,school,family,search_h,valid_h,m,validated,rsjson,final_alloc,rjson,updated in rows:
        try: replay=json.loads(rjson) if rjson else []
        except Exception: replay=[]
        try: respecs=json.loads(rsjson) if rsjson else []
        except Exception: respecs=[]
        steps=[]; rotations=[]
        for r in replay:
            try: lvl=int(r.get('level'))
            except Exception: continue
            if not (10 <= lvl <= 59):
                continue
            steps.append([lvl,str(r.get('action') or ''),str(r.get('detail') or ''),str(r.get('allocation') or '')])
            rotations.append([lvl,str(r.get('rotation') or '')])
        hours=float(valid_h) if valid_h is not None else (float(search_h) if search_h is not None else None)
        out.append({'kind':'talent_path','talent_path_id':tid,'candidate_path_id':pid,'source':source,
                    'school':school,'family':family,'hours':hours,'search_hours':search_h,
                    'validated_hours':valid_h,'validated':bool(validated),'m':int(m or 0),
                    'respec_levels':respecs,'final_build':final_alloc,'steps':steps,'rotations':rotations,
                    'updated_at':float(updated)})
    return {'sim_code_hash':cur,'water_mode':str(water_mode),'points':out,'limit':limit,'generated_at':time.time(),
            'metadata_note':'One point = one unique talent trajectory across lvl10-59 (the leveling path to ding 60). Rotation variants of the same talent path are collapsed to the best/highest-precision result.'}


def clear_current_hash():
    cur=current_sim_hash(); con=_connect()
    con.execute('DELETE FROM scenario_heads WHERE code_hash=?',(cur,))
    con.execute('DELETE FROM path_observations WHERE code_hash=?',(cur,))
    con.commit()


def compact_current_hash(batch_size: int = 2000, vacuum: bool = False, progress_callback=None):
    """Rewrite current-hash heads into the compact binary storage format.

    Intended as a one-off maintenance operation with the optimizer stopped. It
    preserves simulator keys/scores and does not change the semantic hash.
    Terminal (100-mob) rows drop continuation state because no later extension
    can consume it. VACUUM is optional because it rewrites the SQLite file.
    """
    global _CACHE_STATS_STATUS
    flush_writes()
    ensure_db()
    con = _connect()
    cur = current_sim_hash()
    batch_size = max(1, int(batch_size))
    last_rowid = 0
    converted = 0
    while True:
        rows = con.execute('''SELECT rowid,max_n,metrics_blob,metrics_history_json,chain_state
                              FROM scenario_heads
                              WHERE code_hash=? AND rowid>? AND
                                    (metrics_blob IS NULL OR substr(metrics_blob,1,4)<>? OR metrics_history_json<>'' OR
                                     (max_n>=? AND length(chain_state)>0) OR
                                     (max_n<? AND length(chain_state)>0 AND substr(chain_state,1,4)<>?))
                              ORDER BY rowid LIMIT ?''',
                           (cur, last_rowid, _METRICS_MAGIC, int(max(PRECISION_LADDER)),
                            int(max(PRECISION_LADDER)), _STATE_MAGIC, batch_size)).fetchall()
        if not rows:
            break
        updates = []
        for rowid, max_n, mblob, hjson, state_blob in rows:
            hist = decode_metrics_history(mblob, hjson)
            if _terminal_precision(max_n):
                compact_state = b''
            elif state_blob:
                compact_state = encode_chain_state(decode_chain_state(state_blob))
            else:
                compact_state = b''
            updates.append((encode_metrics_history(hist), '', compact_state, int(rowid)))
            last_rowid = int(rowid)
        con.execute('BEGIN IMMEDIATE')
        try:
            con.executemany('''UPDATE scenario_heads
                               SET metrics_blob=?,metrics_history_json=?,chain_state=?
                               WHERE rowid=?''', updates)
            con.commit()
        except Exception:
            con.rollback(); raise
        converted += len(updates)
        if progress_callback:
            progress_callback(converted)
    try:
        con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    except Exception:
        pass
    if vacuum:
        con.execute('VACUUM')
    _CACHE_STATS_STATUS = (0.0, None)
    return converted


def _main():
    import argparse
    ap = argparse.ArgumentParser(description='PnP cache maintenance')
    ap.add_argument('--compact-current', action='store_true', help='rewrite current simulator hash rows to compact binary format')
    ap.add_argument('--vacuum', action='store_true', help='VACUUM after compaction to reclaim file size')
    ap.add_argument('--batch-size', type=int, default=2000)
    args = ap.parse_args()
    if args.compact_current:
        before = cache_stats(force=True)
        print(f"[cache compact] start rows={before.get('rows_current',0)} binary={before.get('rows_binary',0)} db={before.get('db_bytes',0)/1024/1024:.1f} MiB", flush=True)
        n = compact_current_hash(args.batch_size, args.vacuum,
                                 progress_callback=lambda x: print(f'[cache compact] converted={x}', flush=True) if x % max(1,args.batch_size*10)==0 else None)
        after = cache_stats(force=True)
        print(f"[cache compact] done converted={n} binary={after.get('rows_binary',0)} db={after.get('db_bytes',0)/1024/1024:.1f} MiB", flush=True)
    else:
        print(cache_stats(force=True))


if __name__ == '__main__':
    _main()
