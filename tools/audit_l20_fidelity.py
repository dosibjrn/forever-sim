from __future__ import annotations

"""Bounded cross-class L20 mechanics audit for v0.11.48.77.

This intentionally rescales/rescores a small set of representative production
L20 decisions instead of launching four full 10->20 route searches.  It is a
fidelity decomposition, not a ranking benchmark or a claim of exhaustive L20
optimization.
"""

import csv
import json
import time
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def _timing(total,kill,recovery,travel):
    return {
        'mobs_per_hour':360000.0/float(total),
        'seconds_per_mob':float(total)/100.0,
        'kill_s_per_mob':float(kill)/100.0,
        'recovery_s_per_mob':float(recovery)/100.0,
        'travel_s_per_mob':float(travel)/100.0,
    }


def _mage():
    from src import game_context
    game_context.configure('forever','mage')
    from src.engine_registry import reset_engine_cache,get_engine
    reset_engine_cache(); e=get_engine()
    t=e.Talents(imp_frostbolt=5,elemental_precision=1,permafrost=1,frostbite=3,ice_lance=1)
    # Re-run the bounded independent L20 analytic search as an internal cross-
    # check. The comparison row below still uses event timing so HP/contact
    # recovery is represented, but this proves the ~197 result is not an
    # artifact of hand-picking one Frost corridor.
    from src.v2.local_search import search_level_analytic
    from src.v2.analytic_scorer import AnalyticOptions
    analytic_rows=search_level_analytic(
        20,e.SimConfig(),options=AnalyticOptions(),beam_width=16,
        family_keep=3,final_k=8,school='all',
    )
    analytic=analytic_rows[0]
    ad=dict(analytic.details or {})
    analytic_ref={
        'mobs_per_hour':360000.0/float(analytic.score_s_per_100),
        'seconds_per_mob':float(analytic.score_s_per_100)/100.0,
        'kill_s_per_mob':float(ad.get('kill_s') or 0.0)/100.0,
        'recovery_s_per_mob':float(ad.get('recovery_s') or 0.0)/100.0,
        'travel_s_per_mob':float(ad.get('travel_s') or 0.0)/100.0,
        'allocation':e.final_allocation(analytic.talents),
        'policy':getattr(analytic.policy,'name',str(analytic.policy)),
        'beam_width':16,'family_keep':3,'final_k':8,
    }
    # Production L20 has bounded event adjudication. Use the same event policy
    # search on the known structural Frost/Ice-Lance corridor rather than the
    # cheaper analytic screen so HP/contact recovery is represented.
    event=e.policy_search(20,t,e.SimConfig(),'frost',n=64,seed=7)
    best=dict(event.get('best_found') or {})
    kill=float(best['kill_seconds_per_mob']); rec=float(best['recovery_seconds_per_mob']); travel=float(best['travel_seconds_per_mob'])
    total=(kill+rec+travel)*100.0
    return {
        'class':'mage','selection_basis':'known L20 Frost/Ice-Lance production corridor; bounded event policy adjudication n=64 seed=7',
        'allocation':e.final_allocation(t),'combat_profile':'single_target','pull_size':1,
        **_timing(total,kill*100.0,rec*100.0,travel*100.0),
        'representative_mob_hp':float(e.MOB_BASE_HP[20]),
        'active_dps':float(e.MOB_BASE_HP[20])/kill,
        'policy':best.get('rotation'),'recovery_solver_id':best.get('recovery_solver_id'),
        'resource':{'casts':best.get('casts'),'pushback_s_per_mob':best.get('pushback_seconds_per_mob'),'melee_contact_s_per_mob':best.get('melee_contact_seconds_per_mob')},
        'bounded_independent_search':analytic_ref,
        'scope_note':'single-target; Blizzard/AoE leveling remains server-profile dependent and is not credited in this comparison',
    }


def _hunter():
    from src import game_context
    game_context.configure('forever','hunter')
    from src.engine_registry import reset_engine_cache,get_engine
    reset_engine_cache(); e=get_engine()
    corridors=[
        ('beast_mastery',e.Talents(deadly_aspects=5,endurance_training=5,bestial_swiftness=1)),
        ('marksmanship',e.Talents(lethal_attacks=5,careful_aim=5,lone_wolf=1)),
        ('survival',e.Talents(improved_tracking=5,survivalist=5,surefooted=1)),
    ]
    rows=[]
    for route,t in corridors:
        r=e.experimental_level_score(20,t,route)
        row={'route':route,'allocation':e.final_allocation(t),**_timing(r['total_s'],r['kill_s'],r['recovery_s'],r['travel_s']),
             'pull_size':int(r.get('pull_size') or 1),'profile':r.get('profile'),'policy':r.get('rotation'),
             'active_dps':float(r.get('dps') or 0.0),'recovery_solver_id':r.get('recovery_solver_id'),
             'mana_spent_per_mob':r.get('mana_spent_per_mob'),'mana_deficit_per_mob':r.get('mana_deficit_per_mob'),
             'combat_mana_regen_per_s':r.get('combat_mana_regen_per_s'),'ooc_mana_regen_per_s':r.get('ooc_mana_regen_per_s')}
        rows.append(row)
    best=min(rows,key=lambda x:x['seconds_per_mob'])
    return {
        'class':'hunter','selection_basis':'best rescore of the three declared legal L20 endpoint corridors; not exhaustive unconstrained search',
        **best,'representative_mob_hp':484.0,'corridors':rows,
        'scope_note':'single-target ranged/pet model; Aspect-of-the-Cheetah-style level-20 travel speed is credited by the Hunter model',
    }


