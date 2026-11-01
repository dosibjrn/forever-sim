import json, os
from src.engine_registry import eng
from src.objective import search_level_weight_per_100
from src.v2.experimental_classes import _BeamRow, _select_diverse, _key, _allocation, _family, _tree_points, _mobs_per_hour

TARGETS={20,40,60}
beam=[_BeamRow(eng.Talents(),0.0,eng.experimental_level_score(10,eng.Talents(),'all'),tuple())]
out=[]
for level in range(10,61):
    generated={}
    for parent in beam:
        for name in eng.TALENT_RULES:
            if not eng.legal_add(parent.talents,name): continue
            child=eng.add_point(parent.talents,name)
            if child.points()!=level-9: continue
            k=_key(child)
            if k in generated: continue
            score=eng.experimental_level_score(level,child,'all')
            weight=max(.01,float(search_level_weight_per_100(level)))
            generated[k]=_BeamRow(child,parent.cumulative_s+weight*float(score['total_s']),score,tuple())
    if not generated: raise RuntimeError(level)
    beam=_select_diverse(list(generated.values()),10,2)
    if level in TARGETS:
        best=min(beam,key=lambda r:(float(r.score['total_s']),r.cumulative_s))
        s=best.score
        out.append({
            'level':level,'mobs_per_hour':_mobs_per_hour(s),'rotation':s.get('rotation'),
            'allocation':_allocation(best.talents),'talent_family':_family(best.talents),
            'combat_profile':s.get('profile','auto'),'gear':s.get('gear'),
            'pull_size':s.get('pull_size',1),'policy':s.get('policy'),
            'aura':s.get('aura'),'mana_plan':s.get('mana_plan'),
            'talent_ranks':{n:int(getattr(best.talents,n)) for n in best.talents.__dataclass_fields__ if int(getattr(best.talents,n))},
            'score_s_per_100':float(s['total_s'])
        })
print(json.dumps(out,indent=2))
