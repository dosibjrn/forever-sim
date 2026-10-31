from __future__ import annotations

"""Top-N smooth-vs-event validation report for Forever Paladin.

This module does not participate in talent search.  It consumes already-visible
Fast candidates, replays each one with ``event_replay``, then computes a hybrid
cycle proxy from event combat/end resources plus the existing explicit
out-of-combat recovery model.  The result is diagnostic evidence for deciding
whether event fidelity is mature enough to become scorer authority later.
"""

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from .event_replay import validate_smooth_row
from .gear import archetypes
from .talents import Talents
from . import mechanics as smooth


def validate_candidate(level:int,talents:Talents,row:dict) -> dict:
    v=validate_smooth_row(int(level),talents,row)
    ev=v["event"]
    n=max(1,int(row.get("pull_size",1)))
    gear=next(g for g in archetypes(int(level)) if g.name==row.get("gear"))
    player_hp=float(row.get("player_hp",0.0))
    mana_pool=float(row.get("mana_pool",0.0))
    hp_target=float(row.get("next_start_hp",row.get("start_hp",player_hp)))
    mana_target=float(row.get("start_mana",mana_pool))
    hp_missing=max(0.0,hp_target-float(ev.get("player_hp_end",0.0)))
    mana_missing=max(0.0,mana_target-float(ev.get("mana_end",0.0)))
    heal=smooth._heal_model(
        int(level),talents,gear,
        float(row.get("mob_landed_swings_per_s",0.0))*max(1.0,float(row.get("avg_alive_mobs",1.0))),
    )
    if ev.get("complete"):
        recovery_s,recovery_method,_recovery_detail=smooth._recovery(
            int(level),hp_missing,mana_missing,mana_pool,heal,gear.spirit_bonus,
        )
        travel_s=2.2/(1+.04*talents.pursuit_of_justice)
        raw_cycle=float(ev["kill_s"])+recovery_s+travel_s
        cycle=max(raw_cycle,float(ev.get("emergency_cooldown_floor_s",0.0)))
        adjusted_mph=3600.0*n/max(.1,cycle)
    else:
        recovery_s=float("inf"); recovery_method="incomplete event replay"
        travel_s=2.2/(1+.04*talents.pursuit_of_justice)
        cycle=float("inf"); adjusted_mph=0.0
    smooth_mph=float(row.get("mobs_per_hour",0.0))
    return {
        "supported":bool(v.get("supported",False)),
        "event_complete":bool(ev.get("complete",False)),
        "pull_size":n,
        "gear":row.get("gear"),
        "profile":row.get("profile"),
        "policy":row.get("policy"),
        "aura":row.get("aura"),
        "mana_plan":row.get("mana_plan"),
        "smooth_mobs_per_hour":smooth_mph,
        "event_adjusted_mobs_per_hour":adjusted_mph,
        "throughput_delta_pct":((adjusted_mph/smooth_mph-1.0)*100.0) if smooth_mph>0 else None,
        "smooth_combat_s":float(row.get("combat_s_per_pack",0.0)),
        "event_combat_s":float(ev.get("kill_s",float("inf"))),
        "event_recovery_s":recovery_s,
        "event_travel_s":travel_s,
        "event_cycle_s":cycle,
        "recovery_method":recovery_method,
        "hp_recovery_needed":hp_missing,
        "mana_recovery_needed":mana_missing,
        "event_hp_end":float(ev.get("player_hp_end",0.0)),
        "event_mana_end":float(ev.get("mana_end",0.0)),
        "heal_casts_requested":int(ev.get("heal_casts_requested",0)),
        "heal_casts_completed":int(ev.get("heal_casts_completed",0)),
        "emergency_actions_used":list(ev.get("emergency_actions_used") or ()),
        "fury_breaks":int(ev.get("fury_breaks",0)),
        "shield_spec_procs":int(ev.get("shield_spec_procs",0)),
        "authority":"hybrid_event_validation_proxy_only",
    }


