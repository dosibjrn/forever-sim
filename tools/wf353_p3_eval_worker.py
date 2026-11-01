"""Cold OS child: canonical source DB -> IR -> gear -> CombatRuntime 100 mobs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import monotonic, process_time

from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_persistent_joint_finalists import (
    prepare_candidate, evaluate_persistent_candidate,
)
from src.game.recovery_between_pulls import BetweenPullPolicy
from src.game.data.forever.source_checkpoint_p3_swaps import (
    substituted_stage, substituted_multi_stage,
)


def _checkpoint_from_stage(stage):
    gear = stage['gear_policy_result']['winner']['gear']
    return str(gear['class_key']).lower(), int(gear['level'])


def run(stage, db, slot=None, item_id=None, swaps=None, recovery_policy=None,
        allow_partial_gear_stats=False):
    start, cpu = monotonic(), process_time()
    class_key, level = _checkpoint_from_stage(stage)
    with ability_source_scope(db):
        ir = build_game_ir_slice(class_key=class_key, level=level, ability_db_path=db)
        if slot is not None:
            stage = substituted_stage(stage=stage, class_key=class_key, level=level,
                                      slot=slot, item_id=item_id)
        if swaps is not None:
            stage = substituted_multi_stage(stage=stage, class_key=class_key,
                                            level=level, swaps=swaps)
        candidate = prepare_candidate(
            class_key=class_key, level=level, stage=stage, source_ir=ir,
            strict_l2_item_effects=not allow_partial_gear_stats,
            allow_partial_gear_stats=allow_partial_gear_stats,
        )
        result = evaluate_persistent_candidate(
            candidate, level=level, mobs=100, max_wall_s=13., max_cpu_s=13.,
            max_total_events=200000,
            recovery_policy=None if recovery_policy is None
                else BetweenPullPolicy(**recovery_policy),
        )
    return {
        **result,
        'checkpoint': {'class_key': class_key, 'level': level},
        'gear_effect_coverage': candidate.ir.provenance.get(
            'gear_effect_coverage',
            {'complete': True, 'mode': 'STRICT_SOURCE_GEAR', 'unsupported_stats': {}},
        ),
        'end_to_end_child_wall_s': monotonic() - start,
        'end_to_end_child_cpu_s': process_time() - cpu,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--source-db', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--slot')
    parser.add_argument('--item-id', type=int)
    parser.add_argument('--swaps-json', type=Path)
    parser.add_argument('--recovery-policy-json', type=Path)
    parser.add_argument('--allow-partial-gear-stats', action='store_true')
    args = parser.parse_args()
    try:
        result = run(
            json.loads(args.stage.read_text()), args.source_db, args.slot,
            args.item_id,
            json.loads(args.swaps_json.read_text()) if args.swaps_json else None,
            json.loads(args.recovery_policy_json.read_text())
                if args.recovery_policy_json else None,
            args.allow_partial_gear_stats,
        )
    except BaseException as exc:
        result = {'status': 'ERROR', 'reason': type(exc).__name__ + ':' + str(exc)[:400]}
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, sort_keys=True, default=str))
    temporary.replace(args.output)
    print(json.dumps({'status': result.get('status'),
                      's_per_mob': result.get('mean_s_per_mob')}), flush=True)
    sys.exit(0 if result.get('status') == 'COMPLETE' else 2)
