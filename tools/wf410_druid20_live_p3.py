"""WF410 PROCESS v2: fresh Druid L20 source-IR/P3 re-evaluation.

Reads unchanged canonical source & WF347 empirical context weights. Real combat IR
is rebuilt, not inferred from a stale WF407 JSON policy flag. Produces diagnostic
blockers; never alters weights, source DB, PROCESS or OVERALL PLAN.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from src.game.checkpoint_p3_smoke import fast_p3_smoke_for_policy
from src.game.data.forever.druid import build_source_slice
from src.game.model.ir import PolicyDefinition, PolicyRuleDefinition
from src.rulesets.forever.items.runtime_selection import catalogue_path


def main():
    root = Path(__file__).resolve().parents[1]
    previous_file = root / 'evidence/wf347/WF347_TOP5.json'
    previous = json.loads(previous_file.read_text())
    item_db_hash = hashlib.sha256(catalogue_path().read_bytes()).hexdigest()
    if item_db_hash != previous['catalogue_sha256']:
        raise ValueError('WF410_ITEM_SOURCE_CHANGED_FROM_MEASURED_WEIGHTS')
    if previous['level'] != 20 or previous['class_key'] != 'druid':
        raise ValueError('WF410_WEIGHT_CONTEXT_MISMATCH')
    ir = build_source_slice(20)
    claw = next(a for a in ir.actions if a.id == 'claw:20')
    policy = PolicyDefinition(id='source:claw:20', label='source-backed Claw test policy',
                              rules=(PolicyRuleDefinition(id='source:claw:20',action_id=claw.id),))
    start=time.perf_counter()
    result = fast_p3_smoke_for_policy(source_ir=ir, policy=policy,
              class_key='druid', level=20,
              weights=previous['stat_weights']['weights'],
              weight_evidence_kind='MEASURED_SOURCE_CONTEXT',
              required_level_policy='catalogue')
    result['wall_s'] = time.perf_counter()-start
    result['item_db_sha256'] = item_db_hash
    result['weights_file_sha256'] = hashlib.sha256(previous_file.read_bytes()).hexdigest()
    result['build_identity_sha256'] = previous['build_identity_sha256']
    result['feral_claw_source'] = {
        'damage_source_dps_stat_id': next(e.damage_source.dps_stat_id for e in claw.effects
             if e.effect_type == 'weapon_damage'),
        'damage_source_flat_dps': next(e.damage_source.flat_dps for e in claw.effects
             if e.effect_type == 'weapon_damage'),
        'weapon_damage_effect_is_not_equipped_weapon_dependency': not result['weapon_damage_dependent'],
    }
    path = root / 'evidence/wf410/WF410_DRUID20_PROCESS_V2_P3_LIVE.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    summary={key:val for key,val in result.items() if key not in ('slots',)}
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0 if result['p3_pass'] else 2

if __name__=='__main__':
    raise SystemExit(main())
