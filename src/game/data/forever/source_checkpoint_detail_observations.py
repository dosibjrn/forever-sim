"""Fail-closed, class-neutral join of source-detail L0 observations to indexed ranks.

Observations come from a separate provenance-bearing evidence JSON, never
from guessed IDs, same-name siblings or the engine's spell table. They are
L0 semantic screening only; not trained-spell or paid-L2 authorizations.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse, unquote
import json
import re

_ALLOWED_ACTION_TYPES = {
    'actor_action', 'talent_grant_action', 'conditional_granted_action',
    'triggered_effect_not_player_cast', 'passive_modifier_not_cast'
}


def load_detail_observations(path: str | Path, indexed_rows) -> dict[int, dict]:
    source=json.loads(Path(path).read_text())
    if source.get('schema') != 'wf331_web_detail_observation_v1':
        raise ValueError('SOURCE_DETAIL_OBSERVATION_SCHEMA_MISMATCH')
    rows={int(row['spell_id']): row for row in indexed_rows}
    output={}
    for item in source['records']:
        sid=int(item['spell_id'])
        if sid in output:
            raise ValueError('DUPLICATE_SOURCE_DETAIL_OBSERVATION_ID')
        if sid not in rows:
            raise ValueError('SOURCE_DETAIL_ID_NOT_INDEXED_FOR_CHECKPOINT_CLASS')
        indexed=rows[sid]
        indexed_payload=json.loads(indexed['raw_listview_json'])
        if int(indexed_payload.get('id',-1))!=sid:
            raise ValueError('SOURCE_DETAIL_CANONICAL_ID_CONFLICT')
        url=item['source_url']
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.netloc!='www.wowhead.com':
            raise ValueError('SOURCE_DETAIL_INVALID_PROVIDER')
        pathpart=unquote(parsed.path)
        if not re.fullmatch(r'/forever/spell='+str(sid)+r'(?:/[a-z0-9-]+)?',pathpart):
            raise ValueError('SOURCE_DETAIL_URL_ID_MISMATCH')
        if str(indexed['source_url']).rstrip('/') != f'https://www.wowhead.com/forever/spell={sid}':
            raise ValueError('SOURCE_DETAIL_INDEX_PROVIDER_MISMATCH')
        if item['observed_action_type'] not in _ALLOWED_ACTION_TYPES:
            raise ValueError('SOURCE_DETAIL_INVALID_ACTION_ROLE')
        if not item['observed_effect_role'] or not isinstance(item['context_conditions'],list):
            raise ValueError('SOURCE_DETAIL_MISSING_CONTEXT')
        if item.get('legal_acquisition_proven') is not False:
            raise ValueError('SOURCE_DETAIL_NOT_AN_ACQUISITION_CERTIFICATE')
        if item['source_retrieval'] != 'public_search_index_text':
            raise ValueError('SOURCE_DETAIL_UNEXPECTED_AUTHORITY')
        output[sid]=item
    return output
