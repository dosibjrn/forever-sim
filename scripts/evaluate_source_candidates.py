#!/usr/bin/env python3
"""Evaluate the bounded source-legal naked-gear talent/policy envelope."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.v2.legal_candidate_enumeration import evaluate_source_candidate_envelope
from src.version import SOFTWARE_VERSION


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--class-key', required=True)
    p.add_argument('--levels', type=int, nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    result = {'software_version': SOFTWARE_VERSION,
              'status': 'EVALUATED_SOURCE_ENVELOPE_NOT_JOINT_OPTIMIZED',
              'levels': {str(level): evaluate_source_candidate_envelope(class_key=args.class_key, level=level)
                         for level in args.levels}}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + '\n')
    for level, row in result['levels'].items():
        print(f"{args.class_key} L{level}: {row['evaluated_count']} evaluated; "
              f"best {row['winner']['seconds_per_mob']:.6f} s/mob; "
              f"talents={row['winner']['talents']} actions={row['winner']['actions']}")


if __name__ == '__main__':
    main()
