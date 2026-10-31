"""Run source-versioned L30 P2 diagnostic; never claim PASS with missing ranks."""
from pathlib import Path
import json
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint,evaluate_p2

SOURCE=Path('evidence/wf349/druid_l30_talent_rank_observations_70338.json')
SPELL=Path('evidence/wf348/druid_spellbook_70338_level1_30.json')
OUT=Path('evidence/wf349/WF349_P2_DIAGNOSTIC.json')
SUMMARY=Path('evidence/wf349/WF349_P2_SOURCE_GAPS.json')

def run():
    ir=build_game_ir_slice(class_key='druid',level=30)
    result=evaluate_p2(ir,P2Checkpoint('druid',30),source_observations_path=SOURCE,spellbook_path=SPELL)
    gaps={'checkpoint':'druid:L30:unrestricted','source_build':'1.60.1.70338',
        'p2_pass':result['p2_pass'],
        'canonical_candidate_ranks_with_numeric_l0':result['l0_scored_reachable_rank_count'],
        'canonical_candidate_ranks_seen':result['known_reachable_rank_count'],
        'source_rank_mismatches':result['source_rank_mismatches'],
        'known_source_rank_gaps_at_l30':[{'talent_id':r['talent_id'],'rank':n}
            for r in result['source_rank_mismatches'] for n in r['possibly_missing_source_ranks_at_checkpoint']],
        'source_identity_gaps':result['unknown_position_families'],
        'unscored_canonical_candidates':result['blocked'],
        'note':'Verified subset only; NOT a complete denominator for all live source talents. L2 joint search must fail closed on this certificate.'}
    OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    SUMMARY.write_text(json.dumps(gaps,indent=2,sort_keys=True)+'\n')
    return gaps

if __name__=='__main__':
    print(json.dumps(run(),indent=2,sort_keys=True))
