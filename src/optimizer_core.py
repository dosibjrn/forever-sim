#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
import os
import pickle
import random
import signal
import time
import uuid
import json
import hashlib
from concurrent.futures import ProcessPoolExecutor, as_completed, wait, FIRST_COMPLETED
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.engine_registry import eng
from src import pnp_cache
from src import policy_codec


# Authoritative Classic Era 11->60 objective lives in one shared module.
from src import objective as objective_model

OBJECTIVE_VERSION = objective_model.OBJECTIVE_VERSION
TARGET_DING_LEVEL = objective_model.TARGET_DING_LEVEL
LAST_XP_LEVEL = objective_model.LAST_XP_LEVEL
XP_TO_NEXT_LEVEL = objective_model.XP_TO_NEXT_LEVEL
same_level_mob_xp = objective_model.same_level_mob_xp
xp_to_next = objective_model.xp_to_next
estimated_same_level_mobs = objective_model.estimated_same_level_mobs
estimated_workload_mobs = objective_model.estimated_workload_mobs
level_weight_per_100 = objective_model.level_weight_per_100
search_level_weight_per_100 = objective_model.search_level_weight_per_100
objective_level_meta = objective_model.objective_level_meta

STRUCTURAL_FRONTIER_CACHE_VERSION = 'structural_frontier_v2_fixed_base'
STRUCTURAL_FRONTIER_BASE_SEED = 0x5A17C0DE
STRUCTURAL_FRONTIER_MAX_WIDTH = 192
# Bump when outer-DP pruning/probe semantics change incompatibly with saved outer_layers.
OUTER_SEARCH_SEMANTICS_VERSION = 2


@dataclass
class SnapshotState:
    talents: eng.Talents
    local_s: float = math.inf
    policy: Optional[eng.Policy] = None
    relative_se: float = math.inf


@dataclass
class Event:
    level: int
    kind: str
    detail: str
    policy: str
    score_s: float


@dataclass
class OuterState:
    talents: eng.Talents
    cumulative_s: float
    respecs_used: int
    events: List[Event] = field(default_factory=list)
    last_respec_level: Optional[int] = None
    # Secondary objective only. Search time remains the primary objective; this
    # breaks exact score ties in favor of talent spends that actually support
    # the selected per-level policy instead of TALENT_RULES insertion order.
    coherence_penalty: float = 0.0


CheckpointCallback = Optional[Callable[[dict], None]]


class StopRequested(Exception):
    """Raised only after an atomic checkpoint when the parent requested stop."""


_TALENT_VALUE_PRIOR = {}

def set_talent_value_prior(stats: dict | None):
    """Load tiny persisted per-talent-rank marginal priors for runtime proposals.

    Exact simulation remains the oracle; this only orders local mutation probes.
    """
    global _TALENT_VALUE_PRIOR
    out={}
    for row in ((stats or {}).get('talents') or {}).values():
        try:
            name=str(row.get('talent')); rank=int(row.get('rank'))
            d=row.get('delta_active_dps') or {}
            # Max observed gain is intentionally optimistic: it answers
            # "has this rank ever been useful?" for proposal ordering.
            val=float(d.get('max',0.0) or 0.0)
            if name in eng.TALENT_RULES and val==val:
                out[(name,rank)]=val
        except Exception:
            continue
    _TALENT_VALUE_PRIOR=out

def talent_value_prior(t: eng.Talents) -> float:
    total=0.0
    for name in eng.TALENT_RULES:
        for rank in range(1,int(getattr(t,name))+1):
            total += max(0.0,float(_TALENT_VALUE_PRIOR.get((name,rank),0.0)))
    return total


def _worker_init():
    # On Windows spawn workers otherwise receive Ctrl-C with the parent and each
    # prints its own traceback. The parent owns shutdown/checkpoint semantics.
    # On fork-based platforms also discard any inherited SQLite connection;
    # sharing a live sqlite3 connection across processes can deadlock reads.
    try:
        pnp_cache.close_connection()
    except Exception:
        pass
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        pass


def talent_alignment_penalty(t: eng.Talents, p: Optional[eng.Policy]) -> float:
    """Soft secondary measure of how much the current build supports policy p.

    This never overrides a strictly faster simulation score: it is used only as
    a secondary sort key. Neutral prerequisite filler in an active tree receives
    a small penalty; points in an unrelated tree receive a larger one.
    """
    if p is None:
        return 0.0
    relevant = {
        'arcane_subtlety', 'arcane_concentration', 'arcane_meditation', 'arcane_resilience',
        'arcane_mind', 'arcane_instability',
    }
    active_trees = set()

    frost_cast = p.primary == 'frostbolt' or p.fbo_r1_mode != 'none'
    fire_cast = (p.primary in ('fireball', 'scorch') or p.fireball_block > 0
                 or p.scorch_block > 0 or p.scorch_to_stacks > 0 or p.use_fireblast
                 or p.pyro_opener)
    arcane_cast = p.primary == 'arcane_missiles' or p.clearcast_am

    if frost_cast:
        active_trees.add('frost')
        relevant.update({'imp_frostbolt','elemental_precision','ice_shards','frostbite',
                         'permafrost','piercing_ice','arctic_reach','frost_channeling',
                         'winters_chill','ice_barrier','master_elements'})
    if p.use_nova:
        active_trees.add('frost')
        relevant.update({'imp_frost_nova','arctic_reach','shatter'})
    if fire_cast:
        active_trees.add('fire')
        relevant.update({'elemental_precision','impact','ignite','flame_throwing',
                         'burning_soul','master_elements','critical_mass','fire_power','combustion'})
        if p.primary == 'fireball' or p.fireball_block > 0 or p.scorch_to_stacks > 0:
            relevant.add('imp_fireball')
        if p.pyro_opener:
            relevant.add('pyroblast')
        if p.use_fireblast:
            relevant.update({'imp_fire_blast','incinerate'})
        if p.primary == 'scorch' or p.scorch_block > 0 or p.scorch_to_stacks > 0:
            relevant.update({'imp_scorch','incinerate'})
    if arcane_cast:
        active_trees.add('arcane')
        relevant.update({'arcane_subtlety','arcane_focus','imp_arcane_missiles','arcane_concentration',
                         'arcane_meditation','arcane_resilience','arcane_mind','arcane_instability'})

    # Arcane utility can support any school even if Arcane is not primary.
    if any(getattr(t, n, 0) for n in ('arcane_concentration','arcane_meditation','arcane_mind','arcane_instability')):
        active_trees.add('arcane')

    penalty = 0.0
    neutral_fillers = {'frost_warding','improved_blizzard','cold_snap','ice_block','improved_cone_of_cold','arcane_filler',
                       'improved_flamestrike','fire_warding'}
    for name, (tree, _mx, _need, _pre) in eng.TALENT_RULES.items():
        pts = getattr(t, name)
        if not pts or name in relevant:
            continue
        if tree in active_trees:
            penalty += pts * (0.15 if name in neutral_fillers else 0.25)
        else:
            penalty += pts * 1.0
    return penalty


def snapshot_rank_key(st: SnapshotState):
    return (st.local_s, talent_alignment_penalty(st.talents, st.policy), talent_key(st.talents))


def state_rank_key(st: OuterState):
    return (st.cumulative_s, getattr(st, 'coherence_penalty', 0.0), talent_key(st.talents))


def tree_triplet(t: eng.Talents) -> Tuple[int, int, int]:
    return (eng.tree_points(t, 'frost'), eng.tree_points(t, 'arcane'), eng.tree_points(t, 'fire'))


def talent_key(t: eng.Talents):
    return eng.talent_key(t)


def diversity_bucket(t: eng.Talents):
    f, a, fi = tree_triplet(t)
    return (
        min(10, f // 5), min(10, a // 5), min(10, fi // 5),
        min(2, t.imp_frost_nova), min(1, t.arcane_resilience),
        min(1, t.shatter), min(1, t.frost_channeling),
        min(1, t.ice_barrier),
        min(1, t.arcane_subtlety), min(1, t.arcane_concentration), min(1, t.arcane_mind),
        min(1, t.pyroblast), min(1, t.combustion),
        min(1, t.master_elements), min(1, t.fire_power),
    )


def retain_diverse(items, width: int, score_fn, talent_fn, exploration_frac: float = 0.15):
    if len(items) <= width:
        return sorted(items, key=score_fn)
    ranked = sorted(items, key=score_fn)
    global_n = max(1, int(width * max(0.25, 0.5 - exploration_frac / 2)))
    chosen = ranked[:global_n]
    seen_keys = {talent_key(talent_fn(x)) for x in chosen}

    best_by_bucket = {}
    for x in ranked:
        b = diversity_bucket(talent_fn(x))
        if b not in best_by_bucket:
            best_by_bucket[b] = x
    for x in sorted(best_by_bucket.values(), key=score_fn):
        k = talent_key(talent_fn(x))
        if k not in seen_keys:
            chosen.append(x)
            seen_keys.add(k)
        if len(chosen) >= width:
            break

    # Deliberately retain a few candidates deeper in the ranking. When the
    # search plateaus the controller increases exploration_frac, which pushes
    # the optimizer into structurally stranger builds instead of declaring done.
    if len(chosen) < width and exploration_frac > 0:
        remaining = [x for x in ranked if talent_key(talent_fn(x)) not in seen_keys]
        slots = width - len(chosen)
        if remaining and slots:
            step = max(1, len(remaining) // max(1, slots))
            for i in range(0, len(remaining), step):
                x = remaining[i]
                k = talent_key(talent_fn(x))
                if k not in seen_keys:
                    chosen.append(x)
                    seen_keys.add(k)
                if len(chosen) >= width:
                    break

    if len(chosen) < width:
        for x in ranked:
            k = talent_key(talent_fn(x))
            if k not in seen_keys:
                chosen.append(x)
                seen_keys.add(k)
            if len(chosen) >= width:
                break
    return sorted(chosen, key=score_fn)


def _score_worker(args):
    level, t, cfg, n, _seed, coarse = args
    # Workers are read/simulate only. Returning deferred cache writes to the
    # parent avoids dozens of contending SQLite write transactions per talent.
    return pnp_cache.optimize_policy_cached(
        level, t, cfg, n=n, seed=pnp_cache.canonical_seed(level),
        coarse=coarse, defer_writes=True)


def score_many(level: int, talents, cfg: eng.SimConfig, n: int, seed: int, cache, executor=None, coarse=True):
    talents = list(talents)
    out = [None] * len(talents)
    missing = []
    for i, t in enumerate(talents):
        ck = (level, talent_key(t), n, pnp_cache.canonical_seed(level), coarse)
        if ck in cache:
            out[i] = cache[ck]
        else:
            missing.append((i, ck, t))
    if missing:
        args = [(level, t, cfg, n, seed, coarse) for _, _, t in missing]
        if executor is None or len(args) == 1:
            for item, a in zip(missing, args):
                i, ck, _ = item
                res, writes = _score_worker(a)
                cache[ck] = res; out[i] = res
                pnp_cache.enqueue_writes(writes)
        else:
            # Stream completions instead of list(executor.map(...)): DB writes
            # overlap the whole simulation batch and the parent never waits for a
            # slow tail before publishing already-finished cache rows.
            futures = {executor.submit(_score_worker, a): item for item, a in zip(missing, args)}
            for fut in as_completed(futures):
                i, ck, _ = futures[fut]
                res, writes = fut.result()
                cache[ck] = res; out[i] = res
                pnp_cache.enqueue_writes(writes)
    return out


def save_checkpoint(path: Path, data: dict):
    _atomic_pickle_dump(path, data)


def load_checkpoint(path: Path):
    if path.exists():
        with path.open('rb') as f:
            return pickle.load(f)
    return None


def _dominant_family(t: eng.Talents) -> str:
    pts = {'frost': eng.tree_points(t, 'frost'),
           'arcane': eng.tree_points(t, 'arcane'),
           'fire': eng.tree_points(t, 'fire')}
    ordered = sorted(pts.items(), key=lambda kv: (-kv[1], kv[0]))
    if ordered[0][1] == ordered[1][1]:
        return ordered[0][0] + '+' + ordered[1][0]
    secondary = ordered[1][0] if ordered[1][1] >= 5 else 'none'
    return f'{ordered[0][0]}+{secondary}'


def _structural_signature(t: eng.Talents):
    """Performance-free signature used while walking the talent tree.

    The independent seed generator must not decide that Fire is better while a
    Frost path is still paying prerequisites.  This signature therefore uses
    only tree depth / milestone structure, never simulated DPS/time.
    """
    f, a, fi = tree_triplet(t)
    # Include every modeled-value talent rank, not only deep milestones.
    # Otherwise e.g. 5/5 Improved Frostbolt + Frost Warding and 5/5 Improved
    # Frostbolt + Improved Fireball collapse into the same low-level signature
    # and a random filler can erase the actually sensible Frost continuation.
    neutral_fillers = {'frost_warding', 'improved_blizzard', 'cold_snap', 'ice_block', 'improved_cone_of_cold', 'arcane_filler',
                       'improved_flamestrike', 'fire_warding'}
    meaningful = tuple((name, getattr(t, name)) for name in eng.TALENT_RULES
                       if name not in neutral_fillers and getattr(t, name))
    filler_tree = (
        sum(getattr(t, n) for n in ('frost_warding','improved_blizzard','cold_snap','ice_block','improved_cone_of_cold')),
        getattr(t, 'arcane_filler'),
        sum(getattr(t, n) for n in ('improved_flamestrike','fire_warding')),
    )
    return (f, a, fi, meaningful, filler_tree)


def _stable_structural_hash(t: eng.Talents, salt: int) -> int:
    raw = (repr(talent_key(t)) + ':' + str(salt)).encode('utf-8')
    return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), 'big')


