from __future__ import annotations
"""Canonical source-backed mode/resource transition rules."""
from dataclasses import replace
from pathlib import Path
import sqlite3
from src.game.model.ir import ModeDefinition, ModeResourceRule
from src.game.data.forever.sqlite_talents import DEFAULT_DB


def apply_mode_resource_facts(class_key: str, modes: tuple[ModeDefinition,...], *, db_path: Path | None = None):
    conn = sqlite3.connect(f'file:{Path(db_path or DEFAULT_DB)}?mode=ro',uri=True)
    conn.row_factory = sqlite3.Row
    try:
        facts = list(conn.execute("SELECT * FROM mode_resource_transition_source_facts WHERE class_key=?",(str(class_key).lower(),)))
    finally:
        conn.close()
    out=[]
    for mode in modes:
        label = ''.join(x if x.isalnum() else '_' for x in mode.label.lower()).strip('_')
        rows=[r for r in facts if r['mode_label']==label]
        if not rows:
            out.append(mode);continue
        rules=list(mode.resource_rules)
        for row in rows:
            idx=next((i for i,r in enumerate(rules) if r.resource_id==row['resource_id']),None)
            if idx is None:
                raise ValueError('sourced mode resource fact references unavailable resource')
            if row['on_enter'] not in ('preserve','reset_to_zero') or row['on_exit'] not in ('preserve','reset_to_zero'):
                raise ValueError('unsupported sourced mode transition rule')
            rules[idx]=replace(rules[idx],on_enter=row['on_enter'],on_exit=row['on_exit'])
        out.append(replace(mode,resource_rules=tuple(rules),provenance=mode.provenance+tuple({
            'authority':r['authority'],'source_url':r['source_url'],
            'capture_id':r['capture_id'],'source_build':r['source_build'],
            'evidence_text':r['evidence_text']} for r in rows)))
    return tuple(out)
