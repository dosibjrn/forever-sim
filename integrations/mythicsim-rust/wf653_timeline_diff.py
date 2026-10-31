#!/usr/bin/env python3
"""Time-resolved damage attribution from engine combat logs.

One-iteration stochastic replicas yield a mean trajectory E[damage(t)].
Balanced first-fight trace is compared separately; it is not a multi-fight
balanced mean and must NOT be reported as full balanced-mode convergence.
"""
import argparse, json, re
from pathlib import Path

LINE=re.compile(r'^\[(-?[\d.]+)\].*\[Target \d+\].*? (?:tick )?(?:Hit|Crit|Glance|Crush) for ([\d.]+) damage')
OTHER=re.compile(r'^\[(-?[\d.]+)\].*\[Target \d+\].*? (?:Miss|Dodge|Parry|Resist)')

def events(report):
    log=report["result"]["logs"]
    out=[]
    for line in log.splitlines():
        m=LINE.search(line)
        if m:
            out.append((float(m[1]),float(m[2]),line.split("{SpellID: ")[-1].split("}")[0].split(",")[0]))
    return out

def curve(event_sets,seconds=120,step=5):
    points=[]
    for t in range(0,seconds+1,step):
        samples=[sum(d for at,d,_ in e if at<=t) for e in event_sets]
        mean=sum(samples)/len(samples)
        points.append({"second":t,"mean_cumulative_damage":mean,
                       "mean_running_dps":mean/t if t else 0})
    return points

def compare(stochastic,balanced):
    a=curve([events(x) for x in stochastic])
    b=curve([events(balanced)])
    rows=[]
    for s,t in zip(a,b):
        ref=s["mean_cumulative_damage"]
        actual=t["mean_cumulative_damage"]
        rows.append({"second":s["second"],"stochastic_mean_damage":ref,
                     "balanced_first_fight_damage":actual,
                     "damage_diff":actual-ref,"damage_diff_pct":100*(actual/ref-1) if ref else None,
                     "stochastic_running_dps":s["mean_running_dps"],
                     "balanced_running_dps":t["mean_running_dps"]})
    return rows

def first_divergence(rows,threshold_pct=5):
    # Ignore near-zero denominators at the first few seconds.
    return next((r for r in rows if r['second']>=5 and r['stochastic_mean_damage']>=1000
                 and r['damage_diff_pct'] is not None and abs(r['damage_diff_pct'])>threshold_pct),None)

def spell_summary(stochastic,balanced):
    from collections import defaultdict
    totals=defaultdict(float)
    for report in stochastic:
        for t,d,spell in events(report):
            if 0<=t<=120:totals[('reference',spell)]+=d/len(stochastic)
    for t,d,spell in events(balanced):
        if 0<=t<=120:totals[('balanced',spell)]+=d
    spells=sorted(set(spell for _,spell in totals))
    return sorted(({'spell_id':spell,'reference_mean_damage':totals['reference',spell],
                   'balanced_first_damage':totals['balanced',spell],
                   'difference':totals['balanced',spell]-totals['reference',spell]}
                   for spell in spells), key=lambda r:abs(r['difference']),reverse=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--stochastic-dir",type=Path,required=True)
    p.add_argument("--balanced",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    x=p.parse_args()
    runs=[json.loads(f.read_text()) for f in sorted(x.stochastic_dir.glob("*.json"))]
    assert len(runs)>=30,"Require >=30 independent stochastic first-fight traces"
    balanced=json.loads(x.balanced.read_text())
    rows=compare(runs,balanced)
    x.out.write_text(json.dumps({"stochastic_fights":len(runs),"warning":"balanced_first_fight_only_not_converged_balanced_mean","points":rows,"first_over_5pct":first_divergence(rows),
                                 "spell_attribution":spell_summary(runs,balanced)},indent=2))
    print('First >5% cumulative deviation:', first_divergence(rows))
    print('Largest spell differences:',spell_summary(runs,balanced)[:8])
    for row in rows:
        print(f"{row['second']:3d}s ref={row['stochastic_mean_damage']:9.1f} bal={row['balanced_first_fight_damage']:9.1f} diff={row['damage_diff_pct']}")
if __name__=="__main__":
    main()
