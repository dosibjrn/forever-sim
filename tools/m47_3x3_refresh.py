from __future__ import annotations
import csv, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

VERSION='v0.11.47.6'
LEVELS=(20,40,60); CLASSES=('mage','paladin','druid')
BASELINE='M47_3X3_BASELINE_v0.11.47.0.json'
PAL_SEL={20:'M47_PALADIN_L20_SELECTION_v0.11.47.2.json',40:'M47_PALADIN_L40_SELECTION_v0.11.47.3.json',60:'M47_PALADIN_L60_SELECTION_v0.11.47.4.json'}
DRUID60='M47_DRUID_L60_ADVERSARIAL_v0.11.47.5.json'


def _load(name): return json.loads((ROOT/name).read_text(encoding='utf-8'))

def _normalize(row):
    r=dict(row)
    mph=float(r.get('mobs_per_hour') or 0.0)
    if mph and r.get('seconds_per_mob') is None: r['seconds_per_mob']=3600.0/mph
    return r

def _gate_state(cls,level):
    if cls=='paladin':
        return {'selection':'closed','mechanic_authority':'open_hybrid_event_proxy','gate_a':'open','evidence':PAL_SEL[level]}
    if cls=='druid' and level==60:
        return {'selection':'closed_bounded','mechanic_authority':'closed_independent_oracle','gate_a':'closed_bounded','evidence':DRUID60}
    if cls=='mage' and level==20:
        return {'selection':'closed_bounded_event_rerank','mechanic_authority':'m46_release_validated','gate_a':'needs_m47_cell_adversarial_classification','evidence':BASELINE}
    return {'selection':'baseline_only','mechanic_authority':'m46_floor_only','gate_a':'open_needs_m47_adversarial_cell_check','evidence':BASELINE}

def build():
    base=_load(BASELINE)
    rows={(r['class'],int(r['level'])):_normalize(r) for r in base['rows']}
    # Replace obsolete smooth-only Paladin rows with the production selections
    # already proven by the L20/L40/L60 selection regressions.
    for level,name in PAL_SEL.items():
        p=_load(name); b=dict(p['published_event_winner']); old=rows[('paladin',level)]
        merged=dict(old); merged.update(b)
        merged['class']='paladin'; merged['level']=level
        merged['seconds_per_mob']=3600.0/float(merged['mobs_per_hour'])
        merged['selection_authority']=p['selection_authority']
        merged['selection_source']=name
        rows[('paladin',level)]=merged
    # Druid L60 numerical baseline is unchanged, but its closure authority is newer.
    d60=_load(DRUID60)
    assert abs(float(rows[('druid',60)]['mobs_per_hour'])-float(d60['baseline']['mobs_per_hour']))<1e-9
    out=[]
    for cls in CLASSES:
        for level in LEVELS:
            r=rows[(cls,level)]; r['gate_a_status']=_gate_state(cls,level); out.append(r)
    gaps=[]
    for r in out:
        g=r['gate_a_status']['gate_a']
        if not str(g).startswith('closed'):
            gaps.append({'class':r['class'],'level':int(r['level']),'gate_a':g,'selection':r['gate_a_status']['selection'],'mechanic_authority':r['gate_a_status']['mechanic_authority']})
    return {
      'schema_version':1,'version':VERSION,'milestone':'M47','status':'REFRESHED_3X3_GATE_A_IN_PROGRESS',
      'assembly_authority':'evidence_composed_no_reoptimization',
      'contract':base['contract'],
      'optimization_scope':'Mage/Druid rows reuse the reproducible v0.11.47.0 baseline evidence; Paladin rows are replaced by the current production event-reranked selection evidence; Druid L60 carries v0.11.47.5 bounded adversarial + independent-oracle closure.',
      'rows':out,'remaining_gate_a_gaps':gaps,
      'source_artifacts':[BASELINE,*PAL_SEL.values(),DRUID60],
    }

def write(payload,out_prefix):
    jp=ROOT/f'{out_prefix}.json'; cp=ROOT/f'{out_prefix}.csv'; mp=ROOT/f'{out_prefix}.md'
    jp.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    fields=['class','level','mobs_per_hour','seconds_per_mob','combat_profile','gear','pull_size','rotation','allocation','selection_authority','gate_a']
    with cp.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in payload['rows']:
            x={k:r.get(k) for k in fields};x['gate_a']=r['gate_a_status']['gate_a'];w.writerow(x)
    lines=[f"# M47 refreshed optimized 3×3 — {payload['version']}",'',
      '**State:** evidence-composed production-selection refresh; no full 3×3 re-optimization was run. M47 Gate A remains IN_PROGRESS.','',
      '| Class | L | mobs/h | sec/mob | profile | pull | Gate A | allocation |','|---|---:|---:|---:|---|---:|---|---|']
    for r in payload['rows']:
        lines.append(f"| {r['class'].title()} | {r['level']} | {float(r.get('mobs_per_hour') or 0):.1f} | {float(r.get('seconds_per_mob') or 0):.2f} | {r.get('combat_profile') or r.get('profile')} | {r.get('pull_size')} | {r['gate_a_status']['gate_a']} | `{str(r.get('allocation') or '—').replace('|','/')}` |")
    lines += ['', '## Remaining Gate-A gaps','']
    for g in payload['remaining_gate_a_gaps']:
        lines.append(f"- {g['class'].title()} L{g['level']}: **{g['gate_a']}** — selection `{g['selection']}`, mechanic authority `{g['mechanic_authority']}`")
    lines += ['', '## What changed from v0.11.47.0','',
      '- Paladin L20: smooth 386.6 → published event-reranked **299.6 mobs/h**.',
      '- Paladin L40: smooth 266.0 → published event-reranked **225.4 mobs/h**.',
      '- Paladin L60: smooth 260.5 → published event-reranked **221.8 mobs/h**.',
      '- Druid L60 remains **172.6 mobs/h Bear**, now carrying bounded adversarial + independent-oracle closure.', '',
      'Next Gate-A work should not reopen those selection closures. The remaining priority is Paladin mechanic authority, then bounded M47 adversarial checks for Mage L20/L40/L60 and Druid L20/L40.']
    mp.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return [jp,cp,mp]

def main():
    p=build(); paths=write(p,f'M47_3X3_REFRESH_{VERSION}'); print(json.dumps({'ok':True,'files':[str(x) for x in paths],'rows':len(p['rows']),'remaining_gate_a_gaps':len(p['remaining_gate_a_gaps'])},indent=2))
if __name__=='__main__': main()
