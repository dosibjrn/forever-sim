from __future__ import annotations

"""Cross-class Forever leveling comparison report.

This module intentionally does *not* collapse heterogeneous backends into a
single confidence-adjusted winner.  Raw sustainable throughput is shown next to
machine-readable model fidelity so a mature Mage chain model is not silently
presented as equivalent evidence to an early Druid smooth proxy.
"""

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable

from src.class_registry import class_names, get_definition
from .class_model import Evaluation

CLASSES = class_names("forever", comparison_default=True)


def model_fidelity(class_name: str) -> dict:
    return get_definition("forever", class_name).fidelity()


def snapshot_path(project_root: Path, class_name: str) -> Path:
    return Path(project_root) / "state" / "games" / f"forever-{class_name}" / "v2" / "viewer.json"


def _best_rows(snapshot: dict, class_name: str) -> dict[int, dict]:
    views=snapshot.get("views") or {}
    definition=get_definition("forever", class_name)
    view=next((views.get(name) for name in definition.viewer_view_priority if views.get(name)), {})
    out={}
    for summary in view.get("level_summaries") or []:
        best=summary.get("best") or {}
        if best:
            out[int(summary.get("level",best.get("level",0)))]=best
    return out


def _throughput(best: dict) -> float | None:
    mph=best.get("mobs_per_hour")
    if mph is not None:
        try: return float(mph)
        except Exception: pass
    score=best.get("score_s_per_100")
    try:
        score=float(score)
        return 360000.0/score if score>0 else None
    except Exception:
        return None


def comparison_row(level: int, class_name: str, best: dict) -> dict:
    details=best.get("details") or {}
    fid=dict(best.get("model_fidelity") or model_fidelity(class_name))
    ev=Evaluation.from_published_row(best)
    score=ev.score_s_per_100
    recovery=ev.recovery_s_per_100
    if recovery is None and details.get("recovery_s_per_pack") is not None:
        pull=max(1,int(best.get("pull_size") or details.get("pull_size") or 1))
        recovery=float(details["recovery_s_per_pack"])*100.0/pull
    survival_margin=None
    if details.get("risk_adjusted_end_hp") is not None:
        survival_margin=details.get("risk_adjusted_end_hp")
    elif details.get("end_hp") is not None and details.get("min_hp") is not None:
        survival_margin=float(details["end_hp"])-float(details["min_hp"])
    return {
        "level": int(level),
        "class": str(class_name),
        "mobs_per_hour": ev.mobs_per_hour,
        "score_s_per_100": float(score),
        "pull_size": int(best.get("pull_size") or details.get("pull_size") or 1),
        "kill_s_per_100": ev.kill_s_per_100,
        "recovery_s_per_100": float(recovery) if recovery is not None else None,
        "travel_s_per_100": ev.travel_s_per_100,
        "timing_contract": ev.timing_contract,
        "timing_complete": ev.timing_complete,
        "timing_consistent": ev.timing_consistent,
        "timing_residual_s_per_100": ev.timing_residual_s_per_100,
        "survival_margin_hp": float(survival_margin) if survival_margin is not None else None,
        "allocation": best.get("allocation"),
        "talent_family": best.get("talent_family",best.get("family")),
        "combat_profile": best.get("combat_profile",best.get("profile",details.get("profile"))),
        "gear": best.get("gear") or details.get("gear"),
        "stat_mix_guidance": ">".join(best.get("stat_mix_guidance") or []),
        "policy": best.get("policy") or details.get("rotation"),
        "source": best.get("source"),
        "fidelity_rating": fid.get("rating"),
        "fidelity_backend": fid.get("backend"),
        "fidelity_pull_model": fid.get("pull_model"),
        "fidelity_resource_continuity": fid.get("resource_continuity"),
        "fidelity_survival": fid.get("survival"),
        "fidelity_mc_validated": bool(fid.get("mc_validated",False)),
        "model_fidelity": fid,
    }


def build_comparison(project_root: Path, *, start_level: int | None = None,
                     end_level: int | None = None, classes: Iterable[str] = CLASSES) -> dict:
    classes=tuple(classes)
    per_class={}
    paths={}
    for c in classes:
        p=snapshot_path(project_root,c); paths[c]=str(p)
        if not p.exists():
            raise FileNotFoundError(f"missing {c} snapshot: {p}; run that Forever class first")
        snap=json.loads(p.read_text(encoding="utf-8"))
        per_class[c]=_best_rows(snap,c)
    common=set.intersection(*(set(v) for v in per_class.values())) if per_class else set()
    if start_level is not None: common={x for x in common if x>=int(start_level)}
    if end_level is not None: common={x for x in common if x<=int(end_level)}
    rows=[]
    for level in sorted(common):
        for c in classes:
            rows.append(comparison_row(level,c,per_class[c][level]))
    return {
        "ruleset":"forever",
        "classes":list(classes),
        "levels":sorted(common),
        "rows":rows,
        "source_snapshots":paths,
        "interpretation":"Raw throughput is not a confidence-adjusted ranking; compare model_fidelity beside every row.",
    }


def write_report(report: dict, output_dir: Path) -> tuple[Path,Path]:
    output_dir=Path(output_dir); output_dir.mkdir(parents=True,exist_ok=True)
    jp=output_dir/"class_comparison.json"; cp=output_dir/"class_comparison.csv"
    jp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    rows=report.get("rows") or []
    if rows:
        flat=[]
        for r in rows:
            d={k:v for k,v in r.items() if k!="model_fidelity"}
            flat.append(d)
        with cp.open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=list(flat[0])); w.writeheader(); w.writerows(flat)
    else:
        cp.write_text("level,class\n",encoding="utf-8")
    return jp,cp


def main(argv=None):
    ap=argparse.ArgumentParser(description="Compare Forever Mage/Paladin/Druid per-level leveling decisions with fidelity visible")
    ap.add_argument("--project-root",type=Path,default=Path(__file__).resolve().parents[2])
    ap.add_argument("--start-level",type=int,default=None)
    ap.add_argument("--end-level",type=int,default=None)
    ap.add_argument("--output-dir",type=Path,default=None)
    args=ap.parse_args(argv)
    report=build_comparison(args.project_root,start_level=args.start_level,end_level=args.end_level)
    out=args.output_dir or (args.project_root/"state"/"comparisons"/"forever")
    jp,cp=write_report(report,out)
    print(f"wrote {len(report['levels'])} common level(s): {jp} {cp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
