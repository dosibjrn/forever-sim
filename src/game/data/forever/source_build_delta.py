"""Fail-closed, class-scoped reuse of an older complete client spellbook.

A version change alone does not invalidate an unchanged class spellbook if a
version-pinned, source-record-level delta proves no class spell or talent
changes.  This is client evidence, not proof of server gameplay parity.
"""
from __future__ import annotations
from pathlib import Path
import json


def _count(data: dict, field: str) -> int:
    value=data.get(field)
    if isinstance(value,bool) or not isinstance(value,int) or value<0:
        raise ValueError('SOURCE_DELTA_INCOMPLETE_CHANGE_COUNTS')
    return value


def _assert_no_class_delta(data: dict) -> int:
    """Return source's unrelated new-spell count or reject any class change."""
    added=data.get('new_spells_by_category')
    if (not isinstance(added,dict) or not added
            or any(not isinstance(v,int) or isinstance(v,bool) or v<0 for v in added.values())):
        raise ValueError('SOURCE_DELTA_INVALID_NEW_SPELL_CLASSIFICATION')
    if (_count(data,'changed_spell_records') or _count(data,'removed_spell_records')
            or any(v for category,v in added.items() if category.lower()!='other')):
        raise ValueError('SOURCE_DELTA_CLASS_SPELL_CHANGE')
    if any(_count(data,field) for field in (
            'changed_talent_records','new_talent_records','removed_talent_records')):
        raise ValueError('SOURCE_DELTA_TALENT_CHANGE')
    return added.get('other',0)


def validate_source_build_bridge(path: str | Path, spellbook, *, class_key: str,
                                 target_build: str) -> dict:
    data=json.loads(Path(path).read_text())
    if data.get('schema')!='forever_client_build_delta_class_bridge_v1':
        raise ValueError('SOURCE_DELTA_INVALID_SCHEMA')
    if (data.get('from_build')!=spellbook.data['build']
            or data.get('to_build')!=target_build
            or data.get('class_key')!=class_key.lower()
            or data.get('from_build')==data.get('to_build')):
        raise ValueError('SOURCE_DELTA_BUILD_MISMATCH')
    if data.get('unchanged_source_sha256')!=spellbook.sha256:
        raise ValueError('SOURCE_DELTA_SPELLBOOK_SHA_MISMATCH')
    if (not str(data.get('source_url','')).startswith('https://')
            or not data.get('compared_on') or not data.get('uncertainty')):
        raise ValueError('SOURCE_DELTA_MISSING_PROVENANCE')
    unrelated_new_spells = _assert_no_class_delta(data)
    return {'source_build':spellbook.data['build'],'effective_build':target_build,
            'class_key':class_key.lower(),'source_url':data['source_url'],
            'unchanged_source_sha256':spellbook.sha256,
            'new_spells_other':unrelated_new_spells,'new_spells_class':0,
            'client_only_uncertainty':data['uncertainty']}


def resolve_spellbook_build(spellbook, *, class_key: str, target_build: str,
                            delta_path: str | Path | None, missing_error: str) -> dict | None:
    """Shared P1/P2 version rule; unchanged-build snapshots need no bridge."""
    if spellbook.data['build']==target_build:
        if delta_path is not None:
            raise ValueError('SOURCE_BUILD_BRIDGE_UNUSED')
        return None
    if delta_path is None:
        raise ValueError(missing_error)
    return validate_source_build_bridge(delta_path,spellbook,class_key=class_key,
                                        target_build=target_build)
