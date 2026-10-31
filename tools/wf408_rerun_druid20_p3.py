"""Rerun merged WF407 P3 on actual production item scoring; no fake PASS."""
from __future__ import annotations
import json,hashlib,time
from pathlib import Path
from src.game.checkpoint_p3_smoke import fast_p3_smoke
from src.rulesets.forever.items.runtime_selection import catalogue_path


def main():
    root=Path(__file__).resolve().parents[1]
    ancestor=json.loads((root/'evidence/wf407/WF407_DRUID_L20_FAST_P3_LIVE.json').read_text())
    previous=json.loads((root/'evidence/wf347/WF347_TOP5.json').read_text())
    pinned=hashlib.sha256(catalogue_path().read_bytes()).hexdigest()
    assert pinned==previous['catalogue_sha256']==ancestor['item_db_sha256'], 'P3_STALE_SOURCE_CONTEXT'
    policy=ancestor['source_policy']
    assert policy['weapon_damage_effect_derived_from_ir'] is True
    assert policy['action_ids'] and policy['source_ir_id'] and policy['policy_id']
    t=time.monotonic()
    result=fast_p3_smoke(class_key='druid',level=20,
        weights=previous['stat_weights']['weights'],
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT',
        weapon_damage_dependent=ancestor['weapon_damage_dependent'],
        required_level_policy='catalogue')
    result['source_policy']=policy
    result['source_policy_attestation_inherited_from']='WF407_DRUID_L20_FAST_P3_LIVE.json'
    result['item_db_sha256']=pinned
    result['weight_evidence_sha256']=hashlib.sha256((root/'evidence/wf347/WF347_TOP5.json').read_bytes()).hexdigest()
    result['build_identity_sha256']=previous['build_identity_sha256']
    result['wall_s']=time.monotonic()-t
    path=root/'evidence/wf408/WF408_DRUID20_MERGED_P3_LIVE.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='slots'},indent=2))
    return 0 if result['p3_pass'] else 2

if __name__=='__main__':raise SystemExit(main())
