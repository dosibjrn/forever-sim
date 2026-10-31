"""Source-derived Rake ranks and generic direct+periodic mechanics from canonical SQLite.

Fail closed on changed or incomplete source captures. A newer page changes the
spell_index capture, not the engine. No class spell damage values live here.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from math import isfinite
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from .source_db_scope import active_ability_db

_RAKE_TEXT = re.compile(r'^Rake the target for (\d+) damage and an additional (\d+) damage over (\d+) sec\. Awards 1 combo point\.$')
_COST_TEXT = re.compile(r'^(\d+) Energy$')


def load_rake_facts(level: int, *, db_path: Path | None = None) -> dict | None:
    path=Path(db_path or active_ability_db(DEFAULT_DB))
    if not path.is_file(): raise FileNotFoundError(f'canonical source database unavailable: {path}')
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as con:
        con.row_factory=sqlite3.Row
        ranks=con.execute('''SELECT si.*, sem.tick_interval_s,sem.direct_can_crit,
            sem.periodic_can_crit,sem.attack_resource_id,sem.target_resource_id,
            sem.source_url AS semantics_url,sem.source_build,sem.captured_at,sem.evidence
            FROM spell_index si JOIN sourced_direct_periodic_melee_semantics sem
            ON si.spell_id=sem.spell_id
            WHERE lower(si.class_key)='druid' AND si.name='Rake' AND si.level_hint<=?
            ORDER BY si.level_hint DESC, si.spell_id DESC''',(int(level),)).fetchall()
        available=con.execute('''SELECT COUNT(*) FROM spell_index WHERE
            lower(class_key)='druid' AND name='Rake' AND level_hint<=?''',(int(level),)).fetchone()[0]
    if not available:return None
    if len(ranks)!=available:
        raise ValueError('canonical Rake effect semantics coverage missing for legal rank')
    ranks=[r for r in ranks if r['source_url']==r['semantics_url']]
    if len(ranks)!=available:raise ValueError('Rake source capture and semantics URL disagree')
    r=ranks[0]
    raw=json.loads(r['raw_listview_json'])
    current=(raw.get('envChange') or {}).get('after')
    if not current:
        raise ValueError('Rake current source tooltip missing (no legacy fallback)')
    match=_RAKE_TEXT.fullmatch(current.get('text',''))
    cost=_COST_TEXT.fullmatch(current.get('cost',''))
    if not match or not cost:
        raise ValueError('Rake tooltip mismatch; source facts need a new parser')
    direct,periodic,duration=map(float,match.groups())
    tick=float(r['tick_interval_s'])
    if (tick<=0 or duration<=0 or duration%tick!=0 or
        int(r['direct_can_crit']) not in (0,1) or int(r['periodic_can_crit']) not in (0,1)
        or any(not isfinite(x) or x<0 for x in (direct,periodic)) or
        r['attack_resource_id']!='energy' or r['target_resource_id']!='combo_points' or
        not r['source_build'] or not r['captured_at'] or not r['evidence']):
        raise ValueError('invalid source Rake mechanics')
    return {'spell_id':int(r['spell_id']),'level':int(r['level_hint']),
        'energy':float(cost.group(1)),'direct':direct,'periodic':periodic,
        'duration':duration,'tick':tick, 'direct_can_crit':bool(r['direct_can_crit']),
        'periodic_can_crit':bool(r['periodic_can_crit']), 'source_url':r['source_url'],
        'source_build':r['source_build'],'captured_at':r['captured_at'],
        'evidence':r['evidence'],'batch_id':r['batch_id']}
