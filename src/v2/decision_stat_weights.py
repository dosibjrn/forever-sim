from __future__ import annotations

"""Canonical stat-weight authority for listener-selectable decision rows.

The listener must never depend on whether a route happened to survive a
spec-matrix publication.  A decision row identifies one fixed scorer state
(level, talents, gear, policy/profile).  This module fingerprints that state and
attaches the class backend's canonical local sensitivity model.  Existing
published weights are preserved; missing weights are rehydrated once and cached
by the scorer-state fingerprint.

This is deliberately *not* a talent search.  Rehydration scores one fixed
allocation only, and only when an older/incomplete publication omitted weights.
Normal current publications should already carry them.
"""

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping
from contextlib import contextmanager
from threading import RLock

from src.class_registry import get_definition
from .stat_weight_model import compute_for_engine


class StatWeightContractError(RuntimeError):
    pass


# Process-local cache. /api/decisions may be requested more than once while the
# service is alive; never repeat the fixed-state sensitivity work for the same
# canonical row.
_WEIGHT_CACHE: dict[str, dict] = {}
_ENGINE_CONTEXT_LOCK = RLock()


@contextmanager
def _active_engine_context(class_name: str):
    """Temporarily bind legacy eng-proxy code to one Forever class.

    Only mature Mage rehydration still traverses modules that read the process
    engine proxy. Serialize and restore the prior game selection so the Decisions
    service does not leak class context between requests. Normal experimental
    backends are called directly and do not need this scope.
    """
    from src import game_context
    from src.engine_registry import reset_engine_cache
    with _ENGINE_CONTEXT_LOCK:
        previous = game_context.current()
        try:
            game_context.configure("forever", str(class_name))
            reset_engine_cache()
            yield
        finally:
            game_context.configure(previous.ruleset, previous.class_name)
            reset_engine_cache()


def clear_cache() -> None:
    _WEIGHT_CACHE.clear()


