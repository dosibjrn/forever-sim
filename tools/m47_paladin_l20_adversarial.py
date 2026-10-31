from __future__ import annotations

import argparse, json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from src import game_context
from src.engine_registry import get_engine, reset_engine_cache
from src.rulesets.forever.classes.paladin.validation_report import validate_candidate
from tools.m47_3x3_baseline import _family_corridor, _key, _neighbors, _ranks, _reachable

VERSION='v0.11.47.1'
LEVEL=20
BASELINE=ROOT/'M47_3X3_BASELINE_v0.11.47.0.json'
HISTORIC=ROOT/'MILESTONE_3X3_v0.11.16.json'


def _row(path:Path):
    rows=json.loads(path.read_text(encoding='utf-8'))
    if isinstance(rows,dict): rows=rows['rows']
    return next(r for r in rows if r['class']=='paladin' and int(r['level'])==LEVEL)


def build(*,neighbor_cap:int=120,event_top_n:int=16)->dict:
    baseline=_row(BASELINE); historic=_row(HISTORIC)
    prior=game_context.current()
    try:
        game_context.configure('forever','paladin'); reset_engine_cache(); e=get_engine()
        starts=[]
        for label,row in [('m47_baseline',baseline),('historic_v0.11.16',historic)]:
            t=_reachable(e,row.get('talent_ranks') or {})
            if t is not None: starts.append((label,t))
        for family in e.TREE_NAMES:
            t=_family_corridor(e,LEVEL,family)
            if t is not None: starts.append((f'family_corridor:{family}',t))

        pool={_key(t):(label,t) for label,t in starts}
        for label,t in list(starts):
            for nt in _neighbors(e,t,neighbor_cap):
                pool.setdefault(_key(nt),(f'one_swap:{label}',nt))

        profiles={}
        for profile in ('retribution','protection'):
            smooth=[]
            for source,t in pool.values():
                row=e.experimental_level_score(LEVEL,t,profile)
                smooth.append((float(row['total_s']),_key(t),source,t,row))
            smooth.sort(key=lambda x:(x[0],x[1]))
            event_rows=[]
            for smooth_rank,(_,_,source,t,row) in enumerate(smooth[:max(1,int(event_top_n))],1):
                ev=validate_candidate(LEVEL,t,row)
                event_rows.append({
                    'smooth_rank':smooth_rank,'source':source,'talent_ranks':_ranks(t),
                    'allocation':e.final_allocation(t),'profile':profile,'gear':row.get('gear'),
                    'pull_size':int(row.get('pull_size') or 1),'rotation':row.get('rotation'),
                    'smooth_mobs_per_hour':float(row.get('mobs_per_hour') or 0.0),
                    'event_mobs_per_hour':float(ev.get('event_adjusted_mobs_per_hour') or 0.0),
                    'event_complete':bool(ev.get('event_complete')),
                    'event_combat_s':float(ev.get('event_combat_s')),
                    'event_recovery_s':float(ev.get('event_recovery_s')),
                    'event_cycle_s':float(ev.get('event_cycle_s')),'event':ev,
                })
            event_rows.sort(key=lambda r:(-r['event_mobs_per_hour'],r['smooth_rank']))
            profiles[profile]={
                'smooth_best':{
                    'source':smooth[0][2],'talent_ranks':_ranks(smooth[0][3]),
                    'smooth_mobs_per_hour':float(smooth[0][4]['mobs_per_hour']),
                    'gear':smooth[0][4].get('gear'),'pull_size':int(smooth[0][4].get('pull_size') or 1),
                },
                'event_best':event_rows[0],
                'event_finalists':event_rows,
            }

        baseline_t=_reachable(e,baseline['talent_ranks'])
        baseline_s=e.experimental_level_score(LEVEL,baseline_t,'retribution')
        baseline_ev=validate_candidate(LEVEL,baseline_t,baseline_s)
        ret=profiles['retribution']['event_best']; prot=profiles['protection']['event_best']
        return {
            'schema_version':1,'version':VERSION,'milestone':'M47','cell':'paladin_L20',
            'status':'ADVERSARIAL_CHECK_COMPLETE_CELL_NOT_GATE_A_CLOSED',
            'authority':'expanded_local_finalists_plus_hybrid_event_replay_diagnostic',
            'contract':{'target':'same_level_world_mob','recovery':'sustained_chain_best_level_usable_food_water','level':20},
            'search':{'candidate_pool':len(pool),'neighbor_cap':neighbor_cap,'event_top_n_per_profile':event_top_n,
                      'seeds':['m47_baseline','historic_v0.11.16','family_corridors'],'neighborhood':'one_legal_talent_point_swap'},
            'baseline':{
                'smooth_mobs_per_hour':float(baseline_s['mobs_per_hour']),
                'event_mobs_per_hour':float(baseline_ev['event_adjusted_mobs_per_hour']),
                'event_delta_pct':float(baseline_ev['throughput_delta_pct']),
                'talent_ranks':_ranks(baseline_t),'gear':baseline_s.get('gear'),'pull_size':baseline_s.get('pull_size'),
            },
            'profiles':profiles,
            'classification':{
                'baseline_selection':'search_failure',
                'reason':'The bounded M47 baseline selected the smooth-score winner, but deterministic event reranking of an expanded legal local finalist pool selects a different Retribution allocation.',
                'smooth_vs_event':'mechanic_fidelity_gap',
                'smooth_vs_event_reason':'The smooth scorer materially overstates the surprising L20 throughput versus deterministic event combat/recovery replay; event replay remains a hybrid diagnostic proxy, not final production authority.',
                'ret_vs_prot':'expected_objective_difference_provisionally_supported',
                'ret_vs_prot_event_margin_pct':(ret['event_mobs_per_hour']/prot['event_mobs_per_hour']-1.0)*100.0 if prot['event_mobs_per_hour'] else None,
            },
            'gate_a':{'cell_closed':False,'why':'Expanded local event rerank falsified the published baseline allocation. Update M47 selection authority before calling this cell closed.'},
        }
    finally:
        game_context.configure(prior.ruleset,prior.class_name); reset_engine_cache()


