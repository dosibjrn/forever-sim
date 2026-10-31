"""Fail-closed provenance gate: source citation is not canonical SQLite authority.

A URL or an in-Python Wowhead transcription is evidence of origin, not proof
that the executable numeric facts were read from the canonical database.
This gate deliberately reports INCOMPLETE until field-level DB lineage lands.
"""
from __future__ import annotations


def audit_ir_database_authority(ir) -> dict:
    """Audit *all* action/talent/actor lineage; never infer DB authority from URLs.

    Contract for accepting an executable fact: the provenance entry explicitly
    declares canonical_sqlite authority, the source table, immutable capture
    batch and entity row key, and provides field-level lineage. The current IR
    normally fails this strict contract: that is an intended truthful blocker.
    """
    rows = []
    elements = [('actor', ir.actor.id, ir.actor.provenance)]
    elements += [('action', a.id, a.provenance) for a in ir.actions]
    elements += [('talent', t.id, t.provenance) for t in ir.talents]
    for kind, identifier, entries in elements:
        proven = any(
            isinstance(p, dict) and p.get('authority') == 'canonical_sqlite'
            and all(p.get(k) for k in ('database', 'table', 'row_key', 'capture_batch', 'field_lineage'))
            for p in entries
        )
        if not proven:
            rows.append({'kind': kind, 'id': identifier, 'reason': 'unproven_canonical_sqlite_field_lineage'})
    return {'status': 'INCOMPLETE_SOURCE_AUTHORITY' if rows else 'DECLARED_SQLITE_LINEAGE',
            'complete_optimizer': False, 'source_ir_id': ir.id,
            'audited_count': len(elements), 'blocker_count': len(rows), 'blockers': rows,
            'limitation': 'Declared lineage is not proof of SQLite contents; independent DB row validation remains required.'}


def require_ir_database_authority(ir) -> None:
    audit = audit_ir_database_authority(ir)
    if audit['blocker_count']:
        raise ValueError(f"incomplete canonical SQLite authority: {audit['blocker_count']} facts lack field lineage")
