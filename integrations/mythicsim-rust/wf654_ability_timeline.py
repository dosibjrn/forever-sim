#!/usr/bin/env python3
"""WF654: per-ability time-series diagnosis of stochastic mean vs balanced RNG.

All stochastic traces are independent single-fight simulations. Group by SpellID,
tick flag, and outcome. Compare event count, hit/crit/miss counts, per-event
damage, and cumulative damage at 5-second intervals; avoids pretending a
single balanced run is a many-fight expectation.
"""
import argparse,json,re,collections
from pathlib import Path
LOG_RE=re.compile(r'^\[(-?[\d.]+)\].*?\{SpellID: (\d+)(?:, Tag: [^}]+)?\} (tick )?(Hit|Crit|Miss|Dodge|Parry|Resist|Glance|Crush)(?: for ([\d.]+) damage)?')
def events(doc):
    out=[]
    for line in doc['result']['logs'].splitlines():
        m=LOG_RE.search(line)
        if not m:continue
        t,spell,tick,outcome,d=m.groups()
        if float(t)<0:continue
        out.append((float(t),spell+(':tick' if tick else ''),outcome,float(d or 0)))
    return out
def aggregate(fights,step=5,end=120):
    evs=[events(d) for d in fights]
    abilities=sorted({a for es in evs for _,a,_,_ in es})
    rows=[]
    for ability in abilities:
        for second in range(step,end+1,step):
            history=[(t,o,d) for es in evs for t,a,o,d in es if a==ability and t<=second]
            counts=collections.Counter(o for _,o,_ in history)
            dmg=sum(d for _,_,d in history)/len(evs)
            n=sum(counts.values())/len(evs)
            rows.append({'ability':ability,'second':second,'damage':dmg,'events':n,
                         'damage_per_event':dmg/n if n else 0,
                         'hits':counts['Hit']/len(evs),'crits':counts['Crit']/len(evs),
                         'misses':sum(counts[k] for k in ('Miss','Dodge','Parry','Resist'))/len(evs)})
    return {(x['ability'],x['second']):x for x in rows}
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--stochastic-dir',type=Path,required=True)
    p.add_argument('--balanced',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    stochastic=[json.loads(f.read_text()) for f in sorted(a.stochastic_dir.glob('*.json'))]
    assert len(stochastic)>=30
    balanced=json.loads(a.balanced.read_text())
    sr=aggregate(stochastic);br=aggregate([balanced])
    rows=[]
    for key in sorted(sr.keys()|br.keys(),key=lambda k:(k[1],k[0])):
        ref=sr.get(key);bal=br.get(key)
        if not ref:continue
        if not bal:bal={'damage':0,'events':0,'damage_per_event':0,'hits':0,'crits':0,'misses':0}
        rows.append({'ability':key[0],'second':key[1],
                     **{f'ref_{k}':ref[k] for k in ('damage','events','damage_per_event','hits','crits','misses')},
                     **{f'balanced_{k}':bal[k] for k in ('damage','events','damage_per_event','hits','crits','misses')},
                     'delta_damage':bal['damage']-ref['damage'],
                     'delta_events':bal['events']-ref['events']})
    at_end=sorted((r for r in rows if r['second']==120),key=lambda r:abs(r['delta_damage']),reverse=True)
    a.out.write_text(json.dumps({'stochastic_fights':len(stochastic),
       'balanced_fights':1,'note':'First-fight balanced comparison only. Verify full balanced multi-fight output separately.',
       'rows':rows,'largest_ability_deltas_120s':at_end},indent=2))
    print('ABILITY | REF DAMAGE | BAL DAMAGE | DELTA | REF EVENTS | BAL EVENTS | REF CRITS | BAL CRITS')
    for r in at_end[:15]:
        print(f"{r['ability']:15} {r['ref_damage']:10.1f} {r['balanced_damage']:10.1f} {r['delta_damage']:9.1f} {r['ref_events']:8.1f} {r['balanced_events']:8.1f} {r['ref_crits']:8.1f} {r['balanced_crits']:8.1f}")
    print('TIME SERIES FIRST THREE ABILITIES')
    for abi in [r['ability'] for r in at_end[:3]]:
        for r in rows:
            if r['ability']==abi and r['second']%15==0:
                print(abi,r['second'],round(r['ref_damage'],1),round(r['balanced_damage'],1),round(r['delta_damage'],1))
if __name__=='__main__':main()
