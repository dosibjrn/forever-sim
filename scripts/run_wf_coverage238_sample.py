"""Independent deterministic source-family + hash sample, not a global optimum."""
import argparse
import hashlib
import json
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_search import enumerate_legal_talent_allocations, talent_candidate_id
import src.v2.source_staged_joint_search as staged


def run(output:Path, *,sample_count:int=160, policy_cap:int=24):
    ir=build_game_ir_slice(class_key='druid',level=20)
    legal,truncated=enumerate_legal_talent_allocations(ir,level=20,max_candidates=100000)
    if truncated:raise ValueError('executable allocation enumeration truncated')
    held={'ferocity':5,'heart_of_the_wild':3,'thick_hide':2,'savage_fury':1}
    held_id=talent_candidate_id(held)
    ranked=sorted(legal,key=lambda a:(sum(a.values()),talent_candidate_id(a)))
    families=sorted({tid for a in legal for tid in a})
    selected={talent_candidate_id(a):a for a in ranked[:1]}
    for family in families:
        a=next((a for a in ranked if family in a and talent_candidate_id(a)!=held_id),None)
        if a is not None:selected[talent_candidate_id(a)]=a
    # Source content hash, not old reference results or a handpicked class build.
    hashed=sorted((hashlib.sha256(talent_candidate_id(a).encode()).hexdigest(),talent_candidate_id(a),a)
                  for a in legal if talent_candidate_id(a)!=held_id)
    for _,cid,a in hashed:
        if len(selected)>=sample_count:break
        selected[cid]=a
    sample=tuple(selected.values())
    if held_id in selected:raise AssertionError('held-out challenger seeded discovery')
    original=staged.enumerate_legal_talent_allocations
    staged.enumerate_legal_talent_allocations=lambda *a,**k:(sample,False)
    try:
        result=staged.evaluate_staged_joint_search(
            class_key='druid',level=20,ir_slice=ir,
            screening_gear_count=2,finalist_talent_count=16,
            max_policies_per_path=policy_cap,max_caster_policies=policy_cap,
            held_out_allocation=held)
    finally:staged.enumerate_legal_talent_allocations=original
    out={'version':'0.11.48.238','source_executable_legal_count':len(legal),
         'independent_sample_count':len(sample),
         'source_family_representatives':families,
         'unscored_legal_count':len(legal)-len(sample),
         'held_out_separate':True,
         'sampling':'minimum-points-per-executable-family + SHA256 content-hash selections; old Feral excluded',
         'evaluation':result,'global_optimum_claim':False}
    output.write_text(json.dumps(out,indent=2)+'\n')
    print('allocations',len(legal),'sample',len(sample),'runtime',result['elapsed_s'])
    print('winner',result['winner']['seconds_per_mob'],result['winner']['talent_allocation'])
    print('heldout',result['held_out']['best']['seconds_per_mob'])
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--sample-count',type=int,default=160)
    p.add_argument('--policy-cap',type=int,default=24)
    a=p.parse_args();run(a.output,sample_count=a.sample_count,policy_cap=a.policy_cap)
