from __future__ import annotations

"""Canonical candidate union and full-path stochastic adjudication.

This layer deliberately knows about persisted candidate dictionaries, but not
about master_optimizer control flow. It converts eligible replay paths into the
strict frozen representation used by :mod:`src.mc_path_race`, deduplicates one
semantic path across Fast/native/historical provenance, and returns an explicit
resolved/unresolved race result.
"""

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from src.engine_registry import eng
from src import optimizer_core as opt
from src import pnp_cache
from src import state_manager as sm
from src.mc_path_race import FrozenLevel, FrozenPath, PathRaceResult, race_paths


@dataclass(frozen=True)
class PreparedCandidate:
    path_id: str
    frozen: FrozenPath
    sources: tuple[str, ...]
    raw_candidates: tuple[dict, ...]


@dataclass(frozen=True)
class AdjudicationResult:
    prepared: tuple[PreparedCandidate, ...]
    race: PathRaceResult
    winner: PreparedCandidate | None
    promoted: bool = False


def _strict_frozen_from_replay(replay: list[dict], *, name: str,
                               expected_levels: Sequence[int]) -> FrozenPath:
    # Reuse the strict legality validator first. This catches malformed point
    # deltas, allocation/detail drift, and unparseable persisted policies.
    opt.outer_state_from_replay(replay)

    by_level: dict[int, FrozenLevel] = {}
    for raw in replay:
        if not isinstance(raw, dict) or raw.get('level') is None:
            continue
        lvl = int(raw['level'])
        if lvl not in expected_levels:
            continue
        allocation = str(raw.get('allocation') or '').strip()
        rotation = str(raw.get('rotation') or raw.get('policy') or '').strip()
        if not allocation:
            raise ValueError(f'missing allocation at level {lvl}')
        if not rotation or rotation == 'unscored':
            raise ValueError(f'missing frozen policy at level {lvl}')
        talents = opt.parse_allocation(allocation)
        policy = opt.policy_from_desc(rotation, lvl)
        by_level[lvl] = FrozenLevel(lvl, talents, policy)

    want = tuple(int(x) for x in expected_levels)
    got = tuple(sorted(by_level))
    if got != tuple(sorted(want)):
        raise ValueError(f'candidate {name!r} does not cover expected levels: got {got}, want {tuple(sorted(want))}')
    return FrozenPath(name, tuple(by_level[lvl] for lvl in want))


def prepare_candidate_union(candidates: Iterable[dict], *,
                            expected_levels: Sequence[int] = tuple(range(11, 60))) -> tuple[PreparedCandidate, ...]:
    grouped: dict[str, list[dict]] = {}
    frozen_by_id: dict[str, FrozenPath] = {}

    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        if raw.get('replayable', True) is False or not raw.get('full_arc', True):
            continue
        replay = raw.get('replay')
        if not isinstance(replay, list) or not replay:
            raise ValueError(f"eligible candidate {raw.get('id','?')} has no replay")
        canonical = sm.candidate_path_id_from_replay(replay)
        persisted = raw.get('path_id')
        if persisted and str(persisted) != canonical:
            raise ValueError(f"candidate {raw.get('id','?')} path_id mismatch")
        frozen = _strict_frozen_from_replay(replay, name=canonical, expected_levels=expected_levels)
        grouped.setdefault(canonical, []).append(raw)
        prior = frozen_by_id.get(canonical)
        if prior is None:
            frozen_by_id[canonical] = frozen
        else:
            # Same canonical replay must imply the same frozen decisions.
            if tuple((x.level, x.talents, eng.policy_desc(x.policy, x.level)) for x in prior.levels) != tuple(
                (x.level, x.talents, eng.policy_desc(x.policy, x.level)) for x in frozen.levels
            ):
                raise ValueError(f'canonical path collision for {canonical}')

    out = []
    for path_id in sorted(grouped):
        rows = grouped[path_id]
        sources = []
        for row in rows:
            vals = list(row.get('sources') or [])
            if row.get('source'):
                vals.append(row.get('source'))
            for src in vals:
                if src and src not in sources:
                    sources.append(str(src))
        out.append(PreparedCandidate(path_id, frozen_by_id[path_id], tuple(sources), tuple(rows)))
    return tuple(out)


