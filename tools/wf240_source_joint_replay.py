"""Independent source-family stratified L20 diagnostic and held-out Feral replay.

NOT an exhaustive joint optimizer. No old allocation/gear is used in sampling.
"""
from __future__ import annotations
import hashlib,json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_search import enumerate_legal_talent_allocations,talent_candidate_id
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection
from src.v2.source_joint_discovery import _gear_envelope,_evaluate_caster_already_talented
from src.v2.source_mode_search import evaluate_discovered_mode_search
from src.v2.source_staged_joint_search import _diverse_gear_indices


def score(ir,gear,allocation):
    geared,_=apply_gear_selection(ir,aggregate_stats=gear['selection'].aggregate_stats,
        selected_items=tuple(gear['selection'].slots.values()),source='canonical_sqlite_forever_catalogue')
    talented,_=apply_talent_selection(geared,allocation,level=20)
    rows=[]
    for branch,fn in (('caster',lambda:_evaluate_caster_already_talented(
            talented,level=20,max_policies=128,schedule_incoming_attacks=True)),
            ('mode',lambda:evaluate_discovered_mode_search(class_key='druid',level=20,
            ir_slice=talented,max_policies_per_path=256,schedule_incoming_attacks=True))):
        try:
            result=fn();win=result['winner']
            rows.append({'branch':branch,'seconds_per_mob':win['seconds_per_mob'],
                         'selected_actions':[a['action_id'] for a in win['selected_actions']],
                         'policy':win['policy'],'combat_kill_s':win['combat_kill_s'],
                         'recovery_s':win['recovery_s']})
        except (ValueError,RuntimeError) as exc:
            rows.append({'branch':branch,'error':str(exc)})
    valid=[r for r in rows if 'seconds_per_mob' in r]
    if not valid:return None
    best=min(valid,key=lambda r:(r['seconds_per_mob'],r['branch']))
    return {'seconds_per_mob':best['seconds_per_mob'],'gear_id':gear['id'],
            'gear_role':gear['gear_role'],
            'gear_slots':{k:{'item_id':v['item_id'],'name':v['name']} for k,v in gear['selection'].slots.items()},
            'talent_allocation':dict(allocation),'best_policy':best,
            'branch_scores':{r['branch']:r.get('seconds_per_mob') for r in rows}}


def run():
    started=time.monotonic()
    ir=build_game_ir_slice(class_key='druid',level=20)
    allocations,truncated=enumerate_legal_talent_allocations(ir,level=20,max_candidates=30000)
    assert not truncated
    gears=_gear_envelope('druid',20,max_gear_candidates=64,
        required_level_policy='observed',include_melee_gear=True,ir_slice=ir)
    gears=[gears[i] for i in _diverse_gear_indices(gears,7)]
    old={'ferocity':5,'heart_of_the_wild':3,'thick_hide':2,'savage_fury':1}
    old_id=talent_candidate_id(old)
    # Deterministic rank-family coverage + hash-ordered broad sample.
    families=sorted({name for alloc in allocations for name,rank in alloc.items() if rank>0})
    selected={}
    for fam in families:
        possible=[a for a in allocations if a.get(fam,0)>0 and talent_candidate_id(a)!=old_id]
        if possible:
            # No scoring, gear, reference or prior winner influences the choice.
            pick=min(possible,key=lambda a:(-a[fam],sum(a.values()),talent_candidate_id(a)))
            selected[talent_candidate_id(pick)]=pick
    by_hash=sorted((a for a in allocations if talent_candidate_id(a)!=old_id),
        key=lambda a:hashlib.sha256(talent_candidate_id(a).encode()).hexdigest())
    for alloc in by_hash[:4]:selected[talent_candidate_id(alloc)]=alloc
    independent=list(selected.values())
    evaluated=[]
    for i,alloc in enumerate(independent):
        scores=[score(ir,gear,alloc) for gear in gears]
        good=[s for s in scores if s]
        if good:
            evaluated.append(min(good,key=lambda s:s['seconds_per_mob']))
        if i%10==0:print('progress',i+1,len(independent),flush=True)
    winner=min(evaluated,key=lambda s:s['seconds_per_mob'])
    # Held-out old challenger evaluated AFTER independent winner, same 7 source-diverse gear
    # envelope and same source runtime, without insertion into candidate search.
    old_rows=[score(ir,gear,old) for gear in gears]
    old_best=min((s for s in old_rows if s),key=lambda s:s['seconds_per_mob'])
    evidence={'version':'0.11.48.240','class_key':'druid','level':20,
        'scope':'stratified_bounded_joint_sample_not_global_optimum',
        'all_executable_legal_allocations':len(allocations),
        'independent_allocation_count':len(independent),
        'independent_sample_rule':'source_family_max_rank_min_spent_then_4_SHA256_allocations',
        'source_gear_count':len(gears),'state_evaluations':len(independent)*len(gears)+len(gears),
        'old_challenger_not_seeded':True,'old_challenger_actually_evaluated':True,
        'same_engine_objective_and_gear_envelope':True,
        'winner':winner,'held_out':old_best,'sampled_allocations':independent,
        'elapsed_s':time.monotonic()-started,
        'limitations':['not exhaustive over 17489 executable allocations',
            'source action/talent completeness incomplete',
            'rear-only Shred excluded without explicit positional opportunity',
            'root break and hit/crit fidelity incomplete',
            'regrowth compound heal not yet considered by recovery optimizer']}
    Path('WF240_DRUID_L20_JOINT_REPLAY.json').write_text(json.dumps(evidence,indent=2))
    print('RESULT',winner['seconds_per_mob'],old_best['seconds_per_mob'],len(independent),len(gears),flush=True)

if __name__=='__main__':run()