def build_report(project_root:Path|str=".",*,start_level:int|None=None,end_level:int|None=None,top_n:int=5) -> dict:
    root=Path(project_root)
    viewer=root/"state"/"games"/"forever-paladin"/"v2"/"viewer.json"
    data=json.loads(viewer.read_text(encoding="utf-8"))
    summaries=((data.get("views") or {}).get("experimental") or {}).get("level_summaries") or []
    levels=[]; rows=[]; ordering=[]
    for summary in summaries:
        level=int(summary.get("level",0))
        if start_level is not None and level<int(start_level): continue
        if end_level is not None and level>int(end_level): continue
        # Paladin runner snapshots may preserve a deeper smooth finalist pool
        # specifically for event validation.  It is intentionally cheaper than
        # the visible candidates (no stat weights / pull-envelope diagnostics),
        # so validation can catch cases like lvl 15 where the event winner sits
        # well below smooth rank 5 without bloating the player-facing table.
        candidate_source=(summary.get("validation_candidates") or summary.get("candidates") or [])
        candidates=list(candidate_source)[:max(1,int(top_n))]
        if not candidates: continue
        levels.append(level)
        level_rows=[]
        for smooth_rank,c in enumerate(candidates,1):
            tr=dict(c.get("talent_ranks") or {})
            details=dict(c.get("details") or {})
            if not tr or not details:
                continue
            t=Talents(**tr)
            r=validate_candidate(level,t,details)
            r.update({
                "level":level,
                "smooth_rank":smooth_rank,
                "allocation":c.get("allocation"),
                "talent_family":c.get("talent_family",c.get("family")),
                "combat_profile":c.get("combat_profile",c.get("profile")),
                "talent_ranks":tr,
            })
            level_rows.append(r)
        event_sorted=sorted(level_rows,key=lambda x:(-float(x["event_adjusted_mobs_per_hour"]),int(x["smooth_rank"])))
        rank_map={id(r):i+1 for i,r in enumerate(event_sorted)}
        # Objects are the same dict instances after sorting.
        for r in level_rows:
            r["event_adjusted_rank"]=rank_map[id(r)]
            r["rank_delta"]=int(r["smooth_rank"])-int(r["event_adjusted_rank"])
        changed=any(r["smooth_rank"]!=r["event_adjusted_rank"] for r in level_rows)
        smooth_top=min(level_rows,key=lambda r:int(r["smooth_rank"]))
        event_top=min(level_rows,key=lambda r:int(r["event_adjusted_rank"]))
        material_keys=("gear","pull_size","combat_profile","policy","aura","mana_plan")
        material_changes=[k for k in material_keys if smooth_top.get(k)!=event_top.get(k)]
        talent_changed=smooth_top.get("allocation")!=event_top.get("allocation")
        top_changed=(smooth_top is not event_top)
        if material_changes:
            change_kind="playstyle"
        elif talent_changed or top_changed:
            change_kind="talent_only"
        else:
            change_kind="none"
        ordering.append({
            "level":level,
            "ordering_changed":changed,
            "validated_candidates":len(level_rows),
            "top_candidate_changed":top_changed,
            "top_talent_changed":talent_changed,
            "top_playstyle_changed":bool(material_changes),
            "material_fields_changed":material_changes,
            "decision_change_kind":change_kind,
            "smooth_top_rank_event":int(smooth_top["event_adjusted_rank"]),
            "smooth_top_mobs_per_hour":float(smooth_top["smooth_mobs_per_hour"]),
            "smooth_top_event_adjusted_mobs_per_hour":float(smooth_top["event_adjusted_mobs_per_hour"]),
            "event_top_smooth_rank":int(event_top["smooth_rank"]),
            "event_top_event_adjusted_mobs_per_hour":float(event_top["event_adjusted_mobs_per_hour"]),
        })
        rows.extend(level_rows)
    playstyle_levels=[x["level"] for x in ordering if x.get("top_playstyle_changed")]
    talent_only_levels=[x["level"] for x in ordering if x.get("decision_change_kind")=="talent_only"]
    return {
        "kind":"forever_paladin_topn_event_validation",
        "authority":"diagnostic_validator_only",
        "interpretation":"Event-adjusted throughput is a hybrid validation proxy (event combat/end resources + smooth out-of-combat recovery), not optimizer authority or MC.",
        "levels":sorted(set(levels)),
        "top_n":int(top_n),
        "ordering":ordering,
        "decision_summary":{
            "playstyle_changed_levels":playstyle_levels,
            "talent_only_changed_levels":talent_only_levels,
            "stable_top_levels":[x["level"] for x in ordering if x.get("decision_change_kind")=="none"],
        },
        "rows":rows,
    }


def write_report(report:dict,out_base:Path|str) -> tuple[Path,Path]:
    base=Path(out_base)
    base.parent.mkdir(parents=True,exist_ok=True)
    jp=base.with_suffix(".json"); cp=base.with_suffix(".csv")
    jp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    fields=[
        "level","smooth_rank","event_adjusted_rank","rank_delta","allocation","talent_family","combat_profile",
        "gear","pull_size","policy","aura","mana_plan","smooth_mobs_per_hour","event_adjusted_mobs_per_hour",
        "throughput_delta_pct","smooth_combat_s","event_combat_s","event_recovery_s","event_cycle_s",
        "hp_recovery_needed","mana_recovery_needed","heal_casts_requested","heal_casts_completed",
        "fury_breaks","shield_spec_procs","authority",
    ]
    with cp.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader()
        for row in report.get("rows",[]):
            w.writerow(row)
    return jp,cp


def main(argv:list[str]|None=None) -> int:
    ap=argparse.ArgumentParser(description="Validate visible Forever Paladin Fast candidates with deterministic event replay")
    ap.add_argument("--project-root",default=".")
    ap.add_argument("--start-level",type=int)
    ap.add_argument("--end-level",type=int)
    ap.add_argument("--top-n",type=int,default=5)
    ap.add_argument("--out",default="state/games/forever-paladin/v2/event_validation")
    args=ap.parse_args(argv)
    report=build_report(args.project_root,start_level=args.start_level,end_level=args.end_level,top_n=args.top_n)
    jp,cp=write_report(report,Path(args.project_root)/args.out)
    print(json.dumps({
        "levels":report["levels"],"rows":len(report["rows"]),
        "decision_summary":report.get("decision_summary",{}),
        "ordering":report["ordering"],"json":str(jp),"csv":str(cp)
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
