"""Reproduce source-legal bounded per-level L2 evidence from the full ZIP.

Examples (run from ZIP root):
 python -m tools.wf288_replay_route --class-key druid --start 10 --end 30 --output /tmp/l10_30.json
 python -m tools.wf288_replay_route --class-key druid --start 31 --end 40 --resume /tmp/l10_30.json --output /tmp/l10_40.json
 python -m tools.wf288_replay_route --class-key druid --pretalent --output /tmp/l1_9.json

Each resume checks every previous source/engine/scenario fingerprint and pays a
fresh endpoint L2 verification. No game world/acquisition route is claimed.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from src.v2.source_stateful_level_route import (
    search_source_pretalent_prefix, search_stateful_contiguous_route,
    join_source_bounded_leveling_route)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--class-key',required=True)
    p.add_argument('--start',type=int,default=10)
    p.add_argument('--end',type=int,default=20)
    p.add_argument('--resume',type=Path)
    p.add_argument('--pretalent',action='store_true')
    p.add_argument('--join-prefix',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-candidates',type=int,default=3)
    p.add_argument('--beam',type=int,default=2)
    p.add_argument('--attempts',type=int,default=6)
    p.add_argument('--events-per-candidate',type=int,default=1200)
    p.add_argument('--global-events',type=int,default=45000)
    p.add_argument('--wall-seconds',type=float,default=60)
    args=p.parse_args()
    if args.pretalent:
        r=search_source_pretalent_prefix(class_key=args.class_key)
    else:
        prior=json.loads(args.resume.read_text()) if args.resume else None
        r=search_stateful_contiguous_route(class_key=args.class_key,
            start_level=args.start,end_level=args.end,resume_from=prior,
            max_candidates_per_level=args.max_candidates,beam_width=args.beam,
            attempts_per_candidate=args.attempts,
            events_per_candidate=args.events_per_candidate,
            global_event_cap=args.global_events,
            max_wall_ns=int(args.wall_seconds*1e9))
        if args.join_prefix:
            r=join_source_bounded_leveling_route(
                json.loads(args.join_prefix.read_text()),r)
    args.output.write_text(json.dumps(r,indent=2,default=str)+'\n')
    print(json.dumps({'status':r['status'],
        'levels':len(r['bounded_route']),
        'blocker':r.get('blocked'),
        'budget':r.get('budget')},indent=2))

if __name__=='__main__':
    main()
