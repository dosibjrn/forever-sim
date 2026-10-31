"""Inspect the actual read-only legacy /decisions publication before P7."""
from pathlib import Path
from json import dump
from src.v2.decision_dashboard import build_decision_payload
from src.game.data.forever.source_checkpoint_p7_legacy import validate_p7_replays

ROOT=Path(__file__).resolve().parents[1]

def run():
    old=build_decision_payload(selected_level=30,backend_id='legacy')
    rows=[r for r in old.get('per_level_rows',{}).get('druid',[])
          if int(r.get('level',-1))==30]
    route_rows=old.get('route_rows',{}).get('druid',{}).get('30',{})
    decisions=[x for x in old.get('decisions',[])
               if str(x.get('identity',{}).get('class_name','')).lower()=='druid'
               and int(x.get('identity',{}).get('level',-1))==30]
    available=bool(rows or decisions or (route_rows.get('routes') and any(
        r.get('status')=='available' and any(
            int(v.get('level',-1))==30 for v in r.get('rows',[]))
        for r in route_rows['routes'].values())))
    if available:
        # Publication rows alone may still lack full source-legal gear/policy.
        raise ValueError('LEGACY_L30_PUBLISHED_VERIFY_FULL_BUILD_BEFORE_P7')
    cert=validate_p7_replays(legacy_stage=None,new_stage=None,
        legacy_publication_sha256=None,source_context_sha256=None,
        old_replay=None,new_replay=None,recovery_semantics_verification=None,
        checkpoint='druid:L30:unrestricted')
    result={'gate':'P7_LEGACY_HOLDOUT','checkpoint':'druid:L30:unrestricted',
        'legacy_backend':'legacy','legacy_levels':old.get('levels',[]),
        'legacy_endpoint_targets':sorted(old.get('endpoint_paths',{}).get('druid',{}).get('targets',{})),
        'druid_L30_per_level_rows':len(rows),'druid_L30_decision_records':len(decisions),
        'druid_L30_route_present':bool(route_rows),
        'required_legacy_full_build_available':False,
        'preflight_p7':cert,
        'runtime_recovery_gap':{
            'current_persistent_scorer':'src/v2/source_persistent_joint_finalists.py:evaluate_persistent_candidate calls recover_actor_to_full directly with Cat actor',
            'alternate_repeated_pulls':'src/game/multi_pull.py explicitly executes source post_combat mode exit and pre_combat re-entry',
            'missing':'opportunistic exit caster + cast HoT + re-enter cat + next mob with active HoT; no forced full mana/health per mob',
            'consequence':'L30 Cat/Resto winner and P3 stat weights cannot be accepted under gameplay-parity recovery'},
        'checkpoint_scoreboard':'1/148','status':'BLOCKED'}
    out=ROOT/'evidence/wf355/WF355_P7_LEGACY_PREFLIGHT.json'
    out.write_text(__import__('json').dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
    return result
if __name__=='__main__':
 result=run();print('P7',result['preflight_p7']['status'],result['preflight_p7']['reason'])
