from __future__ import annotations

"""Shared stat-weight attachment + legacy finite-difference fallback.

The public stat-weight contract is class agnostic.  Engines may expose a smooth
``analytic_stat_gradient``; when present that is preferred.  The historical
symmetric Mage probe remains here as a validation/fallback path rather than the
primary player-facing estimator.
"""

import csv
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.engine_registry import eng
from src import presentation
from .analytic_scorer import AnalyticOptions, optimize_policy_analytic
from .path_dp import LevelNode
from .stat_weight_model import compute_for_engine

PROBED_STATS = ("intellect", "spirit", "spell_power")


def probe_increment(level: int) -> float:
    """Linear +4 @ level 10 -> +40 @ level 60, clamped outside that range."""
    level = max(10, min(60, int(level)))
    return 4.0 + (level - 10) * (36.0 / 50.0)


def _perturbed_config(cfg: eng.SimConfig, stat: str, amount: float) -> eng.SimConfig:
    if stat == "intellect":
        return replace(cfg, gear_bonus_intellect=float(cfg.gear_bonus_intellect) + amount)
    if stat == "spirit":
        return replace(cfg, gear_bonus_spirit=float(cfg.gear_bonus_spirit) + amount)
    if stat == "spell_power":
        return replace(cfg, gear_bonus_spell_power=float(cfg.gear_bonus_spell_power) + amount)
    raise ValueError(f"unsupported stat {stat!r}")


def _legacy_probe_node(node: LevelNode, cfg: eng.SimConfig, *, options: AnalyticOptions,
                      school: str = "all") -> LevelNode:
    """Attach symmetric local stat weights to one already-selected top build.

    The objective is seconds per 100 mobs (lower is better). Talents remain
    frozen, but combat policy is re-optimized at both -increment and +increment.
    A symmetric difference is materially more stable than a one-sided probe for
    the discrete cast-count boundaries in the leveling model.

    The reported absolute weight is seconds saved per 100 mobs per stat point.
    Positive is good. `points_per_one_intellect` directly answers how many
    points of the given stat have the same local value as one point of Intellect.
    """
    level = int(node.level)
    inc = probe_increment(level)
    baseline = float(node.score_s_per_100)
    raw: dict[str, dict] = {}

    for stat in PROBED_STATS:
        minus_cfg = _perturbed_config(cfg, stat, -inc)
        plus_cfg = _perturbed_config(cfg, stat, inc)
        minus_policy, minus_result = optimize_policy_analytic(
            level, node.talents, minus_cfg, options=options, school=school
        )
        plus_policy, plus_result = optimize_policy_analytic(
            level, node.talents, plus_cfg, options=options, school=school
        )
        minus_score = float(minus_result["total_s"])
        plus_score = float(plus_result["total_s"])
        # Objective decreases as a useful stat increases. Therefore the local
        # positive stat value is (score(-d)-score(+d))/(2d).
        symmetric = (minus_score - plus_score) / (2.0 * inc)
        forward = (baseline - plus_score) / inc
        backward = (minus_score - baseline) / inc
        raw[stat] = {
            "minus_perturbed_s_per_100": minus_score,
            "plus_perturbed_s_per_100": plus_score,
            # Compatibility alias: positive-side score from the older forward probe.
            "perturbed_s_per_100": plus_score,
            "seconds_saved_per_100": baseline - plus_score,
            "seconds_saved_per_100_per_point": symmetric,
            "forward_seconds_saved_per_100_per_point": forward,
            "backward_seconds_saved_per_100_per_point": backward,
            "minus_reoptimized_policy": eng.policy_desc(minus_policy, level),
            "plus_reoptimized_policy": eng.policy_desc(plus_policy, level),
            "reoptimized_policy": eng.policy_desc(plus_policy, level),
        }

    spw = float(raw["spell_power"]["seconds_saved_per_100_per_point"])
    intw = float(raw["intellect"]["seconds_saved_per_100_per_point"])
    for stat in PROBED_STATS:
        w = float(raw[stat]["seconds_saved_per_100_per_point"])
        raw[stat]["normalized_to_spell_power"] = (w / spw) if abs(spw) > 1e-12 else None
        raw[stat]["value_in_intellect"] = (w / intw) if abs(intw) > 1e-12 else None
        raw[stat]["points_per_one_intellect"] = (intw / w) if w > 1e-12 else None

    d = dict(node.details or {})
    d["stat_weights"] = {
        "method": "symmetric_difference_reoptimized_policy",
        "talents_fixed": True,
        "probe_increment": inc,
        "baseline_s_per_100": baseline,
        "unit": "seconds_saved_per_100_mobs_per_stat_point",
        "stats": raw,
    }
    return replace(node, details=d)



