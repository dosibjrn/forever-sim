"""Run a source-backed, bounded, independent joint search from the project root.

Example:
  python scripts/run_staged_joint_search.py --class-key druid --level 20 \
    --screening-gears 3 --finalists 16 --held-out-json legacy.json \
    --output druid20.json

A held-out JSON file contains a {talent_id: rank} mapping; it is not fed to
independent candidate discovery. This is a bounded search, not global proof.
"""
import argparse
import json
import sys
from pathlib import Path

# Direct `python scripts/run_staged_joint_search.py` must resolve the canonical
# source package without relying on a caller-supplied PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.v2.source_staged_joint_search import evaluate_staged_joint_search


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--class-key', required=True)
    parser.add_argument('--level', type=int, required=True)
    parser.add_argument('--screening-gears', type=int, default=3)
    parser.add_argument('--finalists', type=int, default=16)
    parser.add_argument('--max-talents', type=int, default=10000)
    parser.add_argument('--policy-cap', type=int, default=96)
    parser.add_argument('--held-out-json', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    held_out = json.loads(args.held_out_json.read_text()) if args.held_out_json else None
    result = evaluate_staged_joint_search(
        class_key=args.class_key, level=args.level,
        screening_gear_count=args.screening_gears,
        finalist_talent_count=args.finalists,
        max_talent_candidates=args.max_talents,
        max_policies_per_path=args.policy_cap,
        max_caster_policies=args.policy_cap,
        held_out_allocation=held_out,
    )
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    winner = result['winner']
    print(f"{args.class_key} L{args.level}: {winner['seconds_per_mob']:.6f} s/mob, "
          f"{result['talent_allocations_screened']}/{result['talent_allocations_enumerated']} "
          f"executable allocations screened, {result['gear_envelope_count']} gear sets")
    print('talents:', winner['talent_allocation'])
    if result['held_out']:
        print('held-out:', (result['held_out']['best'] or {}).get('seconds_per_mob'),
              'legal:', result['held_out']['legal'])
    print('bounded result; global optimum NOT claimed')


if __name__ == '__main__':
    main()
