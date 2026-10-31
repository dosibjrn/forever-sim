from __future__ import annotations

"""Bridge analytic Fast results into the stochastic MC optimizer.

The bridge is deliberately guidance-only until MC replays a full path.  Fast
publishes:
  * per-level talent allocations under ``state/v2/mc_bridge/seeds``;
  * full legal paths in ``top_candidates.json``;
  * respec timing hints in ``respec_schedules.json``.

Before an MC run, ``inject_into_mc`` adds the Fast full paths as *unvalidated*
MC challengers.  master_optimizer's existing startup replay then scores them
with the current stochastic simulator.  import_state_priors() separately feeds
Fast allocations/respec schedules into the ordinary MC search, alongside all of
its native candidates.
"""

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Iterable

from src.engine_registry import eng
from src import optimizer_core as opt
from src import state_manager as sm

BRIDGE_ROOT = sm.STATE / 'v2' / 'mc_bridge'
SEED_DIR = BRIDGE_ROOT / 'seeds'
TOP_CANDIDATES = BRIDGE_ROOT / 'top_candidates.json'
RESPEC_SCHEDULES = BRIDGE_ROOT / 'respec_schedules.json'
MANIFEST = BRIDGE_ROOT / 'manifest.json'


def _talent_dict(t: eng.Talents) -> dict:
    return {name: int(getattr(t, name)) for name in t.__dataclass_fields__}


def _talent_key_from_dict(vals: dict) -> tuple[int, ...]:
    return tuple(int(vals.get(name, 0)) for name in eng.Talents.__dataclass_fields__)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
    except Exception:
        return default


def reset(*, water_mode: str, views: str) -> None:
    """Start a fresh Fast proposal generation without touching MC state."""
    if BRIDGE_ROOT.exists():
        shutil.rmtree(BRIDGE_ROOT, ignore_errors=True)
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    sm.atomic_write_json(MANIFEST, {
        'version': 1,
        'status': 'building',
        'water_mode': sm.normalize_water_mode(water_mode),
        'views': views,
        'started_at': time.time(),
        'updated_at': time.time(),
        'note': 'Fast analytic proposals only; MC must replay before results are authoritative.',
    })


def publish_level_candidates(level: int, nodes: Iterable, *, view: str,
                             water_mode: str, cap: int = 32) -> None:
    """Merge analytic level candidates into an MC-compatible seed-bank file."""
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    path = SEED_DIR / f'lvl_{int(level):02d}.json'
    old = _read_json(path, {})
    rows = list(old.get('candidates') or []) if isinstance(old, dict) else []
    by_key = {}
    for row in rows:
        vals = row.get('talents') if isinstance(row, dict) else None
        if isinstance(vals, dict):
            by_key[_talent_key_from_dict(vals)] = row

    for n in nodes:
        try:
            vals = _talent_dict(n.talents)
            key = _talent_key_from_dict(vals)
            score = float(n.score_s_per_100)
            pol = eng.policy_desc(n.policy, int(level)) if n.policy else ''
            row = {
                'talents': vals,
                'allocation': eng.final_allocation(n.talents),
                'source': f'fast_{view}',
                'analytic_score_s_per_100': score,
                'policy': pol,
                'view': view,
            }
        except Exception:
            continue
        prior = by_key.get(key)
        if prior is None or score < float(prior.get('analytic_score_s_per_100', float('inf'))):
            by_key[key] = row

    vals = list(by_key.values())
    vals.sort(key=lambda r: (float(r.get('analytic_score_s_per_100', float('inf'))), r.get('allocation', '')))
    payload = {
        'version': 1,
        'mode': 'fast_analytic_mc_prior_v1',
        'level': int(level),
        'meta': {
            'water_mode': sm.normalize_water_mode(water_mode),
            'guidance_only': True,
            'updated_at': time.time(),
        },
        'candidates': vals[:max(1, int(cap))],
    }
    sm.atomic_write_json(path, payload)


def _prefix_point_names(target: eng.Talents) -> list[str]:
    """Find one legal point order from empty talents to ``target``."""
    start = eng.Talents()
    target_key = tuple(int(getattr(target, n)) for n in target.__dataclass_fields__)
    memo = set()

    def key(t):
        return tuple(int(getattr(t, n)) for n in t.__dataclass_fields__)

    def dfs(cur: eng.Talents):
        ck = key(cur)
        if ck == target_key:
            return []
        if ck in memo:
            return None
        memo.add(ck)
        for name in cur.__dataclass_fields__:
            if int(getattr(cur, name)) >= int(getattr(target, name)):
                continue
            try:
                nxt = eng.add_point(cur, name)
            except Exception:
                continue
            nk = key(nxt)
            if any(nk[i] > target_key[i] for i in range(len(nk))):
                continue
            tail = dfs(nxt)
            if tail is not None:
                return [name] + tail
        return None

    out = dfs(start)
    if out is None:
        raise ValueError(f'cannot construct legal prefix for {eng.final_allocation(target)}')
    return out


