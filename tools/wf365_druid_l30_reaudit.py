"""WF365: adversarial, unseeded historical-challenger re-audit on ONE sourced runtime.

Past results are never added to the candidate search; they are independent
held-out falsifiers of an asserted checkpoint winner.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.registry import build_game_ir_slice
from src.game.recovery_between_pulls import BetweenPullPolicy
from src.v2.source_persistent_joint_finalists import prepare_candidate, evaluate_persistent_candidate
from tools.wf321_ingest_control_observations import ingest as ingest_control

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SOURCE_SHA256 = '63c56b316c9ed6ba175c5f895870c372fb553fc78962fc8ee15c1e8cd5423244'


def compare_heldout(*, accepted: dict, challenger: dict, abs_tol_s: float = 1e-9) -> dict:
    """A demonstrated, legal faster holdout falsifies a claimed best winner.

    'Both P4 and P5 found the same value' does not override that falsifier.
    """
    if accepted.get('status') != 'COMPLETE' or challenger.get('status') != 'COMPLETE':
        raise ValueError('INCOMPLETE_HOLDOUT_REPLAY')
    for key in ('count', 'source_db_sha256', 'recovery_policy'):
        if accepted.get(key) != challenger.get(key):
            raise ValueError('INCOMPARABLE_HOLDOUT_'+key.upper())
    if accepted['count'] != 100:
        raise ValueError('REQUIRES_100_MOBS')
    earlier = float(accepted['mean_s_per_mob'])
    proposed = float(challenger['mean_s_per_mob'])
    if not (0 < earlier < float('inf') and 0 < proposed < float('inf')):
        raise ValueError('INVALID_SCORE')
    falsified = proposed + abs_tol_s < earlier
    return {'falsified': falsified,
            'claimed_s_per_mob': earlier,
            'heldout_s_per_mob': proposed,
            'absolute_gap_s_per_mob': earlier-proposed,
            'percent_slower_than_challenger': 100.0*(earlier/proposed-1.0),
            'same_source': True,
            'same_recovery': True,
            'same_100_mob_objective': True}


def run(output: Path | None = None) -> dict:
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    recovery = BetweenPullPolicy(.25,.10,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')
    source = ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
    with tempfile.TemporaryDirectory(prefix='wf365_l30_holdout_') as tmp:
        db=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f'file:{source.resolve()}?mode=ro',uri=True) as src, sqlite3.connect(db) as dst:
            src.backup(dst)
        ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        digest=hashlib.sha256(db.read_bytes()).hexdigest()
        if digest != EXPECTED_SOURCE_SHA256:
            raise ValueError('DIFFERENT_SOURCE_FOR_HOLDOUT: '+digest)
        with ability_source_scope(db):
            ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
            source_actions={a.id for a in ir.actions}
            source_bear_present= 'primal_bite:25' in source_actions and 'bear_form:5487' in source_actions
            if not source_bear_present:
                raise ValueError('MISSING_SOURCE_BEAR_PRIMAL_BITE_L30')
            stages={
                'claimed_wf360': json.loads((ROOT/'evidence/wf360/WF360_L30_P4_30S.json').read_text())['winner_stage'],
                'heldout_wf358': json.loads((ROOT/'evidence/wf358/WF358_L30_BEST_JOINT_P3_STAGE.json').read_text())}
            reports={}
            for label,stage in stages.items():
                candidate=prepare_candidate(class_key='druid',level=30,stage=stage,
                    source_ir=ir,strict_l2_item_effects=True)
                run_result=evaluate_persistent_candidate(candidate,level=30,mobs=100,
                    recovery_policy=recovery,max_wall_s=15,max_cpu_s=15,max_total_events=200000)
                reports[label]={k:run_result.get(k) for k in ('status','count','mean_s_per_mob',
                    'combat_s','recovery_s','maintenance_s','events')}
                reports[label]['source_db_sha256']=digest
                reports[label]['recovery_policy']=vars(recovery)
    verdict=compare_heldout(accepted=reports['claimed_wf360'],challenger=reports['heldout_wf358'])
    if not verdict['falsified']:
        raise AssertionError('EXPECTED_REPORTED_REGRESSION_NOT_REPRODUCED')
    report={'schema':'wf365_druid_l30_historical_challenger_replay_v1',
            'checkpoint':'druid:L30:unrestricted','source_db_sha256':digest,
            'replays':reports,'comparison':verdict,
            'bear_l30_primal_bite_source_action':source_bear_present,
            'accepted_checkpoints_after_revocation':'1/148',
            'L30_status':'REVOKED','P4_status':'FAIL_WORSE_THAN_LEGAL_PREVIOUS_CANDIDATE',
            'P5_status':'FAIL_WORSE_THAN_LEGAL_PREVIOUS_CANDIDATE',
            'P6_status':'INSUFFICIENT_HISTORICAL_HOLDOUT',
            'holdout_used_as_search_seed':False,
            'limitations':['Neither replay models 20-yard-spaced multi-enemy pulls.',
               'Bear Primal Bite exists in IR but this audit has not certified a Bear 100-mob winner.',
               'Does not assert a global optimum.']}
    if output is not None:
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    return report

if __name__=='__main__':
    out=ROOT/'evidence/wf365/WF365_DRUID_L30_REVOCATION.json'
    result=run(out)
    print(json.dumps({k:result[k] for k in ('checkpoint','L30_status','accepted_checkpoints_after_revocation')},sort_keys=True))
