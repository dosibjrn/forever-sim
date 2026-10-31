"""Recalculate WF346 Top5 from the unchanged measured 100-mob Cat build.

Zero for elemental resistances / penetration is justified ONLY for the
physical Cat/Claw + physical-incoming checkpoint scenario, not all builds.
"""
from pathlib import Path
import json
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p3_weights import ranked_top_items,verify_weighted_ranking
from src.rulesets.forever.items.source_numeric_extras import NUMERIC_EXTRA_TO_ACTOR_STAT

ROOT=Path(__file__).resolve().parents[1]

def run():
    base=json.loads((ROOT/'evidence/wf345/WF345_SOURCE_DISPLAY_PERCENT_EQUIPMENT_TOP5.json').read_text())
    stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    source=build_game_ir_slice(class_key='druid',level=20)
    policy=stage['gear_policy_result']['winner']['winner']
    assert all(x.school=='physical' for x in source.incoming_attacks)
    assert policy['fallback'].split(':')[0]=='claw'
    assert all(x.split(':')[0]=='cat_form' for x in policy['prefix'])
    weights=json.loads(json.dumps(base['stat_weights']))
    # Only conditional magic stats can be zero for the pinned physical target.
    # A later schema extension (e.g. HP5) must never inherit this zero.
    for key in sorted(set(NUMERIC_EXTRA_TO_ACTOR_STAT.values()) - {'health_regeneration_per_5s'}):
        weights['weights'][key]={
            'status':'CONTEXTUAL_ZERO_PHYSICAL_CAT_CLAW_MELEE_TARGET_ONLY',
            'weight_s_saved_per_mob_per_unit':0.,
            'scope':'WF325 pinned Cat Form -> Claw policy; ordinary physical-only incoming enemy; no sourced target school resistance',
            'reason':'No outgoing magical damage affected by penetration, no incoming magical damage mitigated by school resistance',
            'not_a_global_item_stat_weight':True,
            'on_build_or_enemy_change':'remeasure_using_100mob_runtime',
        }
    report=ranked_top_items(class_key='druid',level=20,stage=stage,weight_evidence=weights,top_n=5)
    verify_weighted_ranking(report,class_key='druid',level=20,stage=stage)
    report['source_item_conversion']=base.get('source_item_conversion',{})
    report['source_item_conversion']['TBC_level_scaling_used']=False
    report['p3_user_contract_pass']=False
    report['p3_user_contract_blockers']=['34 unresolved source item effects','partial Defense and proc coverage','build-dependent ranking uncertain for other enemy contexts']
    report['paid_gear_proposal_count']=base['paid_gear_proposal_count']
    report['paid_gear_slot_coverage']=base['paid_gear_slot_coverage']
    report['WF346_numeric_extra_bridge']={
        'runtime_axes':sorted(set(NUMERIC_EXTRA_TO_ACTOR_STAT.values())),
        'source_fields':dict(NUMERIC_EXTRA_TO_ACTOR_STAT),
        'physical_melee_reference_contextually_zero':True,
        'known_nonzero_on_magic_attack_context':True,
    }
    output=ROOT/'evidence/wf346';output.mkdir(parents=True,exist_ok=True)
    (output/'WF346_TOP5.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
    readable=['# WF346 Druid L20 known Cat/Claw build: Top 5 per slot',
        '', '1171 legal items, 18 slots. Source numeric elemental resistances and spell penetration are executed generically.',
        'In this physical-only Cat/Claw reference their local weight is exactly zero; NOT a global zero weight.',
        f"Unresolved item effects: {sum(bool(x['unresolved_effects']) for x in __import__('src.game.data.forever.source_checkpoint_p3',fromlist=['checkpoint_item_l0']).checkpoint_item_l0(class_key='druid',level=20)['source_items'])}.",
        '', '## Build-specific stat weights', '', '| Stat | s/mob per source stat unit | status |','|---|---:|---|']
    for stat,w in sorted(weights['weights'].items()):
        readable.append(f"| {stat} | {w.get('weight_s_saved_per_mob_per_unit')} | {w['status']} |")
    for slot,data in sorted(report['slots'].items()):
        readable.extend(['',f'## {slot}', '', '| # | Item | ID | Known weight score | Uncertain? |','|---:|---|---:|---:|---|'])
        for idx,item in enumerate(data['weighted_top'],1):
            readable.append(f"| {idx} | {item['name']} | {item['item_id']} | {item['known_score_s_saved_per_mob']:.6f} | {bool(item['unknown_effects'])} |")
            readable.append('  - '+', '.join(f"{c['stat']}: {c['amount']} × {c['weight']:.6g} = {c['contribution_s_saved_per_mob']:.6g}"
                     for c in item['contributions']))
    (output/'WF346_TOP5.md').write_text('\n'.join(readable))
    return {'legal_items':report['total_legal_items'],'slots':len(report['slots']),
        'item_unresolved':sum(bool(x['unresolved_effects']) for x in __import__('src.game.data.forever.source_checkpoint_p3',fromlist=['checkpoint_item_l0']).checkpoint_item_l0(class_key='druid',level=20)['source_items']),
        'top5_incomplete':report['unknown_item_count']}

if __name__=='__main__':print(json.dumps(run(),indent=2))
