"""Reproducible P2 rank-and-allocation coverage certificate (no fake L2 work)."""
from pathlib import Path
import json
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint,evaluate_p2,evaluate_p2_allocation_l0

SOURCE=Path('evidence/wf336/druid_l20_talent_rank_observations_70338.json')
OUTPUT=Path('evidence/wf336/WF336_P2_CHECKPOINT_CERTIFICATE.json')

def run():
    ir=build_game_ir_slice(class_key='druid',level=20)
    cp=P2Checkpoint('druid',20)
    result=evaluate_p2(ir,cp,source_observations_path=SOURCE,spellbook_path='evidence/wf335/druid_spellbook_70338_level1_20.json')
    # Two real source-legal 11-point talent interactions, including a L2-
    # unsupported source grant; never present as executor victories.
    result['allocation_probes']=[evaluate_p2_allocation_l0(result,ir,x,cp) for x in
      ({'ferocity':5,'heart_of_the_wild':5,'feral_charge':1},
       {'natures_focus':5,'furor':5,'subtlety':1},
       {'ferocity':5,'heart_of_the_wild':5,'shredding_attacks':1})]
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result
if __name__=='__main__':
    x=run();print(json.dumps({k:x[k] for k in ('p2_pass','known_reachable_rank_count','l0_scored_reachable_rank_count','source_only_l0_rank_count','l2_unsupported_scored_rank_count','status_counts')},indent=2))
