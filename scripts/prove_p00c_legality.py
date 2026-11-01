#!/usr/bin/env python3
"""Reproduce WF-P00c independent Druid L10→11 legality and scored child."""
import json
from dataclasses import replace
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.game.level_legality import LevelState, validate_level_transition
from src.v2.level_evaluation_trace import evaluate_legal_level_continuation
from src.version import SOFTWARE_VERSION


def main():
    parent = LevelState('druid', 10, 'tauren', {'improved_wrath': 1}, ('wrath:5177',))
    child = LevelState('druid', 11, 'tauren', {'improved_wrath': 2}, ('wrath:5177',))
    evaluated = evaluate_legal_level_continuation(parent=parent, child=child)
    rejected = {}
    cases = {
        'illegal_refund': replace(child, talents={}),
        'unavailable_rank': replace(child, action_ids=('wrath:999999',)),
        'unverified_gear': replace(child, selected_items=('item:999999',)),
        'race_change': replace(child, race_key='night_elf'),
        'overbudget': replace(child, talents={'improved_wrath':3}),
    }
    for name, bad in cases.items():
        try:
            validate_level_transition(parent, bad)
        except ValueError as exc:
            rejected[name] = str(exc)
        else:
            raise AssertionError(f'illegal fixture accepted: {name}')
    proof = {
        'schema_version': 1, 'version': SOFTWARE_VERSION,
        'increment': 'WF-P00c', 'status': 'EVALUATED',
        'parent': {'level': 10, 'talents': {'improved_wrath':1}, 'action_ids':['wrath:5177']},
        'transition': evaluated['transition'],
        'child_score_seconds_per_mob': evaluated['child_trace']['evaluation']['seconds_per_mob'],
        'child_talent': evaluated['child_trace']['talent'],
        'negative_cases_rejected': rejected,
        'limitations': ['naked_gear_only','representative_tauren_race_only',
                        'no_cross_level_resource_carry_forward','not_joint_optimized',
                        'no_1_to_60_route','fidelity_backlog_not_changed'],
    }
    out=Path(__file__).resolve().parents[1] / f'WF_P00C_DRUID_L10_L11_LEGALITY_v{SOFTWARE_VERSION}.json'
    out.write_text(json.dumps(proof,indent=2,sort_keys=True)+'\n')
    print(out)
    return proof

if __name__=='__main__':
    main()
