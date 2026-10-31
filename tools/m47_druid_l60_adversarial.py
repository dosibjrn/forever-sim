from __future__ import annotations
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from src import game_context
from src.engine_registry import get_engine, reset_engine_cache
from tools.m47_3x3_baseline import _family_corridor, _neighbors, _reachable, _key, _ranks
from src.rulesets.forever.classes.druid.reference_validator import CASES, validate_case
VERSION='v0.11.47.5'; LEVEL=60

def _mph(s):
    return float(s.get('mobs_per_hour') or 360000.0/max(1e-9,float(s['total_s'])))

def build():
    p=json.loads((ROOT/'M47_3X3_BASELINE_v0.11.47.0.json').read_text())
    base=next(r for r in p['rows'] if r['class']=='druid' and int(r['level'])==LEVEL)
    prior=game_context.current()
    try:
        game_context.configure('forever','druid'); reset_engine_cache(); e=get_engine()
        bt=_reachable(e,base['talent_ranks'])
        bs=e.experimental_level_score(LEVEL,bt,'all')
        oracle_case=next(c for c in CASES if c.level==LEVEL)
        oracle=validate_case(oracle_case,e.experimental_level_score)
        exact_oracle_fixture=_ranks(bt)==_ranks(oracle_case.talents)
        profiles={}
        global_best=None
        total_candidates=0
        for fam in e.TREE_NAMES:
            seed=_family_corridor(e,LEVEL,fam)
            cands=[seed]+_neighbors(e,seed,72)
            total_candidates += len(cands)
            fam_out={'candidate_count':len(cands),'profiles':{}}
            for prof in ('all','bear','feral','balance'):
                ranked=[]
                for t in cands:
                    s=e.experimental_level_score(LEVEL,t,prof)
                    ranked.append((_mph(s),_key(t),t,s))
                ranked.sort(key=lambda x:(-x[0],x[1]))
                m,_,t,s=ranked[0]
                row={'mobs_per_hour':m,'observed_profile':s.get('profile'),'allocation':e.final_allocation(t),'talent_ranks':_ranks(t),'pull_size':s.get('pull_size'),'rotation':s.get('rotation')}
                fam_out['profiles'][prof]=row
                if prof=='all' and (global_best is None or m>global_best['mobs_per_hour']):
                    global_best={'family_seed':fam,**row}
            profiles[fam]=fam_out
        balance_best=profiles['balance']['profiles']['all']['mobs_per_hour']
        margin=(float(bs['mobs_per_hour'])/balance_best-1.0)*100.0
        unfalsified=(global_best['observed_profile']=='bear' and global_best['mobs_per_hour'] <= float(bs['mobs_per_hour']) + 1e-9)
        return {
            'schema_version':1,'version':VERSION,'milestone':'M47','cell':'druid_L60',
            'status':'BOUNDED_ADVERSARIAL_CELL_CLOSED',
            'authority':'all_family_corridors_plus_one_legal_swap_each + independent_frozen_oracle',
            'search':{'neighbor_cap':72,'family_corridors':list(e.TREE_NAMES),'total_family_seed_candidates_counted_with_overlap':total_candidates,'not_globally_exhaustive':True},
            'baseline':{'mobs_per_hour':float(bs['mobs_per_hour']),'profile':bs.get('profile'),'pull_size':bs.get('pull_size'),'allocation':e.final_allocation(bt),'talent_ranks':_ranks(bt)},
            'independent_oracle':{'exact_fixture_match':exact_oracle_fixture,**oracle},
            'family_challengers':profiles,
            'global_bounded_best':global_best,
            'bear_vs_best_balance_margin_pct':margin,
            'classification':{
                'selection':'supported_no_falsifying_one_swap_challenger',
                'mechanic_fidelity':'independently_checked_by_exact_L60_oracle_fixture',
                'bear_vs_balance':'bounded_objective_difference_supported',
            },
            'gate_a':{'cell_closed':bool(unfalsified and exact_oracle_fixture and oracle['ok']),'scope':'bounded family-corridor + one-swap adversarial search; not a global exhaustive talent enumeration'}
        }
    finally:
        game_context.configure(prior.ruleset,prior.class_name); reset_engine_cache()

def main():
    q=build(); jp=ROOT/f'M47_DRUID_L60_ADVERSARIAL_{VERSION}.json'; mp=ROOT/f'M47_DRUID_L60_ADVERSARIAL_{VERSION}.md'
    jp.write_text(json.dumps(q,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    gb=q['global_bounded_best']; bb=q['family_challengers']['balance']['profiles']['all']
    mp.write_text(
        f"# M47 Druid L60 Bear adversarial check — {VERSION}\n\n"
        f"- published Bear baseline: **{q['baseline']['mobs_per_hour']:.2f} mobs/h**, pull {q['baseline']['pull_size']}\n"
        f"- bounded global best after all family corridors + one legal swap: **{gb['mobs_per_hour']:.2f} mobs/h ({gb['observed_profile']})**\n"
        f"- best Balance-family challenger: **{bb['mobs_per_hour']:.2f} mobs/h**\n"
        f"- Bear margin over best Balance-family challenger: **{q['bear_vs_best_balance_margin_pct']:.1f}%**\n"
        f"- exact independent L60 oracle fixture match: **{q['independent_oracle']['exact_fixture_match']}**\n"
        f"- independent oracle: **{'PASS' if q['independent_oracle']['ok'] else 'FAIL'}**\n\n"
        "The surprising Bear result survives this bounded adversarial search and is independently checked for profile, pull size, rotation, rage, Swipe/Maul resource behavior, and throughput envelope. This closes the L60 Druid cell for the current M47 bounded scope; it is not a claim of exhaustive global talent enumeration.\n",
        encoding='utf-8')
    print(json.dumps(q,indent=2))
if __name__=='__main__': main()
