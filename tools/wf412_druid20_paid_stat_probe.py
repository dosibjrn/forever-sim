"""WF412 paid Druid L20 diagnostic, no checkpoint acceptance promotion.

Uses an actual prior *source-discovered* checkpoint stage (WF325), no hand-picked
item IDs or fabricated coefficients. Re-optimizes recovery for each stat probe
via common source CombatRuntime. Previous WF347 P3 weight context is distinct:
results cannot simply be spliced into its weight certificate.
"""
from __future__ import annotations
import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path

from src.game.gear import _replace_equipped_weapon_dps
from src.game.checkpoint_p3_smoke import policy_uses_equipped_weapon_damage, policy_uses_equipped_weapon_mean_hit
from src.game.recovery_between_pulls import BetweenPullPolicy
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.v2.source_reoptimized_stat_sensitivity import reoptimized_stat_sensitivity
from src.rulesets.forever.items.runtime_selection import catalogue_path

ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json'
OUT=ROOT/'evidence/wf412/WF412_DRUID20_PAID_REOPTIMIZED_STAT_PROBES.json'


def main():
    started=time.monotonic()
    stage=json.loads(STAGE.read_text())['finalist']['winner']['stage']
    c=prepare_candidate(class_key='druid',level=20,stage=stage)
    # The forms, exit and reentry IDs are read from the *same* source policy
    # adapter used by P4, rather than hardcoded in the sensitivity algorithm.
    from src.v2.source_bounded_joint_frontier import _recovery_variants
    recovery_candidates=_recovery_variants(c.ir,stage,2)
    template=next((r for _,r in recovery_candidates if r is not None),None)
    if template is None:
        raise ValueError('NO_SOURCE_LEGAL_CONDITIONAL_RECOVERY_FRONTIER')
    recovery=(replace(template,health_fraction=.25,mana_fraction=.10),
              replace(template,health_fraction=.50,mana_fraction=.10))
    # Audit what the optimizer actually equipped, versus the naked anchor.
    equipped=stage['gear_policy_result']['winner']['gear']['slots']['weapon']
    weapon_dps=float(equipped['weapon_dps'])
    claw=next(a for a in c.ir.actions if a.family_key=='claw')
    equipped_claw=next(e.damage_source.flat_dps for e in claw.effects
                       if e.effect_type=='weapon_damage')
    assert abs(weapon_dps-equipped_claw) < 1e-8
    baseline=evaluate_persistent_candidate(c,level=20,mobs=100,max_wall_s=12.)
    exchanged_ir=_replace_equipped_weapon_dps(c.ir,weapon_dps+10.)
    swapped=evaluate_persistent_candidate(replace(c,ir=exchanged_ir),
                                         level=20,mobs=100,max_wall_s=12.)
    if baseline['status']!='COMPLETE' or swapped['status']!='COMPLETE':
        raise ValueError('WEAPON_SWAP_PAID_100MOB_INCOMPLETE')
    weapon_derivative=(float(baseline['mean_s_per_mob'])-float(swapped['mean_s_per_mob']))/10.
    if weapon_derivative<=0:
        raise ValueError('SOURCE_EQUIPPED_FERAL_WEAPON_DPS_NOT_EFFECTIVE')
    stats={}
    for stat,delta in [('stamina',20.),('spirit',20.),('mp5',10.),('spell_power',30.)]:
        stats[stat]=reoptimized_stat_sensitivity(candidate=c,stat=stat,delta=delta,
                   level=20,recovery_policies=recovery,mobs=100,max_wall_s_per_eval=12.)
    # Paid sensitivity in this build does not certify a prior different build.
    result={
       'release':'WF412','status':'SOURCE_PAID_DIAGNOSTIC_NOT_P3_ACCEPTED',
       'source_stage':'wf325_actual_source_discovered_checkpoint_stage',
       'stage_sha256':hashlib.sha256(STAGE.read_bytes()).hexdigest(),
       'catalogue_sha256':hashlib.sha256(catalogue_path().read_bytes()).hexdigest(),
       'sample_build_allocation':stage['allocation'],
       'weapon':{'observed_item_id':equipped['item_id'],
                 'observed_weapon_dps':weapon_dps,'claw_runtime_flat_dps':equipped_claw,
                 'positive_equipped_weapon_dps_dependence':policy_uses_equipped_weapon_damage(c.ir,c.policy),
                 'equipped_mean_hit_dependence':policy_uses_equipped_weapon_mean_hit(c.ir,c.policy),
                 'plus_10_dps_100mob':{'before':baseline['mean_s_per_mob'],
                                      'after':swapped['mean_s_per_mob'],
                                      'weight_s_saved_per_mob_per_dps':weapon_derivative,
                                      'before_events':baseline['events'],'after_events':swapped['events']}},
       'recovery_sensitivity':stats,
       'all_four_positive':all(r['status']=='COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE'
                               and r['positive'] for r in stats.values()),
       'measured_wall_s':time.monotonic()-started,
       'checkpoint_accepted':False,
       'notes':['WF325 and WF347 gear/policy builds differ; this proof must NOT be pasted into WF347 stat-weight vector.',
                'P3 uses a fast separately cached scoring test; expensive paid sensitivity is generated only on demand.',
                'No global optimum guarantee; policy frontier is exactly the recorded two source-legal recoveries.'],
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':result['status'],'all_four_positive':result['all_four_positive'],
          'weapon_dps_weight':weapon_derivative,
          'stat_weights':{k:round(v['weight_s_saved_per_mob_per_unit'],9) for k,v in stats.items()},
          'elapsed_wall_s':result['measured_wall_s']},sort_keys=True))
    return 0 if result['all_four_positive'] else 2

if __name__=='__main__':
    raise SystemExit(main())
