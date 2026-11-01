"""Nine-class L20 real continuous runtime canary (not a checkpoint proof)."""
import json
from pathlib import Path
from time import process_time,perf_counter
from src.game.data.forever.registry import build_game_ir_slice
from src.game.multi_pull import evaluate_repeated_pulls
from src.v2.source_companion_policy_search import companion_policy_envelope
from src.shared.leveling.objective import representative_hp

def run():
    out={}
    for cls in ('druid','hunter','mage','paladin','priest','rogue','shaman','warlock','warrior'):
        start=perf_counter(); cpu=process_time(); ir=build_game_ir_slice(class_key=cls,level=20)
        attempts=[]
        companion_variants, companion_coverage = companion_policy_envelope(ir)
        for policy in ir.policies[:3]:
            try:
                result=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=20,
                     target_health=representative_hp(20),count=2,
                     schedule_incoming_attacks=True,apply_target_defense=True,
                     companion_policy_override=companion_variants[0])
                attempts.append({'policy':policy.id,'status':'EXECUTED','score_s_per_mob':result.seconds_per_mob,
                    'events':sum(p['event_transitions'] for p in result.pulls)})
                break
            except (ValueError,RuntimeError,KeyError) as e:
                attempts.append({'policy':policy.id,'status':'BLOCKED','reason':str(e)[:180]})
        out[cls]={'companion_coverage':companion_coverage,'attempts':attempts,'cpu_s':process_time()-cpu,'wall_s':perf_counter()-start,
                  'executable':any(a['status']=='EXECUTED' for a in attempts)}
    return out
if __name__=='__main__':
    x=run();Path('/mnt/data/WF300_NINE_CLASS_CONTINUITY_CANARY.json').write_text(json.dumps(x,indent=2))
    print(json.dumps({k:{'executable':v['executable'],'attempts':v['attempts'][-1], 'cpu_s':round(v['cpu_s'],3)} for k,v in x.items()},indent=2))