def adjudicate_candidates(candidates: Iterable[dict], cfg: eng.SimConfig, *,
                          expected_levels: Sequence[int] = tuple(range(11, 60)),
                          **race_kwargs: Any) -> AdjudicationResult:
    prepared = prepare_candidate_union(candidates, expected_levels=expected_levels)
    if not prepared:
        raise ValueError('no eligible candidates to adjudicate')
    race = race_paths([p.frozen for p in prepared], cfg, **race_kwargs)
    winner = prepared[race.winner_index] if race.resolved else None
    return AdjudicationResult(prepared, race, winner)


def candidate_updates_from_adjudication(result: AdjudicationResult, *, sim_code_hash: str) -> list[dict]:
    """Convert race evidence into mergeable candidate cards.

    Every participant receives race diagnostics.  Only a uniquely resolved
    winner receives authoritative validation fields; unresolved races never
    manufacture a BEST candidate from sample-mean ordering.
    """
    rows_by_idx = {r.candidate_index: r for r in result.race.rows}
    out: list[dict] = []
    for i, prepared in enumerate(result.prepared):
        row = rows_by_idx[i]

        # Prefer the richest persisted representation as a display base while
        # preserving provenance across duplicate sources.
        raw_rows = list(prepared.raw_candidates)
        base = max(
            raw_rows,
            key=lambda c: (
                c.get('validated_hours') is not None,
                int(c.get('validation_mobs') or 0),
                int(c.get('search_precision_mobs') or 0),
            ),
        )
        card = dict(base)
        card['path_id'] = prepared.path_id
        card['sources'] = list(prepared.sources)
        card['path_race_mean_hours'] = row.mean_hours
        card['path_race_stderr_hours'] = row.stderr_hours
        card['path_race_ci_lower_hours'] = row.lower_seconds / 3600.0
        card['path_race_ci_upper_hours'] = row.upper_seconds / 3600.0
        card['path_race_mobs_per_level'] = int(row.mobs_per_level)
        card['path_race_eliminated'] = bool(row.eliminated)
        card['path_race_resolved'] = bool(result.race.resolved)
        card['path_race_survivors'] = list(result.race.survivor_indices)
        card['path_race_rounds'] = int(result.race.rounds)

        # Race evidence supersedes any pre-existing fixed-N validation only for
        # authority. Keep proposal/search fields and provenance for diagnostics.
        card['validated_hours'] = None
        card['validation_mobs'] = None
        card['validation_mode'] = None
        card['sim_code_hash'] = None
        if result.race.resolved and i == result.race.winner_index:
            card['validated_hours'] = row.mean_hours
            card['validation_mobs'] = int(row.mobs_per_level)
            card['validation_mode'] = 'adaptive_path_race'
            card['sim_code_hash'] = str(sim_code_hash)
            card['validation_stderr_hours'] = row.stderr_hours
            card['objective_version'] = opt.OBJECTIVE_VERSION
        out.append(card)
    return out



def provisionalize_fixed_validation(card: dict) -> dict:
    """Keep a fixed-N replay as evidence without granting BEST authority."""
    out = dict(card)
    if out.get('validated_hours') is not None:
        out['fixed_replay_hours'] = out.get('validated_hours')
        out['fixed_replay_mobs'] = out.get('validation_mobs')
        out['fixed_replay_validation_mode'] = out.get('validation_mode')
        out['fixed_replay_sim_code_hash'] = out.get('sim_code_hash')
    out['validated_hours'] = None
    out['validation_mobs'] = None
    out['sim_code_hash'] = None
    out['validation_mode'] = 'fixed_policy_replay_provisional'
    return out


def pnp_cached_simulator(level, talents, policy, cfg, *, target_n, seed, continuation):
    """Path-race simulator backed by the authoritative persistent PnP cache.

    ``seed``/``continuation`` are part of the generic race interface.  Production
    uses the cache's canonical per-level seed and internal continuation so race
    rounds extend the exact same scenario already used by fixed replay/search.
    """
    metrics = pnp_cache.evaluate_policy(
        int(level), talents, policy, cfg,
        target_n=int(target_n), seed=pnp_cache.canonical_seed(int(level)),
    )
    return metrics, {'n': int(target_n)}


def _prepared_rank_key(candidate: PreparedCandidate) -> tuple:
    vals = []
    for raw in candidate.raw_candidates:
        for key in ('path_race_mean_hours', 'validated_hours', 'fixed_replay_hours', 'search_hours', 'fast_analytic_hours'):
            v = raw.get(key)
            if v is not None:
                try:
                    vals.append(float(v))
                    break
                except Exception:
                    pass
    return (min(vals) if vals else float('inf'), candidate.path_id)


