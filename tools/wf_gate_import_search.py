#!/usr/bin/env python3
"""Import ACTUAL WF463 30s/300s paid search + independent 100mob replays.

No best scores from optimizer summaries alone; no manually populated PASS fields.
No mixed DB SHA, code SHA, encounter or spec provenance. P6 is generated ONLY
when both imported P4 and P5 reports exist and identify the same experiment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

from wf_gate import ROOT


def checked_score(rows):
    valid=[x for x in rows if isinstance(x,dict) and x.get('status')=='COMPLETE'
        and x.get('count')==100 and type(x.get('full_s_per_mob')) in (int,float)
        and math.isfinite(x['full_s_per_mob']) and x['full_s_per_mob']>0]
    return len(valid),min((x['full_s_per_mob'] for x in valid),default=None)


def import_search(raw: dict, *, cls: str, level: int, spec: str, gate: str,
                  db: Path, checkout: Path) -> dict:
    if gate not in ('P4','P5') or cls!='druid' or level != 30:
        raise ValueError('WF463_IMPORT_SUPPORTED_ONLY_DRUID_L30_P4_P5')
    tree={'feral-cat':'feral','balance':'balance'}.get(spec)
    mode='cat' if spec=='feral-cat' else None
    if tree is None:
        raise ValueError('SUPPORTED_SPEC_FERAL_CAT_OR_BALANCE')
    if raw.get('schema')!='wf463_spec_100mob_v1':
        raise ValueError('WRONG_SOURCE_SEARCH_REPORT_SCHEMA')
    if raw.get('checkpoint') != f'{cls}:L{level}:{tree}':
        raise ValueError('SEARCH_CHECKPOINT_MISMATCH')
    constraint=raw.get('spec_constraint') or {}
    if (constraint.get('tree_key')!=tree or constraint.get('minimum_points')!=21
            or constraint.get('required_combat_mode')!=mode):
        raise ValueError('SEARCH_SPEC_CONSTRAINT_MISMATCH')
    if raw.get('bonus_talent_points')!=5:
        raise ValueError('EXPECTED_TALENTED_ON_5_BONUS_POINTS')
    if raw.get('search_budget') != (30 if gate=='P4' else 300):
        raise ValueError('SEARCH_BUDGET_MISMATCH')
    if raw.get('gear_role') != ('druid_feral' if spec=='feral-cat' else 'druid_balance'):
        raise ValueError('SEARCH_GEAR_ROLE_MISMATCH')
    if not db.is_file() or hashlib.sha256(db.read_bytes()).hexdigest()!=raw.get('source_sha256'):
        raise ValueError('SEARCH_DB_SHA256_DIFFERS_FROM_CURRENT_FILE')
    # Engine identity is produced at RUN time, then rechecked on import.
    from wf_gate_engine_fingerprint import runtime_fingerprint
    if raw.get('engine_id') != runtime_fingerprint(checkout):
        raise ValueError('SEARCH_ENGINE_CODE_CHANGED_SINCE_THE_RUN')
    if (not isinstance(raw.get('scenario_id'),str) or len(raw['scenario_id'])!=64
            or not isinstance(raw.get('scenario_payload'),dict)):
        raise ValueError('SEARCH_SCENARIO_PROVENANCE_NOT_RECORDED')
    actual=hashlib.sha256(json.dumps(raw['scenario_payload'],sort_keys=True,default=str).encode()).hexdigest()
    if actual != raw['scenario_id']:
        raise ValueError('SEARCH_SCENARIO_DIGEST_MISMATCH')
    validation=raw.get('validation') or {}
    rows=validation.get('rows') or []
    if not isinstance(rows,list):
        raise ValueError('REPLAY_RESULTS_MISSING')
    number,best=checked_score(rows)
    if (number != validation.get('complete_100mob_replays')
            or len(rows) != validation.get('100mob_replays')):
        raise ValueError('INDEPENDENT_100MOB_COUNT_MISMATCH')
    # Every accepted full-100mob row must originate from an actual FULL config
    # in the search shortlist (source legal spec checked on re-preparation).
    shortlist=raw.get('shortlist') or []
    if not isinstance(shortlist,list) or len(shortlist)!=len(rows):
        raise ValueError('REPLAY_SHORTLIST_CONFIGURATION_COUNT_MISMATCH')
    for row in shortlist:
        if not isinstance(row,dict) or not all(k in row for k in (
                'equipped_gear','allocation','policy_ir','recovery','opening_action_ids',
                'policy_signature')):
            raise ValueError('REPLAY_WAS_NOT_BUILT_FROM_A_COMPLETE_CONFIGURATION')
    axes=raw.get('joint_axis_paid_coverage') or {}
    required=('distinct_talent_allocations','distinct_gear_configs',
              'distinct_policy_signatures','paid_screens')
    if not all(type(axes.get(k)) is int and axes[k]>=2 for k in required):
        raise ValueError('JOINT_PAID_TALENT_GEAR_APL_AXIS_COVERAGE_NOT_PROVEN')
    n=raw.get('unique'); wall=raw.get('search_wall_s')
    if type(n) is not int or n<=0 or type(wall) not in (int,float) or not 0<wall<=(31 if gate=='P4' else 301):
        raise ValueError('INVALID_PAID_SEARCH_COUNTS_OR_WALL_BUDGET')
    return {
        'class':cls,'level':level,'spec':spec,'gate':gate,
        'source_id':raw['source_sha256'],'engine_id':raw['engine_id'],
        'scenario_id':raw['scenario_id'],'source_schema':raw['schema'],'evidence_kind':'WF463_SOURCE_SEARCH_REPLAY',
        'search_wall_s':wall,'unique_full_builds':n,
        'complete_100mob_replays':number,
        'best_full_s_per_mob':best,'mob_count':100,
        'unlock_coverage_pass':raw.get('unlock_coverage_pass') is True,
        'talent_gear_apl_jointly_searched':True,
        'joint_axis_paid_coverage':axes,
        'full_legal_builds':number>0,
        'validation_status':validation.get('status'),
        'ranked_replay_count':len(rows),
        'uncovered_unlock_families':[k for k,v in (raw.get('unlock_coverage') or {}).items()
            if isinstance(v,dict) and v.get('complete_paid_screens',0)<=0],
        'source_search_report_sha256':hashlib.sha256(
             json.dumps(raw,sort_keys=True).encode()).hexdigest(),
        'independent_replay_outside_budget':validation.get('validation_outside_search_budget') is True,
    }


def build_p6(evidence_dir: Path, *, cls: str, level: int, spec: str):
    base=evidence_dir/cls/f'L{level}'/spec
    p4=json.loads((base/'P4.json').read_text())
    p5=json.loads((base/'P5.json').read_text())
    if any(p4.get(x)!=p5.get(x) for x in ('class','level','spec','source_id','engine_id','scenario_id')):
        raise ValueError('P4_P5_SOURCE_ENGINE_SCENARIO_NOT_IDENTICAL')
    if not p4.get('independent_replay_outside_budget') or not p5.get('independent_replay_outside_budget'):
        raise ValueError('P4_P5_LACK_INDEPENDENT_REPLAY_PROOF')
    if not all(p.get('complete_100mob_replays',0)>0 for p in (p4,p5)):
        raise ValueError('INCOMPLETE_P4_OR_P5_100MOB_REPLAYS')
    x={k:p4[k] for k in ('class','level','spec','source_id','engine_id','scenario_id')}
    x.update(evidence_kind='WF463_SOURCE_SEARCH_REPLAY')
    x.update(gate='P6',s_per_mob_30=p4['best_full_s_per_mob'],
             s_per_mob_300=p5['best_full_s_per_mob'],
             independent_replays_same_scenario=True,
             numeric_ratio_30_300=p4['best_full_s_per_mob']/p5['best_full_s_per_mob'])
    return x


def main(argv=None):
    p=argparse.ArgumentParser(description='Convert actual saved WF463 cold paid search reports to class-gate evidence')
    p.add_argument('--class',dest='cls',required=True)
    p.add_argument('--level',type=int,required=True)
    p.add_argument('--spec',choices=('feral-cat','balance'),required=True)
    p.add_argument('--gate',choices=('P4','P5'),required=True)
    p.add_argument('--search',type=Path,required=True)
    p.add_argument('--db',type=Path,default=Path('data/forever/staged_druid_l30_talents_70338.sqlite'))
    p.add_argument('--checkout',type=Path,default=ROOT)
    p.add_argument('--evidence-dir',type=Path,default=ROOT/'gate_evidence')
    p.add_argument('--make-p6',action='store_true')
    args=p.parse_args(argv)
    try:
        x=import_search(json.loads(args.search.read_text()), cls=args.cls,level=args.level,
                        spec=args.spec,gate=args.gate,db=args.db,checkout=args.checkout)
        dest=args.evidence_dir/args.cls/f'L{args.level}'/args.spec
        dest.mkdir(parents=True,exist_ok=True)
        (dest/(args.gate+'.json')).write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
        p6=None
        if args.make_p6 and (dest/'P4.json').is_file() and (dest/'P5.json').is_file():
            p6=build_p6(args.evidence_dir,cls=args.cls,level=args.level,spec=args.spec)
            (dest/'P6.json').write_text(json.dumps(p6,indent=2,sort_keys=True)+'\n')
        print(json.dumps({'class':args.cls,'level':args.level,'spec':args.spec,
             'gate':args.gate,'imported':True,'numeric_ratio_30_300':p6.get('numeric_ratio_30_300') if p6 else None},ensure_ascii=False))
        return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'FAIL','reason':'SEARCH_IMPORT_REFUSED:'+str(exc)},ensure_ascii=False))
        return 1

if __name__=='__main__':
    sys.exit(main())