def _path_to_replay(path: dict) -> list[dict]:
    steps = list(path.get('steps') or [])
    if not steps:
        raise ValueError('Fast path has no steps')
    first = steps[0]
    start_level = int(first['level'])
    first_t = opt.parse_allocation(first.get('allocation') or '')
    names = _prefix_point_names(first_t)
    expected = start_level - 9
    if len(names) != expected:
        raise ValueError(f'Fast prefix has {len(names)} points; expected {expected} at level {start_level}')

    replay = []
    cur = eng.Talents()
    # Talent points start at level 10.  Earlier prefix rows are unscored; the
    # final prefix row is the first Fast objective row and uses its actual policy.
    for i, name in enumerate(names):
        lvl = 10 + i
        cur = eng.add_point(cur, name)
        is_first_scored = lvl == start_level
        replay.append({
            'level': lvl,
            'action': 'point',
            'detail': name,
            'allocation': eng.final_allocation(cur),
            'rotation': first.get('policy') if is_first_scored else 'unscored',
            'normalized_min_per_100': (float(first.get('score_s_per_100') or 0.0) / 60.0) if is_first_scored else 0.0,
        })

    prev = first_t
    for step in steps[1:]:
        lvl = int(step['level'])
        alloc = str(step.get('allocation') or '')
        cur = opt.parse_allocation(alloc)
        kind = str(step.get('kind') or 'point')
        if kind == 'respec':
            action = 'respec'
            detail = alloc
        else:
            action = 'point'
            deltas = [n for n in eng.Talents.__dataclass_fields__
                      if int(getattr(cur, n)) == int(getattr(prev, n)) + 1]
            unchanged = all(int(getattr(cur, n)) in {int(getattr(prev, n)), int(getattr(prev, n)) + 1}
                            for n in eng.Talents.__dataclass_fields__)
            if len(deltas) != 1 or not unchanged:
                raise ValueError(f'Fast point at level {lvl} is not previous allocation + exactly one point')
            inferred = deltas[0]
            detail = str(step.get('talent_added') or '').strip()
            if detail and detail != inferred:
                raise ValueError(f'Fast talent_added mismatch at level {lvl}: {detail!r} != {inferred!r}')
            detail = inferred
        replay.append({
            'level': lvl,
            'action': action,
            'detail': detail,
            'allocation': alloc,
            'rotation': str(step.get('policy') or 'unscored'),
            'normalized_min_per_100': float(step.get('score_s_per_100') or 0.0) / 60.0,
        })
        prev = cur
    return replay


def _bridge_candidate(view: str, budget: str, path: dict, water_mode: str) -> dict:
    replay = _path_to_replay(path)
    raw = json.dumps(replay, sort_keys=True, separators=(',', ':')).encode('utf-8')
    path_id = sm.candidate_path_id_from_replay(replay)
    cid = 'fast_' + path_id
    return {
        'id': cid,
        'path_id': path_id,
        'source': f'fast_{view}_r{budget}',
        'view': view,
        'budget': int(budget),
        'water_mode': sm.normalize_water_mode(water_mode),
        'search_hours': float(path.get('hours') or 0.0),
        'validated_hours': None,
        'respecs_used': int(path.get('respecs_used') or 0),
        'respec_levels': [int(x) for x in (path.get('respec_levels') or [])],
        'final_allocation': str(path.get('final_allocation') or ''),
        'replay': replay,
        'full_arc': True,
        'replayable': True,
        'guidance_only_until_mc_replay': True,
        'created_at': time.time(),
    }