def adjudicate_state_candidates(water_mode: str, cfg: eng.SimConfig, *,
                                expected_levels: Sequence[int] = tuple(range(11, 60)),
                                max_candidates: int = 12,
                                school: str = 'all',
                                simulate_incremental=None,
                                checkpoint=None,
                                **race_kwargs: Any) -> AdjudicationResult | None:
    """Race the best persisted full-path union and persist the evidence.

    This is the thin stateful boundary used by ``master_optimizer``. Search,
    bridge and historical candidates all enter through the same canonical replay
    contract. The only authoritative promotion is a uniquely resolved adaptive
    race winner.
    """
    mode = sm.normalize_water_mode(water_mode)
    tp = sm.track_paths(mode)
    path = tp.best / 'top_candidates.json'
    try:
        rows = __import__('json').loads(path.read_text(encoding='utf-8')) if path.exists() else []
    except Exception as exc:
        raise ValueError(f'cannot read candidate state for adjudication: {exc}') from exc
    if not isinstance(rows, list):
        raise ValueError('top_candidates state is not a list')
    eligible = [
        r for r in rows if isinstance(r, dict)
        and r.get('replayable', True) is not False
        and r.get('full_arc', False)
        and r.get('objective_version') == opt.OBJECTIVE_VERSION
        and isinstance(r.get('replay'), list) and r.get('replay')
        and opt.replay_matches_primary_school(r.get('replay') or [], school)
    ]
    if not eligible:
        return None

    # Persisted state may contain an old or partially-written candidate that
    # satisfies the cheap metadata gate but fails the strict replay contract.
    # Fault-isolate those rows here: one bad historical/Fast challenger must
    # never abort adjudication of otherwise valid full paths.  The strict pure
    # prepare_candidate_union() API still raises by default for callers/tests
    # that want malformed input to fail loudly.
    strict_eligible = []
    rejected = []
    for raw in eligible:
        try:
            prepare_candidate_union([raw], expected_levels=expected_levels)
        except Exception as exc:
            rejected.append((raw, exc))
            continue
        strict_eligible.append(raw)
    for raw, exc in rejected:
        print(
            f'[path race skip] water={mode} id={raw.get("id", "?")} '
            f'reason={type(exc).__name__}: {exc}',
            flush=True,
        )
    if not strict_eligible:
        return None

    prepared = list(prepare_candidate_union(strict_eligible, expected_levels=expected_levels))
    prepared.sort(key=_prepared_rank_key)
    prepared = prepared[:max(1, int(max_candidates))]
    sim = simulate_incremental or pnp_cached_simulator
    race = race_paths([p.frozen for p in prepared], cfg,
                      simulate_incremental=sim, **race_kwargs)
    result = AdjudicationResult(
        tuple(prepared), race,
        prepared[race.winner_index] if race.resolved else None,
    )
    updates = candidate_updates_from_adjudication(result, sim_code_hash=pnp_cache.current_sim_hash())
    sm.merge_display_candidates(updates, max_k=max(8, int(max_candidates)), water_mode=mode)
    sm.atomic_write_json(tp.best / 'adaptive_path_race.json', {
        'resolved': bool(race.resolved),
        'winner_path_id': (result.winner.path_id if result.winner else None),
        'survivor_path_ids': [prepared[i].path_id for i in race.survivor_indices],
        'rounds': int(race.rounds),
        'total_mobs_simulated': int(race.total_mobs_simulated),
        'critical_z': float(race.critical_z),
        'rows': [
            {
                'path_id': prepared[r.candidate_index].path_id,
                'mean_hours': r.mean_hours,
                'stderr_hours': r.stderr_hours,
                'ci_lower_hours': r.lower_seconds / 3600.0,
                'ci_upper_hours': r.upper_seconds / 3600.0,
                'mobs_per_level': int(r.mobs_per_level),
                'eliminated': bool(r.eliminated),
            }
            for r in race.rows
        ],
    })
    promoted = False
    if race.resolved:
        winner_card = next(u for u in updates if u.get('path_id') == result.winner.path_id)
        promoted = sm.set_authoritative_race_winner(winner_card, checkpoint, mode, school=school)
    return AdjudicationResult(result.prepared, result.race, result.winner, promoted)
