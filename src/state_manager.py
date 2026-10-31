from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import pickle
import shutil
import time
import zipfile
import uuid
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from src.engine_registry import eng
from src import game_context
from src import optimizer_core as opt
from src import pnp_cache
from src import presentation

ROOT = Path(__file__).resolve().parents[1]
STATE = game_context.state_root(ROOT)
RUNTIME = STATE / 'runtime'
LOGS = STATE / 'logs'
IMPORTS = STATE / 'imports'
TRACKS = STATE / 'tracks'

# Legacy pre-dual-water locations. Keep them readable for migration and for an
# in-flight old controller checkpoint, but all new results live under tracks/.
BEST = STATE / 'best'
CANDIDATES = BEST / 'candidates'
CHECKPOINTS = STATE / 'checkpoints'
HISTORY = STATE / 'history'
SEEDS = STATE / 'seeds'
USER_CONFIG = STATE / 'config.json'
VIEWER_SNAPSHOT_VERSION = 2
VALIDATION_AUTHORITY_VERSION = 'adaptive_path_race_v1'
_SEED_SUMMARY_CACHE = {}
_SEED_FILE_SUMMARY_CACHE = {}

WATER_MODES = ('buy_water', 'conjured_water')


DEFAULT_USER_CONFIG = {
    'max_respecs': 2,
}

def read_user_config() -> dict:
    cfg=dict(DEFAULT_USER_CONFIG)
    try:
        if USER_CONFIG.exists():
            raw=json.loads(USER_CONFIG.read_text(encoding='utf-8'))
            if isinstance(raw,dict): cfg.update(raw)
    except Exception:
        pass
    try: cfg['max_respecs']=max(0,min(8,int(cfg.get('max_respecs',2))))
    except Exception: cfg['max_respecs']=2
    return cfg

def write_user_config(update: dict) -> dict:
    ensure_dirs()
    cfg=read_user_config()
    if 'max_respecs' in update:
        cfg['max_respecs']=max(0,min(8,int(update['max_respecs'])))
    atomic_write_json(USER_CONFIG,cfg)
    return cfg

def normalize_water_mode(mode: str | None) -> str:
    return 'conjured_water' if str(mode or '').lower() in {'conjured','conjured_water','self','self_water','false','0'} else 'buy_water'

def track_paths(mode: str = 'buy_water'):
    mode = normalize_water_mode(mode)
    root = TRACKS / mode
    best = root / 'best'
    return SimpleNamespace(
        mode=mode, root=root, best=best, candidates=best / 'candidates',
        checkpoints=root / 'checkpoints', history=root / 'history', seeds=root / 'seeds')

def other_water_mode(mode: str) -> str:
    return 'conjured_water' if normalize_water_mode(mode) == 'buy_water' else 'buy_water'

def ensure_dirs():
    for p in (RUNTIME, LOGS, IMPORTS, TRACKS, BEST, CANDIDATES, CHECKPOINTS, HISTORY, SEEDS):
        p.mkdir(parents=True, exist_ok=True)
    if not USER_CONFIG.exists():
        try: atomic_write_json(USER_CONFIG, DEFAULT_USER_CONFIG)
        except Exception: pass
    for mode in WATER_MODES:
        tp = track_paths(mode)
        for p in (tp.root, tp.best, tp.candidates, tp.checkpoints, tp.history, tp.seeds):
            p.mkdir(parents=True, exist_ok=True)


def school_seed_dir(mode: str='buy_water', school: str='all') -> Path:
    """Persistent per-level search bank for one primary-school search scope.

    Exact stochastic policy simulations remain shared in the SQLite PnP cache,
    but ranked per-level talent banks must not be shared across constrained
    search modes: a Frost-only run must never replace the all-school incumbents.
    Keep the historical all-school path for backward compatibility.
    """
    school=eng.normalize_primary_school(school)
    tp=track_paths(mode)
    return tp.seeds if school=='all' else tp.root / f'seeds_{school}'


def talent_marginal_stats_path(mode: str='buy_water', school: str='all') -> Path:
    school=eng.normalize_primary_school(school)
    name='talent_marginal_stats.json' if school=='all' else f'talent_marginal_stats_{school}.json'
    return track_paths(mode).best / name


def _online_stat_add(stat: dict, value: float) -> dict:
    try: x=float(value)
    except Exception: return stat
    if not (x == x and abs(x) != float('inf')):
        return stat
    n=int(stat.get('count',0)); mean=float(stat.get('mean',0.0)); m2=float(stat.get('_m2',0.0))
    n2=n+1; delta=x-mean; mean2=mean+delta/n2; m2 += delta*(x-mean2)
    lo=x if n==0 else min(float(stat.get('min',x)),x)
    hi=x if n==0 else max(float(stat.get('max',x)),x)
    sd=(m2/(n2-1))**0.5 if n2>1 else 0.0
    return {'count':n2,'min':lo,'max':hi,'mean':mean2,'stdev':sd,'_m2':m2}


def update_talent_marginal_stats(samples: list[dict], mode: str='buy_water', school: str='all') -> dict:
    """Persist tiny per-talent-rank online min/max/mean/stdev priors."""
    mode=normalize_water_mode(mode); school=eng.normalize_primary_school(school); path=talent_marginal_stats_path(mode,school)
    try: obj=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except Exception: obj={}
    obj.setdefault('version',1); rows=obj.setdefault('talents',{})
    for smp in samples or []:
        name=str(smp.get('talent') or '')
        try: rank=int(smp.get('rank'))
        except Exception: continue
        if not name or name not in eng.TALENT_RULES: continue
        key=f'{name}:{rank}'
        row=rows.setdefault(key,{'talent':name,'rank':rank,'levels':{},'samples':0})
        row['samples']=int(row.get('samples',0))+1
        lvl=str(int(smp.get('level') or 0)); row.setdefault('levels',{})[lvl]=int(row.get('levels',{}).get(lvl,0))+1
        row['delta_active_dps']=_online_stat_add(dict(row.get('delta_active_dps') or {}),smp.get('delta_active_dps'))
        row['delta_min_per_100']=_online_stat_add(dict(row.get('delta_min_per_100') or {}),smp.get('delta_min_per_100'))
        row['last_sample']={k:smp.get(k) for k in ('level','n','delta_active_dps','delta_min_per_100','active_dps','min_per_100')}
    obj['updated_at']=time.time(); atomic_write_json(path,obj); return obj


def load_talent_marginal_stats(mode: str='buy_water', school: str='all') -> dict:
    path=talent_marginal_stats_path(mode,school)
    try: return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version':1,'talents':{}}
    except Exception: return {'version':1,'talents':{}}


def migrate_legacy_buy_water_state():
    """Copy pre-dual-water state into the buy-water track once, never delete it.

    All historical optimizer runs used SimConfig(use_best_water=True), so they
    belong to buy_water. The old folders remain untouched for rollback and for
    an in-flight controller whose checkpoint path still points there.
    """
    ensure_dirs()
    tp = track_paths('buy_water')
    marker = tp.root / '.legacy_migrated_v1'
    if marker.exists():
        return
    def copy_missing(src: Path, dst: Path, patterns=('*',)):
        if not src.exists(): return
        dst.mkdir(parents=True, exist_ok=True)
        for pattern in patterns:
            for x in src.glob(pattern):
                if not x.is_file(): continue
                y = dst / x.name
                if not y.exists():
                    try: shutil.copy2(x, y)
                    except OSError: pass
    copy_missing(BEST, tp.best)
    copy_missing(CANDIDATES, tp.candidates)
    copy_missing(SEEDS, tp.seeds, ('lvl_*.json',))
    copy_missing(CHECKPOINTS, tp.checkpoints, ('*.pkl',))
    atomic_write_text(marker, 'legacy best-available-water state copied; originals retained\n')


def atomic_temp_path(path: Path) -> Path:
    # Unique temp names are required because heartbeat, optimizer and listener
    # can be separate writers during startup/publication.
    return path.with_name(path.name + f'.{os.getpid()}.{uuid.uuid4().hex}.tmp')


def _replace_with_retry(tmp: Path, path: Path, timeout_s: float = 2.0):
    """Atomic replace with Windows sharing-violation tolerance.

    Antivirus/indexers/readers can briefly open the destination without
    FILE_SHARE_DELETE, making os.replace raise PermissionError/WinError 5.
    Retry with short backoff; callers decide whether final failure is fatal.
    """
    deadline = time.monotonic() + timeout_s
    delay = 0.01
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(0.20, delay * 1.7)