def publish_paths(view: str, paths: dict, *, water_mode: str) -> int:
    """Publish legal Fast paths and merge their allocations into seed banks."""
    existing = _read_json(TOP_CANDIDATES, [])
    if not isinstance(existing, list):
        existing = []
    by_id = {str(c.get('id')): c for c in existing if isinstance(c, dict) and c.get('id')}
    schedules = set()
    for c in existing:
        if isinstance(c, dict):
            try: schedules.add(tuple(int(x) for x in (c.get('respec_levels') or [])))
            except Exception: pass

    count = 0
    for budget, path in (paths or {}).items():
        # MC bridge candidates use a finite numeric respec budget.  Runner also
        # publishes auxiliary routes such as ``per_level_best`` in the same
        # mapping; those are valid UI/decision routes but are not finite-budget
        # DP paths and must never be parsed as an integer budget.
        if not str(budget).isdigit():
            continue
        if not isinstance(path, dict) or path.get('hours') is None or path.get('error'):
            continue
        try:
            c = _bridge_candidate(view, str(budget), path, water_mode)
        except Exception as e:
            print(f'[fast->mc] skip {view} r{budget}: {type(e).__name__}: {e}', flush=True)
            continue
        by_id[c['id']] = c
        schedules.add(tuple(c['respec_levels']))
        count += 1

        # Pin every legal path allocation into the level seed bank as well.
        for step in path.get('steps') or []:
            try:
                lvl = int(step['level'])
                t = opt.parse_allocation(step.get('allocation') or '')
                # A tiny LevelNode-like object avoids importing v2.path_dp here.
                node = type('BridgeNode', (), {
                    'talents': t,
                    'score_s_per_100': float(step.get('score_s_per_100') or 0.0),
                    'policy': opt.policy_from_desc(str(step.get('policy') or 'FBo'), lvl),
                })()
                publish_level_candidates(lvl, [node], view=f'{view}_path', water_mode=water_mode, cap=48)
            except Exception:
                continue

    vals = list(by_id.values())
    vals.sort(key=lambda c: (float(c.get('search_hours', float('inf'))), c.get('id', '')))
    sm.atomic_write_json(TOP_CANDIDATES, vals)
    sm.atomic_write_json(RESPEC_SCHEDULES, {
        'version': 1,
        'schedules': [list(x) for x in sorted(schedules)],
        'updated_at': time.time(),
    })
    manifest = _read_json(MANIFEST, {})
    if not isinstance(manifest, dict): manifest = {}
    manifest.update({'status': 'ready', 'path_candidates': len(vals), 'updated_at': time.time()})
    sm.atomic_write_json(MANIFEST, manifest)
    return count


def inject_into_mc() -> dict:
    """Offer Fast full paths to MC as unvalidated startup challengers.

    This never promotes a Fast score to MC BEST.  It reconstructs the legal
    OuterState and writes an ordinary *unvalidated* candidate card.  The
    existing MC startup replay is responsible for current-hash validation.
    """
    vals = _read_json(TOP_CANDIDATES, [])
    if not isinstance(vals, list): vals = []
    grouped = {m: [] for m in sm.WATER_MODES}
    errors = []
    for c in vals:
        if not isinstance(c, dict) or not c.get('replay'):
            continue
        mode = sm.normalize_water_mode(c.get('water_mode'))
        try:
            st = opt.outer_state_from_replay(c['replay'], cumulative_hours_hint=c.get('search_hours'))
            grouped[mode].append((c, st))
        except Exception as e:
            errors.append(f"{c.get('id','?')}: {type(e).__name__}: {e}")

    offered = {}
    sm.ensure_dirs()
    for mode, rows in grouped.items():
        if not rows: continue
        cards = []
        for rank, (raw, st) in enumerate(rows, 1):
            card = sm.candidate_dict(st, rank, f"fast_bridge_{raw.get('view','analytic')}",
                                     water_mode=mode, search_precision_mobs=0)
            card['fast_analytic_hours'] = raw.get('search_hours')
            card['fast_bridge_id'] = raw.get('id')
            cards.append(card)
        sm.merge_display_candidates(cards, max_k=max(10, len(cards) + 5), water_mode=mode)
        offered[mode] = len(cards)
    if errors:
        print('[fast->mc] bridge errors: ' + ' | '.join(errors[:5]), flush=True)
    if offered:
        print('[fast->mc] offered unvalidated full-path challengers: ' +
              ', '.join(f'{m}={n}' for m,n in offered.items()), flush=True)
    return {'offered': offered, 'errors': errors}


def main():
    ap = argparse.ArgumentParser(description='Fast -> MC proposal bridge')
    ap.add_argument('--inject', action='store_true', help='offer saved Fast paths to MC top-candidate state')
    args = ap.parse_args()
    if args.inject:
        result = inject_into_mc()
        print(json.dumps(result, indent=2))
    else:
        print(BRIDGE_ROOT)


if __name__ == '__main__':
    main()
