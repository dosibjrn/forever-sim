from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

from src import game_context
from src.engine_registry import reset_engine_cache

OUT = Path(__file__).resolve().parents[1]


def main() -> None:
    game_context.configure("forever", "mage")
    reset_engine_cache()
    from src.rulesets.forever.classes.mage import engine as mage
    from src.v2 import expected_engine as expected

    talents = mage.Talents(
        imp_frostbolt=5, elemental_precision=1, permafrost=1,
        frostbite=3, ice_lance=1,
    )
    cfg = mage.SimConfig()
    base = next(
        p for p in mage.candidate_policies_for_build(20, talents, focused=True, school="frost")
        if p.use_proc_ice_lance and p.use_fireblast and p.use_nova
        and p.nova_move_yards == 5 and abs(p.blink_min_hp_frac - 0.35) < 1e-12
        and int(p.wand_finisher_max_hits) == 0
    )
    wand = mage.best_wand(20)
    gear = mage.real_gear_snapshot(20)["slots"]["wand"]
    rows = []
    for cutoff in (0, 1, 2, 3):
        policy = replace(base, name=f"wand cutoff {cutoff}", wand_finisher_max_hits=cutoff)
        det = expected.score_policy(20, talents, policy, cfg, cycle_pulls=6)
        evt = mage.simulate_chain(20, talents, policy, cfg, n=32, seed=7)
        rows.append({
            "cutoff": cutoff,
            "det_mph": 360000.0 / float(det["total_s"]),
            "det_kill_s_per_mob": float(det["kill_s"]) / 100.0,
            "det_recovery_s_per_mob": float(det["recovery_s"]) / 100.0,
            "det_contact_s_per_mob": float(det["melee_contact_s"]) / 100.0,
            "det_pushback_s_per_mob": float(det["pushback_s"]) / 100.0,
            "evt_mph": 3600.0 / (float(evt["total_s"]) / 32.0),
            "evt_kill_s_per_mob": float(evt["kill_s"]) / 32.0,
            "evt_recovery_s_per_mob": float(evt["recovery_s"]) / 32.0,
            "evt_contact_s_per_mob": float(evt["melee_contact_s"]) / 32.0,
            "evt_pushback_s_per_mob": float(evt["pushback_s"]) / 32.0,
            "evt_wand_shots_per_mob": float(evt.get("wand_shots", 0.0)) / 32.0,
            "evt_wand_finisher_casts_per_mob": float(evt.get("casts_wand_finisher", 0.0)) / 32.0,
        })
    report = {
        "version": "0.11.48.73",
        "level": 20,
        "wand": {
            "name": wand.name, "item_id": wand.item_id, "school": wand.school,
            "school_origin": wand.school_origin, "dmin": wand.dmin, "dmax": wand.dmax,
            "speed": wand.speed, "dps": wand.dps, "sql_name": gear["name"],
            "ranged_hit_same_level": mage.wand_hit_chance(20, 20),
        },
        "talents": asdict(talents),
        "base_policy": asdict(base),
        "rows": rows,
    }
    (OUT / "MAGE_L20_WAND_CONTACT_v0.11.48.73.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# Mage L20 wand/contact audit — v0.11.48.73", "",
        f"Canonical SQL wand: **{wand.name}** (item {wand.item_id}), {wand.dmin:.0f}–{wand.dmax:.0f} {wand.school.title()} damage, {wand.speed:.2f}s speed, {wand.dps:.2f} DPS.",
        f"Same-level wand Shoot hit chance: **{mage.wand_hit_chance(20,20)*100:.1f}%** (ranged-weapon table, not Mage spell hit).", "",
        "| cutoff | det mph | evt mph | det kill | evt kill | det contact | evt contact | det pushback | evt pushback | evt finisher shots |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['cutoff']} | {r['det_mph']:.1f} | {r['evt_mph']:.1f} | "
            f"{r['det_kill_s_per_mob']:.2f}s | {r['evt_kill_s_per_mob']:.2f}s | "
            f"{r['det_contact_s_per_mob']:.2f}s | {r['evt_contact_s_per_mob']:.2f}s | "
            f"{r['det_pushback_s_per_mob']:.2f}s | {r['evt_pushback_s_per_mob']:.2f}s | "
            f"{r['evt_wand_finisher_casts_per_mob']:.2f} |"
        )
    lines += [
        "", "## Interpretation", "",
        "- The deterministic screen now prices melee contact that begins during a hard cast; v0.11.48.72 could report 0 contact / 0 pushback for this corridor.",
        "- The event backend remains final authority for stochastic Frostbite/Fingers-of-Frost/contact timing.",
        "- Wand cutoff is a searched policy variable. The release does not freeze a particular cutoff winner.",
        "- SQL owns wand availability/damage/speed; a small sourced item-id map supplies magic school because the catalogue schema does not store weapon school.",
    ]
    (OUT / "MAGE_L20_WAND_CONTACT_v0.11.48.73.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
