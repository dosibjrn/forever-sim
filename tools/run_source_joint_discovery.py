#!/usr/bin/env python3
"""Reproducible bounded source-only joint discovery inspection (NOT full optimizer)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.v2.source_joint_discovery import evaluate_bounded_joint_discovery


def render(result: dict) -> str:
    winner = result['winner']
    policy = winner['best_policy']
    lines = [f"# {result['class_key'].title()} L{result['level']} — bounded joint discovery",
             '', f"Status: **{result['status']}** — NOT full optimization / NOT DONE.",
             f"Best modeled score: **{winner['score_s_per_mob']:.4f} s/mob**",
             f"Candidates: {result['gear_candidate_count']} gear sets × "
             f"{result['executable_talent_candidate_count']} talent allocations = "
             f"{result['evaluated_state_count']} evaluated states; "
             f"{result['evaluated_policy_count']} executable policy evaluations.",
             '', '## Rotation / policy',
             f"Branch: {policy['branch']} / {policy['combat_mode']}"]
    for idx, rule in enumerate(policy['policy']['rules'], 1):
        lines.append(f"{idx}. `{rule['action_id']}` — conditions: "
                     f"{json.dumps(rule['conditions'], ensure_ascii=False)}")
    lines += ['', 'Executed actions: ' + ' → '.join(
        row['action_name'] for row in policy['selected_actions'][:12]),
        f"Combat: {policy['combat_kill_s']:.3f} s; recovery: {policy['recovery_s']:.3f} s.",
        '', '## Talents',
        f"Allocation: {json.dumps(winner['talents']['selection'], ensure_ascii=False)}",
        f"Points represented/spent: {winner['talents']['spent_points']} "
        f"of {winner['talents']['available_points']} available.",
        '', '## Gear (catalogue-legal, acquisition NOT verified)',
        '| Slot | Item | ID | Catalogue source |',
        '|---|---|---:|---|']
    for slot, item in sorted(winner['gear_slots'].items()):
        lines.append(f"| {slot} | {item['name']} | {item['item_id']} | "
                     f"{item.get('source_type')}: {item.get('source')} |")
    lines += ['', f"Executable stats: {json.dumps(winner['gear_applied_stats'], sort_keys=True)}",
              f"UNMODELED gear stats: {json.dumps(winner['gear_unsupported_stats'], sort_keys=True)}",
              '', '## Top alternative joint states',
              '| Score s/mob | Talents | Gear selector | Policy branch |',
              '|---:|---|---|---|']
    for alt in result['alternatives'][:8]:
        lines.append(f"| {alt['score_s_per_mob']:.4f} | {alt['talent_id']} | "
                     f"{json.dumps(alt['gear_weight_vector'], sort_keys=True)} | "
                     f"{alt['best_policy']['branch']} / {alt['best_policy']['combat_mode']} |")
    lines += ['', '## Acceptance blockers',
              *[f"- {reason}" for reason in result['missing']],
              '', 'No reference build was supplied as a search candidate. '
              'This finite grid does not establish global optimality or an OG fixture.', '']
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--class-key', required=True)
    parser.add_argument('--level', type=int, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = evaluate_bounded_joint_discovery(class_key=args.class_key, level=args.level)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"WF_JOINT_{args.class_key.upper()}_L{args.level}"
    (args.output_dir / f'{prefix}.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    (args.output_dir / f'{prefix}.md').write_text(render(result))
    print(f"{prefix}: {result['winner']['score_s_per_mob']:.4f} s/mob; "
          f"{result['evaluated_state_count']} states; NOT DONE")


if __name__ == '__main__':
    main()
