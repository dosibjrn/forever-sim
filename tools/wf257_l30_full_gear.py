"""Independent full named-gear rescore of the sole source-executable L30 full-budget allocation.

The allocation universe is generated from L10 source-legal one-point transitions,
not from a legacy build. All gear options in the observed source catalogue
are scored; policy search is still bounded.
"""
from __future__ import annotations
import json
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_search import talent_candidate_id
from src.v2.source_legal_beam import legal_point_frontier
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_multi_pull_joint import _score_state
from src.shared.leveling.objective import representative_hp
ROOT=Path(__file__).resolve().parents[1]

def run():
    allocations=[{}]
    for level in range(10,31):
        ir=build_game_ir_slice(class_key='paladin',level=level)
        allocations=list({talent_candidate_id(y):y for a in allocations for y in
            legal_point_frontier(ir,a,level=level,allow_transfers=False)}.values())
    if len(allocations)!=1 or sum(allocations[0].values())!=21:
        raise ValueError('source full-budget L30 talent universe not unique; re-evaluate all allocations')
    allocation=allocations[0]
    gears=_gear_envelope('paladin',30,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=ir)
    rows=[_score_state(ir,level=30,gear=g,allocation=allocation,pulls=3,
        policy_cap=8,target_health=representative_hp(30)) for g in gears]
    valid=[r for r in rows if r['seconds_per_mob'] is not None]
    if not valid:raise ValueError('no L30 source-executable combat policy')
    winner=min(valid,key=lambda r:(r['seconds_per_mob'],r['gear_id']))
    return {'status':'EVALUATED_BOUNDED','level':30,'class_key':'paladin',
        'full_budget_talent_allocations':len(allocations),'source_gear_evaluated':len(gears),
        'policy_evaluations':sum(r['policy_evaluated'] for r in rows),
        'policy_rejections':sum(r['policy_rejected'] for r in rows),
        'gear_states_blocked':len(rows)-len(valid),
        'independent_winner':winner,
        'gear_scores':[{'gear_id':r['gear_id'],'role':r['gear_role'],
                        'seconds_per_mob':r['seconds_per_mob'],
                        'policy_evaluated':r['policy_evaluated']} for r in rows],
        'global_optimum_proven':False,
        'limitations':['43+ unexecuted Paladin talent families and many legal abilities missing',
            'source gear acquisition unverified','policy frontier capped at eight',
            'player/enemy proxy baselines and some Seal proc rates not server verified']}

if __name__=='__main__':
    r=run();(ROOT/'WF257_PALADIN_L30_FULL_GEAR.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({'score':r['independent_winner']['seconds_per_mob'],
        'talents':r['independent_winner']['talent_allocation'],
        'gear':r['independent_winner']['gear_id'],
        'policy':r['independent_winner']['best_policy']['policy']['rules'],
        'gear_evaluated':r['source_gear_evaluated'],
        'policy_evaluated':r['policy_evaluations']},indent=2))