def _druid():
    from src import game_context
    game_context.configure('forever','druid')
    from src.engine_registry import reset_engine_cache,get_engine
    reset_engine_cache(); e=get_engine()
    t=e.Talents(improved_wrath=5,genesis=2,improved_moonfire=2,natures_majesty=2)
    r=e.experimental_level_score(20,t,'balance')
    return {
        'class':'druid','selection_basis':'rescore of the last bounded L20 Balance winner retained by M47',
        'allocation':e.final_allocation(t),'combat_profile':r.get('profile'),'pull_size':int(r.get('pull_size') or 1),
        **_timing(r['total_s'],r['kill_s'],r['recovery_s'],r['travel_s']),
        'representative_mob_hp':float(r.get('representative_mob_hp') or 484.0),'active_dps':float(r.get('dps') or 0.0),
        'policy':r.get('rotation'),'recovery_solver_id':r.get('recovery_solver_id'),
        'resource':{'mana_spent_per_mob':r.get('mana_spent_per_mob'),'mana_missing':r.get('mana_missing'),'passive_mana_regen_per_s':r.get('passive_mana_regen_per_s'),'combat_mp5_return':r.get('combat_mp5_return')},
        'scope_note':'Balance single-target row used for cross-class decomposition; Cat/Bear constrained route identity is validated separately',
    }


def _paladin():
    from src import game_context
    game_context.configure('forever','paladin')
    from src.engine_registry import reset_engine_cache,get_engine
    reset_engine_cache(); e=get_engine()
    t=e.Talents(deflection=3,benediction=4,improved_judgement=2,holy_conduit=1,seal_of_command=1)
    r=e.experimental_level_score(20,t,'retribution')
    candidate={'talent_ranks':{k:int(getattr(t,k)) for k in t.__dataclass_fields__ if int(getattr(t,k))},
               'details':r,'pull_size':r.get('pull_size'),'gear':r.get('gear'),'combat_profile':r.get('profile'),
               'score_s_per_100':r['total_s'],'allocation':e.final_allocation(t)}
    validated=e.event_validate_candidates(20,[candidate]).get('event_validated_best') or {}
    if validated.get('mobs_per_hour'):
        total=360000.0/float(validated['mobs_per_hour'])
        kill=float(validated.get('kill_seconds_per_mob') or r['kill_s']/100.0)
        rec=float(validated.get('recovery_seconds_per_mob') or r['recovery_s']/100.0)
        travel=float(validated.get('travel_seconds_per_mob') or r['travel_s']/100.0)
    else:
        total=float(r['total_s']); kill=float(r['kill_s'])/100.0; rec=float(r['recovery_s'])/100.0; travel=float(r['travel_s'])/100.0
    return {
        'class':'paladin','selection_basis':'rescore of the M47 L20 Ret event-selected corridor with deterministic finalist validator',
        'allocation':e.final_allocation(t),'combat_profile':r.get('profile'),'pull_size':int(r.get('pull_size') or 1),
        **_timing(total,kill*100.0,rec*100.0,travel*100.0),
        'representative_mob_hp':484.0,'active_dps':float(r.get('dps') or 0.0),'policy':r.get('rotation'),
        'recovery_solver_id':r.get('recovery_solver_id'),
        'resource':{'mana_spent_per_mob':r.get('mana_spent_per_mob'),'mana_recovery_needed':r.get('mana_recovery_needed'),'passive_mana_regen_per_s':r.get('passive_mana_regen_per_s')},
        'scope_note':'multi-target pack model, so travel/recovery are amortized over the selected pull; event validator remains hybrid fidelity authority',
    }


def build():
    started=time.perf_counter()
    rows=[_mage(),_hunter(),_druid(),_paladin()]
    return {
        'schema_version':1,'version':'v0.11.48.77','level':20,
        'purpose':'bounded apples-to-apples timing/resource decomposition after shared recovery unification, dated beta tuning, and pinned Druid/Paladin base Spirit authority',
        'not_a_ranking':True,
        'selection_scope':'representative previously-selected/declared L20 corridors; no four-class exhaustive search',
        'timing_contract':'kill/combat -> recovery -> between-pull travel; non-overlapping seconds per mob',
        'rows':rows,'runtime_s':time.perf_counter()-started,
    }