def allocation_is_legal(t: eng.Talents) -> bool:
    """Validate a completed talent allocation without relying on ancestry.

    Removing a point for a swap probe can invalidate a deeper-tier talent or a
    prerequisite. A rank-r talent with need_tree=N must have at least N other
    points in that tree, because those points had to exist before rank 1 was
    taken. This is the legality condition needed for history-independent probes.
    """
    for name, (tree, mx, need, pre) in eng.TALENT_RULES.items():
        rank = int(getattr(t, name))
        if rank < 0 or rank > mx:
            return False
        if not rank:
            continue
        if eng.tree_points(t, tree) - rank < need:
            return False
        if pre and getattr(t, pre[0]) < pre[1]:
            return False
    return True


def one_point_swap_neighbors(t: eng.Talents, budget: int, seed: int) -> List[eng.Talents]:
    """Deterministic legal 1-point reallocations around one candidate."""
    vals = {}
    for donor in eng.TALENT_RULES:
        if getattr(t, donor) <= 0:
            continue
        base = dataclass_replace_talent(t, donor, getattr(t, donor) - 1)
        if not allocation_is_legal(base):
            continue
        for recv in eng.TALENT_RULES:
            if recv == donor or not eng.legal_add(base, recv):
                continue
            nt = eng.add_point(base, recv)
            if allocation_is_legal(nt):
                vals.setdefault(talent_key(nt), nt)
    ranked = sorted(vals.values(), key=lambda x: (-talent_value_prior(x), _stable_structural_hash(x, seed), talent_key(x)))
    return ranked[:max(0, int(budget))]


def dataclass_replace_talent(t: eng.Talents, name: str, value: int) -> eng.Talents:
    # Keep optimizer_core independent of engine implementation details beyond the
    # public Talents dataclass fields.
    vals = {f: getattr(t, f) for f in t.__dataclass_fields__}
    vals[name] = int(value)
    return eng.Talents(**vals)


def random_legal_allocation(points: int, seed: int) -> eng.Talents:
    """Seeded global jump: random legal walk from the empty tree."""
    rng = random.Random(int(seed))
    t = eng.Talents()
    preferred = rng.choice(('frost', 'arcane', 'fire', None))
    secondary = rng.choice(('frost', 'arcane', 'fire', None))
    for _ in range(max(0, int(points))):
        cands = eng.talent_candidates(t)
        if not cands:
            break
        weights = []
        for name, _nt in cands:
            tree = eng.TALENT_RULES[name][0]
            w = 1.0
            if preferred and tree == preferred:
                w *= 4.0
            if secondary and secondary != preferred and tree == secondary:
                w *= 1.8
            weights.append(w)
        _name, t = rng.choices(cands, weights=weights, k=1)[0]
    return t


