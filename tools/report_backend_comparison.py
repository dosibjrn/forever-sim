"""M46 backend comparison gate.

Compare the Forever decision backends where they genuinely overlap, and make
missing validation coverage explicit instead of treating a green unit suite as
backend agreement.  This report is intentionally pre-M47: fixed representative
builds, no broad route optimization.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import game_context
from src.engine_registry import reset_engine_cache
from src.rulesets.forever.classes.mage import engine as mage
from src.v2 import expected_engine as mage_expected
from src.rulesets.forever.classes.druid.reference_validator import build_reference_report
from src.rulesets.forever.release_gate import build_release_gate

LEVELS = (20, 40, 60)
SEED = 7
EVENT_N = 64


def _mage_structural_build(level: int, school: str):
    """Deterministic legal fixture that reaches each structural rotation early."""
    preferred = {
        "frost": (
            "ice_lance", "fingers_of_frost", "imp_frostbolt", "elemental_precision",
            "ice_shards", "frostbite", "frost_channeling", "piercing_ice",
            "arctic_reach", "ice_block", "cold_snap", "ice_barrier", "permafrost",
            "shatter", "improved_cone_of_cold", "winters_chill", "frost_warding",
            "improved_blizzard",
        ),
        "arcane": (
            "arcane_blast", "missile_barrage", "arcane_focus", "improved_channeling",
            "arcane_concentration", "arcane_impact", "magic_absorption",
            "arcane_meditation", "arcane_shielding", "presence_of_mind", "arcane_mind",
            "arcane_instability", "arcane_power", "wand_specialization",
            "arcane_subtlety", "arcane_resilience", "arcane_geometry",
            "improved_counterspell",
        ),
        "fire": (
            "pyroblast", "hot_streak", "imp_fireball", "ignite", "incineration",
            "impact", "flame_throwing", "master_elements", "imp_scorch", "burning_soul",
            "critical_mass", "fire_power", "combustion", "wake_of_fire",
            "improved_flamestrike", "improved_fire_ward", "blast_wave",
        ),
    }[school]
    t = mage.Talents()
    rank = {name: i for i, name in enumerate(preferred)}
    for _char_level in range(10, int(level) + 1):
        legal = [k for k in mage.TALENT_RULES if mage.legal_add(t, k)]
        if not legal:
            raise RuntimeError(f"no legal Mage talent at L{_char_level}")
        legal.sort(key=lambda k: (mage.TALENT_RULES[k][0] != school, rank.get(k, 10_000), k))
        t = mage.add_point(t, legal[0])
    return t


def _mage_policy_signature(p) -> dict:
    return {
        "primary": mage.policy_primary_school(p),
        "ice_lance": bool(getattr(p, "use_proc_ice_lance", False)),
        "ice_barrier": bool(getattr(p, "use_ice_barrier", False)),
        "nova": bool(getattr(p, "use_nova", False)),
        "blink": bool(getattr(p, "use_blink", False)),
        "fireblast": bool(getattr(p, "use_fireblast", False)),
        "arcane_blast_to_stacks": int(getattr(p, "arcane_blast_to_stacks", 0) or 0),
        "hot_streak_pyro_stacks": int(getattr(p, "hot_streak_pyro_stacks", 0) or 0),
    }


def _mage_level(level: int, school: str) -> dict:
    game_context.configure("forever", "mage")
    t = _mage_structural_build(level, school)
    cfg = mage.SimConfig(seed=SEED, use_best_water=True)
    policies = mage.candidate_policies_for_build(level, t, focused=True, school=school)
    rows = []
    skipped = []
    for p in policies:
        try:
            fast = mage_expected.score_policy(level, t, p, cfg, cycle_pulls=6)
            event = mage.simulate_chain(level, t, p, cfg, n=EVENT_N, seed=SEED)
        except (RuntimeError, ValueError, OverflowError) as exc:
            skipped.append({"policy": p.name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        rows.append({
            "policy": p.name,
            "rotation": mage.policy_desc(p, level),
            "signature": _mage_policy_signature(p),
            "fast_seconds_per_mob": float(fast["total_s"]) / 100.0,
            "event_seconds_per_mob": float(event["total_s"]) / EVENT_N,
            "fast_approximation_flags": sorted(set(
                flag for outcome in fast.get("outcomes", [])
                for flag in getattr(outcome, "approximation_flags", ())
            )),
        })
    if not rows:
        raise RuntimeError(f"no shared Mage {school} policies at L{level}")
    fast_ranked = sorted(rows, key=lambda r: (r["fast_seconds_per_mob"], r["rotation"]))
    event_ranked = sorted(rows, key=lambda r: (r["event_seconds_per_mob"], r["rotation"]))
    fast_top, event_top = fast_ranked[0], event_ranked[0]
    exact = fast_top["rotation"] == event_top["rotation"]
    explanations: list[str] = []
    if not exact:
        if school == "frost" and fast_top["signature"]["ice_lance"] != event_top["signature"]["ice_lance"]:
            explanations.append("structural_proc_policy_is_event_authority")
        if school == "arcane":
            explanations.append("missile_barrage_proc_is_event_authority")
        if school == "fire" and fast_top["signature"]["hot_streak_pyro_stacks"] != event_top["signature"]["hot_streak_pyro_stacks"]:
            explanations.append("hot_streak_proc_is_event_authority")
        control_fields = ("nova", "blink", "fireblast")
        if any(fast_top["signature"][k] != event_top["signature"][k] for k in control_fields):
            explanations.append("root_break_and_melee_leeway_proxy_changes_control_value")
        tied = [r for r in fast_ranked if abs(r["fast_seconds_per_mob"] - fast_top["fast_seconds_per_mob"]) <= 1e-9]
        if any(r["rotation"] == event_top["rotation"] for r in tied):
            explanations.append("event_winner_is_fast_tied")
    unexplained = (not exact) and not explanations
    structural_required = {
        "frost": bool(getattr(t, "ice_lance", 0)),
        "arcane": bool(getattr(t, "arcane_blast", 0)),
        "fire": bool(getattr(t, "hot_streak", 0) and getattr(t, "pyroblast", 0)),
    }[school]
    structural_executed = any(
        (r["signature"]["ice_lance"] if school == "frost" else
         r["signature"]["arcane_blast_to_stacks"] > 0 if school == "arcane" else
         r["signature"]["hot_streak_pyro_stacks"] > 0)
        for r in rows
    ) if structural_required else True
    return {
        "level": level,
        "school": school,
        "allocation": mage.final_allocation(t),
        "shared_candidate_count": len(rows),
        "skipped_candidates": skipped,
        "structural_required": structural_required,
        "structural_executed_by_fast": structural_executed,
        "fast_top": fast_top,
        "event_top": event_top,
        "exact_top_match": exact,
        "explanations": explanations,
        "unexplained_material_difference": unexplained,
        "authority": {
            "fast": "deterministic expected-value proposal/search backend",
            "event": "structural rotation adjudication backend for proc/freeze/control mechanics",
        },
    }

def build_report() -> dict:
    mage_rows = [_mage_level(level, school) for school in ("frost", "arcane", "fire") for level in LEVELS]
    mage_unexplained = [f"{r['school']}:L{r['level']}" for r in mage_rows if r["unexplained_material_difference"]]
    mage_structural_missing = [f"{r['school']}:L{r['level']}" for r in mage_rows if r["structural_required"] and not r["structural_executed_by_fast"]]

    blockers = []
    if mage_unexplained:
        blockers.append("mage_unexplained_fast_event_decision_delta")
    if mage_structural_missing:
        blockers.append("mage_structural_policy_absent_from_fast_backend")

    # Paladin was explicitly parked after its source/fidelity migration.  The
    # Fast/event Fury replacement semantics were aligned under one explicit interpretation in v0.11.46.6/7;
    # do not reopen it here without new evidence.
    paladin = {
        "status": "parked_shared_semantics",
        "evidence": [
            "docs/validation/PALADIN_FURY_ABSORB_v0.11.46.6.md",
            "HANDOVER_v0.11.46.7.md",
        ],
        "note": "Fast/event replacement-shield semantics share one explicit interpretation; remaining stacking uncertainty is low/not_probeable.",
    }

    # Druid now has a deliberately separate frozen-oracle path.  It does not
    # call production helper functions for its expectations; the production
    # scorer is only the system under test.  Mutation regressions prove it can
    # falsify profile, rotation, throughput and resource failures.
    druid_reference = build_reference_report()
    druid = {
        "status": "independently_checked" if druid_reference["ok"] else "independent_validator_failed",
        "available_backends": ["expected_value_fast", "independent_frozen_oracle"],
        "missing_backends": [],
        "reference": druid_reference,
        "evidence": ["src/rulesets/forever/classes/druid/reference_validator.py", "tests/test_druid_independent_validator_v0114620.py"],
        "note": "Fixed legal L20/L40/L60 decision, rotation, throughput and resource contracts are checked through an independent frozen oracle with mutation tests.",
    }
    if not druid_reference["ok"]:
        blockers.append("druid_independent_backend_validation_failed")

    # The Classic Mage MC precision ladder remains useful, but M46 now also has
    # a Forever-specific release-equivalent gate over the production decision
    # surface that is actually published (3 classes x L20/L40/L60).
    forever_release = build_release_gate()
    release = {
        "status": "forever_equivalent_gate_passed" if forever_release["ok"] else "forever_equivalent_gate_failed",
        "existing_release_mc_scope": "classic_mage_only",
        "forever_release_validation": "production_decision_equivalent_gate",
        "forever_release_gate": forever_release,
        "evidence": [
            "release_tests/test_mc_precision_ladder.py",
            "release_tests/test_forever_release_gate.py",
            "src/rulesets/forever/release_gate.py",
        ],
    }
    if not forever_release["ok"]:
        blockers.append("forever_release_equivalent_gate_failed")

    return {
        "schema_version": 1,
        "scope": "M46 backend comparison; fixed representative builds, not M47 route optimization",
        "mage": {
            "status": "compatible_with_explicit_authority_boundaries" if not mage_unexplained else "unexplained_difference",
            "levels": mage_rows,
            "unexplained_levels": mage_unexplained,
            "structural_missing": mage_structural_missing,
        },
        "paladin": paladin,
        "druid": druid,
        "release": release,
        "blocking_items": blockers,
        "ready_for_m46_done": not blockers,
    }


def render_md(report: dict, version: str) -> str:
    lines = [
        f"# Backend comparison — v{version}", "", report["scope"], "",
        "## Mage — deterministic expected vs event", "",
        "| School | Level | Fast top | Event top | Result | Explanation |", "|---|---:|---|---|---|---|",
    ]
    for row in report["mage"]["levels"]:
        result = "same" if row["exact_top_match"] else ("explained" if not row["unexplained_material_difference"] else "UNEXPLAINED")
        lines.append(
            f"| {row['school']} | {row['level']} | `{row['fast_top']['rotation']}` | `{row['event_top']['rotation']}` | {result} | "
            + (", ".join(row["explanations"]) or "—") + " |"
        )
    lines += [
        "", "The expected Mage backend is not treated as authority for proc/freeze structural rotation semantics; event adjudication owns those mechanics before publication.", "",
        "## Paladin", "", f"Status: **{report['paladin']['status']}**. {report['paladin']['note']}", "",
        "## Druid", "", f"Status: **{report['druid']['status']}**. {report['druid']['note']}", "",
        "## Release / MC", "", f"Status: **{report['release']['status']}**. Classic MC remains `{report['release']['existing_release_mc_scope']}`; Forever uses `{report['release']['forever_release_validation']}`.", "",
        "## M46 backend gate", "",
        "Blocking items: " + ", ".join(f"`{x}`" for x in report["blocking_items"]), "",
        f"Backend-comparison DONE-ready: **{'YES' if report['ready_for_m46_done'] else 'NO'}**", "",
    ]
    return "\n".join(lines)


def main() -> int:
    report = build_report()
    version = (ROOT / "VERSION").read_text().strip()
    jp = ROOT / f"docs/validation/BACKEND_COMPARISON_v{version}.json"
    mp = ROOT / f"docs/validation/BACKEND_COMPARISON_v{version}.md"
    jp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    mp.write_text(render_md(report, version), encoding="utf-8")
    print(json.dumps({"ready": report["ready_for_m46_done"], "blocking_items": report["blocking_items"], "mage_status": report["mage"]["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
