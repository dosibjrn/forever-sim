#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from src.rulesets.forever.classes.mage import engine as m

PRIORITIES={
 'frost':['imp_frostbolt','elemental_precision','ice_lance','ice_shards','permafrost','frostbite','piercing_ice','frost_channeling','arctic_reach','shatter','fingers_of_frost','winters_chill','cold_snap','ice_barrier','frost_warding','imp_frost_nova','ice_block','improved_cone_of_cold','improved_blizzard'],
 'arcane':['arcane_focus','improved_channeling','arcane_blast','arcane_concentration','arcane_subtlety','missile_barrage','arcane_meditation','arcane_impact','arcane_mind','arcane_instability','wand_specialization','magic_absorption','arcane_resilience','arcane_geometry','arcane_shielding','improved_counterspell','presence_of_mind','arcane_power'],
 'fire':['imp_fireball','incineration','wake_of_fire','ignite','flame_throwing','impact','pyroblast','burning_soul','hot_streak','imp_scorch','master_elements','critical_mass','fire_power','combustion','improved_fire_ward','improved_flamestrike','blast_wave'],
}

def legal_tree_build(level:int,school:str)->m.Talents:
    t=m.Talents(); need=max(0,level-9)
    pr=PRIORITIES[school]
    while t.points()<need:
        added=False
        for name in pr:
            if m.legal_add(t,name):
                t=m.add_point(t,name); added=True; break
        if not added:
            # Finish any remaining legal talents in the primary tree first.
            for name,(tree,*_) in m.TALENT_RULES.items():
                if tree==school and m.legal_add(t,name):
                    t=m.add_point(t,name); added=True; break
        if not added:
            # At L60 some trees contain fewer than 51 spendable points. Keep the
            # requested school as the primary tree and place overflow legally in
            # deterministic secondary-tree priorities rather than fabricating an
            # impossible single-tree build.
            for secondary in ('frost','arcane','fire'):
                if secondary==school:
                    continue
                for name in PRIORITIES[secondary]:
                    if m.legal_add(t,name):
                        t=m.add_point(t,name); added=True; break
                if added:
                    break
        if not added:
            raise RuntimeError(f'cannot build {school} L{level}: {t}')
    return t


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--n',type=int,default=24)
    ap.add_argument('--seed',type=int,default=143)
    ap.add_argument('--json-out',type=Path)
    ap.add_argument('--md-out',type=Path)
    args=ap.parse_args()
    cfg=m.SimConfig()
    report={'levels':{},'n':args.n,'seed':args.seed}
    for lvl in (20,40,60):
        rows={}
        for school in ('frost','arcane','fire'):
            t=legal_tree_build(lvl,school)
            rows[school]={
                'talents':m.final_allocation(t),
                'policy_ab':m.policy_ab(lvl,t,cfg,school,n=args.n,seed=args.seed+lvl),
                'policy_search':m.policy_search(lvl,t,cfg,school,n=args.n,seed=args.seed+lvl),
            }
        report['levels'][str(lvl)]=rows
    if args.json_out:
        args.json_out.parent.mkdir(parents=True,exist_ok=True)
        args.json_out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    if args.md_out:
        lines=['# Mage policy fidelity — v0.11.43','',f'Paired MC mobs per comparison: **{args.n}**','',
               '| Level | School | Meta Δ mobs/h vs baseline | Best-found | Meta regret s/mob |','|---:|---|---:|---|---:|']
        for lvl,schools in report['levels'].items():
            for school,row in schools.items():
                ab=row['policy_ab']; ps=row['policy_search']
                lines.append(f"| {lvl} | {school} | {ab['delta_mobs_per_hour']:+.2f} | {ps['best_found']['policy']} | {ps['meta_regret_seconds_per_mob']:.2f} |")
        lines += ['', 'The guide/meta policy is a prior, not a forced winner. Each row uses one legal build with that school as its primary tree at that level; `policy_ab` keeps the build fixed and `policy_search` searches the bounded build-gated policy family.']
        args.md_out.parent.mkdir(parents=True,exist_ok=True)
        args.md_out.write_text('\n'.join(lines)+'\n')
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