def _probe_sources(states: List[SnapshotState], width: int) -> List[SnapshotState]:
    """Best leaders plus family leaders, so local search is not one-family-only."""
    if not states:
        return []
    ranked = sorted(states, key=snapshot_rank_key)
    wanted = max(2, min(10, width // 4))
    out = []
    seen = set()
    for st in ranked[:max(2, wanted // 2)]:
        k = talent_key(st.talents)
        if k not in seen:
            out.append(st); seen.add(k)
    by_family = {}
    for st in ranked:
        by_family.setdefault(_dominant_family(st.talents), st)
    for st in sorted(by_family.values(), key=snapshot_rank_key):
        k = talent_key(st.talents)
        if k not in seen:
            out.append(st); seen.add(k)
        if len(out) >= wanted:
            break
    return out[:wanted]


def _talent_l1_distance(a: eng.Talents, b: eng.Talents) -> int:
    return sum(abs(int(getattr(a, name)) - int(getattr(b, name))) for name in eng.TALENT_RULES)


def surrogate_probe_priority(t: eng.Talents, references: List[SnapshotState]) -> tuple:
    """Cheap empirical kNN lower-confidence score for an untested allocation.

    Exact simulation remains the oracle. This only decides which proposed
    mutation/global-jump candidates deserve simulation first. Same-family
    observations are preferred; distance/spread provide an exploration bonus so
    a genuinely different build can still beat the local basin.
    """
    refs = [r for r in references if math.isfinite(r.local_s)]
    if not refs:
        return (0.0, 0, _stable_structural_hash(t, 0))
    fam = _dominant_family(t)
    fam_refs = [r for r in refs if _dominant_family(r.talents) == fam]
    pool = fam_refs if len(fam_refs) >= 2 else refs
    near = sorted(((_talent_l1_distance(t, r.talents), r) for r in pool), key=lambda x: x[0])[:5]
    weights = [1.0 / ((1.0 + d) ** 2) for d, _r in near]
    sw = sum(weights) or 1.0
    mean = sum(w * r.local_s for w, (_d, r) in zip(weights, near)) / sw
    var = sum(w * (r.local_s - mean) ** 2 for w, (_d, r) in zip(weights, near)) / sw
    spread = math.sqrt(max(0.0, var))
    novelty = near[0][0] if near else 99
    # Lower is better. Unknown/far candidates receive a bounded lower-confidence
    # bonus rather than being discarded merely because the model is uncertain.
    uncertainty = spread + mean * min(0.15, 0.0125 * novelty)
    lcb = mean - 0.75 * uncertainty
    return (lcb, novelty, _stable_structural_hash(t, 0x51A7))


def surrogate_select_probes(pinned: List[eng.Talents], proposals: List[eng.Talents],
                            references: List[SnapshotState], cap: int, seed: int) -> List[eng.Talents]:
    """Predict -> probe selector with a permanent structural exploration quota."""
    by_key = {talent_key(t): t for t in pinned}
    extras = [t for t in proposals if talent_key(t) not in by_key]
    room = max(0, int(cap) - len(by_key))
    if room <= 0:
        return list(by_key.values())
    explore_n = min(room, max(2, room // 5))
    exploit_n = max(0, room - explore_n)
    ranked = sorted(extras, key=lambda t: surrogate_probe_priority(t, references))
    chosen = ranked[:exploit_n]
    used = {talent_key(t) for t in chosen}
    remaining = [t for t in extras if talent_key(t) not in used]
    # Exploration lane is performance-free and structurally diverse.
    exploratory = _structural_prune(remaining, explore_n, seed + 0xBADC0DE,
                                    pinned[0].points() if pinned else (remaining[0].points() if remaining else 0)) if remaining else []
    for t in chosen + exploratory:
        by_key.setdefault(talent_key(t), t)
    return list(by_key.values())


def augment_probe_candidates(level: int, stage_idx: int, current: List[eng.Talents],
                             previous_states: List[SnapshotState], width: int,
                             exploration_frac: float, seed: int) -> Tuple[List[eng.Talents], dict]:
    """Exploit leaders, mutate locally, and keep a nonzero global-restart lane."""
    if stage_idx <= 0:
        return list(current), {'local_probes': 0, 'global_jumps': 0}
    by_key = {talent_key(t): t for t in current}
    before = len(by_key)

    local_budget = max(8, width)
    sources = _probe_sources(previous_states, width)
    per_source = max(2, local_budget // max(1, len(sources)))
    local_added = 0
    for si, st in enumerate(sources):
        for nt in one_point_swap_neighbors(st.talents, per_source,
                                           seed + level * 10007 + stage_idx * 1009 + si * 97):
            k = talent_key(nt)
            if k not in by_key:
                by_key[k] = nt; local_added += 1

    # A few multi-swap escape probes are generated by mutating an already good
    # allocation twice. This can cross a one-swap valley without exploding the
    # candidate count.
    if stage_idx >= 2 and sources:
        for si, st in enumerate(sources[:3]):
            first = one_point_swap_neighbors(st.talents, 3,
                                             seed + 500003 + level * 101 + stage_idx * 17 + si)
            for fi, mid in enumerate(first[:2]):
                second = one_point_swap_neighbors(mid, 2,
                                                  seed + 700001 + level * 103 + stage_idx * 19 + fi)
                for nt in second:
                    by_key.setdefault(talent_key(nt), nt)

    # Permanent global exploration lane. These are fresh legal random walks,
    # not descendants of survivors, so a missed tree region can re-enter later.
    global_budget = max(4, int(round(width * max(0.10, exploration_frac))))
    global_added = 0
    points = level - 9
    for j in range(global_budget * 3):
        if global_added >= global_budget:
            break
        nt = random_legal_allocation(points,
                                     seed + 900001 + level * 104729 + stage_idx * 100003 + j * 7919)
        k = talent_key(nt)
        if k not in by_key:
            by_key[k] = nt; global_added += 1

    vals = list(by_key.values())
    # Data-driven downselection: exact scored survivors are pinned, then a cheap
    # local kNN surrogate ranks proposed swaps/jumps. A structural exploration
    # quota remains permanent, so the surrogate can never close the search space.
    cap = max(len(current), width * 2)
    if len(vals) > cap:
        vals = surrogate_select_probes(list(current), vals, previous_states, cap,
                                       seed + level * 313 + stage_idx * 271)
    return vals, {
        'local_probes': max(0, len(vals) - before - global_added),
        'global_jumps': min(global_added, max(0, len(vals) - len(current))),
        'surrogate': 'knn_lcb_v1',
    }


def _mandatory_seed_tags(t: eng.Talents):
    """Tags whose best representatives must survive every halving round."""
    f, a, fi = tree_triplet(t)
    pts = {'frost': f, 'arcane': a, 'fire': fi}
    tags = []
    # One best candidate for every dominant school, including deep tiers.
    for tree, n in pts.items():
        if n == max(pts.values()):
            tags.append(('dominant', tree))
            for depth in (10, 15, 20, 25, 30):
                if n >= depth:
                    tags.append(('deep', tree, depth))
    # Preserve meaningful splashes/hybrids too.
    ordered = sorted(pts.items(), key=lambda kv: (-kv[1], kv[0]))
    if ordered[1][1] >= 5:
        tags.append(('hybrid', ordered[0][0], ordered[1][0], min(4, ordered[1][1] // 5)))
    return tags


def retain_seed_families(items, width: int, score_fn):
    """Score-ranked retention with hard archetype/depth representation."""
    if not items:
        return []
    ranked = sorted(items, key=score_fn)
    if len(ranked) <= width:
        return ranked

    chosen = []
    seen = set()

    def take(x):
        k = talent_key(x.talents)
        if k not in seen and len(chosen) < width:
            chosen.append(x)
            seen.add(k)

    # Hard guarantees first: best representative of each tree/depth/hybrid tag.
    best_tag = {}
    for x in ranked:
        for tag in _mandatory_seed_tags(x.talents):
            best_tag.setdefault(tag, x)
    # Dominant/deep tags before hybrids; within class lower score first.
    tag_order = {'dominant': 0, 'deep': 1, 'hybrid': 2}
    for tag, x in sorted(best_tag.items(), key=lambda kv: (tag_order.get(kv[0][0], 9), score_fn(kv[1]), kv[0])):
        take(x)

    # Then global performance leaders.
    global_target = max(len(chosen), min(width, max(3, width // 2)))
    for x in ranked:
        if len(chosen) >= global_target:
            break
        take(x)

    # Then one representative of each structural bucket.
    best_bucket = {}
    for x in ranked:
        best_bucket.setdefault(_structural_signature(x.talents), x)
    for x in sorted(best_bucket.values(), key=score_fn):
        take(x)
        if len(chosen) >= width:
            break

    for x in ranked:
        take(x)
        if len(chosen) >= width:
            break
    return sorted(chosen, key=score_fn)


def _structural_prune(vals, width: int, seed: int, spent: int):
    if len(vals) <= width:
        return vals
    chosen = []
    seen = set()
    def take(t):
        k = talent_key(t)
        if k not in seen and len(chosen) < width:
            chosen.append(t); seen.add(k)

    # Hard lanes for each school. Pure-tree candidates are reserved first so a
    # sensible deep Frost/Fire/Arcane allocation cannot disappear behind hybrid
    # structural noise. Within a pure lane prefer points in modeled-value talents
    # over neutral gate fillers, but never use combat performance here.
    lane_quota = max(8, width // 8)
    neutral = {'frost_warding','improved_blizzard','arcane_filler','improved_flamestrike','fire_warding'}
    tree_names = ('frost','arcane','fire')
    for idx, tree in enumerate(('frost', 'fire', 'arcane')):
        ti = tree_names.index(tree)
        pure = [t for t in vals if tree_triplet(t)[ti] == spent]
        pure.sort(key=lambda t: (-sum(getattr(t,n) for n in eng.TALENT_RULES if n not in neutral),
                                 _stable_structural_hash(t, seed + spent * 97 + idx)))
        for t in pure[:lane_quota]:
            take(t)
        lane = [t for t in vals if tree_triplet(t)[ti] == max(tree_triplet(t))]
        lane.sort(key=lambda t: (_stable_structural_hash(t, seed + spent * 101 + idx), talent_key(t)))
        for t in lane[:lane_quota]:
            take(t)

    # Guarantee representatives of deep-tier and hybrid structural tags.
    best_tag = {}
    for t in vals:
        h = _stable_structural_hash(t, seed + spent * 313)
        for tag in _mandatory_seed_tags(t):
            old = best_tag.get(tag)
            if old is None or h < old[0]:
                best_tag[tag] = (h, t)
    for _tag, (_h, t) in sorted(best_tag.items(), key=lambda kv: (kv[0], kv[1][0])):
        take(t)

    # One per exact structural signature, then deterministic random-like fill.
    sig_rep = {}
    for t in vals:
        sig = _structural_signature(t)
        h = _stable_structural_hash(t, seed + spent)
        old = sig_rep.get(sig)
        if old is None or h < old[0]:
            sig_rep[sig] = (h, t)
    for _h, t in sorted(sig_rep.values(), key=lambda ht: ht[0]):
        take(t)
        if len(chosen) >= width:
            break
    if len(chosen) < width:
        for t in sorted(vals, key=lambda t: _stable_structural_hash(t, seed + spent * 7919)):
            take(t)
            if len(chosen) >= width:
                break
    return chosen


def _structural_frontier_width(terminal_width: int) -> int:
    return min(STRUCTURAL_FRONTIER_MAX_WIDTH, max(192, int(terminal_width) * 2))


def generate_independent_frontiers(max_points: int, terminal_width: int, seed: int):
    """Build performance-free legal-allocation frontiers for every point count.

    This is deliberately deterministic for a given seed. Runtime exploration
    still changes by epoch through terminal sampling, local mutation probes and
    global random-walk injections, so the expensive structural base itself does
    not need to be regenerated every epoch.
    """
    structural_width = _structural_frontier_width(terminal_width)
    cur = [eng.Talents()]
    fronts = {}
    for spent in range(1, max_points + 1):
        by_key = {}
        for t in cur:
            for _name, nt in eng.talent_candidates(t):
                if nt.points() == spent:
                    by_key.setdefault(talent_key(nt), nt)
        cur = _structural_prune(list(by_key.values()), structural_width, seed, spent)
        fronts[spent] = list(cur)
    return fronts


def _structural_frontier_semantics_hash() -> str:
    # Platform/Python-version independent: the frontier depends on engine talent
    # rules/candidate generation plus the structural pruning algorithm version.
    h = hashlib.sha256()
    h.update(STRUCTURAL_FRONTIER_CACHE_VERSION.encode('utf-8')); h.update(b'\0')
    h.update(Path(eng.__file__).resolve().read_bytes())
    return h.hexdigest()[:20]


def _structural_frontier_cache_key(max_points: int, terminal_width: int) -> str:
    structural_width = _structural_frontier_width(terminal_width)
    payload = f'{_structural_frontier_semantics_hash()}|{int(max_points)}|{structural_width}'
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]


def _structural_frontier_cache_paths(max_points: int, terminal_width: int):
    key = _structural_frontier_cache_key(max_points, terminal_width)
    name = f'structural_frontier_{key}.pkl'
    runtime = Path(pnp_cache.CACHE_DIR) / name
    bundled = Path(__file__).resolve().parent / 'precomputed' / name
    return key, runtime, bundled


def _load_structural_frontier_file(path: Path, key: str, max_points: int, terminal_width: int):
    if not path.exists():
        return None
    try:
        with path.open('rb') as f:
            obj = pickle.load(f)
        if not isinstance(obj, dict) or obj.get('version') != STRUCTURAL_FRONTIER_CACHE_VERSION:
            return None
        if obj.get('key') != key or int(obj.get('max_points', -1)) != int(max_points):
            return None
        expected_width = _structural_frontier_width(terminal_width)
        if int(obj.get('structural_width', -1)) != expected_width:
            return None
        fronts = obj.get('fronts')
        if not isinstance(fronts, dict) or int(max_points) not in fronts:
            return None
        return fronts
    except Exception:
        return None


def _replace_with_retry(tmp: Path, path: Path, attempts: int = 10) -> None:
    """Atomic replace tolerant of transient Windows sharing violations.

    Windows antivirus/indexers/listeners can briefly open the destination
    without FILE_SHARE_DELETE, causing os.replace() to raise WinError 5.
    Runtime state writes must retry instead of killing a long optimizer run.
    """
    last = None
    for attempt in range(max(1, int(attempts))):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:
            last = e
            time.sleep(min(1.0, 0.02 * (1.8 ** attempt)))
    if last is not None:
        raise last


def _atomic_pickle_dump(path: Path, obj) -> None:
    """Windows-friendly atomic pickle write with transient replace retry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    try:
        with tmp.open('wb') as f:
            pickle.dump(obj, f, pickle.HIGHEST_PROTOCOL)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _atomic_text_dump(path: Path, text: str) -> None:
    """Durable UTF-8 text write using the same Windows-safe replace path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    try:
        with tmp.open('w', encoding='utf-8', newline='') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def get_independent_frontiers(max_points: int, terminal_width: int):
    """Load the expensive structural base from disk/bundle, building once on miss.

    The base seed is intentionally fixed. Per-epoch diversity is provided later
    by terminal sampling plus local/global mutation lanes, which lets both water
    tracks and all epochs share this serial precomputation safely.
    """
    key, runtime, bundled = _structural_frontier_cache_paths(max_points, terminal_width)
    for label, path in (('runtime', runtime), ('bundled', bundled)):
        fronts = _load_structural_frontier_file(path, key, max_points, terminal_width)
        if fronts is not None:
            if label == 'bundled' and not runtime.exists():
                try:
                    payload = {
                        'version': STRUCTURAL_FRONTIER_CACHE_VERSION, 'key': key,
                        'structural_semantics_hash': _structural_frontier_semantics_hash(),
                        'max_points': int(max_points),
                        'structural_width': _structural_frontier_width(terminal_width),
                        'fronts': fronts,
                    }
                    _atomic_pickle_dump(runtime, payload)
                except Exception:
                    pass
            print(f'[frontier cache] hit {label} {runtime.name}', flush=True)
            return fronts

    t0 = time.perf_counter()
    fronts = generate_independent_frontiers(max_points, terminal_width, STRUCTURAL_FRONTIER_BASE_SEED)
    payload = {
        'version': STRUCTURAL_FRONTIER_CACHE_VERSION, 'key': key,
        'structural_semantics_hash': _structural_frontier_semantics_hash(),
        'max_points': int(max_points),
        'structural_width': _structural_frontier_width(terminal_width),
        'fronts': fronts,
    }
    try:
        _atomic_pickle_dump(runtime, payload)
        where = runtime
    except Exception as e:
        where = f'not saved ({e})'
    print(f'[frontier cache] miss -> built once in {time.perf_counter()-t0:.2f}s; {where}', flush=True)
    return fronts


def terminal_structural_sample(frontier, width: int, seed: int, points: int):
    """Choose a target-level candidate set with hard tree/depth coverage."""
    if len(frontier) <= width:
        return list(frontier)
    # Reuse structural pruning with a smaller width; unlike pure hash truncation
    # this keeps deep Frost/Fire/Arcane and hybrid representatives guaranteed.
    return _structural_prune(list(frontier), width, seed + 999983, points)

def _seed_bank_path(seed_dir: Optional[Path], level: int) -> Optional[Path]:
    return (Path(seed_dir) / f'lvl_{level:02d}.json') if seed_dir else None


def _seed_memory_path(seed_dir: Optional[Path], level: int) -> Optional[Path]:
    return (Path(seed_dir) / 'memory' / f'lvl_{level:02d}.json') if seed_dir else None


def _talents_from_seed_json(path: Optional[Path], level: int):
    if path is None or not path.exists():
        return []
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
        out = []
        fields = eng.Talents.__dataclass_fields__
        for row in obj.get('candidates', []):
            vals = row.get('talents') or {}
            t = eng.Talents(**{name: int(vals.get(name, 0)) for name in fields})
            if t.points() == level - 9:
                out.append(t)
        return out
    except Exception:
        return []


def _save_seed_memory(seed_dir: Optional[Path], level: int, pool: List[SnapshotState], meta: dict, cap: int = 512):
    """Persistent talent-prior memory across epochs and simulator cohorts.

    This is deliberately *not* an authoritative score table.  Old simulator
    cohorts are allowed to guide future exploration, but their numeric scores
    cannot become BEST without a current-hash replay.  The memory therefore
    stores only legal talent allocations plus provenance and is bounded.
    Current final-pool allocations are pinned; older allocations fill the
    remaining space through performance-free structural pruning.
    """
    path = _seed_memory_path(seed_dir, level)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    current = [st.talents for st in pool]
    old = _talents_from_seed_json(path, level)
    seen = {talent_key(t) for t in current}
    older = [t for t in old if talent_key(t) not in seen]
    remaining = max(0, int(cap) - len(current))
    if remaining and older:
        older = _structural_prune(older, remaining, 99173 + level * 1009, level - 9)
    selected = (current + older)[:max(len(current), int(cap))]
    payload = {
        'version': 1, 'mode': 'talent_prior_memory_v1', 'level': level,
        'meta': {
            'note': 'Talent allocations only; stale cohorts are guidance, never authoritative scores.',
            'updated_at': time.time(), 'sim_code_hash_last_writer': pnp_cache.current_sim_hash(),
            'water_mode_last_writer': meta.get('water_mode'), 'cap': int(cap),
        },
        'candidates': [
            {'talents': {name: getattr(t, name) for name in t.__dataclass_fields__},
             'allocation': eng.final_allocation(t), 'family': _dominant_family(t)}
            for t in selected
        ],
    }
    _atomic_text_dump(path, json.dumps(payload, indent=2, ensure_ascii=False))


def _save_seed_bank(seed_dir: Optional[Path], level: int, pool: List[SnapshotState], meta: dict):
    path = _seed_bank_path(seed_dir, level)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'version': 1,
        'mode': 'independent_pnp_v3',
        'level': level,
        'meta': meta,
        'candidates': [
            {
                'rank': i + 1,
                'normalized_min_per_100': st.local_s / 60.0,
                'relative_se': st.relative_se if math.isfinite(st.relative_se) else None,
                'family': _dominant_family(st.talents),
                'tree_points': dict(zip(('frost','arcane','fire'), tree_triplet(st.talents))),
                'allocation': eng.final_allocation(st.talents),
                'policy': eng.policy_desc(st.policy, level) if st.policy else None,
                **objective_level_meta(level),
                'talents': {name: getattr(st.talents, name) for name in st.talents.__dataclass_fields__},
            }
            for i, st in enumerate(pool)
        ],
    }
    _atomic_text_dump(path, json.dumps(payload, indent=2, ensure_ascii=False))


def _load_seed_talents(seed_dir: Optional[Path], level: int):
    # Current final bank + bounded best-ever structural memory.  Deduplicate by
    # allocation so repeated epochs do not inflate the next mapper's workload.
    vals = _talents_from_seed_json(_seed_bank_path(seed_dir, level), level)
    vals += _talents_from_seed_json(_seed_memory_path(seed_dir, level), level)
    by_key = {}
    for t in vals:
        by_key.setdefault(talent_key(t), t)
    return list(by_key.values())


def _pnp_stage_keep(width: int, initial_count: int, stage_idx: int) -> int:
    # One-mob map keeps everything; later reductions are increasingly selective.
    caps = [initial_count, max(width*5,160), max(width*4,128), max(width*3,96),
            max(width*2+8,72), max(width+24,56), max(width+8,40), width]
    return min(initial_count, caps[min(stage_idx, len(caps)-1)])


def _family_gap(states: List[SnapshotState]) -> float:
    """Relative gap to the best genuinely different build family; lower = uncertain."""
    if not states:
        return 1.0
    best=states[0]
    fam0=_dominant_family(best.talents)
    alt=next((x for x in states[1:] if _dominant_family(x.talents)!=fam0), None)
    if alt is None:
        alt=states[1] if len(states)>1 else None
    if alt is None or not math.isfinite(best.local_s) or best.local_s<=0:
        return 1.0
    return max(0.0,(alt.local_s-best.local_s)/best.local_s)


def _base_level_priority(level: int, states: List[SnapshotState]) -> float:
    # Value of information: high-XP levels, close family races and noisy estimates
    # deserve earlier refinement. Constants affect scheduling only, never results.
    xp=max(0.05,level_weight_per_100(level))
    gap=_family_gap(states)
    race_uncertainty=1.0/(0.01+gap)
    rel_se=(states[0].relative_se if states else math.inf)
    stat_uncertainty=25.0 if not math.isfinite(rel_se) else min(25.0,rel_se*100.0)
    return xp*(1.0+min(25.0,race_uncertainty)+stat_uncertainty)


def _range_priority(level: int, work: dict) -> float:
    """Multi-scale 1/2/4/8/16-level uncertainty rollup around one level."""
    levels=sorted(work)
    own=_base_level_priority(level, work[level].get('states') or [])
    best=own
    for width in (2,4,8,16):
        lo=max(min(levels), level-width//2)
        hi=min(max(levels), lo+width-1)
        vals=[_base_level_priority(l,work[l].get('states') or []) for l in levels if lo<=l<=hi]
        if vals:
            # Sum reflects global path impact of an uncertain range; divide mildly
            # so giant ranges do not automatically monopolize the queue.
            best=max(best, sum(vals)/(width**0.35))
    return best


def build_snapshot_pools(start_level: int, end_level: int, cfg: eng.SimConfig,
                         width: int = 32, poll_mobs: int = 3, seed: int = 123,
                         checkpoint: Optional[Path] = None,
                         resume_data: Optional[dict] = None, executor=None,
                         exploration_frac: float = 0.15,
                         callback: CheckpointCallback = None,
                         frontier_callback=None,
                         seed_dir: Optional[Path] = None,
                         cross_seed_dirs: Optional[List[Path]] = None):
    """Persistent map/reduce PnP seed search.

    * Every level is a history-independent full talent-allocation problem.
    * Breadth first precision: all levels at 1 mob, then 2,4,8,16,32,64,100.
    * Within one precision tier, an adaptive multi-scale range priority chooses
      what to calculate next.
    * score_many uses the disk cache, so n->2n simulates only the missing suffix.
    """
    pools: Dict[int,List[SnapshotState]]={}
    score_cache={}
    mode='independent_pnp_v3'
    ladder=tuple(pnp_cache.PRECISION_LADDER)
    work={}

    if resume_data and resume_data.get('snapshot_mode')==mode:
        pools=dict(resume_data.get('snapshot_pools') or {})
        work=dict(resume_data.get('pnp_work') or {})
        if work:
            done=sum(1 for x in work.values() if x.get('done'))
            print(f'[resume] PnP seed map {done}/{len(work)} levels final; precision frontier retained',flush=True)

    # The old mapper started with max(192, width*6) allocations *per level*,
    # which delayed the first full 11->60 answer for minutes. Start compact and
    # let mutation + global restart probes expand promising/unknown regions.
    bootstrap_n=max(48,width*2)
    initial_cap=max(64,width*3)
    max_points=end_level-9
    structural_frontiers=get_independent_frontiers(max_points,max(bootstrap_n,width*3))

    # Initialize any missing level job.  Existing per-level seed files are priors
    # only; all current-hash scores are re-established through the disk cache.
    for lvl in range(start_level,end_level+1):
        if lvl in work:
            continue
        points=lvl-9
        generated=terminal_structural_sample(structural_frontiers[points],bootstrap_n,seed+lvl*1543,points)
        prior=_load_seed_talents(seed_dir,lvl)
        cross=[]
        for d in (cross_seed_dirs or []): cross.extend(_load_seed_talents(d,lvl))
        # Pin the best persisted own-bank candidates and a smaller cross-water
        # sample, then fill the rest structurally. This preserves known-good
        # allocations without letting a 512-entry memory turn bootstrap back
        # into the old giant first pass.
        pinned=[]; seen=set()
        def pin(vals, cap):
            for t in vals[:max(0,int(cap))]:
                k=talent_key(t)
                if k not in seen:
                    pinned.append(t); seen.add(k)
        pin(prior,width)
        pin(cross,max(4,width//4))
        rest=[t for t in generated+prior[width:]+cross[max(4,width//4):] if talent_key(t) not in seen]
        room=max(0,initial_cap-len(pinned))
        if len(rest)>room:
            rest=_structural_prune(rest,room,seed+lvl*1543+17,points)
        talents=(pinned+rest)[:initial_cap]
        work[lvl]={
            'level':lvl,'stage_idx':0,'talents':talents,'states':[], 'done':False,
            'initial_count':len(talents),'own_seed_candidates':len(prior),
            'cross_seed_candidates':len(cross),'last_priority':level_weight_per_100(lvl),
        }

    def persist_job(lvl:int, states:List[SnapshotState], n_mobs:int, final:bool, priority:float):
        job=work[lvl]
        meta={
            'initial_candidates':job['initial_count'],
            'precision_mobs':n_mobs,'final':bool(final),
            'precision_ladder':list(ladder),'seed':seed,'width':width,
            'scheduler_priority':priority,'scheduler':'multiscale_best_first_v1',
            'sim_code_hash':pnp_cache.current_sim_hash(),
            'use_best_water':bool(cfg.use_best_water),
            'water_mode':'buy_water' if cfg.use_best_water else 'conjured_water',
            'own_seed_candidates':job['own_seed_candidates'],
            'cross_seed_candidates':job['cross_seed_candidates'],
            **objective_level_meta(lvl),
        }
        _save_seed_bank(seed_dir,lvl,states,meta)
        # Guidance-only memory is cheap and should remember useful allocations
        # even if Ctrl-C happens before the 100-mob frontier.
        _save_seed_memory(seed_dir,lvl,states,meta)

    while True:
        unfinished=[lvl for lvl,j in work.items() if not j.get('done')]
        if not unfinished: break
        # Breadth-first precision: nobody advances to 2 mobs until every level
        # has its 1-mob map, etc.
        min_stage=min(int(work[l]['stage_idx']) for l in unfinished)
        eligible=[l for l in unfinished if int(work[l]['stage_idx'])==min_stage]
        # Best-first inside the precision frontier.  Recompute priorities after
        # every completed job, so neighboring range information can redirect CPU.
        ranked=[]
        for lvl in eligible:
            pri=_range_priority(lvl,work)
            # Deterministic tiny jitter prevents permanent ties without affecting score.
            pri += (_stable_structural_hash(work[lvl]['talents'][0],seed+lvl) % 1000)*1e-12 if work[lvl]['talents'] else 0
            ranked.append((pri,lvl))
        priority,lvl=max(ranked)
        job=work[lvl]
        stage_idx=int(job['stage_idx']); n_mobs=ladder[stage_idx]
        current=list(job['talents'])
        current,probe_meta=augment_probe_candidates(
            lvl,stage_idx,current,list(job.get('states') or []),width,
            exploration_frac,seed)
        lvl_seed=seed+lvl*7919  # identical stream across all precision stages
        print(f'[pnp next] precision={n_mobs:3d}m level={lvl:02d} priority={priority:8.2f} '
              f'candidates={len(current)} probes=+{probe_meta["local_probes"]}local/+{probe_meta["global_jumps"]}jump range-aware',flush=True)
        results=score_many(lvl,current,cfg,n_mobs,lvl_seed,score_cache,executor,coarse=True)
        scored=[SnapshotState(t,res['total_s']*(100.0/n_mobs),pol,
                              (res.get('stderr_s_per_mob',math.inf)/(res['total_s']/n_mobs) if res.get('total_s',0)>0 else math.inf))
                for t,(pol,res) in zip(current,results)]
        keep=_pnp_stage_keep(width,job['initial_count'],stage_idx)
        keep=min(len(scored),max(width if stage_idx==len(ladder)-1 else 1,keep))
        states=retain_seed_families(scored,keep,snapshot_rank_key)
        fam_counts={}
        for st in states:
            fam=_dominant_family(st.talents); fam_counts[fam]=fam_counts.get(fam,0)+1
        fam_txt=','.join(f'{k}:{v}' for k,v in sorted(fam_counts.items()))
        best=states[0]
        print(f'[seed {lvl:02d} {n_mobs:3d}m] scored={len(scored):4d} -> keep={len(states):3d} '
              f'best={best.local_s/60:7.2f} min/100 gap={_family_gap(states)*100:5.2f}% relSE={(best.relative_se*100 if math.isfinite(best.relative_se) else float("inf")):5.2f}% '
              f'families={fam_txt} | {eng.final_allocation(best.talents)}',flush=True)
        final=stage_idx==len(ladder)-1
        job['states']=states
        job['last_priority']=priority
        # Always expose the best current pool. `done` still means 100-mob final,
        # but outer previews can now use the 1/2/4/... frontier immediately.
        pools[lvl]=states
        if final:
            job['done']=True
        else:
            job['talents']=[st.talents for st in states]
            job['stage_idx']=stage_idx+1
        persist_job(lvl,states,n_mobs,final,priority)
        data={
            'version':7,'phase':'snapshots','snapshot_mode':mode,
            'objective_version':OBJECTIVE_VERSION,'snapshot_pools':pools,
            'snapshot_level':lvl,'snapshot_precision_mobs':n_mobs,'pnp_work':work,
            'use_best_water':bool(cfg.use_best_water),
            'sim_code_hash':pnp_cache.current_sim_hash(),
            'pnp_meta':{'sim_code_hash':pnp_cache.current_sim_hash(),'scheduler':'multiscale_best_first_v1',
                        'precision_ladder':list(ladder)},
        }
        if checkpoint: save_checkpoint(checkpoint,data)
        if callback: callback(data)
        # A precision frontier is complete when every unfinished level has moved
        # beyond this stage (or finished). Emit one full-path preview before the
        # mapper spends CPU on the next precision tier.
        frontier_done=all(j.get('done') or int(j.get('stage_idx',0))>stage_idx for j in work.values())
        if frontier_done:
            # Only precision boundaries need a durability barrier: the next tier
            # may extend these exact chains. All level jobs inside a tier remain
            # fully overlapped with the async SQLite writer.
            pnp_cache.flush_writes()
            if not final and frontier_callback and len(pools)==(end_level-start_level+1):
                frontier_callback(dict(pools),n_mobs,data)
    pnp_cache.flush_writes()
    return pools


def respec_schedule(st: OuterState) -> tuple[int, ...]:
    return tuple(int(ev.level) for ev in st.events if ev.kind == 'respec')


def independent_remaining_lower_bound_s(pools: Dict[int, List[SnapshotState]], start_level: int, end_level: int) -> float:
    """Optimistic weighted seconds from independent per-level minima.

    This deliberately ignores talent continuity/respec limits, so it is a true
    lower bound for scheduler triage only. It must never be used as an
    authoritative score.
    """
    total = 0.0
    for lvl in range(int(start_level), int(end_level) + 1):
        states = pools.get(lvl) or []
        vals = [float(st.local_s) for st in states if math.isfinite(float(st.local_s))]
        if not vals:
            return math.inf
        total += min(vals) * level_weight_per_100(lvl)
    return total


def optimistic_outer_total_s(st: OuterState, current_level: int, end_level: int,
                             pools: Dict[int, List[SnapshotState]]) -> float:
    """Best-case full-arc total for an in-flight outer state.

    The already-incurred prefix is exact for the current coarse search. Future
    levels use independent local minima, which can only make the estimate too
    optimistic. A value below the incumbent therefore means "do not ignore this
    path yet" rather than "this path is better".
    """
    if int(current_level) >= int(end_level):
        return float(st.cumulative_s)
    rem = independent_remaining_lower_bound_s(pools, int(current_level) + 1, int(end_level))
    return float(st.cumulative_s) + rem


def derive_respec_probe_levels(pools: Dict[int, List[SnapshotState]], start_level: int, end_level: int,
                               prior_schedules: Optional[List[List[int]]] = None,
                               boundary_radius: int = 2, max_probe_levels: int = 12) -> set[int]:
    """Return a *bounded* set of levels worth extra respec exploration.

    Fast/imported seed banks can make many per-level family races look nearly
    tied.  Treating every such level as a probe used to turn the outer DP into a
    pathological high-precision search at essentially every level.  Probe hints
    are therefore ranked, not accumulated without bound:

    1. imported/Fast respec timings (frequency first),
    2. actual dominant-family phase changes,
    3. the closest remaining cross-family races.

    The cap affects exploration effort only; ordinary respec transitions remain
    legal at every level.
    """
    from collections import Counter

    lo, hi = int(start_level), int(end_level)
    cap = max(1, int(max_probe_levels))
    chosen: list[int] = []
    seen: set[int] = set()

    def add(level: int) -> None:
        level = int(level)
        if lo <= level <= hi and level not in seen and len(chosen) < cap:
            chosen.append(level); seen.add(level)

    # Fast/historical schedules are the strongest hints.  A level repeated by
    # several candidate paths gets priority, but even a large imported archive
    # cannot expand the probe set past ``cap``.
    prior_counts: Counter[int] = Counter()
    for sched in prior_schedules or []:
        for raw in sched:
            try:
                lvl = int(raw)
            except Exception:
                continue
            if lo <= lvl <= hi:
                prior_counts[lvl] += 1
    prior_centers = [lvl for lvl, _n in sorted(prior_counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    for lvl in prior_centers:
        add(lvl)
    for distance in (1,):
        for lvl in prior_centers:
            add(lvl-distance); add(lvl+distance)

    # Collect family/gap signals before spending the remaining budget.
    flips: list[tuple[float, int]] = []
    close: list[tuple[float, int]] = []
    prev_family = None
    prev_level = None
    prev_gap = 1.0
    for lvl in range(lo, hi + 1):
        states = pools.get(lvl) or []
        if not states:
            continue
        ranked = sorted(states, key=snapshot_rank_key)
        fam = _dominant_family(ranked[0].talents)
        gap = _family_gap(ranked)
        if gap <= 0.05:
            close.append((gap, lvl))
        if prev_family is not None and fam != prev_family:
            # Lower adjacent family gap = more plausible true phase boundary.
            flips.append((min(prev_gap, gap), lvl))
        prev_family, prev_level, prev_gap = fam, lvl, gap

    # Actual phase changes get a small local neighborhood, ordered by confidence.
    flip_centers = [lvl for _gap, lvl in sorted(flips, key=lambda x: (x[0], x[1]))]
    for lvl in flip_centers:
        add(lvl)
    for distance in range(1, max(0, int(boundary_radius)) + 1):
        for lvl in flip_centers:
            add(lvl-distance); add(lvl+distance)

    # Finally use any remaining slots on the closest cross-family races.
    for _gap, lvl in sorted(close, key=lambda x: (x[0], x[1])):
        add(lvl)

    return set(chosen)


def retain_outer_schedule_diverse(vals: List[OuterState], width: int, exploration_frac: float,
                                  probe_levels: Optional[set[int]] = None) -> List[OuterState]:
    """Keep a bounded set of alternate respec timings in addition to talent diversity.

    Exact DP dominance still determines the winner. These schedule pins are an
    anytime/noise exploration lane so a coarse 1/2/4-mob estimate cannot erase
    every nearby respec timing before the next precision frontier recomputes it.
    """
    width = max(0, int(width))
    if width <= 0 or not vals:
        return []
    probe_levels = probe_levels or set()
    # Exact duplicate state key first; do not collapse distinct schedules merely
    # because they currently end in the same allocation.
    best_by = {}
    for st in vals:
        key = (talent_key(st.talents), respec_schedule(st))
        old = best_by.get(key)
        if old is None or state_rank_key(st) < state_rank_key(old):
            best_by[key] = st
    ranked = sorted(best_by.values(), key=state_rank_key)
    if len(ranked) <= width:
        return ranked

    pinned: List[OuterState] = []
    seen_ids = set()
    schedule_cap = max(1, min(width // 3, 12)) if width >= 3 else 0

    # Best representatives of schedules that touch a phase-boundary/prior probe.
    by_sched = {}
    for st in ranked:
        sched = respec_schedule(st)
        if sched and any(l in probe_levels for l in sched):
            by_sched.setdefault(sched, st)
    for st in sorted(by_sched.values(), key=state_rank_key)[:schedule_cap]:
        pinned.append(st); seen_ids.add(id(st))

    # Also preserve different last-respec levels even outside explicit signals.
    if len(pinned) < schedule_cap:
        by_last = {}
        for st in ranked:
            if st.last_respec_level is not None:
                by_last.setdefault(int(st.last_respec_level), st)
        for st in sorted(by_last.values(), key=state_rank_key):
            if id(st) not in seen_ids:
                pinned.append(st); seen_ids.add(id(st))
            if len(pinned) >= schedule_cap:
                break

    room = width - len(pinned)
    remaining = [st for st in ranked if id(st) not in seen_ids]
    fill = retain_diverse(remaining, room, state_rank_key, lambda x: x.talents,
                          exploration_frac) if room > 0 else []
    return sorted((pinned + fill)[:width], key=state_rank_key)


def _retain_destination_family_leaders(states: List[SnapshotState], width: int,
                                       exploration_frac: float) -> List[SnapshotState]:
    if not states or width <= 0:
        return []
    ranked = sorted(states, key=snapshot_rank_key)
    pins = []
    seen = set()
    for st in ranked:
        fam = _dominant_family(st.talents)
        if fam not in seen:
            pins.append(st); seen.add(fam)
    pins = pins[:min(width, 4)]
    pin_keys = {talent_key(x.talents) for x in pins}
    rest = [x for x in ranked if talent_key(x.talents) not in pin_keys]
    fill = retain_diverse(rest, max(0, width-len(pins)), snapshot_rank_key,
                          lambda x: x.talents, exploration_frac) if len(pins) < width else []
    return sorted((pins + fill)[:width], key=snapshot_rank_key)


def destination_shortlist(level: int, pool: List[SnapshotState], cfg: eng.SimConfig,
                          cheap_n: int, refine_n: int, refine_k: int, seed: int,
                          score_cache, executor=None, exploration_frac: float = 0.15,
                          pool_precision_mobs: int = 0):
    if not pool:
        return []
    if int(pool_precision_mobs) >= int(cheap_n):
        cheap = list(pool)
    else:
        s0 = seed + level * 100003 + 17
        results = score_many(level, [st.talents for st in pool], cfg, cheap_n, s0, score_cache, executor, coarse=True)
        cheap = [SnapshotState(st.talents, res['total_s'] * (100.0 / cheap_n), pol,
                 (res.get('stderr_s_per_mob',math.inf)/(res['total_s']/cheap_n) if res.get('total_s',0)>0 else math.inf))
                 for st, (pol, res) in zip(pool, results)]
    cheap = _retain_destination_family_leaders(
        cheap, min(len(cheap), max(refine_k * 2, refine_k)), exploration_frac)
    if refine_n <= cheap_n or int(pool_precision_mobs) >= int(refine_n):
        return cheap[:refine_k]
    s1 = seed + level * 100003 + 29
    results = score_many(level, [st.talents for st in cheap], cfg, refine_n, s1, score_cache, executor, coarse=True)
    refined = [SnapshotState(st.talents, res['total_s'] * (100.0 / refine_n), pol,
               (res.get('stderr_s_per_mob',math.inf)/(res['total_s']/refine_n) if res.get('total_s',0)>0 else math.inf))
               for st, (pol, res) in zip(cheap, results)]
    return _retain_destination_family_leaders(
        refined, min(refine_k, len(refined)), exploration_frac)


def _refine_outer_level_states(states: List[OuterState], level: int, cfg: eng.SimConfig,
                               target_n: int, seed: int, score_cache, executor=None) -> List[OuterState]:
    """Re-score the current level at the precision advertised by the frontier.

    Outer DP intentionally uses a cheap score to generate a broad set of talent
    children.  It is unsafe, however, to *prune* that set using the cheap mean:
    doing so made a nominal 64m preview choose many points from 4-mob noise.
    This pass re-optimizes policy and replaces only the current level's
    contribution before the beam is reduced. Prefix history is unchanged.
    """
    if not states:
        return []
    target_n=max(1,int(target_n))
    by_key={}
    for st in states:
        by_key.setdefault(talent_key(st.talents), st.talents)
    talents=list(by_key.values())
    results=score_many(level,talents,cfg,target_n,seed,score_cache,executor,coarse=True)
    scored={}
    for t,(pol,res) in zip(talents,results):
        scored[talent_key(t)]=(pol,res['total_s']*(100.0/target_n))

    w=level_weight_per_100(level)
    out=[]
    for st in states:
        if not st.events or st.events[-1].level!=level or st.events[-1].score_s<=0:
            out.append(st); continue
        pol,score=scored[talent_key(st.talents)]
        old_ev=st.events[-1]
        prefix_s=st.cumulative_s-old_ev.score_s*w
        try:
            old_pol=policy_from_desc(old_ev.policy,level)
            old_align=talent_alignment_penalty(st.talents,old_pol)
        except Exception:
            old_align=0.0
        new_align=talent_alignment_penalty(st.talents,pol)
        ev=Event(old_ev.level,old_ev.kind,old_ev.detail,eng.policy_desc(pol,level),score)
        out.append(OuterState(
            st.talents,prefix_s+score*w,st.respecs_used,st.events[:-1]+[ev],
            st.last_respec_level,max(0.0,getattr(st,'coherence_penalty',0.0)-old_align)+new_align))
    return out


def optimize_free_respec(start_level: int, end_level: int, pools: Dict[int, List[SnapshotState]], cfg: eng.SimConfig,
                         max_respecs: int = 2, beam_width: int = 28, score_mobs: int = 4,
                         dest_cheap_mobs: int = 2, dest_refine_mobs: int = 5, dest_k: int = 12,
                         seed: int = 321, checkpoint: Optional[Path] = None,
                         resume_data: Optional[dict] = None, executor=None,
                         exploration_frac: float = 0.15,
                         callback: CheckpointCallback = None,
                         pool_precision_mobs: int = 0,
                         respec_prior_schedules: Optional[List[List[int]]] = None,
                         progress_callback: Optional[Callable[[dict], None]] = None):
    score_cache = {}

    def progress(level: int, stage: str, **extra) -> None:
        if progress_callback is None:
            return
        payload = {'level': int(level), 'stage': str(stage)}
        payload.update(extra)
        progress_callback(payload)

    # pool_precision_mobs is the precision named by the current PnP frontier.
    # Cheap score_mobs is proposal-generation only; survivors must be ranked at
    # the advertised precision or "64m" is really a 4m talent search.
    selection_mobs=max(int(score_mobs),int(pool_precision_mobs or score_mobs))
    probe_levels = derive_respec_probe_levels(
        pools, start_level, end_level, respec_prior_schedules)
    if probe_levels:
        print('[respec probes] phase-boundary/prior levels=' + ','.join(map(str, sorted(probe_levels))), flush=True)
    layers: Dict[int, List[OuterState]] = {r: [] for r in range(max_respecs + 1)}
    current_level = 9

    if resume_data and resume_data.get('outer_layers'):
        layers = resume_data['outer_layers']
        current_level = resume_data['outer_level']
        print(f'[resume] outer DP through level {current_level}', flush=True)
    else:
        layers[0] = [OuterState(eng.Talents(), 0.0, 0, [], None)]

    for lvl in range(current_level + 1, min(start_level, end_level + 1)):
        next0 = []
        for st in layers[0]:
            for name, nt in eng.talent_candidates(st.talents):
                if nt.points() == lvl - 9:
                    next0.append(OuterState(nt, st.cumulative_s, 0,
                                            st.events + [Event(lvl, 'point', name, 'unscored', 0.0)], None))
        # Never prune an unscored pre-objective talent point merely because a
        # coarse preview uses beam=1. Keep all legal level-10 starts until level
        # 11 produces an actual simulated score.
        layers[0] = retain_diverse(next0, max(beam_width, len(next0)), state_rank_key, lambda x: x.talents, exploration_frac)
        current_level = lvl

    for lvl in range(max(start_level, current_level + 1), end_level + 1):
        progress(lvl, 'begin', probe=(lvl in probe_levels), selection_mobs=selection_mobs)
        next_layers = {r: [] for r in range(max_respecs + 1)}
        lvl_seed = seed + lvl * 104729

        for r, states in layers.items():
            parents = {}
            for st in states:
                for name, nt in eng.talent_candidates(st.talents):
                    if nt.points() != lvl - 9:
                        continue
                    k = talent_key(nt)
                    old = parents.get(k)
                    if old is None or state_rank_key(st) < state_rank_key(old[0]):
                        parents[k] = (st, name, nt)
            items = list(parents.values())
            pool_lookup = {talent_key(x.talents): x for x in pools.get(lvl, [])}
            resolved = [None] * len(items)
            missing_idx = []
            missing_talents = []
            if int(pool_precision_mobs) >= int(score_mobs):
                for ii, (_st, _name, nt) in enumerate(items):
                    hit = pool_lookup.get(talent_key(nt))
                    if hit is not None and hit.policy is not None:
                        resolved[ii] = (hit.policy, hit.local_s)
                    else:
                        missing_idx.append(ii); missing_talents.append(nt)
            else:
                missing_idx = list(range(len(items)))
                missing_talents = [x[2] for x in items]
            if missing_talents:
                progress(lvl, 'point-score', respec_layer=r, candidates=len(missing_talents), mobs=int(score_mobs))
                results = score_many(lvl, missing_talents, cfg, score_mobs, lvl_seed,
                                     score_cache, executor, coarse=True)
                for ii, (pol, res) in zip(missing_idx, results):
                    resolved[ii] = (pol, res['total_s'] * (100.0 / score_mobs))
            for (st, name, nt), (pol, score) in zip(items, resolved):
                next_layers[r].append(OuterState(
                    nt, st.cumulative_s + score * level_weight_per_100(lvl), r,
                    st.events + [Event(lvl, 'point', name, eng.policy_desc(pol, lvl), score)],
                    st.last_respec_level,
                    getattr(st, 'coherence_penalty', 0.0) + talent_alignment_penalty(nt, pol)))

        local_dest_k = min(len(pools[lvl]), dest_k * (2 if lvl in probe_levels else 1))
        progress(lvl, 'destination-shortlist', pool=len(pools[lvl]), dest_k=int(local_dest_k), probe=(lvl in probe_levels))
        dests = destination_shortlist(lvl, pools[lvl], cfg, dest_cheap_mobs, dest_refine_mobs,
                                      local_dest_k, seed, score_cache, executor, exploration_frac,
                                      pool_precision_mobs)
        if dests and int(pool_precision_mobs) < int(score_mobs):
            progress(lvl, 'destination-score', candidates=len(dests), mobs=int(score_mobs))
            raw_dst = score_many(lvl, [d.talents for d in dests], cfg, score_mobs, lvl_seed,
                                 score_cache, executor, coarse=True)
            dst_scored = [(pol, res['total_s'] * (100.0 / score_mobs)) for pol, res in raw_dst]
        else:
            dst_scored = [(d.policy, d.local_s) for d in dests]
        for r in range(1, max_respecs + 1):
            if not layers[r - 1]:
                continue
            src = min(layers[r - 1], key=state_rank_key)
            for dst, (pol, score) in zip(dests, dst_scored):
                alloc = eng.final_allocation(dst.talents)
                next_layers[r].append(OuterState(
                    dst.talents, src.cumulative_s + score * level_weight_per_100(lvl), r,
                    src.events + [Event(lvl, 'respec', alloc, eng.policy_desc(pol, lvl), score)], lvl,
                    getattr(src, 'coherence_penalty', 0.0) + talent_alignment_penalty(dst.talents, pol)))

        for r in range(max_respecs + 1):
            vals = next_layers[r]
            if vals and selection_mobs>int(score_mobs):
                # Cheap scoring may only prefilter. Keep a generous shortlist,
                # then re-score its current-level contribution at the frontier's
                # real precision before the actual beam prune. This removes the
                # systematic best-of-noise bias that produced bizarre dead-point
                # talent paths and 64m -> 100m score jumps.
                refine_width=min(len(vals),max(beam_width, min(192, beam_width*3)))
                vals=retain_outer_schedule_diverse(
                    vals,refine_width,exploration_frac,probe_levels)
                progress(lvl, 'selection-refine', respec_layer=r, candidates=len(vals), mobs=int(selection_mobs))
                vals=_refine_outer_level_states(
                    vals,lvl,cfg,selection_mobs,lvl_seed,score_cache,executor)
            layers[r] = retain_outer_schedule_diverse(
                vals, beam_width, exploration_frac, probe_levels) if vals else []

        bests = []
        for r in range(max_respecs + 1):
            if layers[r]:
                b = min(layers[r], key=state_rank_key)
                bests.append(f'r{r}={b.cumulative_s/3600:.3f}h')
        progress(lvl, 'done', layers=sum(len(v) for v in layers.values()))
        print(f'[outer {lvl:02d}] ' + ' '.join(bests), flush=True)
        current_level = lvl
        data = {
            'version': 7, 'phase': 'outer', 'snapshot_mode': 'independent_pnp_v3', 'snapshot_pools': pools,
            'objective_version': OBJECTIVE_VERSION,
            'sim_code_hash': pnp_cache.current_sim_hash(),
            'structural_semantics_hash': _structural_frontier_semantics_hash(),
            'outer_layers': layers, 'outer_level': lvl, 'use_best_water': bool(cfg.use_best_water),
            'search_meta': {
                'start_level': start_level, 'end_level': end_level, 'target_ding_level': TARGET_DING_LEVEL,
                'objective_end_level': min(end_level, LAST_XP_LEVEL), 'objective_version': OBJECTIVE_VERSION,
                'beam_width': beam_width, 'score_mobs': score_mobs,
                'selection_mobs': selection_mobs,
                'dest_cheap_mobs': dest_cheap_mobs, 'dest_refine_mobs': dest_refine_mobs,
                'dest_k': dest_k, 'seed': seed, 'exploration_frac': exploration_frac,
                'outer_search_semantics_version': OUTER_SEARCH_SEMANTICS_VERSION,
            },
        }
        if checkpoint:
            save_checkpoint(checkpoint, data)
        if callback:
            callback(data)
    return layers


def migrate_outer_search_checkpoint(data: Optional[dict], use_best_water: bool) -> tuple[Optional[dict], bool]:
    """Drop only stale outer layers after incompatible outer-search changes.

    Per-level snapshot pools remain valid and expensive stochastic cache entries
    stay on disk.  This specifically makes upgrades from the Fast->MC probe
    explosion regression self-healing instead of requiring users to delete state.
    """
    if not data or data.get('phase') != 'outer':
        return data, False
    saved = int((data.get('search_meta') or {}).get('outer_search_semantics_version') or 0)
    if saved == OUTER_SEARCH_SEMANTICS_VERSION:
        return data, False
    return ({
        'version': 7, 'phase': 'snapshots', 'snapshot_mode': 'independent_pnp_v3',
        'snapshot_pools': data.get('snapshot_pools', {}),
        'use_best_water': bool(use_best_water), 'objective_version': OBJECTIVE_VERSION,
        'sim_code_hash': pnp_cache.current_sim_hash(),
        'structural_semantics_hash': _structural_frontier_semantics_hash(),
    }, True)


def run_search(*, start_level: int, end_level: int, snapshot_width: int, snapshot_mobs: int,
               beam: int, score_mobs: int, dest_cheap_mobs: int, dest_refine_mobs: int,
               dest_k: int, max_respecs: int, seed: int, workers: int,
               checkpoint: Path, resume: bool = True, exploration_frac: float = 0.15,
               callback: CheckpointCallback = None, seed_dir: Optional[Path] = None,
               cross_seed_dirs: Optional[List[Path]] = None, use_best_water: bool = True,
               respec_prior_schedules: Optional[List[List[int]]] = None,
               incumbent_hours_provider: Optional[Callable[[], Optional[float]]] = None,
               fastlane_max_per_preview: int = 3):
    eng.school_isolation_selftest()
    pnp_cache.ensure_db()
    cfg = eng.SimConfig(use_best_water=bool(use_best_water), seed=seed, root_break_mode='scaled')
    data = load_checkpoint(checkpoint) if resume else None
    if data and data.get('sim_code_hash') != pnp_cache.current_sim_hash():
        # Numerical checkpoint state belongs to another simulator cohort. Old disk
        # cache/seed files may still guide candidate ordering, but scores/layers
        # cannot be authoritative under the current code hash.
        old_hash = data.get('sim_code_hash')
        print(f'[sim migration] checkpoint hash {old_hash or "legacy"} != {pnp_cache.current_sim_hash()}; rebuilding numeric map/reduce from current cache', flush=True)
        data = None
    # Old snapshot checkpoints used a performance ancestry beam and are unsafe
    # as free-respec destination pools. Preserve them on disk, but never resume
    # them into the independent-seed search.
    if data and data.get('snapshot_mode') != 'independent_pnp_v3':
        print('[seed migration] legacy ancestry snapshot/outer state ignored; rebuilding independent per-level banks', flush=True)
        data = None
    if data:
        # Historical checkpoints predate dual-water search and were always
        # best-available-water. Never resume a checkpoint under the other
        # recovery model.
        checkpoint_best_water = bool(data.get('use_best_water', True))
        if checkpoint_best_water != bool(use_best_water):
            print('[water migration] checkpoint belongs to the other water mode; rebuilding this track', flush=True)
            data = None
    if data and data.get('phase') == 'outer' and data.get('objective_version') != OBJECTIVE_VERSION:
        # Local per-level seed pools remain valid: their scores are still min/100.
        # Only cumulative outer-DP values are invalid because level weights changed.
        print('[objective migration] old equal-100-mobs outer DP ignored; keeping independent seed pools and rebuilding XP-weighted 11->60 path', flush=True)
        data = {
            'version': 7, 'phase': 'snapshots', 'snapshot_mode': 'independent_pnp_v3',
            'snapshot_pools': data.get('snapshot_pools', {}),
            'use_best_water': bool(use_best_water), 'objective_version': OBJECTIVE_VERSION,
            'sim_code_hash': pnp_cache.current_sim_hash(),
            'structural_semantics_hash': _structural_frontier_semantics_hash(),
        }
    data, outer_migrated = migrate_outer_search_checkpoint(data, bool(use_best_water))
    if outer_migrated:
        print(f'[outer migration] incompatible saved outer frontier -> v{OUTER_SEARCH_SEMANTICS_VERSION}; '
              'discarding saved outer layers, preserving snapshot pools/cache', flush=True)
    executor = ProcessPoolExecutor(max_workers=max(1, workers), initializer=_worker_init) if workers > 1 else None
    try:
        existing_pools = data.get('snapshot_pools', {}) if data else {}
        existing_work = data.get('pnp_work', {}) if data else {}
        outer_resume = data if data and data.get('phase') == 'outer' else None
        snapshots_final = bool(
            (data and data.get('phase') == 'outer') or
            (existing_work and all(j.get('done') for j in existing_work.values()))
        )
        if snapshots_final and existing_pools and max(existing_pools) >= end_level:
            pools = existing_pools
        else:
            # Resume the precision frontier even before any level reached 100m.
            # The old code required snapshot_pools to be nonempty, so Ctrl-C at
            # 32m could reload the checkpoint yet silently restart scheduling at
            # 1m. pnp_work is the authoritative in-flight mapper state.
            pool_resume = data if data and (existing_work or existing_pools) else None

            def frontier_preview(preview_pools, precision_mobs, snapshot_data):
                if not callback:
                    return
                # Quick full-arc answer first, then progressively improve it as
                # the per-level map advances 1->2->4... The preview never writes
                # authoritative best files and never replaces the mapper checkpoint.
                if precision_mobs <= 1:
                    # The first answer is intentionally greedy/cheap. Its job is
                    # visibility in seconds, not authority; later frontiers widen.
                    pbeam, pk = 1, min(dest_k, 3)
                elif precision_mobs <= 2:
                    pbeam, pk = min(beam, 4), min(dest_k, 4)
                elif precision_mobs <= 4:
                    pbeam, pk = min(beam, 8), min(dest_k, 6)
                else:
                    pbeam, pk = beam, dest_k
                pscore = min(score_mobs, precision_mobs)
                pcheap = min(dest_cheap_mobs, precision_mobs)
                prefine = min(dest_refine_mobs, precision_mobs)
                objective_end = min(end_level, LAST_XP_LEVEL)
                print(f'[preview start] precision={precision_mobs}m full-arc beam={pbeam} '
                      f'proposal={pscore}m select={precision_mobs}m dest={pcheap}->{prefine} k={pk}', flush=True)
                fastlane_seen = set()
                fastlane_fired = 0

                def preview_outer_progress(partial_data: dict):
                    nonlocal fastlane_fired
                    if not callback or not incumbent_hours_provider:
                        return
                    lvl = int(partial_data.get('outer_level') or 0)
                    # Early levels are cheap enough to let the normal preview run;
                    # fast-forward only once a genuinely substantial prefix exists.
                    if lvl >= objective_end or lvl < max(20, start_level + 8):
                        return
                    if fastlane_fired >= max(0, int(fastlane_max_per_preview)):
                        return
                    try:
                        incumbent_h = incumbent_hours_provider()
                        incumbent_s = float(incumbent_h) * 3600.0 if incumbent_h is not None else math.inf
                    except Exception:
                        incumbent_s = math.inf
                    if not math.isfinite(incumbent_s):
                        return

                    candidates = []
                    for states in (partial_data.get('outer_layers') or {}).values():
                        for st in states:
                            optimistic = optimistic_outer_total_s(st, lvl, objective_end, preview_pools)
                            if optimistic < incumbent_s:
                                candidates.append((optimistic, state_rank_key(st), st))
                    if not candidates:
                        return
                    candidates.sort(key=lambda x: (x[0], x[1]))

                    for optimistic, _rank, st in candidates:
                        prefix_key = (int(precision_mobs), lvl, st.respecs_used,
                                      talent_key(st.talents), respec_schedule(st))
                        if prefix_key in fastlane_seen:
                            continue
                        fastlane_seen.add(prefix_key)
                        focused = {r: [] for r in range(max_respecs + 1)}
                        focused[int(st.respecs_used)] = [st]
                        resume = {'outer_layers': focused, 'outer_level': lvl}
                        fbeam = max(1, min(pbeam, 3))
                        fk = max(1, min(pk, 4))
                        print(f'[fastlane] precision={precision_mobs}m lvl={lvl} optimistic={optimistic/3600:.4f}h '
                              f'< incumbent={incumbent_s/3600:.4f}h; focused finish -> {objective_end}', flush=True)
                        def fastlane_stage_progress(info: dict):
                            if callback:
                                callback({
                                    'phase': 'outer_fastlane_progress',
                                    'outer_level': int(info.get('level') or 0),
                                    'preview_precision_mobs': int(precision_mobs),
                                    'outer_stage': info.get('stage'),
                                    'outer_stage_detail': {k: v for k, v in info.items() if k not in {'level', 'stage'}},
                                })

                        full_layers = optimize_free_respec(
                            start_level, objective_end, preview_pools, cfg, max_respecs,
                            fbeam, pscore, pcheap, prefine, fk, seed,
                            checkpoint=None, resume_data=resume, executor=executor,
                            exploration_frac=min(exploration_frac, 0.20), callback=None,
                            pool_precision_mobs=precision_mobs,
                            respec_prior_schedules=respec_prior_schedules,
                            progress_callback=fastlane_stage_progress)
                        fdata = dict(snapshot_data)
                        fdata.update({
                            'phase': 'outer_fastlane', 'outer_layers': full_layers,
                            'outer_level': objective_end, 'snapshot_pools': preview_pools,
                            'preview_precision_mobs': int(precision_mobs),
                            'fastlane_from_level': lvl,
                            'fastlane_optimistic_hours': optimistic / 3600.0,
                            'fastlane_incumbent_hours': incumbent_s / 3600.0,
                        })
                        fastlane_fired += 1
                        callback(fdata)
                        break

                def preview_stage_progress(info: dict):
                    if not callback:
                        return
                    callback({
                        'phase': 'outer_preview_progress',
                        'outer_level': int(info.get('level') or 0),
                        'preview_precision_mobs': int(precision_mobs),
                        'outer_stage': info.get('stage'),
                        'outer_stage_detail': {k: v for k, v in info.items() if k not in {'level', 'stage'}},
                    })

                preview_layers = optimize_free_respec(
                    start_level, objective_end, preview_pools, cfg, max_respecs,
                    pbeam, pscore, pcheap, prefine, pk, seed,
                    checkpoint=None, resume_data=None, executor=executor,
                    exploration_frac=exploration_frac, callback=preview_outer_progress,
                    pool_precision_mobs=precision_mobs,
                    respec_prior_schedules=respec_prior_schedules,
                    progress_callback=preview_stage_progress)
                pdata = dict(snapshot_data)
                pdata.update({
                    'phase': 'outer_preview', 'outer_layers': preview_layers,
                    'outer_level': objective_end, 'snapshot_pools': preview_pools,
                    'preview_precision_mobs': int(precision_mobs),
                    'search_meta': {
                        'start_level': start_level, 'end_level': end_level,
                        'target_ding_level': TARGET_DING_LEVEL,
                        'objective_end_level': objective_end,
                        'objective_version': OBJECTIVE_VERSION,
                        'beam_width': pbeam, 'score_mobs': pscore,
                        'selection_mobs': int(precision_mobs),
                        'dest_cheap_mobs': pcheap, 'dest_refine_mobs': prefine,
                        'dest_k': pk, 'seed': seed, 'exploration_frac': exploration_frac,
                        'outer_search_semantics_version': OUTER_SEARCH_SEMANTICS_VERSION,
                        'preview_precision_mobs': int(precision_mobs),
                    },
                })
                callback(pdata)

            pools = build_snapshot_pools(start_level, end_level, cfg, snapshot_width, snapshot_mobs,
                                         seed, checkpoint, pool_resume, executor,
                                         exploration_frac, callback, frontier_preview,
                                         seed_dir, cross_seed_dirs)
            if outer_resume:
                outer_resume['snapshot_pools'] = pools
                outer_resume['snapshot_mode'] = 'independent_pnp_v3'
                outer_resume['use_best_water'] = bool(use_best_water)
                outer_resume['sim_code_hash'] = pnp_cache.current_sim_hash()
                save_checkpoint(checkpoint, outer_resume)
            else:
                data = {
                    'version': 7, 'phase': 'snapshots', 'snapshot_mode': 'independent_pnp_v3',
                    'snapshot_pools': pools, 'use_best_water': bool(use_best_water),
                    'objective_version': OBJECTIVE_VERSION,
                    'sim_code_hash': pnp_cache.current_sim_hash(),
                    'structural_semantics_hash': _structural_frontier_semantics_hash(),
                }
                save_checkpoint(checkpoint, data)
        objective_end_level = min(end_level, LAST_XP_LEVEL)
        if end_level >= TARGET_DING_LEVEL:
            print(f'[objective] Classic Era XP-weighted 11->60: outer DP scores levels {start_level}-{objective_end_level}; level 60 seed remains viewer-only', flush=True)
        def final_stage_progress(info: dict):
            if callback:
                callback({
                    'phase': 'outer_progress',
                    'outer_level': int(info.get('level') or 0),
                    'preview_precision_mobs': int(max(pnp_cache.PRECISION_LADDER)),
                    'outer_stage': info.get('stage'),
                    'outer_stage_detail': {k: v for k, v in info.items() if k not in {'level', 'stage'}},
                })

        layers = optimize_free_respec(
            start_level, objective_end_level, pools, cfg, max_respecs, beam, score_mobs,
            dest_cheap_mobs, dest_refine_mobs, dest_k, seed, checkpoint,
            outer_resume, executor, exploration_frac, callback,
            pool_precision_mobs=max(pnp_cache.PRECISION_LADDER),
            respec_prior_schedules=respec_prior_schedules,
            progress_callback=final_stage_progress)
        pnp_cache.flush_writes()
        return layers
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)


def all_top_states(layers: Dict[int, List[OuterState]], top_k: int = 8):
    out = []
    for states in layers.values():
        out.extend(states)
    return sorted(out, key=state_rank_key)[:top_k]


def parse_allocation(text: str, *, strict: bool = True) -> eng.Talents:
    """Parse a persisted allocation. Production replay is strict by default.

    Silent dropping of unknown/duplicate/malformed fields can make a persisted
    candidate replay as a *different* talent path, so strict mode rejects them.
    """
    vals = {name: 0 for name in eng.Talents.__dataclass_fields__}
    seen = set()
    text = (text or '').strip()
    if not text:
        return eng.Talents()
    for part in text.split(','):
        part = part.strip()
        if not part:
            continue
        if '=' not in part:
            if strict:
                raise ValueError(f'malformed allocation field: {part!r}')
            continue
        name, raw = part.split('=', 1)
        name = name.strip()
        if name not in vals:
            if strict:
                raise ValueError(f'unknown talent in allocation: {name!r}')
            continue
        if name in seen:
            if strict:
                raise ValueError(f'duplicate talent in allocation: {name!r}')
            continue
        seen.add(name)
        try:
            value = int(raw.strip())
        except Exception as e:
            if strict:
                raise ValueError(f'invalid rank for {name}: {raw!r}') from e
            continue
        max_rank = int(eng.TALENT_RULES[name][1])
        if value < 0 or value > max_rank:
            if strict:
                raise ValueError(f'out-of-range rank for {name}: {value} not in 0..{max_rank}')
            value = max(0, min(max_rank, value))
        vals[name] = value
    return eng.Talents(**vals)


def _reconstruct_legacy_prefix(target: eng.Talents, level: int, persisted_detail: str = '') -> list[str]:
    """Return one legal point order from level 10 through ``level``.

    Older persisted full-path candidates sometimes start with a level-11
    allocation snapshot instead of carrying the unscored level-10 point row.
    For a first snapshot only, that missing prefix is semantically recoverable:
    level 10 is outside the scored objective and only the allocation present at
    level 11 matters.  If a point ``detail`` is persisted for the snapshot we
    preserve it as the final point in the reconstructed prefix.
    """
    level = int(level)
    expected = level - 9
    if expected <= 0:
        raise ValueError(f'cannot reconstruct talent prefix for level {level}')
    fields = tuple(target.__dataclass_fields__)
    target_key = tuple(int(getattr(target, name)) for name in fields)
    if sum(target_key) != expected:
        raise ValueError(
            f'first allocation at level {level} has {sum(target_key)} points; expected {expected}'
        )
    wanted_last = str(persisted_detail or '').strip()
    if wanted_last and wanted_last not in fields:
        raise ValueError(f'unknown persisted first-point detail: {wanted_last!r}')
    memo = set()

    def key(t):
        return tuple(int(getattr(t, name)) for name in fields)

    def dfs(cur: eng.Talents, depth: int):
        ck = key(cur)
        if ck == target_key:
            return []
        state_key = (ck, depth)
        if state_key in memo:
            return None
        memo.add(state_key)
        remaining = expected - depth
        names = fields
        if remaining == 1 and wanted_last:
            names = (wanted_last,)
        for name in names:
            if int(getattr(cur, name)) >= int(getattr(target, name)):
                continue
            try:
                nxt = eng.add_point(cur, name)
            except Exception:
                continue
            nk = key(nxt)
            if any(nk[i] > target_key[i] for i in range(len(nk))):
                continue
            tail = dfs(nxt, depth + 1)
            if tail is not None:
                return [name] + tail
        return None

    out = dfs(eng.Talents(), 0)
    if out is None:
        suffix = f' ending in {wanted_last}' if wanted_last else ''
        raise ValueError(f'cannot reconstruct legal level-{level} talent prefix{suffix}')
    return out


def outer_state_from_replay(rows, *, cumulative_hours_hint=None) -> OuterState:
    """Reconstruct a replayable OuterState from persisted replay rows.

    This is intentionally allocation-driven rather than trusting historical
    ``detail`` strings.  It lets a stale top path be replayed under a new
    simulator hash even if older UI/event labels changed: point actions are
    inferred from consecutive allocations and respec actions use the persisted
    destination allocation verbatim.
    """
    if not isinstance(rows, list) or not rows:
        raise ValueError('replay rows required')
    prev = eng.Talents()
    events = []
    last_respec = None
    weighted_s = 0.0
    for raw in rows:
        if not isinstance(raw, dict) or raw.get('level') is None:
            continue
        lvl = int(raw['level'])
        alloc = str(raw.get('allocation') or '').strip()
        if not alloc:
            raise ValueError(f'missing allocation at level {lvl}')
        cur = parse_allocation(alloc)
        action = str(raw.get('action') or raw.get('kind') or 'point').strip().lower()
        if action in {'free respec', 'free_respec'}:
            action = 'respec'
        try:
            score_s = float(raw.get('normalized_min_per_100') or 0.0) * 60.0
        except Exception:
            score_s = 0.0
        policy = str(raw.get('rotation') or raw.get('policy') or 'unscored')

        # Backward compatibility for legacy full paths whose first persisted
        # row is a level-11 allocation snapshot.  Such a row legitimately has
        # two talent points (levels 10 and 11), so comparing it directly with
        # an empty allocation falsely looks like a two-point jump.  Rebuild the
        # unscored prefix, preserving a persisted final point label when one is
        # available.  This is intentionally first-row-only: mid-path multi-point
        # jumps remain hard errors.
        if not events and action != 'respec' and lvl > 10:
            point_count = sum(int(getattr(cur, name)) for name in eng.Talents.__dataclass_fields__)
            expected_points = lvl - 9
            if point_count == expected_points and expected_points > 1:
                persisted = str(raw.get('detail') or '').strip()
                names = _reconstruct_legacy_prefix(cur, lvl, persisted)
                prefix_cur = eng.Talents()
                for i, name in enumerate(names):
                    plvl = 10 + i
                    prefix_cur = eng.add_point(prefix_cur, name)
                    is_snapshot = plvl == lvl
                    ppolicy = policy if is_snapshot else 'unscored'
                    pscore = score_s if is_snapshot else 0.0
                    events.append(Event(plvl, 'point', name, ppolicy, pscore))
                    if plvl >= 11:
                        weighted_s += pscore * level_weight_per_100(plvl)
                prev = prefix_cur
                continue

        if action == 'respec':
            detail = alloc
            last_respec = lvl
        else:
            deltas = []
            decreased = False
            for name in eng.Talents.__dataclass_fields__:
                d = int(getattr(cur, name)) - int(getattr(prev, name))
                if d < 0:
                    decreased = True
                if d > 0:
                    deltas.extend([name] * d)
            if len(deltas) != 1 or decreased:
                raise ValueError(f'point row at level {lvl} is not previous allocation + exactly one point')
            inferred = deltas[0]
            persisted = str(raw.get('detail') or '').strip()
            if persisted and persisted != inferred:
                raise ValueError(f'point detail mismatch at level {lvl}: {persisted!r} != {inferred!r}')
            detail = inferred
            action = 'point'
        events.append(Event(lvl, action, detail, policy, score_s))
        if lvl >= 11:
            weighted_s += score_s * level_weight_per_100(lvl)
        prev = cur
    if not events:
        raise ValueError('no replayable events')
    # Ensure every scored row's compact descriptor remains parseable before a
    # large startup replay batch is launched.
    for ev in events:
        if ev.level >= 11 and ev.policy and ev.policy != 'unscored':
            policy_from_desc(ev.policy, ev.level)
    try:
        cumulative_s = float(cumulative_hours_hint) * 3600.0 if cumulative_hours_hint is not None else weighted_s
    except Exception:
        cumulative_s = weighted_s
    return OuterState(
        talents=prev,
        cumulative_s=cumulative_s,
        respecs_used=sum(1 for ev in events if ev.kind == 'respec'),
        events=events,
        last_respec_level=last_respec,
    )


def replay_state(st: OuterState):
    talents = eng.Talents()
    rows = []
    for ev in st.events:
        if ev.kind == 'point':
            talents = eng.add_point(talents, ev.detail)
        elif ev.kind == 'respec':
            talents = parse_allocation(ev.detail)
        rows.append({
            'level': ev.level,
            'action': ev.kind,
            'detail': ev.detail,
            'allocation': eng.final_allocation(talents),
            'rotation': ev.policy,
            'normalized_min_per_100': ev.score_s / 60.0,
            **objective_level_meta(ev.level),
            'weighted_level_hours': ev.score_s * level_weight_per_100(ev.level) / 3600.0,
            'avg_active_dps': None,
        })
    return rows


def write_replay_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    fields = ['level', 'action', 'detail', 'allocation', 'rotation', 'rotation_details',
              'sanity_flags', 'normalized_min_per_100', 'avg_active_dps',
              'xp_to_next', 'estimated_same_level_mobs', 'weighted_level_hours']
    try:
        with tmp.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            w.writeheader()
            for raw in rows:
                r = dict(raw)
                if isinstance(r.get('rotation_details'), list):
                    r['rotation_details'] = ' | '.join(r['rotation_details'])
                if isinstance(r.get('sanity_flags'), list):
                    r['sanity_flags'] = ' | '.join(r['sanity_flags'])
                w.writerow(r)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def talents_by_level(st: OuterState):
    talents = eng.Talents()
    out = {}
    for ev in st.events:
        if ev.kind == 'point':
            talents = eng.add_point(talents, ev.detail)
        elif ev.kind == 'respec':
            talents = parse_allocation(ev.detail)
        out[ev.level] = talents
    return out


def policy_from_desc(desc: str, level: int) -> eng.Policy:
    """Strict shared decoder for the persisted compact policy contract."""
    return policy_codec.parse_descriptor(desc, level)


def replay_matches_primary_school(replay, school: str = 'all') -> bool:
    """True when every scored replay row uses the requested primary rotation school.

    Talent allocation is deliberately ignored: Frost paths may spend in Arcane
    (or any other tree) for support.  Only the persisted primary policy identity
    is constrained.
    """
    wanted=eng.normalize_primary_school(school)
    if wanted=='all':
        return True
    seen=False
    for raw in replay or []:
        try:
            lvl=int(raw.get('level'))
        except Exception:
            continue
        if lvl < 11:
            continue
        desc=str(raw.get('rotation') or raw.get('policy') or '').strip()
        if not desc or desc.lower()=='unscored':
            continue
        try:
            pol=policy_from_desc(desc,lvl)
        except Exception:
            return False
        seen=True
        if eng.policy_primary_school(pol)!=wanted:
            return False
    return seen


def outer_state_matches_primary_school(st: OuterState, school: str = 'all') -> bool:
    wanted=eng.normalize_primary_school(school)
    if wanted=='all':
        return True
    seen=False
    for ev in getattr(st,'events',()) or ():
        if int(getattr(ev,'level',0)) < 11:
            continue
        desc=str(getattr(ev,'policy','') or '').strip()
        if not desc or desc.lower()=='unscored':
            continue
        try:
            pol=policy_from_desc(desc,int(ev.level))
        except Exception:
            return False
        seen=True
        if eng.policy_primary_school(pol)!=wanted:
            return False
    return seen



def _active_dps_from_metrics(level:int, n:int, metrics:dict) -> float:
    total_hp=0.0
    for i in range(max(0,int(n))):
        ml=int(level)+(1 if i%2==0 else 2)
        total_hp += float(eng.MOB_BASE_HP[ml])
    kill_s=float((metrics or {}).get('kill_s') or 0.0)
    v=(total_hp/kill_s) if kill_s>eng.EPS else 0.0
    return v if math.isfinite(v) and v>=0 else 0.0


def repair_terminal_point(st: OuterState, validated: dict, *, n:int=100,
                          use_best_water:bool=True):
    """Deterministic BEST safety-net for the final leveling talent point.

    Re-evaluate every legal level-59 point from the exact level-58 allocation at
    the same precision.  This catches absurd terminal filler choices such as
    Fire Warding when a directly useful damage/mana talent is legal.  The search
    remains free to explore anything; this gate merely refuses to promote a
    trivially dominated last point.

    Returns (state, validated, marginal_samples, info).  Marginal samples compare
    every legal point against the same under-spent level-58 base, so they are
    genuine same-context one-rank effects rather than cross-level differences.
    """
    if not st.events or not validated or int(n)<1:
        return st, validated, [], {'checked':False,'reason':'missing'}
    idx=max((i for i,e in enumerate(st.events) if int(e.level)==LAST_XP_LEVEL), default=-1)
    if idx<0:
        return st, validated, [], {'checked':False,'reason':'no_terminal_level'}
    ev=st.events[idx]
    if ev.kind!='point':
        return st, validated, [], {'checked':False,'reason':'terminal_not_point'}

    before=eng.Talents()
    for e in st.events[:idx]:
        if e.kind=='point':
            try: before=eng.add_point(before,e.detail)
            except Exception: pass
        elif e.kind=='respec':
            before=parse_allocation(e.detail)
    options=[(name,t) for name,t in eng.talent_candidates(before)
             if t.points()==LAST_XP_LEVEL-9]
    if len(options)<=1:
        return st, validated, [], {'checked':True,'reason':'no_alternatives'}

    cfg=eng.SimConfig(use_best_water=bool(use_best_water),seed=9001,root_break_mode='scaled')
    score_cache={}
    # Base is intentionally one point under budget: same level, same gear/mobs,
    # only the candidate talent rank is absent. This makes the recorded marginal
    # effect interpretable and avoids attributing donor effects to the receiver.
    scored_base=score_many(LAST_XP_LEVEL,[before],cfg,int(n),9001,score_cache,None,coarse=True)[0]
    base_pol,base_res=scored_base
    base_min100=float(base_res['total_s'])*(100.0/int(n))/60.0
    base_dps=_active_dps_from_metrics(LAST_XP_LEVEL,int(n),base_res)

    scored=score_many(LAST_XP_LEVEL,[t for _,t in options],cfg,int(n),9001,score_cache,None,coarse=True)
    samples=[]; ranked=[]
    for (name,t),(pol,res) in zip(options,scored):
        min100=float(res['total_s'])*(100.0/int(n))/60.0
        dps=_active_dps_from_metrics(LAST_XP_LEVEL,int(n),res)
        rank=int(getattr(t,name))
        samples.append({
            'talent':name,'rank':rank,'level':LAST_XP_LEVEL,'n':int(n),
            'delta_min_per_100':base_min100-min100,
            'delta_active_dps':dps-base_dps,
            'min_per_100':min100,'active_dps':dps,
        })
        ranked.append((float(res['total_s']),name,t,pol,res))
    ranked.sort(key=lambda x:(x[0],x[1]))
    _tot,name,best_t,best_pol,best_res=ranked[0]

    # Compare to the actually validated terminal row, not the old search estimate.
    old_row=next((r for r in (validated.get('replay') or []) if int(r.get('level') or -1)==LAST_XP_LEVEL),None)
    old_min100=float((old_row or {}).get('normalized_min_per_100') or math.inf)
    new_min100=float(best_res['total_s'])*(100.0/int(n))/60.0
    if not (new_min100 + 1e-10 < old_min100):
        return st, validated, samples, {
            'checked':True,'changed':False,'old_point':ev.detail,'best_point':name,
            'old_min_per_100':old_min100,'best_min_per_100':new_min100,
        }

    new_ev=Event(ev.level,'point',name,eng.policy_desc(best_pol,LAST_XP_LEVEL),
                 float(best_res['total_s'])*(100.0/int(n)))
    events=list(st.events); events[idx]=new_ev
    old_w=level_weight_per_100(LAST_XP_LEVEL)
    new_cum=st.cumulative_s - ev.score_s*old_w + new_ev.score_s*old_w
    repaired=OuterState(best_t,new_cum,st.respecs_used,events,st.last_respec_level,
                        getattr(st,'coherence_penalty',0.0))
    # Replay all rows for authority; already-cached prefix rows make this cheap.
    new_valid=validate_state(repaired,n=int(n),seed=9001,workers=1,use_best_water=use_best_water)
    if float(new_valid.get('validated_hours',math.inf)) + 1e-12 < float(validated.get('validated_hours',math.inf)):
        return repaired,new_valid,samples,{
            'checked':True,'changed':True,'old_point':ev.detail,'best_point':name,
            'old_min_per_100':old_min100,'best_min_per_100':new_min100,
            'hours_saved':float(validated['validated_hours'])-float(new_valid['validated_hours']),
        }
    return st, validated, samples, {
        'checked':True,'changed':False,'old_point':ev.detail,'best_point':name,
        'old_min_per_100':old_min100,'best_min_per_100':new_min100,
        'reason':'full_replay_not_better',
    }

def _replay_level_worker(args):
    level, talents, policy_desc, cfg, n, _seed = args
    pol = policy_from_desc(policy_desc, level)
    pending = []
    res = pnp_cache.evaluate_policy(level, talents, pol, cfg, target_n=n,
                                    seed=pnp_cache.canonical_seed(level), deferred_writes=pending)
    score_s = res['total_s'] * (100.0 / n)
    # Sanity metric: damage dealt divided by active combat time only. Recovery /
    # drinking is deliberately excluded. The mob stream is deterministic +1/+2.
    active_dps = _active_dps_from_metrics(level, int(n), res)
    return level, policy_desc, score_s, active_dps, pending


def _validation_rows(st: OuterState):
    by_level = talents_by_level(st)
    event_by_level = {ev.level: ev for ev in st.events}
    rows = []
    for lvl in sorted(l for l in by_level if l >= 11):
        ev = event_by_level[lvl]
        rows.append((lvl, by_level[lvl], ev.policy, ev))
    return rows


def validate_states_fast(states: List[OuterState], *, n: int = 100, seed: int = 9001,
                         workers: int = 1, progress_callback=None,
                         heartbeat_callback=None, heartbeat_seconds: float = 60.0,
                         candidate_callback=None, stop_check=None,
                         use_best_water: bool = True):
    """Replay-validate many search candidates as one deduplicated parallel batch.

    Crucially this does *not* call optimize_policy. It replays the exact policy
    selected by search. Shared (level, build, rotation) rows across top candidates
    are simulated once and reused, which makes top-10 100-mob validation cheap
    enough to be an interactive feedback step rather than a second full search.
    """
    states = list(states)
    if not states:
        return []
    cfg = eng.SimConfig(use_best_water=bool(use_best_water), seed=seed, root_break_mode='scaled')
    cand_rows = []
    task_args = {}
    task_to_candidates = {}
    for ci, st in enumerate(states):
        rows = _validation_rows(st)
        cand_rows.append(rows)
        for lvl, talents, policy_desc, _ev in rows:
            key = (lvl, talent_key(talents), policy_desc)
            if key not in task_args:
                task_args[key] = (lvl, talents, policy_desc, cfg, n, seed + lvl * 1000003)
            task_to_candidates.setdefault(key, set()).add(ci)

    results = {}
    total = len(task_args)
    done = 0
    next_heartbeat = time.monotonic() + max(1.0, heartbeat_seconds)
    completed_candidates = set()
    needed_by_candidate = [
        {(lvl, talent_key(t), policy_desc) for lvl, t, policy_desc, _ev in rows}
        for rows in cand_rows
    ]

    def build_validated(ci: int):
        replay = []
        total_s = 0.0
        unweighted_s = 0.0
        for lvl, talents, policy_desc, ev in cand_rows[ci]:
            key = (lvl, talent_key(talents), policy_desc)
            _lvl, rotation, score_s, active_dps = results[key]
            weight = level_weight_per_100(lvl)
            weighted_s = score_s * weight
            total_s += weighted_s
            unweighted_s += score_s
            replay.append({
                'level': lvl,
                'action': ev.kind,
                'detail': ev.detail,
                'allocation': eng.final_allocation(talents),
                'rotation': rotation,
                'normalized_min_per_100': score_s / 60.0,
                **objective_level_meta(lvl),
                'weighted_level_hours': weighted_s / 3600.0,
                'avg_active_dps': active_dps,
            })
        return {
            'validated_hours': total_s / 3600.0,
            'legacy_equal_100_hours': unweighted_s / 3600.0,
            'objective_version': OBJECTIVE_VERSION,
            'target_ding_level': TARGET_DING_LEVEL,
            'validation_mobs': n,
            'validation_seed': pnp_cache.SEED_SCHEME,
            'validation_mode': 'fixed_policy_replay_xp_weighted_pnp',
            'sim_code_hash': pnp_cache.current_sim_hash(),
            'structural_semantics_hash': _structural_frontier_semantics_hash(),
            'use_best_water': bool(use_best_water),
            'water_mode': 'buy_water' if use_best_water else 'conjured_water',
            'replay': replay,
        }

    def maybe_complete_candidates():
        for ci in range(len(states)):
            if ci in completed_candidates:
                continue
            if all(k in results for k in needed_by_candidate[ci]):
                completed_candidates.add(ci)
                val = build_validated(ci)
                if candidate_callback:
                    candidate_callback(ci, val)

    if workers > 1 and total > 1:
        ex = ProcessPoolExecutor(max_workers=workers, initializer=_worker_init)
        futures = {ex.submit(_replay_level_worker, a): key for key, a in task_args.items()}
        pending = set(futures)
        try:
            while pending:
                if stop_check and stop_check():
                    for fut in pending: fut.cancel()
                    raise StopRequested()
                ready, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
                for fut in ready:
                    key = futures[fut]
                    packed = fut.result()
                    row, writes = packed[:4], packed[4]
                    pnp_cache.enqueue_writes(writes)
                    results[key] = row
                    done += 1
                    if progress_callback:
                        progress_callback(done, total, *row)
                maybe_complete_candidates()
                now = time.monotonic()
                if now >= next_heartbeat:
                    if heartbeat_callback:
                        heartbeat_callback(done, total, len(completed_candidates), len(states))
                    next_heartbeat = now + max(1.0, heartbeat_seconds)
        finally:
            ex.shutdown(wait=True, cancel_futures=True)
    else:
        for key, a in task_args.items():
            if stop_check and stop_check():
                raise StopRequested()
            packed = _replay_level_worker(a)
            row, writes = packed[:4], packed[4]
            pnp_cache.enqueue_writes(writes)
            results[key] = row
            done += 1
            if progress_callback:
                progress_callback(done, total, *row)
            maybe_complete_candidates()
            now = time.monotonic()
            if now >= next_heartbeat:
                if heartbeat_callback:
                    heartbeat_callback(done, total, len(completed_candidates), len(states))
                next_heartbeat = now + max(1.0, heartbeat_seconds)

    maybe_complete_candidates()
    return [build_validated(i) for i in range(len(states))]


def validate_state(st: OuterState, *, n: int = 100, seed: int = 9001, workers: int = 1,
                   progress_callback=None, stop_check=None, use_best_water: bool = True):
    """Compatibility wrapper: fixed-policy replay validation for one candidate."""
    vals = validate_states_fast([st], n=n, seed=seed, workers=workers,
                                progress_callback=progress_callback, stop_check=stop_check,
                                use_best_water=use_best_water)
    return vals[0]
