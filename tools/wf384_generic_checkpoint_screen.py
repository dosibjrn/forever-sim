"""WF384: automated cross-class source admission + optional paid 100mob APL screen.

Examples:
  PYTHONPATH=. python tools/wf383_generic_checkpoint_screen.py --preflight-only \
      mage:30 druid:20 druid:30 warrior:30 priest:30
  PYTHONPATH=. python tools/wf383_generic_checkpoint_screen.py --max-policies 6 \
      mage:30 druid:20 druid:30 warrior:30

The results do NOT increment the accepted 148-checkpoint scoreboard.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from src.game.checkpoint_pipeline import checkpoint_auto_screen, checkpoint_preflight


def run(checkpoints: list[str], *, preflight_only: bool, max_policies: int) -> dict:
    records={}
    start=perf_counter()
    for item in checkpoints:
        if ':' not in item:
            raise ValueError(f'Invalid class:level checkpoint: {item}')
        cls, raw_level=item.split(':',1)
        lvl=int(raw_level)
        key=f'{cls.lower()}_L{lvl}'
        if key in records:
            raise ValueError(f'Duplicate checkpoint: {key}')
        tick=perf_counter()
        if preflight_only:
            report=checkpoint_preflight(class_key=cls,level=lvl)
            records[key]={'preflight':report,
                'status':'PREFLIGHT_RECORDED','eligible_for_checkpoint_acceptance':False}
        else:
            records[key]=checkpoint_auto_screen(class_key=cls,level=lvl,
                                                   max_policies=max_policies)
        records[key]['elapsed_wall_s']=perf_counter()-tick
    return {'workflow':'WF384_GENERIC_CLASS_INDEPENDENT_CHECKPOINT_PIPELINE',
        'parent_release':'WF382','scoreboard_before':2,'scoreboard_after':2,
        'scoreboard_denominator':148,
        'preflight_only':preflight_only, 'max_policy_budget':max_policies,
        'all_runs_diagnostic':True,
        'no_forever_named_npc_certified':True,
        'results':records, 'elapsed_wall_s':perf_counter()-start}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoints',nargs='+',help='class:level e.g. mage:30')
    parser.add_argument('--preflight-only',action='store_true')
    parser.add_argument('--max-policies',type=int,default=6)
    parser.add_argument('--output',type=Path,default=Path('evidence/wf384/WF384_COMMAND_RUN.json'))
    args=parser.parse_args()
    results=run(args.checkpoints,preflight_only=args.preflight_only,
                max_policies=args.max_policies)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(results,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
    for key,entry in results['results'].items():
        if args.preflight_only:
            print(f"{key}: IR={'YES' if entry['preflight']['enemy'] else 'NO'}, "
                  f"blockers={[x['code'] for x in entry['preflight']['blockers']]}")
        else:
            score=None if not entry.get('best') else entry['best']['best']['seconds_per_mob']
            print(f"{key}: {entry['status']} best_s_per_mob={score}")
    print('Wrote',args.output)


if __name__=='__main__':
    main()
