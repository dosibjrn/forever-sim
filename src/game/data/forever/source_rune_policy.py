"""Source-index rune opt-in policy for the legacy GameIR provider path.

This module only filters unverified rune and engraving action availability;
it does not execute ability effects or model a second combat engine.
"""
from dataclasses import replace
from pathlib import Path
import sqlite3

from .source_db_scope import DEFAULT_DB
from .source_indexed_action_coverage import _source_spell_ids
from .source_action_scope import classify_indexed_ability
from .source_checkpoint_web_l0 import load_observations


def filter_default_runes(ir, *, class_key: str, level: int, ability_db_path=None):
    """Preserve the default-off sourced rune policy and its disabled action IDs."""
    db_path = Path(ability_db_path or DEFAULT_DB)
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        raw_rows=db.execute('SELECT spell_id,name,level_hint,source_url,raw_listview_json '
            "FROM spell_index WHERE class_key=? AND kind='abilities'",
            (class_key.strip().lower(),)).fetchall()
        observed_grants=load_observations(db,class_key.strip().lower())
        talent_grants=set()
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                      "AND name='verified_talent_granted_action_facts'").fetchone():
            import json
            for grant_sid,grant_json in db.execute(
                    'SELECT spell_id,action_json FROM verified_talent_granted_action_facts WHERE class_key=?',
                    (class_key.strip().lower(),)):
                required=json.loads(grant_json).get('required_level')
                if required is not None and int(required)<=int(level):
                    talent_grants.add(int(grant_sid))
    engraving_ids={int(r['spell_id']) for r in raw_rows if
        classify_indexed_ability(dict(r),r['raw_listview_json'])['role']==
            'SOURCE_NAMED_EQUIPMENT_ENGRAVING_SETUP'}
    conditional_rune_ids={sid for sid,obs in observed_grants.items() if
        'rune_grant_unverified' in obs.get('source_flags',()) and sid not in talent_grants}
    blocked_source_ids=engraving_ids | conditional_rune_ids
    disabled_ids={a.id for a in ir.actions if _source_spell_ids(a) & blocked_source_ids}
    if disabled_ids:
        ir=replace(ir,actions=tuple(a for a in ir.actions if a.id not in disabled_ids),
            modes=tuple(replace(m,enabled_action_ids=(
                None if m.enabled_action_ids is None else
                tuple(a for a in m.enabled_action_ids if a not in disabled_ids)))
                for m in ir.modes),
            source_facts=tuple(f for f in ir.source_facts if not (
                isinstance(f,dict) and f.get('fact_kind')=='canonical_indexed_ability_coverage')))
        # Coverage facts must reflect actual post-policy executable IR.
        from .source_indexed_action_coverage import attach_indexed_ability_coverage
        ir=attach_indexed_ability_coverage(ir,class_key=class_key,
                level=int(level),db_path=db_path)
    return ir, disabled_ids
