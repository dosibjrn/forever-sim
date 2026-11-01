"""Conservative Forever Wowhead tooltip header extraction from verified source HTML.

No effect descriptions are interpreted as damage, healing or combat semantics.
Unrecognized fields or conflicting tooltips block executable promotion.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from src.v2.source_sqlite_detail_snapshots import materialize_spell_detail_snapshot


class UnverifiedCombatFacts(ValueError):
    pass


def extract_header_facts(snapshot: dict, *, spell_id: int) -> dict:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise UnverifiedCombatFacts('beautifulsoup4 is required for source HTML parsing') from exc
    soup = BeautifulSoup(snapshot['html'], 'html.parser')
    selectors = [t for t in soup.select('.wowhead-tooltip')
                 if t.get('id') == f'tt{spell_id}' and t.select_one('a.whtt-name')]
    if len(selectors) != 1:
        raise UnverifiedCombatFacts('missing or ambiguous spell-ID-matched visible tooltip')
    tooltip = selectors[0]
    link = tooltip.select_one('a.whtt-name')
    href = link.get('href', '')
    if not re.fullmatch(rf'/forever/spell={spell_id}(?:/[a-z0-9-]+)?', href):
        raise UnverifiedCombatFacts('tooltip link does not match indexed spell ID')
    name = link.get_text(' ', strip=True)
    if not name:
        raise UnverifiedCombatFacts('tooltip has no spell name')
    # The source has three verified DOM layouts: sibling header table, nested
    # table inside the name cell, and bare text next to rank/level.
    # Restrict to the first main tooltip content cell before requirements/effects.
    first_cell = tooltip.select_one('table > tbody > tr > td')
    if first_cell is None:
        raise UnverifiedCombatFacts('missing tooltip header')
    header_copy = BeautifulSoup(str(first_cell), 'html.parser')
    for node in header_copy.select('.q, .wowhead-tooltip-requirements'):
        node.decompose()
    header_text = header_copy.get_text(' ', strip=True)
    costs = re.findall(r'(?<!\w)(\d+(?:\.\d+)?)\s+(Mana|Energy|Rage|Focus)\b', header_text)
    if len(costs) > 1:
        raise UnverifiedCombatFacts('ambiguous resource cost')
    ranges = re.findall(r'(?:\d+ yd range|Melee Range)', header_text)
    if len(ranges) > 1:
        raise UnverifiedCombatFacts('ambiguous range')
    cost = costs[0] if costs else None
    range_candidates = ranges
    requirement = tooltip.select('.wowhead-tooltip-requirements')
    level_matches = [re.fullmatch(r'Requires level (\d+)', el.get_text(' ', strip=True)) for el in requirement]
    levels = [int(m.group(1)) for m in level_matches if m]
    if len(levels) > 1:
        raise UnverifiedCombatFacts('ambiguous required level')
    # Keep text verbatim and exclude hidden formulas: WoW tooltip dynamic formulas are not literal damage facts.
    description = tooltip.select_one('.q')
    if not description:
        raise UnverifiedCombatFacts('missing visible effect description')
    for hidden in description.select('[style*="display:none"]'):
        hidden.decompose()
    effect_text = description.get_text(' ', strip=True)
    if not effect_text:
        raise UnverifiedCombatFacts('empty effect description')
    lineage = snapshot['lineage']
    return {
        'spell_id': spell_id, 'name': name,
        'resource_cost': ({'amount': float(cost[0]), 'resource': cost[1].lower()}
                          if cost else None),
        'range_text': range_candidates[0] if range_candidates else None,
        'required_level': levels[0] if levels else None,
        'unparsed_effect_text': effect_text,
        'source': {**lineage, 'anchor': f'#tt{spell_id} a.whtt-name; adjacent header table; .q'},
        'execution_status': 'BLOCKED_UNPARSED_EFFECTS',
    }


def extract_verified_header_facts(database: str | Path, *, batch_id: str, spell_id: int) -> dict:
    return extract_header_facts(materialize_spell_detail_snapshot(
        database, batch_id=batch_id, spell_id=spell_id), spell_id=spell_id)