def probe_node(node: LevelNode, cfg: eng.SimConfig, *, options: AnalyticOptions,
               school: str = "all") -> LevelNode:
    """Attach class-agnostic stat weights to one already-selected build.

    Prefer the active engine's analytic local gradient.  If a backend has not
    implemented that contract yet, preserve the historical symmetric probe so
    existing Classic/Mage validation workflows remain available.
    """
    baseline = dict(node.details or {})

    def legacy():
        legacy_node = _legacy_probe_node(node, cfg, options=options, school=school)
        return (legacy_node.details or {}).get("stat_weights")

    weights = compute_for_engine(
        eng, int(node.level), node.talents, baseline=baseline, policy=node.policy,
        cfg=cfg, profile=school, options=options, legacy_probe=legacy,
    )
    d = dict(node.details or {})
    if weights is not None:
        d["stat_weights"] = weights
    return replace(node, details=d)

def annotate_top_nodes(nodes: Sequence[LevelNode], cfg: eng.SimConfig, *,
                       options: AnalyticOptions, school: str = "all",
                       top_k: int | None = None) -> list[LevelNode]:
    """Probe only the already-ranked top candidates; leave any tail untouched."""
    out = list(nodes)
    n = len(out) if top_k is None or int(top_k) <= 0 else min(len(out), int(top_k))
    for i in range(n):
        out[i] = probe_node(out[i], cfg, options=options, school=school)
    return out


def write_csv(path: Path, pools: Mapping[int, Sequence[LevelNode]], *, view: str = "smooth") -> Path:
    """Write one flat, analysis-friendly row per probed top build and level."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "view", "level", "rank", "allocation", "baseline_policy",
        "method", "analytical", "baseline_s_per_100", "probe_increment",
    ]
    for stat in PROBED_STATS:
        fields += [
            f"{stat}_minus_perturbed_s_per_100",
            f"{stat}_plus_perturbed_s_per_100",
            f"{stat}_perturbed_s_per_100",
            f"{stat}_seconds_saved_per_100",
            f"{stat}_seconds_saved_per_100_per_point",
            f"{stat}_forward_seconds_saved_per_100_per_point",
            f"{stat}_backward_seconds_saved_per_100_per_point",
            f"{stat}_normalized_to_spell_power",
            f"{stat}_value_in_intellect",
            f"{stat}_points_per_one_intellect",
            f"{stat}_minus_reoptimized_policy",
            f"{stat}_plus_reoptimized_policy",
            f"{stat}_reoptimized_policy",
        ]

    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for level in sorted(pools):
            for rank, node in enumerate(pools[level], 1):
                sw = (node.details or {}).get("stat_weights")
                if not isinstance(sw, dict):
                    continue
                row = {
                    "view": view,
                    "level": int(level),
                    "rank": rank,
                    "allocation": presentation.allocation(node.talents),
                    "baseline_policy": eng.policy_desc(node.policy, int(level)) if node.policy else "",
                    "method": sw.get("method"),
                    "analytical": sw.get("analytical"),
                    "baseline_s_per_100": float(sw.get("baseline_s_per_100", node.score_s_per_100)),
                    "probe_increment": sw.get("probe_increment"),
                }
                stats = sw.get("stats", {})
                for stat in PROBED_STATS:
                    r = stats.get(stat, {})
                    row[f"{stat}_minus_perturbed_s_per_100"] = r.get("minus_perturbed_s_per_100")
                    row[f"{stat}_plus_perturbed_s_per_100"] = r.get("plus_perturbed_s_per_100")
                    row[f"{stat}_perturbed_s_per_100"] = r.get("perturbed_s_per_100")
                    row[f"{stat}_seconds_saved_per_100"] = r.get("seconds_saved_per_100")
                    row[f"{stat}_seconds_saved_per_100_per_point"] = r.get("seconds_saved_per_100_per_point")
                    row[f"{stat}_forward_seconds_saved_per_100_per_point"] = r.get("forward_seconds_saved_per_100_per_point")
                    row[f"{stat}_backward_seconds_saved_per_100_per_point"] = r.get("backward_seconds_saved_per_100_per_point")
                    row[f"{stat}_normalized_to_spell_power"] = r.get("normalized_to_spell_power")
                    row[f"{stat}_value_in_intellect"] = r.get("value_in_intellect")
                    row[f"{stat}_points_per_one_intellect"] = r.get("points_per_one_intellect")
                    row[f"{stat}_minus_reoptimized_policy"] = r.get("minus_reoptimized_policy", "")
                    row[f"{stat}_plus_reoptimized_policy"] = r.get("plus_reoptimized_policy", "")
                    row[f"{stat}_reoptimized_policy"] = r.get("reoptimized_policy", "")
                w.writerow(row)
    return path
