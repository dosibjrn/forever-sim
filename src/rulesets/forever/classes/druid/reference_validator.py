from __future__ import annotations

"""Independent frozen-oracle validation for the Forever Druid scorer.

This module is deliberately *not* a second call into the Druid mechanics scorer.
It owns three legal representative fixtures and narrow output contracts frozen
from an audited validation checkpoint.  The production scorer is only the
system under test.  The oracle checks decision/profile, rotation semantics,
resource behavior, and bounded throughput.  Mutation tests prove the validator
can reject a broken production scorer rather than compare it to itself.
"""

from dataclasses import dataclass
from typing import Callable

from .talents import Talents


@dataclass(frozen=True)
class DruidOracleCase:
    level: int
    talents: Talents
    expected_profile: str
    expected_pull_size: int
    mph_min: float
    mph_max: float
    rotation_required: tuple[str, ...]
    rotation_forbidden: tuple[str, ...] = ()
    min_rage_rate: float = 0.0
    min_incoming_rage_rate: float = 0.0
    min_swipe_rate: float = 0.0
    min_maul_rate: float = 0.0


CASES: tuple[DruidOracleCase, ...] = (
    DruidOracleCase(
        20,
        Talents(ferocity=5, heart_of_the_wild=5, feral_swiftness=1),
        "cat", 3, 230.0, 270.0,
        ("Swipe (Cat)",), ("Bear autos", "Primal Bite"),
    ),
    DruidOracleCase(
        40,
        Talents(ferocity=5, heart_of_the_wild=5, feral_swiftness=2,
                feral_instinct=3, brutal_impact=2, thick_hide=3, savage_fury=2,
                feral_charge=1, sharpened_claws=2, shredding_attacks=3,
                mangle=1, predatory_strikes=2),
        "bear", 3, 160.0, 180.0,
        ("Swipe", "Primal Bite", "Bear autos"), (),
        min_rage_rate=6.0, min_incoming_rage_rate=0.1, min_swipe_rate=0.3,
    ),
    DruidOracleCase(
        60,
        Talents(ferocity=5, heart_of_the_wild=5, feral_swiftness=2,
                feral_instinct=3, brutal_impact=2, thick_hide=3, savage_fury=2,
                feral_charge=1, sharpened_claws=2, shredding_attacks=3,
                mangle=1, predatory_strikes=3, blood_frenzy=2,
                predatory_instincts=2, leader_of_the_pack=1, shifting_power=1, improved_shifting_power=2,
                natural_reaction=5, rend_and_tear=5, berserk=1),
        "bear", 3, 163.0, 183.0,
        ("Swipe", "Primal Bite", "Maul", "Bear autos"), (),
        min_rage_rate=9.0, min_incoming_rage_rate=0.1, min_swipe_rate=0.5,
        min_maul_rate=0.02,
    ),
)


def validate_case(case: DruidOracleCase, scorer: Callable[[int, Talents, str], dict]) -> dict:
    row = scorer(case.level, case.talents, "all")
    failures: list[str] = []
    profile = str(row.get("profile", ""))
    pull_size = int(row.get("pull_size", 1) or 1)
    mph = float(row.get("mobs_per_hour", 360000.0 / max(1e-9, float(row.get("total_s", 1e9)))))
    rotation = str(row.get("rotation", ""))

    if profile != case.expected_profile:
        failures.append(f"profile:{profile}!={case.expected_profile}")
    if pull_size != case.expected_pull_size:
        failures.append(f"pull_size:{pull_size}!={case.expected_pull_size}")
    if not case.mph_min <= mph <= case.mph_max:
        failures.append(f"mobs_per_hour:{mph:.3f} outside [{case.mph_min:.3f},{case.mph_max:.3f}]")
    for token in case.rotation_required:
        if token not in rotation:
            failures.append(f"rotation_missing:{token}")
    for token in case.rotation_forbidden:
        if token in rotation:
            failures.append(f"rotation_forbidden:{token}")

    resource_checks = {
        "rage_rate_proxy": case.min_rage_rate,
        "incoming_damage_rage_rate_proxy": case.min_incoming_rage_rate,
        "swipe_rate_per_s": case.min_swipe_rate,
        "maul_rate_per_s": case.min_maul_rate,
    }
    for key, floor in resource_checks.items():
        if floor > 0.0 and float(row.get(key, 0.0) or 0.0) < floor:
            failures.append(f"{key}:{float(row.get(key,0.0) or 0.0):.6f}<{floor:.6f}")

    # Independent algebraic consistency checks over published pack/resource
    # outputs. These do not call production helper functions.
    if profile == "bear":
        cycle = float(row.get("cycle_s", 0.0) or 0.0)
        combat = float(row.get("combat_s_per_pack", 0.0) or 0.0)
        recovery = float(row.get("recovery_s_per_pack", 0.0) or 0.0)
        if cycle <= combat + recovery:
            failures.append("cycle_missing_positive_travel")
        expected_mph = 3600.0 * pull_size / max(1e-9, cycle)
        if abs(expected_mph - mph) > 1e-6:
            failures.append(f"mph_cycle_identity:{mph:.6f}!={expected_mph:.6f}")
        rage = float(row.get("rage_rate_proxy", 0.0) or 0.0)
        incoming = float(row.get("incoming_damage_rage_rate_proxy", 0.0) or 0.0)
        if rage <= incoming:
            failures.append("rage_budget_not_above_incoming_component")
        swipe = float(row.get("swipe_rate_per_s", 0.0) or 0.0)
        if swipe > (1.0 / 1.5) + 1e-9:
            failures.append("swipe_rate_exceeds_gcd_cap")
        maul = float(row.get("maul_rate_per_s", 0.0) or 0.0)
        if maul > 0.4 + 1e-9:
            failures.append("maul_rate_exceeds_bear_swing_cap")

    return {
        "level": case.level,
        "allocation_points": case.talents.points(),
        "expected_profile": case.expected_profile,
        "observed_profile": profile,
        "pull_size": pull_size,
        "mobs_per_hour": mph,
        "rotation": rotation,
        "resource": {k: row.get(k) for k in resource_checks},
        "failures": failures,
        "ok": not failures,
    }


def build_reference_report(scorer: Callable[[int, Talents, str], dict] | None = None) -> dict:
    if scorer is None:
        from .mechanics import experimental_level_score
        scorer = experimental_level_score
    rows = [validate_case(case, scorer) for case in CASES]
    return {
        "schema_version": 1,
        "kind": "independent_frozen_oracle",
        "levels": [c.level for c in CASES],
        "scope": "fixed legal L20/L40/L60 Druid decision/rotation/resource contracts; not route optimization",
        "production_helper_reuse": False,
        "rows": rows,
        "ok": all(r["ok"] for r in rows),
    }
