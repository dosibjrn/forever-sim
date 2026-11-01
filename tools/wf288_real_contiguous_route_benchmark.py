"""Run source-legal bounded L10–20 corridors, independently verified at each level.

These are NOT complete leveling routes or validated 9*60 checkpoints. Proof
records preserve all source transitions, full L2 evaluation budgets and gaps.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from src.v2.source_budgeted_level_route import search_source_bounded_level_route
from src.game.data.forever.sqlite_talents import DEFAULT_DB as TALENT_DB
from src.version import SOFTWARE_VERSION

CLASSES=('druid','hunter','mage','paladin','priest','rogue','shaman','warlock','warrior')
ROOT=Path(__file__).resolve().parents[1]


def benchmark(*,end_level=20,max_l2_per_state=12):
    data={'producer':'source_budgeted_level_route / production source_stateful_budgeted',
          'software_version':SOFTWARE_VERSION,'scenario':'representative naked source actor, incoming full kill+recovery+survival',
          'start_level':10,'end_level':end_level,
          'canonical_talent_db_sha256':sha256(Path(TALENT_DB).read_bytes()).hexdigest(),
          'canonical_item_db_sha256':sha256((ROOT/'data/forever/catalogue/items_2026-09-29.sqlite').read_bytes()).hexdigest(),
          'classes':{},'summary':{}}
    for key in CLASSES:
        r=search_source_bounded_level_route(class_key=key,end_level=end_level,
            max_active_paths=1,max_children_per_path=2,
            max_l2_per_state=max_l2_per_state,max_events_per_state=2400,
            max_total_events=60000,max_total_l2_attempts=300,use_l1=False)
        data['classes'][key]=r
    results=data['classes']
    data['summary']={
      'full_bounded_legal_source_scenario_corridors':sum(x['status']=='EVALUATED_CONTIGUOUS_BOUNDED_SOURCE_SCENARIO' for x in results.values()),
      'required_class_corridors':len(CLASSES),
      'levels_per_requested_corridor':end_level-9,
      'source_legal_scratch_verified_steps_in_selected_paths':sum(len(x['selected_route']) for x in results.values()),
      'required_source_scenario_steps':len(CLASSES)*(end_level-9),
      'total_real_executor_events_all_attempts':sum(x['compute']['event_transitions'] for x in results.values()),
      'total_real_L2_attempts':sum(x['compute']['l2_attempts'] for x in results.values()),
      'total_scorer_cpu_ms':round(sum(x['compute']['scorer_cpu_ns'] for x in results.values())/1e6,3),
      'total_route_controller_cpu_ms':round(sum(x['compute']['total_cpu_ns'] for x in results.values())/1e6,3),
      'accepted_source_complete_class_level_checkpoints':0,
      'required_source_complete_class_level_checkpoints':540,
      'validated_full_continuous_leveling_routes':0,
      'all_route_acquisitions_verified':False,
    }
    return data


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='WF288_REAL_SOURCE_BOUNDED_ROUTES.json');p.add_argument('--end-level',type=int,default=20)
    args=p.parse_args()
    report=benchmark(end_level=args.end_level)
    Path(args.output).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report['summary'],indent=2,sort_keys=True))
    for name,row in report['classes'].items():
        print(name,row['status'],row['last_contiguous_level'],len(row['selected_route']),row['compute']['event_transitions'])

if __name__=='__main__':main()