def _numeric(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


def _gear_fingerprint(gear: Mapping[str, Any] | None) -> dict:
    gear = dict(gear or {})
    slots = {}
    for slot, raw in sorted(dict(gear.get("slots") or {}).items()):
        row = dict(raw or {})
        # Stable item identity first; numeric fallback keeps synthetic/test rows
        # distinct without hashing icon/provenance decoration.
        slots[str(slot)] = {
            "item_id": row.get("item_id"),
            "name": row.get("name") or row.get("item"),
            "effective_level": row.get("effective_level"),
            "stats": {
                k: row.get(k)
                for k in (
                    "strength", "agility", "stamina", "intellect", "spirit", "mp5",
                    "attack_power", "spell_power", "healing", "defense", "armor",
                    "block_value", "weapon_dps", "weapon_speed", "wand_dps",
                    "hit_rating", "crit_rating", "dodge_rating", "defense_rating",
                )
                if row.get(k) is not None
            },
        }
    aggregate = {
        k: gear.get(k)
        for k in (
            "name", "family", "provenance", "gear_selection_method",
            "strength", "agility", "stamina", "intellect", "spirit", "mp5",
            "attack_power", "ranged_attack_power", "spell_power", "healing",
            "defense", "armor", "body_armor", "shield_armor", "block_value",
            "weapon_dps", "weapon_speed", "wand_dps",
        )
        if gear.get(k) is not None
    }
    return {"aggregate": aggregate, "slots": slots}


def scorer_state_fingerprint(class_name: str, row: Mapping[str, Any], *, profile: str | None = None) -> str:
    """Deterministic identity of the scorer state whose derivative is published."""
    definition = get_definition("forever", str(class_name))
    engine = definition.engine()
    row = dict(row or {})
    payload = {
        "schema": 1,
        "ruleset": "forever",
        "class": str(class_name),
        "engine_build": getattr(engine, "DATA_BUILD", None),
        "level": int(row.get("level", 0) or 0),
        "talent_ranks": sorted((str(k), int(v)) for k, v in dict(row.get("talent_ranks") or {}).items()),
        "profile": str(profile or row.get("score_profile") or row.get("combat_profile") or row.get("profile") or "all"),
        "policy": row.get("policy"),
        "rotation": row.get("rotation"),
        "pull_size": row.get("pull_size"),
        "aura": row.get("aura"),
        "mana_plan": row.get("mana_plan"),
        "gear": _gear_fingerprint(row.get("gear_stats") if isinstance(row.get("gear_stats"), Mapping) else {}),
        "score_s_per_100": row.get("score_s_per_100"),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _profile_for_row(class_name: str, row: Mapping[str, Any], *, route_name: str | None = None) -> str:
    definition = get_definition("forever", str(class_name))
    if route_name and route_name in definition.route_definitions:
        route = dict(definition.route_definitions.get(route_name) or {})
        if route.get("score_profile"):
            return str(route["score_profile"])
    profile = str(row.get("score_profile") or row.get("combat_profile") or row.get("profile") or "all")
    # Druid publishes Cat as the player-facing form name while its scorer API
    # names the corresponding fixed talent/gameplay profile "feral".
    if str(class_name) == "druid" and profile == "cat":
        return "feral"
    if profile in ("", "auto"):
        return "all"
    return profile


def _baseline_from_row(row: Mapping[str, Any]) -> dict:
    row = dict(row or {})
    base = dict(row.get("details") or {})
    # Top-level fields are publication authority for selected gear/policy and
    # may be richer than old details blobs.
    for key, value in row.items():
        if key not in {"details", "stat_weights", "stat_weights_error", "talent_trees", "rotation_steps", "missing"} and value is not None:
            base[key] = value
    total = _numeric(base.get("total_s"))
    if total is None:
        total = _numeric(row.get("score_s_per_100"))
    if total is None:
        spm = _numeric(row.get("seconds_per_mob"))
        if spm is not None:
            total = spm * 100.0
    if total is None:
        mph = _numeric(row.get("mobs_per_hour"))
        if mph and mph > 0:
            total = 360000.0 / mph
    if total is not None:
        base["total_s"] = total
        base.setdefault("score_s_per_100", total)
    for published, raw in (
        ("kill_seconds_per_mob", "kill_s"),
        ("recovery_seconds_per_mob", "recovery_s"),
        ("travel_seconds_per_mob", "travel_s"),
    ):
        if base.get(raw) is None:
            value = _numeric(row.get(published))
            if value is not None:
                base[raw] = value * 100.0
    return base


def _has_weights(weights: Any) -> bool:
    if not isinstance(weights, Mapping):
        return False
    return bool(weights.get("stats") or weights.get("weights") or weights.get("curve_sensitivity"))


def _decorate_weights(weights: Mapping[str, Any], fingerprint: str, *, source: str) -> dict:
    out = deepcopy(dict(weights))
    out["scorer_state_fingerprint"] = fingerprint
    out["decision_stat_weight_source"] = source
    return out


def compute_row_stat_weights(class_name: str, row: Mapping[str, Any], *, route_name: str | None = None) -> tuple[dict, str, str]:
    """Return (weights, fingerprint, source) for one fixed decision row.

    Current rows normally already contain weights. Older route rows are
    rehydrated from the exact published talents/gear/policy state. Mature Mage
    needs a fixed-allocation canonical rescore because legacy endpoint steps do
    not contain the detailed spell cast mix needed by its analytic derivative.
    """
    row = dict(row or {})
    level = int(row.get("level", 0) or 0)
    ranks = dict(row.get("talent_ranks") or {})
    if level <= 0:
        raise StatWeightContractError("decision row has no valid level")

    profile = _profile_for_row(class_name, row, route_name=route_name)
    fingerprint = scorer_state_fingerprint(class_name, row, profile=profile)
    existing = row.get("stat_weights") or dict(row.get("details") or {}).get("stat_weights")
    if _has_weights(existing):
        existing_fp = str(dict(existing).get("scorer_state_fingerprint") or "").strip()
        # A weight blob explicitly tied to a different scorer state is stale.
        # Never relabel it with the new fingerprint: fall through to exact
        # fixed-state rehydration instead. Legacy blobs without a fingerprint
        # remain accepted for backward compatibility when route identity itself
        # has already been validated by the decision dashboard.
        if not existing_fp or existing_fp == fingerprint:
            return _decorate_weights(existing, fingerprint, source="published"), fingerprint, "published"
    if fingerprint in _WEIGHT_CACHE:
        return deepcopy(_WEIGHT_CACHE[fingerprint]), fingerprint, "cache"
    if not ranks:
        raise StatWeightContractError("decision row has no machine-readable talent_ranks for rehydration")

    definition = get_definition("forever", str(class_name))
    if not bool(definition.capabilities.stat_weights):
        raise StatWeightContractError(f"{class_name} does not declare stat-weight capability")
    engine = definition.engine()
    try:
        talents = engine.Talents(**{str(k): int(v) for k, v in ranks.items()})
    except Exception as exc:
        raise StatWeightContractError(f"cannot rehydrate talents for current scorer: {type(exc).__name__}: {exc}") from exc

    baseline = _baseline_from_row(row)
    policy = None
    cfg = None

    try:
        if hasattr(engine, "experimental_level_score"):
            # Experimental backends can reconstruct the exact selected item set
            # from published gear_stats. Do not silently choose different gear
            # for a stale row: without that snapshot the old result is history-only
            # and must be rerun on the current version.
            if not baseline.get("gear_stats"):
                raise StatWeightContractError("published gear snapshot missing; exact stat-weight state cannot be rehydrated")
            if baseline.get("total_s") is None:
                raise StatWeightContractError("published objective missing; exact stat-weight state cannot be rehydrated")
            weights = compute_for_engine(
                engine, level, talents, baseline=baseline,
                policy=policy, cfg=cfg, profile=profile,
            )
        else:
            # Mature Mage endpoint rows historically omit cast-mix details. Use
            # the same fixed-talent analytic scorer as spec_matrix to reconstruct
            # the canonical state, then derive weights from that exact rescore.
            from .spec_matrix import _mature_score, _mature_stat_weights
            with _active_engine_context(class_name):
                score, policy, cfg = _mature_score(engine, level, talents, profile=profile)

                def legacy_probe():
                    return _mature_stat_weights(engine, level, talents, score, policy, cfg)

                weights = compute_for_engine(
                    engine, level, talents, baseline=score, policy=policy, cfg=cfg,
                    profile=profile, legacy_probe=legacy_probe,
                )
    except Exception as exc:
        raise StatWeightContractError(f"canonical stat-weight rehydration failed: {type(exc).__name__}: {exc}") from exc

    if not _has_weights(weights):
        raise StatWeightContractError("canonical scorer returned no stat weights")
    decorated = _decorate_weights(weights, fingerprint, source="canonical_fixed_state_rehydration")
    _WEIGHT_CACHE[fingerprint] = deepcopy(decorated)
    return decorated, fingerprint, "canonical_fixed_state_rehydration"


def ensure_row_stat_weights(class_name: str, row: Mapping[str, Any], *, route_name: str | None = None, strict: bool = True) -> dict:
    out = dict(row or {})
    try:
        weights, fingerprint, source = compute_row_stat_weights(class_name, out, route_name=route_name)
        out["stat_weights"] = weights
        out["stat_weight_fingerprint"] = fingerprint
        out["stat_weight_source"] = source
        out.pop("stat_weights_error", None)
        details = dict(out.get("details") or {})
        details["stat_weights"] = weights
        details.pop("stat_weights_error", None)
        out["details"] = details
        out["stat_weights_contract_ok"] = True
        return out
    except Exception as exc:
        if strict:
            if isinstance(exc, StatWeightContractError):
                raise
            raise StatWeightContractError(str(exc)) from exc
        out["stat_weights_contract_ok"] = False
        out["stat_weights_error"] = str(exc)
        return out
