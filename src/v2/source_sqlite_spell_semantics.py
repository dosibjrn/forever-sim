"""Non-executable source-linked semantic observations from verified Wowhead text.

This is *not* an executor or completeness oracle: observations describe only the
exact source substring matched. The rest of every spell remains an explicit
coverage blocker, including unmodeled targeting, proc and scaling mechanics.
"""
from __future__ import annotations
import re
from pathlib import Path
from src.v2.source_sqlite_typed_spell_facts import extract_verified_header_facts

_NUM = r'(\d+(?:\.\d+)?)'
_SCHOOL = r'(Arcane|Fire|Frost|Nature|Shadow|Holy)'
_DIRECT = re.compile(r'\b(?:caus(?:es|ing)|take)\s+' + _NUM + r'\s+to\s+' + _NUM + r'\s+' + _SCHOOL + r'\s+damage\b', re.I)
_PERIODIC_HEAL = re.compile(r'\bHeals?\s+(?:your pet|the target)\s+(?:of\s+)?' + _NUM + r'\s+(?:health\s+every\s+second|damage\s+over\s+' + _NUM + r'\s+sec)\b', re.I)
_PERIODIC_DAMAGE = re.compile(r'\b(?:an\s+additional\s+|doing\s+)' + _NUM + r'\s+' + _SCHOOL + r'\s+damage\s+over\s+' + _NUM + r'\s+sec\b', re.I)
_SLOW = re.compile(r'\b(?:slowing\s+movement\s+speed|(?:are\s+)?slowed)\s+by\s+' + _NUM + r'%\s+for\s+' + _NUM + r'\s+sec\b', re.I)
_INTERRUPT = re.compile(r'\binterrupts\s+spellcasting\s+and\s+prevents\s+any\s+spell\s+in\s+that\s+school\s+from\s+being\s+cast\s+for\s+' + _NUM + r'\s+sec\b', re.I)
_RESOURCE = re.compile(r'\bgenerate\s+' + _NUM + r'\s+(Rage|Mana|Energy|Focus)\b', re.I)


def extract_semantic_observations(header: dict) -> dict:
    """Extract independent typed text observations; NEVER promote to runnable IR."""
    if (header.get('execution_status') != 'BLOCKED_UNPARSED_EFFECTS'
            or not header.get('source', {}).get('html_sha256')):
        raise ValueError('verified source header with blocked execution required')
    description = header['unparsed_effect_text']
    observations = []
    occupied = [False] * len(description)

    def add(match, kind, **fields):
        lo, hi = match.span()
        if any(occupied[lo:hi]):
            raise ValueError('overlapping semantic observations; source ambiguity')
        for i in range(lo, hi):
            occupied[i] = True
        observations.append({'kind': kind, **fields, 'source_text': description[lo:hi],
                             'text_span': [lo, hi]})

    for match in _DIRECT.finditer(description):
        low, high = float(match[1]), float(match[2])
        if low <= high:
            add(match, 'direct_school_damage_range', min=low, max=high, school=match[3].lower())
    for match in _PERIODIC_HEAL.finditer(description):
        duration = float(match[2]) if match[2] else None
        if duration is None or duration > 0:
            add(match, 'periodic_heal_description', amount=float(match[1]), duration_seconds=duration)
    for match in _PERIODIC_DAMAGE.finditer(description):
        duration = float(match[3])
        if duration > 0:
            add(match, 'periodic_school_damage_description', amount=float(match[1]),
                school=match[2].lower(), duration_seconds=duration)
    for match in _SLOW.finditer(description):
        percent, duration = float(match[1]), float(match[2])
        if 0 < percent <= 100 and duration > 0:
            add(match, 'movement_slow_description', percent=percent, duration_seconds=duration)
    for match in _INTERRUPT.finditer(description):
        duration = float(match[1])
        if duration > 0:
            add(match, 'school_interrupt_lockout_description', duration_seconds=duration)
    for match in _RESOURCE.finditer(description):
        add(match, 'resource_gain_description', amount=float(match[1]), resource=match[2].lower())

    observations.sort(key=lambda item: item['text_span'])
    residual = ''.join(' ' if occupied[i] else ch for i, ch in enumerate(description)).strip()
    return {'spell_id': header['spell_id'], 'observations': observations,
            'unparsed_text': ' '.join(residual.split()),
            'unparsed_characters': sum(not x and not description[i].isspace() for i, x in enumerate(occupied)),
            'source': header['source'], 'execution_status': 'BLOCKED_UNPARSED_EFFECTS',
            'executable_effects': [], 'semantic_completeness': False}


def extract_verified_semantic_observations(database: str | Path, *, batch_id: str, spell_id: int) -> dict:
    return extract_semantic_observations(extract_verified_header_facts(database, batch_id=batch_id, spell_id=spell_id))
