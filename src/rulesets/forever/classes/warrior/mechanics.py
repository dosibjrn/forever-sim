from __future__ import annotations

"""Minimal source-anchored Warrior scorer used only to prove M45 onboarding.

This is intentionally not a Warrior leveling recommendation model.  The scorer
exists so the common registry/search/artifact/listener stack can exercise a
fourth class without shared-code surgery.
"""

from contextvars import ContextVar

from src.v2.stat_weight_model import normalize_objective_gradient
from .talents import Talents

_GEAR_PROBE: ContextVar[dict[str, float]] = ContextVar("warrior_gear_probe", default={})


def _score(level: int, t: Talents, profile: str = "all") -> dict:
    level = int(level)
    probe = dict(_GEAR_PROBE.get() or {})
    # Coarse, monotone proof model. Heroic Strike R1 source facts anchor the
    # action identity/cost/bonus; the surrounding white-damage/rage curve is an
    # explicit local approximation, not a claim about Forever server internals.
    mob_hp = 120.0 + 18.0 * level
    weapon_dps = 8.0 + 0.72 * level + float(probe.get("weapon_dps", 0.0))
    strength = 18.0 + 1.3 * level + float(probe.get("strength", 0.0))
    attack_dps = weapon_dps + 0.10 * strength
    rage_per_s = 2.8 + 0.055 * level
    hs_cost = max(1.0, 15.0 - float(t.improved_heroic_strike))
    hs_per_s = rage_per_s / hs_cost
    # Heroic Strike R1 increases melee damage by 11 (spell 78 tooltip).
    heroic_bonus_dps = hs_per_s * 11.0
    # Improved Rend is identity/legality coverage only in M45; do not invent a
    # damage effect until the Warrior fidelity milestone imports that mechanic.
    total_dps = max(1.0, attack_dps + heroic_bonus_dps)
    kill_s_per_mob = mob_hp / total_dps

    stamina = 24.0 + 1.5 * level + float(probe.get("stamina", 0.0))
    armor = 220.0 + 24.0 * level + float(probe.get("armor", 0.0))
    # Deflection is source-anchored as +parry chance; represent only direction
    # here so the proof class exercises a defensive talent in the scorer.
    avoidance = min(0.25, 0.01 * float(t.deflection))
    exposure = max(0.35, 1.0 - avoidance - min(0.35, armor / (armor + 2400.0)))
    incoming = (7.0 + 0.42 * level) * exposure * kill_s_per_mob
    hp = 180.0 + 10.0 * stamina
    recovery_s_per_mob = max(0.0, incoming - 0.20 * hp) / max(8.0, 0.25 * hp)

    seconds_per_mob = kill_s_per_mob + recovery_s_per_mob + 1.2
    total_s = 100.0 * seconds_per_mob
    return {
        "total_s": total_s,
        "kill_s": 100.0 * kill_s_per_mob,
        "recovery_s": 100.0 * recovery_s_per_mob,
        "travel_s": 120.0,
        "profile": "arms_proof" if profile in ("all", "auto", "arms") else f"{profile}_proof",
        "combat_profile": "single_target_proof",
        "rotation": "Auto Attack; Heroic Strike when rage allows",
        "policy": "heroic_strike_rage_filler",
        "gear": "proof_level_curve",
        "gear_stats": {
            "model": "proof_level_curve",
            "strength": strength,
            "stamina": stamina,
            "armor": armor,
            "weapon_dps": weapon_dps,
            "slots": {},
        },
        "pull_size": 1,
        "mobs_per_hour": 360000.0 / total_s,
        "proof_inputs": {
            "heroic_strike_spell_id": 78,
            "heroic_strike_rage_cost": hs_cost,
            "heroic_strike_bonus_damage": 11.0,
            "deflection_rank": int(t.deflection),
        },
    }


def experimental_level_score(level: int, t: Talents, profile: str = "all") -> dict:
    return _score(level, t, profile)


def marginal_stat_weights(level: int, t: Talents, profile: str = "all", baseline: dict | None = None) -> dict:
    base = baseline or _score(level, t, profile)
    increment = 4.0 + (max(10, min(60, int(level))) - 10) * 36.0 / 50.0
    gradients: dict[str, float] = {}
    probes: dict[str, dict] = {}
    for stat in ("strength", "stamina", "weapon_dps", "armor"):
        token = _GEAR_PROBE.set({stat: increment})
        try:
            plus = _score(level, t, profile)
        finally:
            _GEAR_PROBE.reset(token)
        gradients[stat] = (float(plus["total_s"]) - float(base["total_s"])) / increment
        probes[stat] = {"increment": increment, "plus_s_per_100": plus["total_s"]}
    result = normalize_objective_gradient(
        baseline_s_per_100=float(base["total_s"]),
        objective_gradient=gradients,
        method="finite_difference_warrior_m45_proof",
        reference_stat="weapon_dps",
        metadata={"probes": probes, "profile": profile, "proof_only": True},
        note="M45 onboarding proof only; values are not a production Warrior gearing model.",
        declared_stats=("strength", "agility", "stamina", "weapon_dps", "armor", "defense", "block_value"),
        stat_status={
            "agility": {"status": "not_modeled", "reason": "proof scorer has no crit/dodge curve"},
            "defense": {"status": "not_modeled", "reason": "proof scorer models Deflection talent only, not Defense rating/items"},
            "block_value": {"status": "not_modeled", "reason": "proof scorer has no shield/block action path"},
        },
    )
    result["analytical"] = False
    return result
