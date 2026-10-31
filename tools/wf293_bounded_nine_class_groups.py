"""Run real production 9-class bounded L2 in small reproducible batches."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from src.v2.source_budgeted_level_route import search_source_bounded_level_route
GROUPS=(('druid','hunter','mage'),('paladin','priest','rogue'),('shaman','warlock','warrior'))
def main():
 p=argparse.ArgumentParser()
 p.add_argument('--group',type=int,choices=range(3),required=True)
 p.add_argument('--output',type=Path,required=True)
 a=p.parse_args()
 classes={}
 for cls in GROUPS[a.group]:
  r=search_source_bounded_level_route(class_key=cls,end_level=20,
     max_active_paths=1,max_children_per_path=2,max_l2_per_state=12,
     max_events_per_state=2400,max_total_events=60000,
     max_total_l2_attempts=300,use_l1=False)
  classes[cls]=r
 result={'group':a.group,'classes':classes}
 a.output.write_text(json.dumps(result,indent=2,sort_keys=True))
 print(json.dumps({k:{'selected':len(v['selected_route']),
     'status':v['status'],'cpu_ms':round(v['compute']['total_cpu_ns']/1e6,1),
     'events':v['compute']['event_transitions'],
     'attempts':v['compute']['l2_attempts'],
     'first_score':(v['selected_route'][0]['full_cycle_s_per_mob'] if v['selected_route'] else None)}
     for k,v in classes.items()}))
if __name__=='__main__':main()