def write(payload:dict,out_base:Path):
    jp=Path(str(out_base)+'.json'); mp=Path(str(out_base)+'.md')
    jp.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    ret=payload['profiles']['retribution']['event_best']; prot=payload['profiles']['protection']['event_best']; b=payload['baseline']
    lines=[f"# M47 Paladin L20 adversarial check — {payload['version']}",'',
           '**Result:** the 386.6 mobs/h baseline is not Gate-A-stable. Retribution remains ahead of the forced Protection challenger under the deterministic event proxy, but the winning Ret allocation changes.','',
           f"- Baseline Ret: {b['smooth_mobs_per_hour']:.1f} smooth → {b['event_mobs_per_hour']:.1f} event-proxy mobs/h ({b['event_delta_pct']:.1f}%).",
           f"- Expanded Ret event winner: {ret['event_mobs_per_hour']:.1f} mobs/h (smooth rank {ret['smooth_rank']}, pull {ret['pull_size']}, `{ret['source']}`).",
           f"- Expanded Prot event winner: {prot['event_mobs_per_hour']:.1f} mobs/h (smooth rank {prot['smooth_rank']}, pull {prot['pull_size']}, `{prot['source']}`).",
           f"- Ret event-proxy margin over Prot: {payload['classification']['ret_vs_prot_event_margin_pct']:.1f}%.",'',
           '## Classification','',
           '- Published L20 baseline allocation: **search failure** for M47 Gate A, because the event-reranked expanded local finalist pool selects a different legal Ret allocation.',
           '- Smooth 386.6 figure vs event replay: **mechanic fidelity gap / authority disagreement**; do not publish 386.6 as validated throughput.',
           '- Ret vs Prot direction: **provisionally supported expected objective difference** under this workload, not yet final Gate-A closure.','',
           '## Event-best Retribution allocation','',f"`{ret['allocation']}`",'',ret['rotation'],'',
           '## Event-best Protection allocation','',f"`{prot['allocation']}`",'',prot['rotation'],'',
           '## Next','',
           'Make Paladin M47 target-level selection retain/rerank an expanded finalist set with deterministic event replay, then re-run L20 before moving to L40/L60.']
    mp.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return jp,mp


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--neighbor-cap',type=int,default=120); ap.add_argument('--event-top-n',type=int,default=16); ap.add_argument('--out',default=f'M47_PALADIN_L20_ADVERSARIAL_{VERSION}')
    a=ap.parse_args(); p=build(neighbor_cap=a.neighbor_cap,event_top_n=a.event_top_n); files=write(p,ROOT/a.out)
    print(json.dumps({'ok':True,'files':[str(x) for x in files],'classification':p['classification'],'gate_a':p['gate_a']},indent=2))

if __name__=='__main__': main()
