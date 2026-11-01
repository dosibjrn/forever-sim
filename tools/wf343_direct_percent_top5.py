"""Rebuild source-backed item stat weights and all slot Top5 after TBC removal."""
from __future__ import annotations
import os,json,sqlite3,tempfile
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.game.data.forever.source_checkpoint_p3_weights import (
    measured_stat_weights, ranked_top_items, verify_weighted_ranking)
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.v2.source_persistent_slot_search import _source_slot_proposals,_gear_replace
from src.rulesets.forever.items.runtime_selection import available_items
from src.game.data.forever.source_checkpoint_p3_ratings import source_item_stat_to_combat
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1]

def run():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    prior=json.loads((ROOT/'evidence/wf341/WF341_DRUID_L20_CHANCE_SENSITIVITY_TOP5.json').read_text())['stat_weights']
    stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    with tempfile.TemporaryDirectory(prefix='wf343_src_') as tmp:
        path=Path(tmp)/'abilities.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as base,sqlite3.connect(path) as copy:base.backup(copy)
        ingest_observations(path,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(path,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(path):
            candidate=prepare_candidate(class_key='druid',level=20,stage=stage)
            weights=measured_stat_weights(candidate=candidate,class_key='druid',level=20,mobs=100,prior_weights=prior)
            report=ranked_top_items(class_key='druid',level=20,stage=stage,weight_evidence=weights,top_n=5)
            verify_weighted_ranking(report,class_key='druid',level=20,stage=stage)
            base=evaluate_persistent_candidate(candidate,level=20,mobs=100,max_total_events=250000)
            by_id={int(r.item_id):r for r in available_items('druid',20,required_level_policy='observed')}
            spot={}
            for item_id,slot in [(7348,'hands'),(12985,'ring1')]:
                item=by_id[item_id]
                modified=deepcopy(stage)
                modified['gear_policy_result']['winner']['gear']=_gear_replace(
                    modified['gear_policy_result']['winner']['gear'],slot,item)
                scored=prepare_candidate(class_key='druid',level=20,stage=modified)
                out=evaluate_persistent_candidate(scored,level=20,mobs=100,max_total_events=250000)
                info=scored.ir.provenance['source_equipped_item_combat_stats']
                spot[str(item_id)]={'item_name':item.name,'slot':slot,'status':out['status'],
                    'measured_100mob_s_per_mob':out.get('mean_s_per_mob'),
                    'displayed_crit_pct':info['displayed_crit_pct'],
                    'displayed_hit_pct':info['displayed_hit_pct'],
                    'defense_skill':info['defense_skill'],'full_L2_valid':info['complete_Forever_L2']}
            proposals,counts=_source_slot_proposals(class_key='druid',level=20,
                base=stage['gear_policy_result']['winner']['gear'],weighted_p3_report=report,
                seed_stage=stage,per_slot=2,max_proposals=45)
    report['p3_user_contract_pass']=False
    report['p3_user_contract_blockers']=['defense_parry_block_crit_suppression_incomplete',
        'proc_relic_special_effects_incomplete','spell_crit_scope_and_display_sources_need_full_client_confirmation']
    report['source_item_conversion']={'raw_crit_per_display_pct':14,
        'raw_hit_per_display_pct':10,'raw_dodge_per_display_pct':12,
        'defense_raw_unit':'defense_skill', 'TBC_level_scaling_used':False,
        'observed_example_sources':{kind:source_item_stat_to_combat(kind,1,level=20)['source_urls']
                                    for kind in ('crit','hit','dodge','defense')}}
    report['reference_replay_100mob']=base
    report['selected_item_executor_probes']=spot
    report['paid_gear_proposal_count']=len(proposals)
    report['paid_gear_slot_coverage']=counts
    output=ROOT/'evidence/wf343';output.mkdir(parents=True,exist_ok=True)
    (output/'WF343_SOURCE_DISPLAY_PERCENT_TOP5.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str))
    readable=['# Druid L20 — source display % stat weights & Top 5 per slot',
        '', '**Status: P3 FAIL** (remaining defense channels, procs/relics and other effects).',
        '',f"Items: {report['total_legal_items']}; slots: {len(report['slots'])}; uncertain items: {report['unknown_item_count']}.",
        '', 'Raw SQLite values: crit 14 = +1%; hit 10 = +1%; dodge 12 = +1%; defense is skill. No TBC scaling.',
        '', '## Build-specific weights',
        '', 'Units: seconds saved per mob per ONE RAW SQLITE STAT unit (except weapon-speed as stated).',
        '', '| Stat | weight | source/status |','|---|---:|---|']
    for stat,row in sorted(weights['weights'].items()):
        value=row.get('weight_s_saved_per_mob_per_unit')
        readable.append(f"| {stat} | {value if value is not None else 'UNKNOWN'} | {row['status']} |")
    for slot,section in report['slots'].items():
        readable.extend(['',f'## {slot} — weighted Top 5','', '| # | Item | Item ID | Known score | Uncertainty |','|---:|---|---:|---:|---|'])
        for idx,item in enumerate(section['weighted_top'],1):
            missing=', '.join(x['reason'] for x in item['unknown_effects']) or 'none'
            readable.append(f"| {idx} | {item['name']} | {item['item_id']} | {item['known_score_s_saved_per_mob']:.6f} | {missing} |")
            details=', '.join(f"{x['stat']} {x['amount']}×{x['weight']:.6g}={x['contribution_s_saved_per_mob']:.5g}"
                              for x in item['contributions'])
            readable.append(f"  - Components: {details or 'no mapped stat effects'}")
    readable.extend(['','## Reference and item runtime spot-checks','','```json',json.dumps(spot,indent=2),'```'])
    (output/'WF343_TOP5_READABLE_REPORT.md').write_text('\n'.join(readable))
    return report

if __name__=='__main__':
    r=run();print(json.dumps({'items':r['total_legal_items'],'slots':len(r['slots']),
      'uncertain_items':r['unknown_item_count'],'weight_status':{k:v['status'] for k,v in r['stat_weights']['weights'].items() if k in ('crit','hit','defense','dodge')},
      'items_tested':r['selected_item_executor_probes'],
      'base_s_per_mob':r['reference_replay_100mob'].get('mean_s_per_mob'),
      'proposals':r['paid_gear_proposal_count']},indent=2))