def write(report):
    jp=ROOT/'CROSS_CLASS_L20_FIDELITY_v0.11.48.77.json'
    mp=ROOT/'CROSS_CLASS_L20_FIDELITY_v0.11.48.77.md'
    cp=ROOT/'CROSS_CLASS_L20_FIDELITY_v0.11.48.77.csv'
    jp.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    lines=['# Cross-class L20 fidelity audit — v0.11.48.77','',
           'Bounded mechanics decomposition, **not** an exhaustive class ranking. All rows use the canonical non-overlapping timing contract `kill -> recovery -> travel` and the same shared recovery solver for ordinary food/water timing.','',
           '| Class | mobs/h | kill s/mob | recovery s/mob | travel s/mob | pull | solver |',
           '|---|---:|---:|---:|---:|---:|---|']
    for r in report['rows']:
        lines.append(f"| {r['class'].title()} | {r['mobs_per_hour']:.1f} | {r['kill_s_per_mob']:.2f} | {r['recovery_s_per_mob']:.2f} | {r['travel_s_per_mob']:.2f} | {r['pull_size']} | {r.get('recovery_solver_id') or '—'} |")
    by={r['class']:r for r in report['rows']}
    m=by['mage']; h=by['hunter']; d=by['druid']; p=by['paladin']
    lines += ['', '## What the decomposition says', '',
              f"- Mage is still slower after the recovery fix: **{m['kill_s_per_mob']:.2f}s kill + {m['recovery_s_per_mob']:.2f}s recovery + {m['travel_s_per_mob']:.2f}s travel**. The largest remaining gap is kill time, not the old recovery mismatch.",
              f"- A separate bounded independent Mage L20 analytic search lands at **{m['bounded_independent_search']['mobs_per_hour']:.1f} mobs/h** ({m['bounded_independent_search']['kill_s_per_mob']:.2f}s kill + {m['bounded_independent_search']['recovery_s_per_mob']:.2f}s recovery + {m['bounded_independent_search']['travel_s_per_mob']:.2f}s travel). The small-sample event row is higher; the dedicated wand/contact audit checks the same policy family with a larger event sample instead of treating either backend as exact.",
              f"- Hunter endpoint corridors now land around **{min(x['mobs_per_hour'] for x in h['corridors']):.1f}–{max(x['mobs_per_hour'] for x in h['corridors']):.1f} mobs/h** after 5SR-correct Spirit handling. Its kill time is about half Mage's and its level-20 travel assumption is faster.",
              f"- Druid Balance sits between them at **{d['mobs_per_hour']:.1f} mobs/h** with raw public Wrath tooltip rows plus the dated September 24 ~50% base-damage tuning override and the same-level spell-hit baseline; it is also single-target in this audit.",
              f"- Paladin's **{p['pull_size']}-target** pack model amortizes recovery/travel over several mobs, so its per-mob throughput is not a single-target DPS comparison.",
              '', '## Remaining fidelity flags', '',
              '- Mage deterministic structural screening now carries armor-mitigated melee HP loss into the shared recovery solver. The event row remains the higher-fidelity comparison authority.',
              '- Druid and Paladin now publish pinned race/class base Spirit separately from item Spirit and feed total Spirit plus the vanilla base mana-regeneration term through the shared recovery solver.',
              '- Mage Blizzard/AoE grinding remains outside this default comparison because server behavior is profile-dependent. Do not interpret this table as coverage of Mage AoE leveling.',
              '', f"Runtime: **{report['runtime_s']:.2f}s**."]
    mp.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    fields=['class','selection_basis','allocation','combat_profile','profile','mobs_per_hour','seconds_per_mob','kill_s_per_mob','recovery_s_per_mob','travel_s_per_mob','pull_size','representative_mob_hp','active_dps','recovery_solver_id','policy','scope_note']
    with cp.open('w',newline='',encoding='utf-8') as fh:
        w=csv.DictWriter(fh,fieldnames=fields,extrasaction='ignore')
        w.writeheader()
        for r in report['rows']:
            w.writerow(r)
    return jp,mp,cp


if __name__=='__main__':
    report=build(); jp,mp,cp=write(report)
    print(json.dumps({'json':str(jp),'md':str(mp),'csv':str(cp),'runtime_s':report['runtime_s'],
                      'rows':[{k:r[k] for k in ('class','mobs_per_hour','kill_s_per_mob','recovery_s_per_mob','travel_s_per_mob','pull_size')} for r in report['rows']]},indent=2))