def atomic_write_text(path: Path, text: str, *, replace_timeout_s: float = 2.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = atomic_temp_path(path)
    try:
        tmp.write_text(text, encoding='utf-8')
        _replace_with_retry(tmp, path, replace_timeout_s)
    finally:
        try:
            if tmp.exists(): tmp.unlink()
        except OSError:
            pass


def atomic_write_json(path: Path, obj: Any):
    atomic_write_text(path, json.dumps(obj, indent=2, ensure_ascii=False))


def atomic_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = atomic_temp_path(dst)
    try:
        shutil.copy2(src, tmp)
        _replace_with_retry(tmp, dst)
    finally:
        try:
            if tmp.exists(): tmp.unlink()
        except OSError:
            pass


class CompatUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if name in {'SnapshotState', 'Event', 'OuterState'} and module in {
            '__main__', 'mage_free_respec_anytime', 'mage_free_respec_anytime_parallel',
            'optimizer_core', 'src.optimizer_core'
        }:
            return getattr(opt, name)
        if module in {'classic_mage_leveling_optimizer_v10', 'src.classic_mage_leveling_optimizer_v10'}:
            return getattr(eng, name)
        return super().find_class(module, name)


def compat_load_checkpoint(path: Path):
    with path.open('rb') as f:
        return CompatUnpickler(f).load()


def checkpoint_summary(data: dict) -> dict:
    out = {
        'phase': data.get('phase'),
        'outer_level': data.get('outer_level'),
        'snapshot_level': data.get('snapshot_level'),
        'search_meta': data.get('search_meta', {}),
    }
    layers = data.get('outer_layers')
    if layers:
        tops = opt.all_top_states(layers, top_k=8)
        out['top'] = [
            {
                'search_hours': st.cumulative_s / 3600.0,
                'respecs_used': st.respecs_used,
                'respec_levels': [ev.level for ev in st.events if ev.kind == 'respec'],
                'final_allocation': eng.final_allocation(st.talents),
            }
            for st in tops
        ]
    return out


def discover_legacy_checkpoints() -> list[Path]:
    """Find likely old optimizer checkpoints without crawling state/history.

    This lets a new package be unpacked over the existing local repo and adopt
    the checkpoint that survived the old final-CSV crash.
    """
    ensure_dirs()
    patterns = [
        '*.pkl',
        'mage_optimizer_artifacts/*_state.pkl',
        'mage_optimizer_artifacts/*/*.pkl',
    ]
    found = []
    for pattern in patterns:
        for p in ROOT.glob(pattern):
            try:
                if p.is_file() and STATE not in p.parents and not p.name.endswith('.tmp'):
                    found.append(p)
            except OSError:
                pass
    # If the package was unpacked as a child directory of the old repo,
    # also look one level up for the conventional legacy checkpoint names.
    for pattern in ('mage_free_respec*.pkl', '*_state.pkl'):
        for p in ROOT.parent.glob(pattern):
            if p.is_file() and not p.name.endswith('.tmp'):
                found.append(p)
    for p in IMPORTS.glob('*.pkl'):
        if p.is_file() and not p.name.endswith('.tmp'):
            found.append(p)
    # Unique and newest first.
    uniq = {str(p.resolve()): p for p in found}
    return sorted(uniq.values(), key=lambda p: p.stat().st_mtime, reverse=True)



def _import_add_talent(by_level: dict[int, dict], level: int, t: eng.Talents):
    try:
        level = int(level)
    except Exception:
        return
    if level < 11 or level > 60:
        return
    if t.points() != level - 9 or not opt.allocation_is_legal(t):
        return
    by_level.setdefault(level, {})[opt.talent_key(t)] = t


def _import_replay_rows(rows, by_level: dict[int, dict], schedules: set[tuple[int, ...]]):
    if not isinstance(rows, list):
        return
    rs = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            lvl = int(row.get('level'))
        except Exception:
            continue
        action = str(row.get('action') or row.get('kind') or '').lower()
        if action in {'respec', 'free respec', 'free_respec'}:
            rs.append(lvl)
        alloc = row.get('allocation') or row.get('talents_after_action') or row.get('respec_allocation')
        if isinstance(alloc, str) and alloc.strip():
            try:
                _import_add_talent(by_level, lvl, opt.parse_allocation(alloc))
            except Exception:
                pass
        vals = row.get('talents')
        if isinstance(vals, dict):
            try:
                t = eng.Talents(**{name: int(vals.get(name, 0)) for name in eng.Talents.__dataclass_fields__})
                _import_add_talent(by_level, lvl, t)
            except Exception:
                pass
    if rs:
        schedules.add(tuple(rs))


def import_state_priors(paths: Iterable[str | Path]) -> dict:
    """Read old optimizer state folders as guidance-only search priors.

    Imported folders are never modified. We extract only talent allocations and
    respec timing schedules; old numeric scores never enter authoritative state.
    The normalized priors are written under current state/imports so subsequent
    epochs can reuse them without reparsing arbitrary legacy layouts.
    """
    ensure_dirs()
    requested = [Path(x).expanduser() for x in (paths or [])]
    requested = [x for x in requested if str(x).strip()]
    seed_dirs: list[Path] = []
    all_schedules: set[tuple[int, ...]] = set()
    manifests = []

    for raw_root in requested:
        try:
            root = raw_root.resolve()
        except Exception:
            root = raw_root
        if not root.exists() or not root.is_dir():
            print(f'[state import] skip missing/non-directory: {raw_root}', flush=True)
            continue
        # Stable destination for this source path. Re-importing is idempotent and
        # refreshes the normalized prior if the old folder gained new results.
        tag = hashlib.sha1(str(root).encode('utf-8', errors='replace')).hexdigest()[:12]
        out_root = IMPORTS / 'state_priors' / tag
        seed_dir = out_root / 'seeds'
        seed_dir.mkdir(parents=True, exist_ok=True)
        by_level: dict[int, dict] = {}
        schedules: set[tuple[int, ...]] = set()
        files_seen = 0

        # 1) Seed banks / memories: cheapest and highest-value source.
        seed_files = []
        try:
            seed_files = [p for p in root.rglob('lvl_*.json')
                          if out_root not in p.parents and p.is_file()][:1000]
        except OSError:
            seed_files = []
        for fp in seed_files:
            try:
                obj = json.loads(fp.read_text(encoding='utf-8'))
            except Exception:
                continue
            files_seen += 1
            try:
                lvl = int(obj.get('level') or fp.stem.split('_')[-1])
            except Exception:
                continue
            for row in obj.get('candidates', []) if isinstance(obj, dict) else []:
                vals = row.get('talents') if isinstance(row, dict) else None
                if not isinstance(vals, dict):
                    continue
                try:
                    t = eng.Talents(**{name: int(vals.get(name, 0)) for name in eng.Talents.__dataclass_fields__})
                    _import_add_talent(by_level, lvl, t)
                except Exception:
                    pass

        # 2) Human-facing candidate/replay JSONs.
        json_names = {'top_candidates.json', 'best_replay.json'}
        json_files = []
        try:
            json_files = [p for p in root.rglob('*.json') if p.name in json_names and p.is_file()][:100]
        except OSError:
            json_files = []
        for fp in json_files:
            try:
                obj = json.loads(fp.read_text(encoding='utf-8'))
            except Exception:
                continue
            files_seen += 1
            candidates = obj if isinstance(obj, list) else [obj]
            for cand in candidates:
                if not isinstance(cand, dict):
                    continue
                _import_replay_rows(cand.get('replay'), by_level, schedules)
                rs = cand.get('respec_levels')
                if isinstance(rs, list) and rs:
                    try: schedules.add(tuple(int(x) for x in rs))
                    except Exception: pass

        # 3) Replay CSVs from older packages.
        csv_files = []
        try:
            csv_files = [p for p in root.rglob('best_replay.csv') if p.is_file()][:50]
        except OSError:
            csv_files = []
        for fp in csv_files:
            try:
                rows = list(csv.DictReader(fp.open(encoding='utf-8')))
            except Exception:
                continue
            files_seen += 1
            _import_replay_rows(rows, by_level, schedules)

        # 4) A bounded set of newest checkpoints. They can contain useful
        # allocations never published to JSON because the old run was stopped.
        checkpoint_files = []
        try:
            checkpoint_files = [p for p in root.rglob('*.pkl') if p.is_file() and not p.name.endswith('.tmp')]
            checkpoint_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            checkpoint_files = checkpoint_files[:24]
        except OSError:
            checkpoint_files = []
        for fp in checkpoint_files:
            try:
                data = compat_load_checkpoint(fp)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            files_seen += 1
            for raw_lvl, pool in (data.get('snapshot_pools') or {}).items():
                try: lvl = int(raw_lvl)
                except Exception: continue
                for st in pool or []:
                    t = getattr(st, 'talents', None)
                    if isinstance(t, eng.Talents):
                        _import_add_talent(by_level, lvl, t)
            states = [st for vals in (data.get('outer_layers') or {}).values() for st in (vals or [])]
            for st in sorted(states, key=opt.state_rank_key)[:64]:
                try:
                    for lvl, t in opt.talents_by_level(st).items():
                        _import_add_talent(by_level, lvl, t)
                    sched = opt.respec_schedule(st)
                    if sched: schedules.add(sched)
                except Exception:
                    pass

        # Bound each level's imported universe. Performance is deliberately not
        # used for pruning because old scores may be stale; keep deterministic
        # structural diversity only.
        total = 0
        for lvl, mapping in sorted(by_level.items()):
            vals = list(mapping.values())
            if len(vals) > 512:
                vals = opt._structural_prune(vals, 512, 81173 + lvl * 1009, lvl - 9)
            total += len(vals)
            payload = {
                'version': 1, 'mode': 'imported_state_prior_v1', 'level': lvl,
                'meta': {
                    'source_state_dir': str(root),
                    'note': 'Guidance-only allocations imported read-only; numeric legacy scores intentionally discarded.',
                    'updated_at': time.time(),
                },
                'candidates': [
                    {'talents': {name: getattr(t, name) for name in t.__dataclass_fields__},
                     'allocation': eng.final_allocation(t)} for t in vals
                ],
            }
            atomic_write_json(seed_dir / f'lvl_{lvl:02d}.json', payload)

        sched_list = [list(x) for x in sorted(schedules)]
        atomic_write_json(out_root / 'respec_schedules.json', {
            'version': 1, 'source_state_dir': str(root), 'schedules': sched_list,
            'updated_at': time.time(),
        })
        atomic_write_json(out_root / 'manifest.json', {
            'version': 1, 'source_state_dir': str(root), 'files_read': files_seen,
            'levels': len(by_level), 'allocations': total, 'respec_schedules': len(schedules),
            'updated_at': time.time(),
        })
        seed_dirs.append(seed_dir)
        all_schedules.update(schedules)
        manifests.append((str(root), total, len(schedules), files_seen))
        print(f'[state import] {root} -> allocations={total} levels={len(by_level)} schedules={len(schedules)} files={files_seen}', flush=True)

    return {
        'seed_dirs': seed_dirs,
        'respec_schedules': [list(x) for x in sorted(all_schedules)],
        'sources': manifests,
    }


def checkpoint_scored_start(data: dict) -> Optional[int]:
    layers = data.get('outer_layers') or {}
    states = [s for vals in layers.values() for s in vals]
    if not states:
        return None
    st = min(states, key=opt.state_rank_key)
    scored = [ev.level for ev in st.events if getattr(ev, 'score_s', 0) > 0]
    return min(scored) if scored else None


def best_legacy_checkpoint() -> Optional[tuple[Path, dict]]:
    best = None
    for p in discover_legacy_checkpoints():
        try:
            data = compat_load_checkpoint(p)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        outer_level = int(data.get('outer_level') or 0)
        snap_level = int(data.get('snapshot_level') or (max(data.get('snapshot_pools', {0: []})) if data.get('snapshot_pools') else 0))
        phase_bonus = 1000 if data.get('phase') == 'outer' else 0
        start = checkpoint_scored_start(data)
        coverage = (outer_level - start + 1) if start and outer_level >= start else 0
        # Prefer broader scored coverage over a newer narrow window that also
        # happens to end at level 60. This prevents 48-60 window checkpoints
        # from replacing a valid 11-60 legacy handoff.
        score = phase_bonus + coverage * 100 + outer_level * 10 + snap_level
        # Prefer newer only on equal coverage/phase.
        key = (score, p.stat().st_mtime)
        if best is None or key > best[0]:
            best = (key, p, data)
    if best:
        return best[1], best[2]
    return None


def adopt_legacy_if_useful() -> Optional[dict]:
    ensure_dirs()
    marker = RUNTIME / 'legacy_adopted.json'
    if marker.exists():
        try:
            prior = json.loads(marker.read_text(encoding='utf-8'))
            if prior.get('adopted'):
                return prior
            # A prior no-file result is not sticky: rescan on later launches so
            # the user can drop/copy a legacy checkpoint in without reconfiguring.
        except Exception:
            pass
    found = best_legacy_checkpoint()
    if not found:
        atomic_write_json(marker, {'adopted': False, 'reason': 'no compatible legacy checkpoint found'})
        return None
    src, data = found
    dst = CHECKPOINTS / 'legacy_latest.pkl'
    # Re-pickle through compatibility loader so future loads have stable src.* classes.
    opt.save_checkpoint(dst, data)
    atomic_copy(dst, RUNTIME / 'optimizer.pkl')
    info = {
        'adopted': True,
        'source': str(src),
        'destination': str(dst.relative_to(ROOT)),
        'summary': checkpoint_summary(data),
        'adopted_at': time.time(),
    }
    atomic_write_json(marker, info)
    return info



def normalize_rotation_desc(desc: str) -> str:
    return (desc or '').replace('Ã','×').replace('â','→').replace('â¤','≤').replace('â¥','≥')


def rotation_details(desc: str) -> list[str]:
    """Expand compact policy_desc text into browser-friendly semantics."""
    d = normalize_rotation_desc(desc)
    if not d or d == 'unscored':
        return []
    parts = [x.strip() for x in d.split('|') if x.strip()]
    out = []
    primary = parts[0] if parts else ''
    if primary == 'FBo':
        out.append('Primary: cast max-rank Frostbolt.')
    elif primary == 'FBa':
        out.append('Primary: cast max-rank Fireball.')
    elif primary == 'AM':
        out.append('Primary: channel max-rank Arcane Missiles.')
    elif primary == 'Sc':
        out.append('Primary: cast max-rank Scorch.')
    elif primary.startswith('Sc×') and '→FBa' in primary:
        n = primary.split('×',1)[1].split('→',1)[0]
        out.append(f'Build {n} Improved Scorch stack(s), then use Fireball.')
    else:
        out.append(f'Primary policy: {primary}.')
    for token in parts[1:]:
        if token.startswith('FBoR1:'):
            mode = token.split(':',1)[1]
            if mode == 'opener':
                out.append('Open with Frostbolt Rank 1 once for a cheap chill/slow.')
            elif mode == 'maintain':
                out.append('Maintain Frostbolt Rank 1 chill when it is about to expire outside melee.')
            else:
                out.append(f'Use Frostbolt Rank 1 utility mode: {mode}.')
        elif token.startswith('FBl≤'):
            pct = token.split('≤',1)[1]
            out.append(f'Use Fire Blast as an execute when the mob is at or below {pct} HP, if ready/in range.')
        elif token.startswith('FN') and '+step' in token:
            rank = 'Rank 1' if token.startswith('FNR1') else 'highest learned rank'
            yards = token.split('+step',1)[1]
            out.append(f'When the mob reaches melee, Frost Nova ({rank}) and move {yards} yd away.')
        elif token.startswith('Blink≥'):
            pct = token.split('≥',1)[1]
            out.append(f'If caught in melee while the mob still has at least {pct} HP, Blink to reopen distance.')
        elif token == 'CC→AM':
            out.append('On Clearcasting, consume the proc with Arcane Missiles.')
        else:
            out.append(token)
    return out


def rotation_relevant_talents(desc: str, level: int) -> set[str]:
    """Talents with a direct modeled effect on this exact policy/level.

    Do not infer this from words in the compact descriptor: Arcane Subtlety,
    Elemental Precision, Combustion, Improved Fireball, etc. can directly
    change the simulation without their talent name appearing in the rotation.
    """
    try:
        p = opt.policy_from_desc(normalize_rotation_desc(desc), int(level))
    except Exception:
        return set()
    return {name for name in eng.TALENT_RULES
            if eng.talent_directly_affects_policy(name, p, int(level))}


def replay_sanity_flags(row: dict) -> list[str]:
    d = normalize_rotation_desc(row.get('rotation',''))
    if not d or d == 'unscored':
        return []
    relevant = rotation_relevant_talents(d, int(row.get('level') or 0))
    flags = []
    if row.get('action') == 'point':
        name = row.get('detail','')
        if name in eng.TALENT_RULES and name not in relevant:
            flags.append(f"Point {name} is not directly used by this level's rotation; it may be future setup/prerequisite spend.")
    elif row.get('action') == 'respec':
        t = opt.parse_allocation(row.get('allocation',''))
        off = [(name, getattr(t,name)) for name in eng.TALENT_RULES if getattr(t,name) and name not in relevant]
        n = sum(v for _,v in off)
        if n >= 2:
            names = ', '.join(f'{name}={v}' for name,v in off[:6])
            flags.append(f"Respec contains {n} point(s) not directly used by this level's rotation ({names}); inspect for gating/future setup.")
    return flags


def annotate_replay(replay: list[dict]) -> list[dict]:
    out = []
    for raw in replay:
        r = dict(raw)
        r['rotation'] = normalize_rotation_desc(r.get('rotation',''))
        r['rotation_details'] = rotation_details(r['rotation'])
        r['sanity_flags'] = replay_sanity_flags(r)
        out.append(r)
    return out

def candidate_id_from_replay(replay: list[dict]) -> str:
    # Historical display id includes the score estimate. Keep this stable for
    # existing state/best_meta compatibility. `path_id` below is the precision-
    # independent identity used to dedupe the same decisions across refinements.
    core = [{k: r.get(k) for k in ('level','action','detail','allocation','rotation','normalized_min_per_100')} for r in replay]
    payload = json.dumps(core, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hashlib.sha1(payload).hexdigest()[:12]

def candidate_path_id_from_replay(replay: list[dict]) -> str:
    core = [{k: r.get(k) for k in ('level','action','detail','allocation','rotation')} for r in replay]
    payload = json.dumps(core, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hashlib.sha1(payload).hexdigest()[:12]


def talent_path_id_from_replay(replay: list[dict]) -> str:
    """Identity of the 10->60 leveling *talent trajectory* only.

    Rotation choices are intentionally excluded so the landscape has one point
    per talent path.  The final level-60 talent point is outside the ding-60
    objective, so the path consists of the decisions made at levels 10..59.
    """
    core=[]
    for r in replay or []:
        try: lvl=int(r.get('level'))
        except Exception: continue
        if 10 <= lvl <= opt.LAST_XP_LEVEL:
            core.append({'level':lvl,'allocation':r.get('allocation')})
    payload=json.dumps(core,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return hashlib.sha1(payload).hexdigest()[:16]


def _candidate_scope_from_replay(replay: list[dict]) -> tuple[Optional[int], Optional[int], bool]:
    levels = [int(r.get('level')) for r in replay if r.get('level') is not None]
    scored = [int(r.get('level')) for r in replay
              if r.get('level') is not None and float(r.get('normalized_min_per_100') or 0) > 0
              and str(r.get('rotation') or '').strip().lower() != 'unscored']
    through = max(levels) if levels else None
    scored_start = min(scored) if scored else None
    full_arc = scored_start == 11 and through == opt.LAST_XP_LEVEL
    return scored_start, through, full_arc


def _enrich_candidate_scope(c: dict) -> dict:
    c = dict(c)
    replay = c.get('replay') or []
    start, through, full_arc = _candidate_scope_from_replay(replay)
    c.setdefault('scored_start_level', start)
    c.setdefault('through_level', through)
    c.setdefault('full_arc', full_arc)
    if replay:
        # Persisted candidates from older builds may carry a stale/non-canonical
        # path_id even though their replay is the authority.  Always recompute
        # path identity from the replay so merge/startup dedupe cannot replay
        # the same decision path twice under different historical ids.
        c['path_id'] = candidate_path_id_from_replay(replay)
        c['talent_path_id'] = talent_path_id_from_replay(replay)
    else:
        c.setdefault('path_id', c.get('id'))
        c.setdefault('talent_path_id', c.get('path_id'))
    # Path school is deliberately NOT final-tree identity.  A Frost/Arcane
    # hybrid remains Frost when Frost has the most talent points on the
    # majority of leveling rows.  Recompute this even for persisted candidates
    # so old top_candidates.json files migrate automatically on next merge.
    try:
        school, counts = path_school_from_replay(replay)
        if school:
            c['school'] = school
            c['school_level_counts'] = counts
    except Exception:
        pass
    try:
        t = opt.parse_allocation(c.get('final_allocation') or (replay[-1].get('allocation') if replay else '') or '')
        _final_school, family = _talent_school_family(t)
        c['family'] = family
        c.setdefault('school', _final_school)
    except Exception:
        pass
    c.setdefault('search_precision_mobs', candidate_search_precision(c))
    return c


def _talent_school_family(t: eng.Talents) -> tuple[str, str]:
    return presentation.school_family(t)


def path_school_from_replay(replay: list[dict]) -> tuple[Optional[str], dict[str, int]]:
    """Classify a leveling path by dominant talent tree over the whole path.

    For each scored leveling row (11..59), the row votes for the tree with the
    strictly largest talent-point total.  Tied rows cast no primary vote.  The
    path school is the tree winning the most rows.  Deterministic tie-breakers
    are XP-weighted dominant-row votes, then XP-weighted total tree points.
    This matches the intended identity: a hybrid can still be Frost/Fire/Arcane
    when that tree is the largest one for most of the leveling journey.
    """
    counts = {k: 0 for k in ('frost','fire','arcane')}
    weighted_votes = {k: 0.0 for k in counts}
    weighted_points = {k: 0.0 for k in counts}
    usable = 0
    for row in replay or []:
        try:
            lvl = int(row.get('level'))
        except Exception:
            continue
        if not (11 <= lvl <= opt.LAST_XP_LEVEL):
            continue
        alloc = str(row.get('allocation') or '').strip()
        if not alloc:
            continue
        try:
            t = opt.parse_allocation(alloc)
        except Exception:
            continue
        pts = {k: eng.tree_points(t, k) for k in counts}
        w = max(0.0, float(opt.level_weight_per_100(lvl)))
        for k, v in pts.items():
            weighted_points[k] += w * float(v)
        top = max(pts.values())
        winners = [k for k, v in pts.items() if v == top]
        if len(winners) == 1:
            k = winners[0]
            counts[k] += 1
            weighted_votes[k] += w
        usable += 1
    if not usable:
        return None, counts
    order = {'frost': 0, 'fire': 1, 'arcane': 2}
    school = min(counts, key=lambda k: (-counts[k], -weighted_votes[k], -weighted_points[k], order[k]))
    return school, counts


def startup_replay_candidates(water_mode: str = 'buy_water', global_top: int = 5) -> list[dict]:
    """Select stale/full-arc top paths to replay before normal search starts.

    Selection is global prior top-N plus the best prior representative of each
    path school.  Already-current-hash validated paths are skipped.  This gives
    a new simulator hash a useful incumbent immediately without sacrificing
    school diversity.
    """
    mode = normalize_water_mode(water_mode)
    vals = [_enrich_candidate_scope(c) for c in _read_json_file(track_paths(mode).best / 'top_candidates.json', [])]
    cur = pnp_cache.current_sim_hash()
    vals = [c for c in vals
            if c.get('full_arc') and c.get('replay') and c.get('replayable', True) is not False
            and c.get('objective_version') == opt.OBJECTIVE_VERSION
            and not (c.get('validated_hours') is not None and c.get('sim_code_hash') == cur)]
    def prior_score(c):
        v = c.get('validated_hours')
        if v is None:
            v = c.get('search_hours')
        try: return float(v)
        except Exception: return float('inf')
    vals.sort(key=lambda c: (prior_score(c), -candidate_search_precision(c)))
    picked = vals[:max(0, int(global_top))]
    for school in ('frost','fire','arcane'):
        hit = next((c for c in vals if c.get('school') == school), None)
        if hit is not None:
            picked.append(hit)
    out=[]; seen=set()
    for c in picked:
        pid=c.get('path_id') or c.get('id')
        if not pid or pid in seen: continue
        seen.add(pid); out.append(c)
    return out


def candidate_search_precision(c: dict) -> int:
    try:
        if c.get('search_precision_mobs') is not None:
            return int(c.get('search_precision_mobs') or 0)
    except Exception:
        pass
    src = str(c.get('source') or '')
    marker = '_preview_'
    if marker in src:
        tail = src.rsplit(marker, 1)[-1]
        if tail.endswith('m'):
            try: return int(tail[:-1])
            except Exception: pass
    return 0


def candidate_dict(st: opt.OuterState, rank: int, source: str, validated: Optional[dict] = None, water_mode: str = 'buy_water', search_precision_mobs: Optional[int] = None) -> dict:
    replay = annotate_replay(validated['replay'] if validated else opt.replay_state(st))
    cid = candidate_id_from_replay(replay)
    path_id = candidate_path_id_from_replay(replay)
    talent_path_id = talent_path_id_from_replay(replay)
    scored_levels = [ev.level for ev in st.events if ev.score_s > 0]
    through_level = max((ev.level for ev in st.events), default=None)
    scored_start_level = min(scored_levels) if scored_levels else None
    full_arc = scored_start_level == 11 and through_level == opt.LAST_XP_LEVEL
    path_school, path_counts = path_school_from_replay(replay)
    final_school, final_family = _talent_school_family(st.talents)
    return {
        'id': cid,
        'path_id': path_id,
        'talent_path_id': talent_path_id,
        'rank': rank,
        'source': source,
        'water_mode': normalize_water_mode(water_mode),
        'use_best_water': normalize_water_mode(water_mode) == 'buy_water',
        'objective_version': opt.OBJECTIVE_VERSION,
        'target_ding_level': opt.TARGET_DING_LEVEL,
        'search_hours': st.cumulative_s / 3600.0,
        'validated_hours': validated.get('validated_hours') if validated else None,
        'validation_mobs': validated.get('validation_mobs') if validated else None,
        'validation_seed': validated.get('validation_seed') if validated else None,
        'validation_mode': validated.get('validation_mode') if validated else None,
        'sim_code_hash': validated.get('sim_code_hash') if validated else None,
        'legacy_equal_100_hours': validated.get('legacy_equal_100_hours') if validated else None,
        'kind': 'validated' if validated else ('search_challenger' if full_arc else 'search_frontier'),
        'replayable': True,
        'respecs_used': st.respecs_used,
        'respec_levels': [ev.level for ev in st.events if ev.kind == 'respec'],
        'final_allocation': eng.final_allocation(st.talents),
        'school': path_school or final_school,
        'school_level_counts': path_counts,
        'family': final_family,
        'search_precision_mobs': int(search_precision_mobs or 0),
        'scored_start_level': scored_start_level,
        'through_level': through_level,
        'full_arc': full_arc,
        'replay': replay,
    }


def write_candidate_files(candidates: list[dict], water_mode: str = 'buy_water'):
    ensure_dirs()
    tp = track_paths(water_mode)
    # Remove only generated candidate replay files, not arbitrary user files.
    for old in tp.candidates.glob('candidate_*.csv'):
        try:
            old.unlink()
        except OSError:
            pass
    atomic_write_json(tp.best / 'top_candidates.json', candidates)
    tmp = atomic_temp_path(tp.best / 'top_candidates.csv')
    with tmp.open('w', newline='', encoding='utf-8') as f:
        fields = ['rank', 'id', 'source', 'search_hours', 'validated_hours', 'validation_mobs',
                  'respecs_used', 'respec_levels', 'final_allocation']
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for c in candidates:
            row = {k: c.get(k) for k in fields}
            row['respec_levels'] = ','.join(map(str, c.get('respec_levels', [])))
            w.writerow(row)
    _replace_with_retry(tmp, tp.best / 'top_candidates.csv')

    for i, c in enumerate(candidates, 1):
        opt.write_replay_csv(tp.candidates / f'candidate_{i:02d}_{c["id"]}.csv', c['replay'])

    # `best_replay.*` is authoritative state, not merely the first display card.
    # Never let a stale-hash validated prior, an unvalidated search challenger,
    # or a partial frontier masquerade as the current replayable BEST.  Those
    # remain visible in top_candidates.* under their own categories.
    cur_hash = pnp_cache.current_sim_hash()
    authoritative = next((
        c for c in candidates
        if c.get('validated_hours') is not None
        and c.get('sim_code_hash') == cur_hash
        and c.get('objective_version') == opt.OBJECTIVE_VERSION
        and c.get('full_arc')
        and c.get('replayable', True) is not False
    ), None)
    for stale_path in (tp.best / 'best_replay.csv', tp.best / 'best_replay.json'):
        if authoritative is None:
            try: stale_path.unlink()
            except FileNotFoundError: pass
            except OSError: pass
    if authoritative is not None:
        opt.write_replay_csv(tp.best / 'best_replay.csv', authoritative['replay'])
        atomic_write_json(tp.best / 'best_replay.json', authoritative)


def load_baseline_csv(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    rows = list(csv.DictReader(path.open(encoding='utf-8')))
    if not rows:
        return None
    replay = []
    respec_levels = []
    for r in rows:
        action = r.get('action', '')
        detail = action
        if action == 'FREE RESPEC':
            respec_levels.append(int(r['level']))
            detail = r.get('respec_allocation') or action
        replay.append({
            'level': int(r['level']),
            'action': 'respec' if action == 'FREE RESPEC' else 'point',
            'detail': detail,
            'allocation': r.get('talents_after_action', ''),
            'rotation': r.get('rotation', ''),
            'normalized_min_per_100': float(r.get('total_min_100') or 0),
        })
    return {
        'id': candidate_id_from_replay(annotate_replay(replay)),
        'rank': 1,
        'source': 'baseline_100mob_csv',
        'search_hours': None,
        'validated_hours': float(rows[-1]['cumulative_hours']),
        'validation_mobs': 100,
        'validation_seed': None,
        'respecs_used': len(respec_levels),
        'respec_levels': respec_levels,
        'final_allocation': rows[-1].get('talents_after_action', ''),
        'replay': annotate_replay(replay),
    }


def refresh_candidate_annotations(water_mode: str = 'buy_water'):
    tp = track_paths(water_mode)
    p = tp.best / 'top_candidates.json'
    if not p.exists():
        return
    try:
        candidates = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return
    changed = False
    for c in candidates:
        annotated = annotate_replay(c.get('replay', []))
        if annotated != c.get('replay', []):
            c['replay'] = annotated
            changed = True
    if changed:
        write_candidate_files(candidates, water_mode)


def migrate_reference_benchmark(water_mode: str = 'buy_water'):
    """Keep the old stitched number as reference only; never as a replayable path."""
    ensure_dirs()
    water_mode = normalize_water_mode(water_mode)
    tp = track_paths(water_mode)
    ref_path = tp.best / 'reference_benchmark.json'
    baseline = load_baseline_csv(IMPORTS / 'baseline_2respec_100mob.csv') if water_mode == 'buy_water' else None

    # Capture any old baseline candidate/meta before cleaning it out.
    old_candidates = []
    cand_path = tp.best / 'top_candidates.json'
    if cand_path.exists():
        try: old_candidates = json.loads(cand_path.read_text(encoding='utf-8'))
        except Exception: old_candidates = []
    old_base = next((c for c in old_candidates if c.get('source') == 'baseline_100mob_csv'), None)
    old_meta = {}
    meta_path = tp.best / 'best_meta.json'
    if meta_path.exists():
        try: old_meta = json.loads(meta_path.read_text(encoding='utf-8'))
        except Exception: old_meta = {}

    if not ref_path.exists():
        if baseline:
            ref = dict(baseline)
        elif old_base:
            ref = dict(old_base)
        elif old_meta.get('source') == 'baseline_100mob_csv' and old_meta.get('best_validated_hours') is not None:
            ref = {
                'id': old_meta.get('candidate_id'), 'source': 'baseline_100mob_csv',
                'validated_hours': old_meta.get('best_validated_hours'),
                'validation_mobs': old_meta.get('validation_mobs', 100),
                'respec_levels': [24, 32], 'replay': [],
            }
        else:
            ref = None
        if ref:
            ref['kind'] = 'reference_benchmark'
            ref['replayable'] = False
            ref['note'] = 'Legacy/stitch benchmark only; not accepted as one coherent replayable optimizer path.'
            atomic_write_json(ref_path, ref)

    clean = [c for c in old_candidates
             if c.get('source') != 'baseline_100mob_csv' and c.get('replayable', True) is not False]
    if clean != old_candidates:
        write_candidate_files(clean, water_mode)

    if old_meta.get('source') == 'baseline_100mob_csv':
        atomic_write_json(meta_path, {
            'best_validated_hours': None,
            'candidate_id': None,
            'source': None,
            'validation_mobs': None,
            'updated_at': time.time(),
            'note': 'Awaiting first replayable full-path validation; legacy benchmark is reference-only.',
        })

def current_reference_benchmark(water_mode: str = 'buy_water') -> dict:
    p = track_paths(water_mode).best / 'reference_benchmark.json'
    if p.exists():
        try: return json.loads(p.read_text(encoding='utf-8'))
        except Exception: pass
    return {}

def migrate_objective_state(water_mode: str = 'buy_water'):
    """Quarantine pre-XP-weighted rankings without deleting historical files.

    Per-level seed banks remain valid because they are local min/100 searches.
    Full-path cumulative hours from the old equal-100-mobs-per-level objective are
    not numerically comparable with the XP-weighted journey-to-60 objective.
    """
    water_mode = normalize_water_mode(water_mode)
    tp = track_paths(water_mode)
    meta_path = tp.best / 'best_meta.json'
    cand_path = tp.best / 'top_candidates.json'
    old_meta = {}
    try:
        if meta_path.exists(): old_meta = json.loads(meta_path.read_text(encoding='utf-8'))
    except Exception:
        old_meta = {}
    if old_meta.get('objective_version') == opt.OBJECTIVE_VERSION:
        return
    # Only archive/reset if there is actual pre-weighted ranking state.
    has_old = old_meta.get('best_validated_hours') is not None
    try:
        old_candidates = json.loads(cand_path.read_text(encoding='utf-8')) if cand_path.exists() else []
    except Exception:
        old_candidates = []
    has_old = has_old or bool(old_candidates)
    if has_old:
        archive = tp.history / 'legacy_equal100_objective'
        archive.mkdir(parents=True, exist_ok=True)
        if meta_path.exists() and not (archive / 'best_meta.json').exists():
            try: atomic_copy(meta_path, archive / 'best_meta.json')
            except OSError: pass
        if cand_path.exists() and not (archive / 'top_candidates.json').exists():
            try: atomic_copy(cand_path, archive / 'top_candidates.json')
            except OSError: pass
        write_candidate_files([], water_mode)
    atomic_write_json(meta_path, {
        'best_validated_hours': None, 'candidate_id': None, 'source': None,
        'validation_mobs': None, 'objective_version': opt.OBJECTIVE_VERSION,
        'target_ding_level': opt.TARGET_DING_LEVEL, 'updated_at': time.time(),
        'note': 'Awaiting first XP-weighted replayable 11->60 validation. Old equal-100 objective archived.',
    })



def migrate_adaptive_validation_authority(water_mode: str = 'buy_water'):
    """Migrate BEST authority from fixed-N replay to adaptive whole-path race.

    Old fixed replay measurements remain useful evidence and search guidance, but
    must not remain authoritative once adaptive race semantics are enabled.
    They are preserved as ``fixed_replay_*`` fields while ``validated_hours`` is
    cleared.  A current adaptive-race BEST is preserved and merely versioned.
    """
    water_mode = normalize_water_mode(water_mode)
    tp = track_paths(water_mode)
    meta_path = tp.best / 'best_meta.json'
    cand_path = tp.best / 'top_candidates.json'
    try:
        meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
    except Exception:
        meta = {}
    try:
        candidates = json.loads(cand_path.read_text(encoding='utf-8')) if cand_path.exists() else []
    except Exception:
        candidates = []
    if not isinstance(candidates, list):
        candidates = []

    if meta.get('validation_authority_version') == VALIDATION_AUTHORITY_VERSION:
        return

    cur_hash = pnp_cache.current_sim_hash()
    preserve_best = (
        meta.get('best_validated_hours') is not None
        and meta.get('validation_mode') == 'adaptive_path_race'
        and meta.get('objective_version') == opt.OBJECTIVE_VERSION
        and meta.get('sim_code_hash') == cur_hash
    )

    if meta.get('best_validated_hours') is not None and not preserve_best:
        archive = tp.history / 'legacy_fixed_validation_authority'
        archive.mkdir(parents=True, exist_ok=True)
        if meta_path.exists() and not (archive / 'best_meta.json').exists():
            try: atomic_copy(meta_path, archive / 'best_meta.json')
            except OSError: pass
        if cand_path.exists() and not (archive / 'top_candidates.json').exists():
            try: atomic_copy(cand_path, archive / 'top_candidates.json')
            except OSError: pass

    changed = False
    migrated = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        c = dict(raw)
        if c.get('validated_hours') is not None and c.get('validation_mode') != 'adaptive_path_race':
            c['fixed_replay_hours'] = c.get('validated_hours')
            c['fixed_replay_mobs'] = c.get('validation_mobs')
            c['fixed_replay_validation_mode'] = c.get('validation_mode')
            c['fixed_replay_sim_code_hash'] = c.get('sim_code_hash')
            c['validated_hours'] = None
            c['validation_mobs'] = None
            c['validation_mode'] = 'fixed_policy_replay_provisional'
            c['sim_code_hash'] = None
            changed = True
        migrated.append(c)
    if changed:
        write_candidate_files(migrated, water_mode)

    if preserve_best:
        meta = dict(meta)
        meta['validation_authority_version'] = VALIDATION_AUTHORITY_VERSION
        meta['updated_at'] = time.time()
    else:
        meta = {
            'best_validated_hours': None,
            'candidate_id': None,
            'source': None,
            'validation_mobs': None,
            'validation_mode': None,
            'validation_authority_version': VALIDATION_AUTHORITY_VERSION,
            'objective_version': opt.OBJECTIVE_VERSION,
            'target_ding_level': opt.TARGET_DING_LEVEL,
            'sim_code_hash': cur_hash,
            'updated_at': time.time(),
            'note': 'Awaiting resolved adaptive whole-path stochastic race.',
        }
    atomic_write_json(meta_path, meta)

def seed_baseline_if_needed(water_mode: str = 'buy_water'):
    ensure_dirs()
    water_mode = normalize_water_mode(water_mode)
    tp = track_paths(water_mode)
    migrate_reference_benchmark(water_mode)
    migrate_objective_state(water_mode)
    # There may be no replayable validated candidate yet. That is intentional:
    # the legacy stitched 36.5668 h value is a reference benchmark, not a path.
    target = tp.best / 'top_candidates.json'
    if target.exists():
        refresh_candidate_annotations(water_mode)
    else:
        write_candidate_files([], water_mode)
    meta = tp.best / 'best_meta.json'
    if not meta.exists():
        atomic_write_json(meta, {
            'best_validated_hours': None, 'candidate_id': None, 'source': None,
            'validation_mobs': None, 'objective_version': opt.OBJECTIVE_VERSION,
            'target_ding_level': opt.TARGET_DING_LEVEL, 'updated_at': time.time(),
        })

def _best_meta_path(water_mode: str = 'buy_water', school: str = 'all') -> Path:
    school=eng.normalize_primary_school(school)
    name='best_meta.json' if school=='all' else f'best_meta_{school}.json'
    return track_paths(water_mode).best / name


def current_best_meta(water_mode: str = 'buy_water', school: str = 'all') -> dict:
    school=eng.normalize_primary_school(school)
    p = _best_meta_path(water_mode,school)
    if p.exists():
        try:
            obj = json.loads(p.read_text(encoding='utf-8'))
            if obj.get('objective_version') != opt.OBJECTIVE_VERSION:
                return {'best_validated_hours': None, 'objective_version': opt.OBJECTIVE_VERSION}
            cur_hash=pnp_cache.current_sim_hash()
            if obj.get('sim_code_hash') != cur_hash:
                return {'best_validated_hours': None, 'objective_version': opt.OBJECTIVE_VERSION,
                        'sim_code_hash': cur_hash, 'stale_previous_hours': obj.get('best_validated_hours'),
                        'stale_previous_hash': obj.get('sim_code_hash')}
            return obj
        except Exception:
            pass
    return {'best_validated_hours': None, 'primary_school': school}


def _write_best_candidate_meta(candidate: dict, checkpoint: Optional[Path], water_mode: str, school: str = 'all') -> bool:
    water_mode = normalize_water_mode(water_mode)
    tp = track_paths(water_mode)
    school=eng.normalize_primary_school(school)
    atomic_write_json(_best_meta_path(water_mode,school), {
        'best_validated_hours': candidate['validated_hours'],
        'candidate_id': candidate['id'],
        'source': candidate['source'],
        'water_mode': water_mode,
        'primary_school': school,
        'validation_mobs': candidate.get('validation_mobs'),
        'validation_mode': candidate.get('validation_mode'),
        'validation_authority_version': (VALIDATION_AUTHORITY_VERSION if candidate.get('validation_mode') == 'adaptive_path_race' else None),
        'sim_code_hash': candidate.get('sim_code_hash'),
        'objective_version': opt.OBJECTIVE_VERSION,
        'target_ding_level': opt.TARGET_DING_LEVEL,
        'updated_at': time.time(),
    })
    if checkpoint and checkpoint.exists():
        cp_name='best_checkpoint.pkl' if school=='all' else f'best_checkpoint_{school}.pkl'
        atomic_copy(checkpoint, tp.best / cp_name)
    return True


def set_authoritative_race_winner(candidate: dict, checkpoint: Optional[Path] = None, water_mode: str = 'buy_water', school: str = 'all') -> bool:
    """Replace BEST with a uniquely resolved adaptive-race winner.

    Unlike ordinary improvement promotion, this deliberately allows the new
    estimate to be numerically slower than the previous BEST: the previous
    estimate is superseded evidence, not a competing authoritative truth.
    """
    if candidate.get('validated_hours') is None:
        return False
    if candidate.get('objective_version') != opt.OBJECTIVE_VERSION:
        return False
    if candidate.get('validation_mode') != 'adaptive_path_race':
        return False
    if candidate.get('sim_code_hash') != pnp_cache.current_sim_hash():
        return False
    school=eng.normalize_primary_school(school)
    if school!='all' and not opt.replay_matches_primary_school(candidate.get('replay') or [],school):
        return False
    return _write_best_candidate_meta(candidate, checkpoint, water_mode, school)


def promote_if_better(candidate: dict, checkpoint: Optional[Path] = None, water_mode: str = 'buy_water', *, require_adaptive: bool = False, school: str = 'all') -> bool:
    if candidate.get('validated_hours') is None or candidate.get('objective_version') != opt.OBJECTIVE_VERSION:
        return False
    if require_adaptive and candidate.get('validation_mode') != 'adaptive_path_race':
        return False
    # Stale simulator cohorts may guide search, but can never become BEST.
    if candidate.get('sim_code_hash') != pnp_cache.current_sim_hash():
        return False
    water_mode = normalize_water_mode(water_mode)
    school=eng.normalize_primary_school(school)
    if school!='all' and not opt.replay_matches_primary_school(candidate.get('replay') or [],school):
        return False
    old = current_best_meta(water_mode,school).get('best_validated_hours')
    if old is not None and candidate['validated_hours'] >= old - 1e-12:
        return False
    return _write_best_candidate_meta(candidate, checkpoint, water_mode, school)


def _seed_summary_signature(mode: str, school: str='all'):
    seed_dir = school_seed_dir(mode,school)
    try:
        return tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(seed_dir.glob('lvl_*.json')))
    except OSError:
        return ()


def viewer_seed_summaries(mode: str, school: str='all'):
    mode = normalize_water_mode(mode); school=eng.normalize_primary_school(school)
    cache_key=(mode,school)
    sig = _seed_summary_signature(mode,school)
    cached = _SEED_SUMMARY_CACHE.get(cache_key)
    if cached and cached[0] == sig:
        return cached[1]
    out=[]
    live_keys=set()
    for name, mtime, size in sig:
        p=school_seed_dir(mode,school) / name
        key=(str(p), int(mtime), int(size)); live_keys.add(key)
        summary=_SEED_FILE_SUMMARY_CACHE.get(key)
        if summary is None:
            try: obj=json.loads(p.read_text(encoding='utf-8'))
            except Exception: continue
            rows=obj.get('candidates') or []
            if not rows: continue
            best=dict(rows[0])
            lvl=int(obj.get('level') or 0)
            if lvl:
                for k,v in opt.objective_level_meta(lvl).items(): best.setdefault(k,v)
            best['rotation_details']=rotation_details(best.get('policy') or '')
            summary={'level':lvl,'mode':obj.get('mode'),'candidate_count':len(rows),'best':best}
            _SEED_FILE_SUMMARY_CACHE[key]=summary
        out.append(summary)
    # Bound cache to current file versions plus a little slack; replaced seed
    # banks should not accumulate forever over a multi-day anytime run.
    if len(_SEED_FILE_SUMMARY_CACHE) > 256:
        for k in list(_SEED_FILE_SUMMARY_CACHE):
            if k not in live_keys:
                _SEED_FILE_SUMMARY_CACHE.pop(k, None)
    _SEED_SUMMARY_CACHE[cache_key]=(sig,out)
    return out


def current_validated_path_ids(water_mode: str = 'buy_water', school: str = 'all') -> set[str]:
    mode=normalize_water_mode(water_mode); p=track_paths(mode).best/'top_candidates.json'
    vals=_read_json_file(p, [])
    cur=pnp_cache.current_sim_hash(); out=set(); school=eng.normalize_primary_school(school)
    for raw in vals:
        c=_enrich_candidate_scope(raw)
        if school!='all' and not opt.replay_matches_primary_school(c.get('replay') or [],school):
            continue
        if c.get('validated_hours') is not None and c.get('sim_code_hash')==cur:
            out.add(c.get('path_id') or c.get('id'))
    return {x for x in out if x}


def top_candidates_by_school(candidates: list[dict]) -> dict:
    candidates=[_enrich_candidate_scope(c) for c in (candidates or [])]
    cur=pnp_cache.current_sim_hash()
    def key(c):
        if c.get('validated_hours') is not None and c.get('sim_code_hash')==cur:
            return (0, float(c.get('validated_hours') or 1e99), 0)
        if c.get('validated_hours') is None and c.get('full_arc'):
            return (1, -candidate_search_precision(c), float(c.get('search_hours') or 1e99))
        if c.get('validated_hours') is not None:
            return (2, float(c.get('validated_hours') or 1e99), 0)
        return (3, -(c.get('through_level') or 0), float(c.get('search_hours') or 1e99))
    out={}
    for school in ('frost','fire','arcane'):
        vals=[c for c in candidates if c.get('school')==school]
        if vals: out[school]=min(vals,key=key)
    return out


def viewer_snapshot_path(mode: str) -> Path:
    return RUNTIME / f'viewer_{normalize_water_mode(mode)}.json'


def viewer_snapshot_payload(mode: str = 'buy_water', status_override: Optional[dict] = None) -> dict:
    mode=normalize_water_mode(mode); tp=track_paths(mode)
    status=dict(status_override) if status_override is not None else _read_json_file(RUNTIME/'status.json', {})
    school=eng.normalize_primary_school(status.get('school','all'))
    candidates=[_enrich_candidate_scope(c) for c in _read_json_file(tp.best/'top_candidates.json', [])]
    if school!='all':
        candidates=[c for c in candidates if opt.replay_matches_primary_school(c.get('replay') or [],school)]
    seed_by={m:viewer_seed_summaries(m,school) for m in WATER_MODES}
    return {
        'viewer_snapshot_version': VIEWER_SNAPSHOT_VERSION, 'generated_at': time.time(),
        'water_mode':mode, 'status':status,
        'best':current_best_meta(mode,school),
        'best_by_water':{m:current_best_meta(m,school) for m in WATER_MODES},
        'best_all_school':current_best_meta(mode,'all'),
        'reference':_read_json_file(tp.best/'reference_benchmark.json', {}),
        'candidates':candidates, 'top_by_school':top_candidates_by_school(candidates),
        'controller':_read_json_file(RUNTIME/'controller.json', {}),
        'seed_levels':seed_by[mode], 'seed_levels_by_water':seed_by,
        'user_config':read_user_config(), 'pnp_cache':pnp_cache.cache_stats_fast(),
    }


def _read_json_file(path: Path, default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except Exception: return default


def publish_viewer_snapshot(mode: str = 'buy_water', status_override: Optional[dict] = None):
    """Publish one tiny pre-aggregated file; listener requests do no DB scans."""
    try:
        atomic_write_json(viewer_snapshot_path(mode), viewer_snapshot_payload(mode, status_override))
    except OSError as e:
        try: print(f'[viewer warning] snapshot skipped: {type(e).__name__}: {e}', flush=True)
        except Exception: pass


def publish_status(status: dict):
    """Publish ephemeral UI state. Never let UI/status I/O kill compute."""
    status = dict(status)
    status['updated_at'] = time.time()
    try:
        atomic_write_json(RUNTIME / 'status.json', status)
    except OSError as e:
        # status.json is advisory only; optimizer checkpoints/results are the
        # authoritative state. A transient Windows sharing violation must not
        # abort an expensive search. Keep stdout ASCII-safe as well.
        try:
            print(f'[status warning] publish skipped: {type(e).__name__}: {e}', flush=True)
        except Exception:
            pass


def heartbeat_snapshot(status: dict, keep: int = 288):
    ensure_dirs()
    mode = normalize_water_mode(status.get('water_mode'))
    hb_dir = track_paths(mode).history / 'heartbeats'
    hb_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    atomic_write_json(hb_dir / f'{stamp}.json', status)
    files = sorted(hb_dir.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def make_chat_handoff():
    """Small single-file handoff containing both water tracks."""
    ensure_dirs()
    dst = STATE / 'chat_handoff.zip'
    tmp = atomic_temp_path(dst)
    include = [
        RUNTIME / 'controller.json', RUNTIME / 'status.json', RUNTIME / 'optimizer.pkl',
        ROOT / 'src' / 'optimizer_core.py', ROOT / 'src' / 'classic_mage_leveling_optimizer_v10.py',
        ROOT / 'src' / 'master_optimizer.py', ROOT / 'src' / 'state_manager.py',
        ROOT / 'src' / 'listener.py', ROOT / 'src' / 'pnp_cache.py', USER_CONFIG, ROOT / 'run.sh', ROOT / 'run.ps1',
    ]
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in include:
            if p.exists(): z.write(p, p.relative_to(ROOT))
        for mode in WATER_MODES:
            tp = track_paths(mode)
            for p in [tp.best / 'best_meta.json', tp.best / 'reference_benchmark.json',
                      tp.best / 'top_candidates.json', tp.best / 'top_candidates.csv',
                      tp.best / 'best_replay.json', tp.best / 'best_replay.csv']:
                if p.exists(): z.write(p, p.relative_to(ROOT))
            for p in sorted(tp.candidates.glob('candidate_*.csv')):
                try:
                    z.write(p, p.relative_to(ROOT))
                except FileNotFoundError:
                    # Candidate files are a rotating display cache.  A concurrent
                    # write_candidate_files() may replace them between glob() and
                    # ZipFile.write(); skipping that one file is safe because the
                    # authoritative JSON/CSV snapshots are included separately.
                    continue
            for school in eng.PRIMARY_SCHOOLS:
                sd=school_seed_dir(mode,school)
                for p in sorted(sd.glob('lvl_*.json')):
                    z.write(p, p.relative_to(ROOT))
                for p in sorted((sd / 'memory').glob('lvl_*.json')) if (sd / 'memory').exists() else []:
                    z.write(p, p.relative_to(ROOT))
        # Keep the next ChatGPT session from reconstructing architecture from
        # stale conversation history.  These files are tiny and are part of the
        # handoff contract, while the potentially huge SQLite cache stays local.
        for p in [ROOT / 'HANDOVER_NEXT_SESSION.md', ROOT / 'README_PNP.md',
                  ROOT / 'README_DUAL_WATER.md', ROOT / 'README_XP_WEIGHTING.md',
                  ROOT / 'tests' / 'test_pnp_review.py']:
            if p.exists(): z.write(p, p.relative_to(ROOT))
    _replace_with_retry(tmp, dst)

def _merge_same_path_candidate(prior: dict, current: dict) -> dict:
    """Merge two representations of one canonical path without losing provenance.

    Validation/search fields from ``current`` win, but proposal metadata (notably
    Fast analytic evidence) survives so the viewer can explain model deltas.
    """
    out = dict(prior)
    out.update(current)

    sources = []
    for row in (prior, current):
        for src in list(row.get('sources') or []) + ([row.get('source')] if row.get('source') else []):
            if src and src not in sources:
                sources.append(src)
    if sources:
        out['sources'] = sources

    for row in (prior, current):
        for key, value in row.items():
            if key.startswith('fast_') and value is not None:
                out[key] = value

    fast_h = out.get('fast_analytic_hours')
    mc_h = out.get('validated_hours')
    if fast_h is not None and mc_h is not None:
        out['fast_vs_mc_delta_hours'] = float(mc_h) - float(fast_h)
    return out


def merge_display_candidates(new_candidates: Iterable[dict], max_k: int = 8, water_mode: str = 'buy_water'):
    old = []
    water_mode = normalize_water_mode(water_mode)
    tp = track_paths(water_mode)
    p = tp.best / 'top_candidates.json'
    if p.exists():
        try:
            old = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            old = []
    old = [_enrich_candidate_scope(c) for c in old]
    incoming = [_enrich_candidate_scope(c) for c in new_candidates]
    # Landscape persistence is deliberately separate from the tiny display
    # shortlist: every full-arc candidate reaching this merge is retained as a
    # full 10->60 talent trajectory observation.
    pnp_cache.record_path_candidates(incoming, water_mode)
    by_id = {(c.get('path_id') or c.get('id')): c for c in old if (c.get('path_id') or c.get('id'))}
    for c in incoming:
        ckey = c.get('path_id') or c.get('id')
        prior = by_id.get(ckey)
        # Same exact path: validated beats unvalidated; otherwise keep the
        # highest-precision search estimate, not a lucky stale 1-mob number.
        if prior is None:
            by_id[ckey] = c
        elif c.get('validated_hours') is not None:
            by_id[ckey] = _merge_same_path_candidate(prior, c)
        elif prior.get('validated_hours') is not None:
            # Keep authoritative validation, but retain any new proposal/source
            # metadata for diagnostics and Fast-vs-MC parity.
            by_id[ckey] = _merge_same_path_candidate(c, prior)
        elif candidate_search_precision(c) >= candidate_search_precision(prior):
            by_id[ckey] = _merge_same_path_candidate(prior, c)
        else:
            by_id[ckey] = _merge_same_path_candidate(c, prior)
    vals = [c for c in by_id.values()
            if c.get('source') != 'baseline_100mob_csv' and c.get('replayable', True) is not False
            and c.get('objective_version') == opt.OBJECTIVE_VERSION]
    cur_hash=pnp_cache.current_sim_hash()
    current_validated = sorted(
        [c for c in vals if c.get('validated_hours') is not None and c.get('sim_code_hash')==cur_hash],
        key=lambda c: c['validated_hours'])
    stale_validated = sorted(
        [c for c in vals if c.get('validated_hours') is not None and c.get('sim_code_hash')!=cur_hash],
        key=lambda c: c['validated_hours'])
    full_challengers = sorted(
        [c for c in vals if c.get('validated_hours') is None and c.get('full_arc')],
        key=lambda c: (-candidate_search_precision(c),
                       c.get('search_hours') if c.get('search_hours') is not None else float('inf')))
    frontier = sorted(
        [c for c in vals if c.get('validated_hours') is None and not c.get('full_arc')],
        key=lambda c: (-(c.get('through_level') or 0), -candidate_search_precision(c),
                       c.get('search_hours') if c.get('search_hours') is not None else float('inf')))

    # Keep a small school-diverse lane in addition to the global top list. This
    # makes Fire/Frost/Arcane challengers visible even when one school dominates
    # the coarse global ranking.
    school_pool = current_validated + full_challengers + stale_validated + frontier
    school_leaders = []
    for school in ('frost','fire','arcane'):
        hit = next((c for c in school_pool if c.get('school') == school), None)
        if hit is not None:
            school_leaders.append(hit)

    combined = current_validated[:max_k] + stale_validated[:max_k] + full_challengers[:max_k] + frontier[:max_k] + school_leaders
    out=[]; seen=set()
    for c in combined:
        cid=c.get('id')
        if cid in seen: continue
        seen.add(cid); out.append(c)
    for i, c in enumerate(out, 1):
        c['rank'] = i
    write_candidate_files(out, water_mode)
    return out
