"""WF291 reproducible source-method coverage + native L2 route benchmark.

All character location, money, inventory and completed quests in this test are
synthetic scenario inputs, NOT observed world-route evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from src.game.data.forever.source_acquisition_events import (
    AcquisitionCharacterState, AcquisitionEvent, apply_source_consistent_acquisition,
    verified_source_acquisition_entities)
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2.source_budgeted_level_route import search_source_bounded_level_route
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_indexed_action_coverage import _source_spell_ids


def main():
    with sqlite3.connect(DEFAULT_DB) as db:
        db.row_factory=sqlite3.Row
        rows=[dict(r) for r in db.execute('''SELECT e.class_key,e.spell_id,e.required_level_hint,
            e.methods_observed_json,e.training_cost_hint FROM ability_acquisition_evidence e
            WHERE e.methods_observed_json!='{}' ORDER BY e.class_key,e.spell_id''')]
        total_index=db.execute("SELECT COUNT(*) FROM spell_index WHERE kind='abilities'").fetchone()[0]
        entities_count=db.execute('SELECT COUNT(*) FROM ability_acquisition_entities').fetchone()[0]
    class_methods=Counter()
    executed=[]
    source_executable=[]
    for row in rows:
        cls,sid=row['class_key'],row['spell_id']
        methods=json.loads(row['methods_observed_json'])
        eligible={k:v for k,v in methods.items() if k in ('taught_by_npc','taught_by_item','reward_from_quest')}
        if not eligible:
            continue
        entities=verified_source_acquisition_entities(class_key=cls,spell_id=sid)
        ir=build_game_ir_slice(class_key=cls,level=max(10,int(row['required_level_hint'] or 1)))
        executable=[a.id for a in ir.actions if sid in _source_spell_ids(a)] if ir else []
        if executable: source_executable.append({'class_key':cls,'spell_id':sid,'action_ids':executable})
        for method in eligible:
            entity=next(x for x in entities if x['method']==method and
                        (method!='taught_by_npc' or json.loads(x['zone_ids_json'])))
            zone=(json.loads(entity['zone_ids_json'])[0] if method=='taught_by_npc' else None)
            copper=int(row['training_cost_hint'] or 0) if method=='taught_by_npc' else 0
            state=AcquisitionCharacterState(cls,max(1,int(row['required_level_hint'] or 1)),
                zone,copper,inventory_item_ids=frozenset({entity['entity_id']})
                if method=='taught_by_item' else frozenset(),
                completed_quest_ids=frozenset({entity['entity_id']})
                if method=='reward_from_quest' else frozenset())
            updated,rec=apply_source_consistent_acquisition(state,
                AcquisitionEvent(method,sid,entity['entity_id'],zone))
            assert sid in updated.learned_spell_ids and not rec['world_route_proven']
            class_methods[cls]+=1
            executed.append({'class_key':cls,'spell_id':sid,'method':method,
                'source_entity_id':entity['entity_id'],
                'zone_assumed':zone,'copper_assumed':copper,
                'world_route_proven':False})
    mage_state=AcquisitionCharacterState('mage',10,12,400,
        learned_spell_ids=frozenset({205,143,2136}))
    mage_event=AcquisitionEvent('taught_by_npc',122,328,12)
    common=dict(class_key='mage',start_level=10,end_level=11,
        max_active_paths=1,max_children_per_path=1,max_l2_per_state=10,
        max_events_per_state=2000,max_total_events=4000,max_total_l2_attempts=20)
    unfiltered=search_source_bounded_level_route(**common)
    filtered=search_source_bounded_level_route(**common,
        initial_acquisition_state=mage_state,
        acquisition_events_by_level={10:(mage_event,)})
    assert filtered['bounded_contiguous_levels']==2
    assert filtered['accepted_class_level_checkpoints']==0
    return {
        'baseline':'v0.11.48.289 + WF290 WIP + WF291 WIP (no full release)',
        'canonical_ability_db_sha256':sha256(Path(DEFAULT_DB).read_bytes()).hexdigest(),
        'source_indexed_ranks':total_index,
        'source_verified_detail_methods':len(rows),
        'source_verified_entity_links':entities_count,
        'source_method_local_scenario_transitions':len(executed),
        'local_scenario_transitions_by_class':dict(class_methods),
        'local_scenario_transitions':executed,
        'source_method_spells_executable_at_first_available_scenario':source_executable,
        'world_acquisition_events_verified':0,
        'fully_validated_checkpoints':{'before':0,'after':0,'total':540},
        'continuous_world_routes':{'before':0,'after':0},
        'native_l2_mage_l10_11':{
            label:{'status':r['status'],'levels':r['bounded_contiguous_levels'],
                'scores_s_per_mob':[s['full_cycle_s_per_mob'] for s in r['selected_route']],
                'selected_action_ids':[s['source_action_ids'] for s in r['selected_route']],
                'compute':r['compute'],
                'local_acquisition_event_count':r['source_consistent_local_acquisition_events'],
                'world_route_complete':r['full_route_complete'],
                'accepted_checkpoints':r['accepted_class_level_checkpoints']}
            for label,r in [('unrestricted_bounded',unfiltered),('acquired_source_id_filtered',filtered)]},
        'limits':['initial learned ranks, zone, currency and quest/item possession are assumed',
            'trainer zone ID from source does not establish a traversable route',
            'source training cost hint is not proof of an actual purchase',
            'no XP, gear acquisition, world travel, complete source effects or independent optimizer proof',
            'source-consistent local scenarios are NOT validated class-level checkpoints']
    }


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result=main();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('local_scenario_transitions','native_l2_mage_l10_11')},indent=2))
