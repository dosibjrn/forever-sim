"""Conservative source-index roles, distinct from ability executability.

Forever's *abilities listview* includes zero-level passive/talent records and
engraving recipes as well as combat skills. Neither an indexed source name nor
required level 1 certifies a legal combat action. All classifications are
provenance-preserving: a role classification NEVER closes a gameplay blocker.
"""
from __future__ import annotations
import json
import re

_ENGRAVING = re.compile(r'^Engrave\s+(?P<equipment_slot>[A-Za-z][A-Za-z ]*)\s+-\s+.+$',re.I)


def classify_indexed_ability(record:dict, raw_index_json:str)->dict:
    """Use exact source spell-ID join and source listview fields, not build seeds."""
    raw=json.loads(raw_index_json)
    if not isinstance(raw,dict) or int(raw.get('id',-1))!=int(record['spell_id']):
        raise ValueError('SOURCE_LISTVIEW_SPELL_ID_MISMATCH')
    if str(raw.get('name'))!=str(record['name']):
        raise ValueError('SOURCE_LISTVIEW_NAME_MISMATCH')
    level=record.get('level_hint')
    if raw.get('level') != level:
        raise ValueError('SOURCE_LISTVIEW_LEVEL_MISMATCH')
    env=raw.get('envChange') or {}
    role='UNRESOLVED_POSITIVE_LEVEL_ENTRY'
    reason='source index contains no proof of combat execution or acquisition'
    slot=None
    if env.get('status')=='removed':
        role='EXPLICITLY_REMOVED_FROM_SOURCE_CHANGESET'
        reason='source envChange.status=removed; scenario patch applicability still requires checking'
    else:
        engraving=_ENGRAVING.fullmatch(str(raw['name']))
        if engraving:
            role='SOURCE_NAMED_EQUIPMENT_ENGRAVING_SETUP'
            slot=engraving.group('equipment_slot').strip().lower()
            reason='source lists a gear engraving; rune legality, grant effects and slots require detail/acquisition'
        elif level is None or int(level)<=0:
            role='ZERO_OR_UNKNOWN_LEVEL_PASSIVE_TALENT_CANDIDATE'
            reason='nonpositive/unknown level is not a trained combat button; talent/passive identity remains unverified'
    return {'role':role,'role_evidence':'exact_source_index_fields',
            'source_spell_id':int(record['spell_id']), 'source_url':record['source_url'],
            'source_level_hint':level, 'slot_hint':slot,
            'gameplay_coverage_complete':False, 'source_acquisition_verified':False,
            'reason':reason}
