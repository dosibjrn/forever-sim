import json
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_policy_search import synthesize_source_policies
from src.v2.source_action_coverage import audit_source_action_coverage

cases=[]
for cls,level,mode in [('druid',20,'cat'),('mage',10,None),('priest',10,None)]:
    ir=build_game_ir_slice(class_key=cls,level=level)
    envelope=synthesize_source_policies(ir,level=level,mode_id=mode,
        include_auto_resource_fallback=bool(mode),max_policies=1024)
    audit=audit_source_action_coverage(ir,level=level,search_envelopes=(envelope,))
    cases.append({'class':cls,'level':level,'mode':mode,'candidate_count':envelope['candidate_count'],
        'eligible_actions':list(envelope['eligible_buttons']),
        'audit_status':audit['status'],'audit_blocker_count':audit['blocker_count'],
        'unexecutable_effects':sum(len(r['unexecutable_effects']) for r in audit['actions']),
        'complete_optimizer':audit['complete_optimizer']})
print(json.dumps({'version':'0.11.48.207','cases':cases},indent=2))
