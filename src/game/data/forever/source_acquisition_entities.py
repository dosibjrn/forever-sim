"""Strict source HTML typed related-listview parser (no JS evaluation)."""
from __future__ import annotations
import json
import re

# Typed source acquisition methods; item *use* is not a learning method.
TYPES = {'taught_by_npc': ('npc', 'taught-by-npc'),
         'taught_by_item': ('item', 'taught-by-item'),
         'reward_from_quest': ('quest', 'reward-from-q')}

def _typed_listview(html: str, anchor: str, template: str) -> list[dict]:
    # Restrict match to a single HTML script tag and exact listview id/template;
    # parse the JS `data` value with a JSON decoder (NEVER eval). This format
    # contains JSON literal data under a JS object, not JSON for the outer args.
    start = 0
    matches = []
    for script in re.finditer(r'<script\b[^>]*>(.*?)</script\s*>', html, re.S | re.I):
        body = script.group(1)
        for m in re.finditer(r'new\s+Listview\s*\(\s*\{', body):
            # One configuration object per new Listview, terminated after its
            # data array and before the next listview. Limited scan by next
            # constructor prevents unrelated tab data being paired.
            part = body[m.end():]
            until = re.search(r'\}\)\s*;|new\s+Listview\s*\(', part)
            if until:
                part = part[:until.start()]
            idmatch = re.search(r"\bid\s*:\s*['\"]([^'\"]+)['\"]", part)
            if not idmatch or idmatch.group(1) != anchor:
                continue
            typematch = re.search(r"\btemplate\s*:\s*['\"]([^'\"]+)['\"]", part)
            if not typematch or typematch.group(1) != template:
                raise ValueError('related tab template mismatched: ' + anchor)
            datamatch = re.search(r'\bdata\s*:\s*', part)
            if not datamatch:
                raise ValueError('related tab has no inline source entries: ' + anchor)
            entries, _ = json.JSONDecoder().raw_decode(part[datamatch.end():])
            if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
                raise ValueError('malformed related entries: ' + anchor)
            matches.append(entries)
    if len(matches) != 1:
        raise ValueError(f'{anchor}: expected exactly one typed source listview, got {len(matches)}')
    return matches[0]


# Canonical relation kind -> (source entity template, typed Wowhead related tab).
TYPES = {'taught_by_npc': ('npc', 'taught-by-npc'),
         'taught_by_item': ('item', 'taught-by-item'),
         'reward_from_quest': ('quest', 'reward-from-q')}
