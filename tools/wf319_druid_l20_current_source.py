"""Druid L20 unrestricted: explicit CURRENT source build, existing L2 search.

This is an acceptance gate, not a new optimizer or a new engine. A historical
compatibility default must not accidentally benchmark current 2026-10 source
as if the October 8 listview change had never happened.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from hashlib import sha256
from pathlib import Path

from src.forever_build import FOREVER_BUILD_ENV, FOREVER_BUILD_SOURCE_ENV
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_index_rank_parity import indexed_rank_fact
from src.game.data.forever.source_indexed_action_coverage import _source_spell_ids
from tools.wf297_druid_l20_checkpoint import run as existing_joint_search


@contextmanager
def _build_at(as_of: date):
    prior = {key: os.environ.get(key) for key in (FOREVER_BUILD_ENV, FOREVER_BUILD_SOURCE_ENV)}
    os.environ[FOREVER_BUILD_ENV] = as_of.isoformat()
    os.environ[FOREVER_BUILD_SOURCE_ENV] = 'wf319_explicit_current_checkpoint'
    try:
        yield
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _single_effect(ir, family, type_name, spell_id):
    effects = [e for action in ir.actions if action.family_key == family
               and spell_id in _source_spell_ids(action)
               for e in action.effects if type(e).__name__ == type_name]
    if len(effects) != 1:
        raise ValueError(f'AMBIGUOUS_L20_RUNTIME_EFFECT:{family}:{type_name}:{len(effects)}')
    return effects[0]


def current_l20(*, as_of: date, db_path: Path = DEFAULT_DB):
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro', uri=True) as db:
        source_rows = db.execute("SELECT captured_at FROM capture_batches WHERE status='complete'").fetchall()
    if not source_rows:
        raise ValueError('NO_COMPLETE_SOURCE_CAPTURE')
    newest_capture = max(date.fromisoformat(r[0][:10]) for r in source_rows)
    if as_of < newest_capture:
        raise ValueError(f'STALE_BUILD_BEFORE_SOURCE_CAPTURE:{as_of}:{newest_capture}')
    with _build_at(as_of):
        ir = build_game_ir_slice(class_key='druid', level=20, ability_db_path=db_path)
        checks = (
            ('Wrath', 14, 'direct_damage', 'wrath', 'DamageEffect', 'base_min', 'low'),
            ('Moonfire', 16, 'direct_periodic_damage', 'moonfire', 'DamageEffect', 'base_min', 'low'),
            ('Moonfire', 16, 'direct_periodic_damage', 'moonfire', 'PeriodicEffect', 'total_base_damage', 'periodic_total'),
            ('Rejuvenation', 16, 'periodic_heal', 'rejuvenation', 'PeriodicHealEffect', 'total_base_heal', 'total'),
            ('Healing Touch', 20, 'direct_heal', 'healing_touch', 'HealEffect', 'base_min', 'low'),
        )
        parity = []
        for name, rank_level, source_kind, family, effect_type, field, source_field in checks:
            fact = indexed_rank_fact(class_key='druid', name=name,
                required_level=rank_level, effect_kind=source_kind, db_path=db_path)
            if fact is None:
                raise ValueError('L20_REQUIRED_INDEX_FACT_MISSING:'+name)
            effect = _single_effect(ir, family, effect_type, fact['spell_id'])
            actual = float(getattr(effect, field))
            expected = float(fact[source_field])
            if abs(actual - expected) > 1e-9:
                raise ValueError(f'L20_SOURCE_RUNTIME_PARITY_FAIL:{name}:{field}:{actual}:{expected}')
            parity.append({'spell':name,'source_spell_id':fact['spell_id'],
                'field':field,'runtime':actual,'source_fact':expected,
                'index_after':expected if fact['source_authority']=='canonical_forever_source_index_after_tooltip' else None,
                'source_authority':fact['source_authority'],
                'source_url':fact['source_url'],'raw_index_sha256':fact['raw_index_sha256'],
                'independent_detail_verified':fact['detail_html_independently_verified']})
        result = existing_joint_search(ability_db_path=db_path)
        return {
            'schema':'wf319_druid_l20_explicit_current_build_v1',
            'source_as_of':as_of.isoformat(),
            'newest_source_capture':newest_capture.isoformat(),
            'source_db_sha256':sha256(db_path.read_bytes()).hexdigest(),
            'checkpoint':'druid:L20:unrestricted',
            'source_runtime_index_parity':parity,
            'index_is_not_independent_detail_verification':True,
            'L2_existing_joint_search':result,
            'accepted_checkpoints':int(result['new_checkpoint_count']),
            'checkpoint_denominator':148,
            'acceptance_status':'BLOCKED_SOURCE_INCOMPLETE' if not result['formal_validated_checkpoint'] else 'VALIDATED',
        }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--as-of',type=date.fromisoformat,default=date.today())
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    result=current_l20(as_of=args.as_of)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True,default=str)+'\n')
    comparison=result['L2_existing_joint_search']['comparison']
    print(json.dumps({'checkpoint':result['checkpoint'],'status':result['acceptance_status'],
        'accepted':result['accepted_checkpoints'],'source_as_of':result['source_as_of'],
        'L2_score_s_per_mob':comparison['new_score_s_per_mob'],
        'L2_cpu_ns':result['L2_existing_joint_search']['controller_cpu_ns_including_old_replay'],
        'L2_attempts':comparison['search_l2_attempts'],
        'L2_events':comparison['search_executor_events'],
        'missing_rank_IR':result['L2_existing_joint_search']['source_completeness']['unrepresented']},indent=2))

if __name__=='__main__':main()
