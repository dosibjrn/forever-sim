from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import quote

from src.rulesets.forever.items.catalogue import ItemCatalogue, extract_wowhead_item_id
from src.rulesets.forever.items.runtime_selection import catalogue_path, item_vector
from src.rulesets.forever.items.wowhead_queries import CANONICAL_CLASS_QUERIES, WOWHEAD_FOREVER_BASE

_ID_RE = re.compile(r"^\s*#?(\d+)\s*$")


def parse_item_id(value: Any) -> int:
    if isinstance(value, int):
        return int(value)
    text = str(value or '').strip()
    m = _ID_RE.match(text)
    if m:
        return int(m.group(1))
    found = extract_wowhead_item_id(text)
    if found is None:
        raise ValueError('item must be an exact item ID or Wowhead Forever item URL')
    return int(found)


def item_payload(item_id: int) -> dict[str, Any]:
    path = catalogue_path()
    with ItemCatalogue(path) as cat:
        item = cat.get_item(int(item_id))
    if item is None:
        raise ValueError(f'item #{item_id} is not in the canonical catalogue')
    return {
        'item_id': int(item.item_id), 'name': item.name, 'slot': item.slot,
        'required_level': item.required_level, 'item_level': item.item_level,
        'weapon_type': item.weapon_type, 'vector': item_vector(item),
        'url': f'https://www.wowhead.com/forever/item={int(item.item_id)}',
    }


def _normalized_weights(raw: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    aliases = {'attack power': 'attack_power', 'spell power': 'spell_power', 'weapon dps': 'weapon_dps', 'wand dps': 'wand_dps'}
    for k, v in dict(raw or {}).items():
        key = aliases.get(str(k).strip().lower(), str(k).strip().lower().replace(' ', '_'))
        try: x = float(v)
        except (TypeError, ValueError): continue
        if x != 0: out[key] = x
    return out


def weighted_item_score(payload: Mapping[str, Any], weights: Mapping[str, Any]) -> tuple[float, dict[str, float]]:
    w = _normalized_weights(weights)
    vec = dict(payload.get('vector') or {})
    contributions = {k: float(wv) * float(vec.get(k, 0.0) or 0.0) for k, wv in w.items() if float(vec.get(k, 0.0) or 0.0) != 0.0}
    return sum(contributions.values()), contributions


def compare_items(item_a: Any, item_b: Any, weights: Mapping[str, Any]) -> dict[str, Any]:
    a = item_payload(parse_item_id(item_a)); b = item_payload(parse_item_id(item_b))
    sa, ca = weighted_item_score(a, weights); sb, cb = weighted_item_score(b, weights)
    keys = sorted(set(a['vector']) | set(b['vector']))
    delta = {k: float(b['vector'].get(k, 0.0) or 0.0)-float(a['vector'].get(k, 0.0) or 0.0) for k in keys}
    delta = {k:v for k,v in delta.items() if abs(v)>1e-12}
    return {
        'authority': 'published_stat_weight_approximation',
        'item_a': a, 'item_b': b, 'score_a': sa, 'score_b': sb, 'score_delta_b_minus_a': sb-sa,
        'winner': 'b' if sb>sa else ('a' if sa>sb else 'tie'), 'stat_delta_b_minus_a': delta,
        'contributions_a': ca, 'contributions_b': cb,
        'note': 'Approximation only: selected-level published stat weights; not a full combat rescore.',
    }


def wowhead_upgrade_search(class_name: str, level: int, weights: Mapping[str, Any], *, slot: str | None = None) -> dict[str, Any]:
    cls = str(class_name).lower()
    query = CANONICAL_CLASS_QUERIES.get(cls)
    if query is None:
        raise ValueError(f'no canonical Wowhead class query for {class_name}')
    # We have a reviewed class/side/listview query, but no reviewed mapping from our
    # normalized stat names to Wowhead numeric filter IDs. Do not fabricate it.
    path = f"{WOWHEAD_FOREVER_BASE}/max-level:{max(1,int(level)+5)}/side:{query.side}/class:{query.class_id}"
    url = f"{path}?filter={query.filter_expr}"
    supported = []
    omitted = sorted(_normalized_weights(weights))
    return {
        'url': url, 'slot': slot, 'level': int(level), 'class_name': cls,
        'applied_weight_filters': supported, 'omitted_weight_filters': omitted,
        'note': 'Class/level search is source-backed. Stat-weight filter IDs are intentionally omitted until their Wowhead query mapping is verified.'
    }
