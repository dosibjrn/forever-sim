#!/usr/bin/env python3
"""Executable, fail-closed Druid L20/L30 source-P2 preflight.

Uses the old, source-pinned WF443 full-rank report as a structural input, NOT
as a claim that current CombatRuntime behavior has been tested. P2 acceptance
requires separate executed per-rank behavior tests at each requested level.

Examples:
    python tools/wf_druid_p2_probe.py --level 20
    python tools/wf_druid_p2_probe.py --level 30 --report FILE --catalogue FILE

This script rejects missing/inconsistent source or witness records rather than
silently inventing legal ranks, tests, or source-game mechanics.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
REPORT = DEFAULT_ROOT / 'gate_sources/druid/WF443_P2_GATE_RED.json'
CATALOGUE = DEFAULT_ROOT / 'gate_sources/druid/WF443_SOURCE_CATALOGUE.json'


def source_report(level: int, report: dict[str, Any], catalogue_text: str) -> dict[str, Any]:
    """One mechanical and reproducible tally from a fixed, pinned source snapshot."""
    if level not in (20, 30):
        raise ValueError('DRUID_P2_ONLY_LEVELS_20_30_SUPPORTED')
    catalogue = json.loads(catalogue_text)
    digest = sha256(catalogue_text.encode('utf-8')).hexdigest()
    # Source JSON text is hashed BEFORE any pretty formatting or newline.
    if report.get('source_sha256') != digest:
        raise ValueError('PINNED_SOURCE_SHA256_MISMATCH')
    if report.get('source_build') != catalogue.get('source_build') or catalogue.get('class_key') != 'druid':
        raise ValueError('SOURCE_CLASS_OR_BUILD_MISMATCH')
    if report.get('checkpoint') != 'druid:L30:unrestricted':
        raise ValueError('REPORT_NOT_DRUID_L30_UNRESTRICTED')
    if report.get('available_points') != 26 or report.get('bonus_talent_points') != 5:
        raise ValueError('SOURCE_REPORT_NOT_26PT_TALENTED_ON')
    if report.get('unresolved_reachability_count') != 0:
        raise ValueError('UNRESOLVED_SOURCE_REACHABILITY')
    definitions = {d['talent_id']: d for d in catalogue['catalogue']}
    if len(definitions) != len(catalogue['catalogue']):
        raise ValueError('DUPLICATE_CATALOGUE_TALENT')
    max_source_ranks = sum(int(d['max_rank']) for d in definitions.values())
    if max_source_ranks != int(report.get('source_rank_total', -1)):
        raise ValueError('RANK_COUNT_DIFFERS_FROM_PINNED_CATALOGUE')
    observed: dict[tuple[str,int], dict] = {}
    groups = (('structural_witnesses','reachable'), ('provably_unreachable','unreachable'), ('unresolved','unresolved'))
    source_reachable = set()
    for group, label in groups:
        for rank in report.get(group, []):
            k = (rank['talent_id'], rank['rank'])
            if k in observed:
                raise ValueError('DUPLICATE_SOURCE_RANK:' + str(k))
            definition = definitions.get(rank['talent_id'])
            if not definition or not isinstance(rank['rank'], int) or not 1 <= rank['rank'] <= definition['max_rank']:
                raise ValueError('RANK_NOT_IN_SOURCE_CATALOGUE:' + str(k))
            if not isinstance(rank.get('row'),int) or rank['row'] < 0:
                raise ValueError('SOURCE_TIER_MISSING:' + str(k))
            if rank.get('source_build') != catalogue.get('source_build'):
                raise ValueError('RANK_SOURCE_BUILD_MISMATCH:' + str(k))
            observed[k] = rank
            if label == 'reachable':
                source_reachable.add(k)
                witness = rank.get('witness')
                if not isinstance(witness, dict) or any(
                    d not in definitions or definitions[d]['tree_key'] != definition['tree_key']
                    or type(n) is not int or n < 1 or n > definitions[d]['max_rank']
                    for d,n in witness.items()
                ) or witness.get(rank['talent_id'], 0) < rank['rank']:
                    raise ValueError('ILLEGAL_SOURCE_WITNESS:' + str(k))
                if sum(witness.values()) > 26 or sum(witness.values()) < 5*rank['row']+rank['rank']:
                    raise ValueError('WITNESS_SOURCE_POINT_BUDGET_INVALID:' + str(k))
            elif label == 'unreachable' and rank.get('why') != 'TIER_MINIMUM_EXCEEDS_BUDGET':
                raise ValueError('SOURCE_UNREACHABLE_NOT_BUDGET_PROVEN:' + str(k))
    missing = {(d['talent_id'],r) for d in catalogue['catalogue'] for r in range(1,d['max_rank']+1)} - set(observed)
    if missing:
        raise ValueError('SOURCE_MISSING_RANKS:' + str(sorted(missing)[:10]))
    if len(source_reachable) != report['reachable_rank_count']:
        raise ValueError('SOURCE_L30_REACHABLE_COUNT_MISMATCH')
    points = level - 9 + 5   # Classic baseline: L10=1 talent point, +5 Forever bonus.
    # At L20 use only legal, *already-applied* WF443 rank witnesses whose sum fits
    # the 16pt budget; every other source rank must have a tier lower bound >16.
    reachable: list[dict] = []
    out_of_budget: list[dict] = []
    unresolved: list[dict] = []
    for k,rank in sorted(observed.items()):
        lower_bound = rank['row']*5 + rank['rank']
        if lower_bound > points:
            out_of_budget.append({'talent_id':k[0], 'rank':k[1], 'row':rank['row'], 'reason':'TIER_MINIMUM_EXCEEDS_BUDGET'})
            continue
        if k not in source_reachable:
            unresolved.append({'talent_id':k[0], 'rank':k[1], 'reason':'RANK_WITHIN_BUDGET_BUT_NO_SOURCE_WITNESS'})
            continue
        witness = rank['witness']
        if sum(witness.values()) > points:
            unresolved.append({'talent_id':k[0], 'rank':k[1], 'reason':'EXISTING_WITNESS_EXCEEDS_TARGET_LEVEL_BUDGET'})
            continue
        applied = rank.get('application',{}).get('status') == 'APPLIED_IN_GAME_IR'
        reachable.append({'talent_id':k[0], 'rank':k[1], 'row':rank['row'],
                          'witness_points':sum(witness.values()),
                          'source_l30_ir_applied':applied,
                          'source_modifier_count':rank.get('modifier_count',0),
                          'historical_semantic_labels':rank.get('partial_semantics',[])})
    if len(reachable)+len(out_of_budget)+len(unresolved) != max_source_ranks:
        raise ValueError('RANK_PARTITION_COUNT_INVARIANT_FAILED')
    missing_ir = [x for x in reachable if not x['source_l30_ir_applied'] or x['source_modifier_count']<=0]
    return {
        'class':'druid','level':level,'spec':'unrestricted','gate':'P2',
        'source_build':catalogue['source_build'],'source_id':digest,
        'engine_id':'WF443_HISTORICAL_IR_ONLY',
        'provenance_scope':'HISTORICAL_WF443_L30_SOURCE_APPLIED_IR_NOT_CURRENT_COMBAT_BEHAVIOR',
        'talent_points':points,'source_rank_total':max_source_ranks,
        'structurally_reachable_ranks':len(reachable),
        'source_budget_unreachable_ranks':len(out_of_budget),
        'source_unresolved_ranks':len(unresolved),
        'source_l30_ir_applied_ranks':len(reachable)-len(missing_ir),
        'ranks_with_executor_paths':len(reachable)-len(missing_ir) if level == 30 else 0,
        'ranks_with_executed_behavior_tests':0,
        'ranks_represented_in_search':0,
        'unlocked_actions_available_to_generated_search':False,
        'reachable_rank_keys':[f"{x['talent_id']}:{x['rank']}" for x in reachable],
        'rank_behavior_results':[],
        'missing_executor_ranks':len(missing_ir) if level==30 else 0,
        'failed_behavior_ranks':0,
        'talent_paths_legal':not unresolved,
        'source_specific_behavior_tests_executed':False,
        'missing_current_level_runtime_executor_verification':0 if level==30 else len(reachable),
        'legacy_semantic_labels_are_not_gate_failures':True,
        'reachable_ranks':reachable,
        'unreachable_ranks':out_of_budget,
        'unresolved_ranks':unresolved,
        'remaining_rank_behavior_tests': [{'talent_id':x['talent_id'],'rank':x['rank']}
                                          for x in reachable],
        'source_witness_sha256':sha256(json.dumps(report,sort_keys=True).encode()).hexdigest(),
    }


def main(argv=None):
    p=argparse.ArgumentParser(description='Recompute historical Druid source-P2 structural coverage, fail closed on missing runtime evidence')
    p.add_argument('--level', type=int, choices=(20,30), required=True)
    p.add_argument('--report',type=Path,default=REPORT)
    p.add_argument('--catalogue',type=Path,default=CATALOGUE)
    p.add_argument('--evidence-dir',type=Path,default=Path('gate_evidence'))
    p.add_argument('--stdout-only',action='store_true',help='Do not write P2 evidence JSON')
    a=p.parse_args(argv)
    try:
        report=json.loads(a.report.read_text(encoding='utf-8'))
        raw=a.catalogue.read_text(encoding='utf-8').strip()
        result=source_report(a.level,report,raw)
    except (ValueError,OSError,KeyError,TypeError) as e:
        print(json.dumps({'class':'druid','level':a.level,'gate':'P2','status':'FAIL',
                          'reasons':['SOURCE_P2_PROBE_ERROR:'+str(e)]},ensure_ascii=False))
        return 1
    path=a.evidence_dir/'druid'/f'L{a.level}'/'unrestricted'/'P2.json'
    if not a.stdout_only:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    summary={k:result[k] for k in ['class','level','gate','talent_points','source_rank_total',
         'structurally_reachable_ranks','source_budget_unreachable_ranks','source_unresolved_ranks',
         'source_l30_ir_applied_ranks','ranks_with_executor_paths','ranks_with_executed_behavior_tests']}
    summary.update({'status':'FAIL','reason':'CURRENT_LEVEL_EXECUTED_BEHAVIOR_WITNESSES_NOT_AVAILABLE',
                    'evidence_file':str(path) if not a.stdout_only else None})
    print(json.dumps(summary,ensure_ascii=False))
    return 1 # P2 cannot PASS just because source modifiers exist.


if __name__=='__main__':
    sys.exit(main())
