"""Source-SQLite rank compiler for reactive maintenance auras.

Reads fully matching Forever listview-after facts, with no hand-entered
ability values; no inference of trainer acquisition or other spell effects.
"""
from __future__ import annotations
import json,re,sqlite3
from pathlib import Path
from .sqlite_talents import DEFAULT_DB
from .source_db_scope import active_ability_db

_THORNS_SHAPE=re.compile(r'^Thorns sprout from the friendly target causing (?P<damage>\d+) (?P<school>[A-Za-z]+) damage to attackers when hit\. Lasts (?P<mins>\d+) min\.$')
_COST=re.compile(r'^(?P<amount>\d+) (?P<resource>Mana|Rage|Energy)$')


def latest_reactive_maintenance_rank(class_key:str,family_name:str,level:int,*,db_path:Path|None=None)->dict|None:
    """Only return exact parsed reactive auras; unknown grammar fails closed."""
    path=Path(db_path or active_ability_db(DEFAULT_DB))
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as conn:
        row=conn.execute('''SELECT spell_id,name,level_hint,raw_listview_json,source_url FROM spell_index
          WHERE class_key=? AND kind='abilities' AND name=?
            AND level_hint IS NOT NULL AND level_hint BETWEEN 1 AND ?
          ORDER BY level_hint DESC,spell_id DESC LIMIT 1''',
          (class_key.lower(),family_name,int(level))).fetchone()
    if row is None:return None
    sid,name,learn,raw_text,url=row;raw=json.loads(raw_text)
    if raw.get('id')!=sid or raw.get('name')!=name or raw.get('level')!=learn:
        raise ValueError('REACTIVE_AURA_SOURCE_IDENTITY_CONFLICT')
    env=raw.get('envChange') or {}
    if env.get('status')=='removed':raise ValueError('LATEST_REACTIVE_AURA_REMOVED')
    after=env.get('after')
    if not isinstance(after,dict):raise ValueError('REACTIVE_AURA_NEEDS_UNAMBIGUOUS_AFTER_TOOLTIP')
    match=_THORNS_SHAPE.fullmatch(str(after.get('text','')))
    cost=_COST.fullmatch(str(after.get('cost','')))
    if (not match or not cost or after.get('cast')!='Instant' or after.get('cooldown') not in ('',None)
        or after.get('name')!=name or match.group('school').lower()!='nature'
        or cost.group('resource')!='Mana' or int(match.group('mins'))<=0):
        raise ValueError('UNPARSED_REACTIVE_AURA_SEMANTICS')
    return {'spell_id':sid,'name':name,'level':learn,'resource_id':'mana',
        'mana_cost':int(cost.group('amount')),'duration_s':int(match.group('mins'))*60,
        'reactive_damage':int(match.group('damage')),'school':match.group('school'),
        'source_url':url,'source_authority':'canonical_forever_spell_index_after_tooltip',
        'acquisition_status':'INDEX_TRAINING_HINT_NOT_INDEPENDENTLY_VERIFIED'}

_MARK_SHAPE = re.compile(
    r"^Increases the friendly target's armor by (?P<armor>\d+)"
    r"(?: and all attributes by (?P<attributes>\d+))?"
    r"(?:, all attributes by (?P<attributes_with_resist>\d+) and all resistances by (?P<resistances>\d+))?"
    r" for (?P<hours>\d+) hour(?:s)?\.$"
)


def latest_stat_maintenance_rank(class_key: str, family_name: str, level: int, *, db_path: Path | None = None) -> dict | None:
    """Compile only literal, exact indexed stat-aura ranks; no fallback facts.

    Acquisition and derived-stat completeness are deliberately not certified by
    the index. The caller must keep those separate from executable effects.
    """
    path = Path(db_path or active_ability_db(DEFAULT_DB))
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as conn:
        row = conn.execute('''SELECT spell_id,name,level_hint,raw_listview_json,source_url
          FROM spell_index WHERE class_key=? AND kind='abilities' AND name=?
            AND level_hint BETWEEN 1 AND ? ORDER BY level_hint DESC,spell_id DESC LIMIT 1''',
                           (class_key.lower(), family_name, int(level))).fetchone()
    if row is None:
        return None
    sid, name, learn, raw_text, url = row
    raw = json.loads(raw_text)
    if (raw.get('id'),raw.get('name'),raw.get('level')) != (sid,name,learn):
        raise ValueError('STAT_AURA_SOURCE_IDENTITY_CONFLICT')
    env = raw.get('envChange') or {}
    if env.get('status') == 'removed':
        raise ValueError('LATEST_STAT_AURA_REMOVED')
    after = env.get('after')
    if not isinstance(after,dict):
        raise ValueError('STAT_AURA_NEEDS_UNAMBIGUOUS_AFTER_TOOLTIP')
    match = _MARK_SHAPE.fullmatch(str(after.get('text', '')))
    cost = _COST.fullmatch(str(after.get('cost','')))
    if (not match or not cost or after.get('cast') != 'Instant'
            or after.get('cooldown') not in ('',None)
            or after.get('name') != name or cost.group('resource') != 'Mana'
            or int(match.group('hours')) <= 0):
        raise ValueError('UNPARSED_STAT_AURA_SEMANTICS')
    return {'spell_id': sid, 'name': name, 'level': learn,
            'mana_cost': int(cost.group('amount')), 'duration_s': int(match.group('hours')) * 3600,
            'armor': int(match.group('armor')),
            'attributes': int(match.group('attributes') or match.group('attributes_with_resist') or 0),
            'resistances':int(match.group('resistances') or 0),
            'source_url': url,
            'source_authority': 'canonical_forever_spell_index_after_tooltip',
            'acquisition_status': 'INDEX_TRAINING_HINT_NOT_INDEPENDENTLY_VERIFIED'}
