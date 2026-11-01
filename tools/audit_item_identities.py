"""Refresh exact item names from Wowhead's Forever tooltip data.

Stores evidence, never trusts a caller-supplied URL slug as item identity.
Run from the repository root: python tools/audit_item_identities.py
"""
import ast
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import urllib.request
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def catalogue_pairs():
    pairs = set()
    for path in (ROOT / 'src/rulesets/forever').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            kw = {x.arg: x.value.value for x in node.keywords if isinstance(x.value, ast.Constant)}
            url = kw.get('source_url', '')
            match = re.search(r'/item=(\d+)', str(url))
            if not match:
                continue
            idx = 2 if getattr(node.func, 'id', '') == 'CraftedItem' else 0
            name = kw.get('name')
            if not name and len(node.args) > idx and isinstance(node.args[idx], ast.Constant):
                name = node.args[idx].value
            if name:
                pairs.add((str(name), int(match[1])))
    sys.path.insert(0, str(ROOT))
    from src.v2.icon_provenance import _ITEM_ENTITY_FALLBACKS
    pairs.update((name, row['entity_id']) for name, row in _ITEM_ENTITY_FALLBACKS.items())
    return sorted(pairs)


def fetch(pair):
    name, item_id = pair
    url = f'https://nether.wowhead.com/forever/tooltip/item/{item_id}'
    row = {'catalogue_name': name, 'item_id': item_id, 'source_url': url}
    try:
        with urllib.request.urlopen(url, timeout=25) as response:
            data = json.load(response)
        row.update(name=data['name'], icon=data.get('icon'), status='matched' if data['name'] == name else 'mismatch')
    except Exception as exc:
        row.update(status='unresolved', error=str(exc))
    return row


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(fetch, catalogue_pairs()))
    output = ROOT / 'data/forever/item_identity_audit.json'
    output.write_text(json.dumps({'checked_at': datetime.now(timezone.utc).isoformat(), 'scope': 'Item ID/name identity only, not a full stat audit', 'rows': rows}, indent=2) + '\n')
    print(json.dumps({'total':len(rows), 'issues':[r for r in rows if r['status'] != 'matched']}, indent=2))
