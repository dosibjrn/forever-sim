"""WF412: reconstruct independently published WF347 winning *full build* and
measure four missing P3 weights with a paid 100-mob recovery-policy search.

This does not use WF347 as a seed for P4/P5. It is a P3 witness for exactly
that historical, source-discovered build. Do not promote P4/P5/P6/P7 here.
"""
from __future__ import annotations
import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from time import monotonic

from src.game.checkpoint_p3_smoke import fast_p3_smoke_for_policy
from src.rulesets.forever.items.runtime_selection import (
    available_items, catalogue_path, effective_level, item_payload,
)
from src.rulesets.forever.items.source_equipment_semantics import validate_equipped_item_ids
from src.v2.source_bounded_joint_frontier import _recovery_variants
from src.v2.source_persistent_joint_finalists import prepare_candidate, evaluate_persistent_candidate
from src.v2.source_reoptimized_stat_sensitivity import reoptimized_stat_sensitivity

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/wf412/WF412_DRUID_L20_P3_REOPTIMIZED_SOURCE_WINNER.json'


def recovered_wf347_winner():
    prior=json.loads((ROOT/'evidence/wf347/WF347_P4_STRICT.json').read_text())
    winner=prior['winner']
    stage=copy.deepcopy(json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage'])
    stage['allocation']=winner['talents']
    by_id={int(i.item_id):i for i in available_items('druid',20,required_level_policy='observed')}
    missing={int(x) for x in winner['gear'].values()}-set(by_id)
    if missing:raise ValueError('WF347_WINNER_GEAR_NOT_IN_CURRENT_SOURCE:'+str(missing))
    validate_equipped_item_ids(winner['gear'].values())
    slots={slot:item_payload(by_id[item_id],display_slot=slot,effective_level=effective_level(by_id[item_id]))
           for slot,item_id in winner['gear'].items()}
    aggregate={}
    for item in slots.values():
        for axis in ('strength','agility','stamina','intellect','spirit','attack_power',
                     'spell_power','healing','mp5','armor','weapon_dps','wand_dps'):
            aggregate[axis]=aggregate.get(axis,0.)+float(item.get(axis,0.))
    gear=stage['gear_policy_result']['winner']['gear']
    gear.update(slots=slots,aggregate_stats=aggregate,item_count=len(slots))
    policy=stage['gear_policy_result']['winner']['winner']
    policy.update(prefix=winner['opening'],fallback=winner['fallback'],
                  guarded_action=None,guarded_conditions=[])
    candidate=prepare_candidate(class_key='druid',level=20,stage=stage,
                                strict_l2_item_effects=True)
    return candidate,stage,prior


def run():
    start=monotonic()
    candidate,stage,prior=recovered_wf347_winner()
    old_result=evaluate_persistent_candidate(candidate,level=20,mobs=100,max_wall_s=12.)
    prior_best=float(prior['winner']['actual_100mob_s_per_mob'])
    if old_result.get('status')!='COMPLETE' or abs(float(old_result['mean_s_per_mob'])-prior_best)>1e-9:
        raise ValueError('HISTORICAL_WF347_FULL_100MOB_SCORE_NOT_REPRODUCIBLE')
    legacy_weights=json.loads((ROOT/'evidence/wf347/WF347_TOP5.json').read_text())
    if hashlib.sha256(catalogue_path().read_bytes()).hexdigest()!=legacy_weights['catalogue_sha256']:
        raise ValueError('WF347_CATALOGUE_CHANGED')
    policies=_recovery_variants(candidate.ir,stage,2)
    template=next((policy for _,policy in policies if policy is not None),None)
    if template is None:raise ValueError('NO_REENTRY_SOURCE_RECOVERY_POLICY')
    thresholds=(replace(template,health_fraction=.25,mana_fraction=.10),
                replace(template,health_fraction=.50,mana_fraction=.10))
    measures={}
    for axis,delta in [('stamina',20.),('spirit',20.),('mp5',10.),('spell_power',30.)]:
        measures[axis]=reoptimized_stat_sensitivity(candidate=candidate,stat=axis,
                     delta=delta,level=20,recovery_policies=thresholds,
                     mobs=100,max_wall_s_per_eval=12.)
        if measures[axis]['status']!='COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE' or not measures[axis]['positive']:
            raise ValueError('P3_REOPTIMIZED_STAT_NOT_POSITIVE:'+axis)
    weights=copy.deepcopy(legacy_weights['stat_weights']['weights'])
    for axis,row in measures.items():
        weights[axis]={'status':'MEASURED_100MOB_REOPTIMIZED_RECOVERY',
                       'weight_s_saved_per_mob_per_unit':row['weight_s_saved_per_mob_per_unit'],
                       'delta':row['delta'], 'before_score':row['best']['before']['mean_s_per_mob'],
                       'after_score':row['best']['after']['mean_s_per_mob'],
                       'source':'WF412_PAID_100MOB_SAME_WF347_FULL_BUILD',
                       'search_scope':'two_source_legal_recovery_threshold_policies'}
    p3=fast_p3_smoke_for_policy(source_ir=candidate.ir,policy=candidate.policy,
                               class_key='druid',level=20,weights=weights,
                               weight_evidence_kind='MEASURED_SOURCE_CONTEXT',
                               required_level_policy='catalogue')
    final={'release':'WF412','checkpoint':'druid:L20:unrestricted',
        'p3_status':'PASS' if p3['p3_pass'] else 'FAIL',
        'p3_report':p3,'reoptimized_evidence':measures,
        'weight_certificate':weights,
        'old_wf347_fixed_full_recovery_100mob_s_per_mob':prior_best,
        'replayed_wf347_fixed_full_recovery_100mob_s_per_mob':old_result['mean_s_per_mob'],
        'replayed_wf347_events':old_result['events'],
        'historical_events':prior['winner']['actual_100mob_events'],
        'replayed_wf347_talents':stage['allocation'],
        'replayed_wf347_gear_ids':{k:int(v['item_id']) for k,v in stage['gear_policy_result']['winner']['gear']['slots'].items()},
        'replayed_wf347_policy_action_ids':[r.action_id for r in candidate.policy.rules],
        'p1_p2_status':'NOT_REVALIDATED_IN_WF412',
        'p4_p5_p6_p7_status':'NOT_REVALIDATED_IN_WF412',
        'accepted_checkpoint':False,
        'source_catalogue_sha256':legacy_weights['catalogue_sha256'],
        'wf347_weight_source_sha256':hashlib.sha256((ROOT/'evidence/wf347/WF347_TOP5.json').read_bytes()).hexdigest(),
        'wall_s':monotonic()-start,
        'notes':['P3 test is fast; paid reranking weights are cached evidence.',
                 'New four weights come from exact item/talent/policy WF347 winner, with recovery re-selection.',
                 'Older remaining weights were sourced and measured on this same WF347 winning build.',
                 'WF347 historical event count differs by one event under current runtime, while objective score matches to 1e-9.',
                 'This is not a new independent cold P4/P5 search, no scoreboard increment.']}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(final,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'p3_status':final['p3_status'],'blockers':p3['blockers'],
        'item_tests':p3['tested_item_count'],'slots':p3['slot_count'],
        'stats':{axis:round(row['weight_s_saved_per_mob_per_unit'],9)
                 for axis,row in measures.items()},'wall_s':final['wall_s']},sort_keys=True))
    return 0 if p3['p3_pass'] else 2

if __name__=='__main__':
    raise SystemExit(run())
