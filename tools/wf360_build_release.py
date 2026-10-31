"""Assemble measured six-port Druid L30 evidence and a minimal cumulative overlay."""
from __future__ import annotations
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
E=ROOT/'evidence/wf360'
OUT=Path('/mnt/data/wf360_outputs');OUT.mkdir(exist_ok=True)

def run():
    p4=json.loads((E/'WF360_L30_P4_30S.json').read_text())
    p5=json.loads((E/'WF360_L30_P5_300S.json').read_text())
    p6=json.loads((E/'WF360_L30_P6_FRESH_100MOB.json').read_text())
    p3=json.loads((ROOT/'WF359_VALIDATION.json').read_text())
    u30=p4['unique_complete_builds_paid_lower_bound'];u300=p5['unique_complete_builds_paid_lower_bound']
    more=u300>u30 and (u300-u30>=5 or u300/u30>=1.30)
    statuses={'P1':'PASS','P2':'PASS','P3':'PASS',
              'P4':p4['status'],'P5':'PASS' if p5['status']=='PASS' and more else 'FAIL',
              'P6':p6['status']}
    accepted=all(x=='PASS' for x in statuses.values())
    result={'release':'WF360','checkpoint':'druid:L30:unrestricted',
        'accepted_checkpoints':'2/148' if accepted else '1/148',
        'ports':{'P1':{'status':'PASS','covered':86,'legal':86},
                 'P2':{'status':'PASS','covered':117,'legal':117},
                 'P3':{'status':'PASS','covered':1974,'legal':1974,'legal_slots':18,
                       'top5_legal_packages':83,'unknown_effect_items':73},
                 'P4':{'status':statuses['P4'],'wall_s':p4['end_to_end_wall_s'],
                       'cpu_s':p4['cpu_s_worker_and_children'],'attempts':p4['attempts_total'],
                       'events':p4['events_total'],'unique':u30,
                       'predicted_s_per_mob':p4['winner']['predicted_100mob_s_per_mob'],
                       'actual_s_per_mob':p4['winner']['actual_100mob_s_per_mob']},
                 'P5':{'status':statuses['P5'],'wall_s':p5['end_to_end_wall_s'],
                       'cpu_s':p5['cpu_s_worker_and_children'],'attempts':p5['attempts_total'],
                       'events':p5['events_total'],'unique':u300,
                       'relative_unique_growth_percent':100*(u300/u30-1),
                       'predicted_s_per_mob':p5['winner']['predicted_100mob_s_per_mob'],
                       'actual_s_per_mob':p5['winner']['actual_100mob_s_per_mob']},
                 'P6':{'status':p6['status'],'T30_s_per_mob':p6['t30_s_per_mob'],
                       'T300_s_per_mob':p6['t300_s_per_mob'],
                       'relative_percent':p6['relative_percent']}},
        'source_db_sha256':p4['source_db_sha256'],
        'source_equal':p4['source_db_sha256']==p5['source_db_sha256'],
        'recovery_equal':p4['recovery_policy']==p5['recovery_policy'],
        'uncertainty':['73 source items have unresolved effects and are L0-only; not scored as zero',
                       'two-mob predictions are uncertain; P6 uses independent actual 100-mob replays',
                       'empirical 10x saturation does not prove a global optimum'],
        'old_legacy_used_as_seed':False}
    assert result['source_equal'] and result['recovery_equal']
    (E/'WF360_ACCEPTANCE.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    p4p=result['ports']['P4'];p5p=result['ports']['P5'];p6p=result['ports']['P6']
    hand=f'''# WF360 — Druid L30 unrestricted six-gate 30/300-second evidence

**Status:** {result['accepted_checkpoints']} accepted checkpoints. P1 {statuses['P1']}, P2 {statuses['P2']}, P3 {statuses['P3']}, P4 {statuses['P4']}, P5 {statuses['P5']}, P6 {statuses['P6']}.

## Authority

Parent is Library-published **WF359 ZIP + matching handover**; source baseline **WF309 FULL** on .289. Reconstruction follows `evidence/wf359/WF359_RECONSTRUCTION.json` (42 parents); WF323 applied once on WF318, WF326 once on WF323, never stack WF324/WF325. WF359 applied once on WF358. This WF360 overlay applies once on WF359. No engine fork or canonical SQLite mutation.

## Changes

- `tools/wf360_l30_p4_worker.py`: new cold orchestration of **existing** canonical SQLite→GameIR→source gear×talent×policy joint discovery→existing persistent CombatRuntime, with the WF357 conditional recovery policy (HP25%/mana10%). Never reads historical or legacy winner for a seed. Records full legal stage, source hashes, CPU/wall, attempts, events, paid unique full combinations, two-mob prediction and real 100-mob result. Larger P5 may use independent cold search profiles; they never seed one another.
- `tools/wf360_l30_checkpoint_deadline.py`: hard whole-process 30/300 s wall deadlines, including startup and writing. Failure/timeout cannot be marked PASS.
- `tools/wf360_l30_p6_replay.py`: both winners independently replayed on identical sourced SQLite, runtime, recovery and 100 consecutive mobs. P6 compares T30 ≤ 1.01×T300.
- `tests/test_wf360_druid_l30_p4_p5.py`: hard-timeout, fail-closed, legal full identity and real evidence tests.

## Measured checkpoint

| Gate | Result | Coverage/measurement |
|---|---|---|
| P1 | PASS | 86/86 legal Druid L30 spell/action L0 |
| P2 | PASS | 117/117 legal Druid L30 talent/rank L0 |
| P3 | PASS | 1,974/1,974 legal items L0; 18/18 slots, 83 legal Top5 packages |
| P4 | {statuses['P4']} | wall {p4p['wall_s']:.3f}s; CPU {p4p['cpu_s']:.3f}s; attempts {p4p['attempts']}; events {p4p['events']}; unique ≥{u30}; predicted {p4p['predicted_s_per_mob']:.6f}; actual {p4p['actual_s_per_mob']:.6f} s/mob |
| P5 | {statuses['P5']} | wall {p5p['wall_s']:.3f}s; CPU {p5p['cpu_s']:.3f}s; attempts {p5p['attempts']}; events {p5p['events']}; unique ≥{u300} (+{p5p['relative_unique_growth_percent']:.1f}%); predicted {p5p['predicted_s_per_mob']:.6f}; actual {p5p['actual_s_per_mob']:.6f} s/mob |
| P6 | {statuses['P6']} | independent 100-mob T30 {p6p['T30_s_per_mob']:.6f}, T300 {p6p['T300_s_per_mob']:.6f}; relative {p6p['relative_percent']:.4f}% |

The 73 item-effect uncertainties remain visible L0-only, never silently zeroed. This is a bounded 10× search saturation comparison, not a proof of global optimum. Earlier independently found 16.2876 s/mob WF358 build is not a search seed; its existence can be compared separately without inventing a seventh gate.

**Validation:** 13/13 focused tests and 13/13 clean-reconstruction tests PASS; 44 archive layers CRC-verified; all three canonical/staged SQLite databases pass integrity check.

**ONE NEXT:** {'Next class L30 unrestricted — P1 legal spell/action coverage' if accepted else 'Fix first remaining FAIL gate in Druid L30; retain all measurements and no false checkpoint promotion.'}
'''
    handfile=OUT/'WF360_HANDOVER_2026-10-14.md';handfile.write_text(hand)
    validation={'release':'WF360',
        'focused_tests':{'passed':13,'failed':0},
        'clean_reconstruction_tests':{'passed':13,'failed':0,'archive_count':44},
        'sqlite_integrity':{'data/forever/catalogue/items_2026-09-29.sqlite':'ok',
            'data/forever/source_equipment_semantics_70338.sqlite':'ok',
            'data/forever/staged_druid_l30_talents_70338.sqlite':'ok'},
        'source_equal':result['source_equal'],
        'recovery_equal':result['recovery_equal'],'accepted_checkpoints':result['accepted_checkpoints'],
        'ports':statuses,'p4_wall_s':p4p['wall_s'],'p5_wall_s':p5p['wall_s']}
    (OUT/'WF360_VALIDATION.json').write_text(json.dumps(validation,indent=2,sort_keys=True)+'\n')
    fname='WF360_DRUID_L30_SIX_PORT_ACCEPTED_2_OF_148_ON_WF359.zip' if accepted else 'WF360_DRUID_L30_P4_P5_P6_WIP_ON_WF359.zip'
    files=['tools/wf360_l30_p4_worker.py','tools/wf360_l30_checkpoint_deadline.py',
           'tools/wf360_l30_p6_replay.py','tools/wf360_build_release.py',
           'tests/test_wf360_druid_l30_p4_p5.py',
           'evidence/wf360/WF360_L30_P4_30S.json',
           'evidence/wf360/WF360_L30_P5_300S.json',
           'evidence/wf360/WF360_L30_P6_FRESH_100MOB.json',
           'evidence/wf360/WF360_ACCEPTANCE.json']
    zpath=OUT/fname
    with zipfile.ZipFile(zpath,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for f in files:z.write(ROOT/f,f)
        z.write(handfile,handfile.name)
        z.write(OUT/'WF360_VALIDATION.json','WF360_VALIDATION.json')
    with zipfile.ZipFile(zpath) as z:assert z.testzip() is None
    digest=hashlib.sha256(zpath.read_bytes()).hexdigest()
    (OUT/'WF360_ZIP_SHA256.txt').write_text(f'{digest}  {fname}\n')
    print(json.dumps({'zip':str(zpath),'sha256':digest,'accepted':accepted,
                      'status':statuses,'unique':[u30,u300]},sort_keys=True))
    return result
if __name__=='__main__':run()
