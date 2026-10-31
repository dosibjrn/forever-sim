from __future__ import annotations
"""Promote indexed Forever ability ranks into existing generic Game IR actions.

Only simple action shapes whose complete numeric effects can be parsed are
promoted. The indexed listview capture is a versioned *source*, not a guessed
rank curve. Unparseable higher ranks remain explicit coverage gaps.
"""
from dataclasses import replace
import json
import re
import sqlite3
from typing import Any

from src.game.model.ir import (ControlEffect, DamageEffect, HealEffect, PeriodicEffect,
                               PeriodicHealEffect, ResourceCost)
from .sqlite_talents import DEFAULT_DB, _slug
from .source_db_scope import active_ability_db

_NUM = r'(\d+(?:\.\d+)?)'
_IMMOBILIZE = re.compile(r'\bfreezes?\b[^.]*?\bin place\b[^.]*?\bfor\s+(?:up\s+to\s+)?' + _NUM + r'\s+sec\b', re.I)


def _seconds(raw: str, *, instant: bool = False) -> float | None:
    if raw.strip().lower() == 'instant':
        return 0.0 if instant else None
    m = re.fullmatch(r'\s*' + _NUM + r'\s+sec(?:onds?)?(?:\s+(?:cast|cooldown))?\s*', raw, re.I)
    return float(m.group(1)) if m else (0.0 if not raw.strip() and not instant else None)


def _source_range_match(raw: str):
    """Parse only a verified numeric yard range; never guess a missing range."""
    text = raw.strip()
    if not text:
        return None
    return re.fullmatch(r'(\d+(?:\.\d+)?)\s+yd\s+range', text, re.I)


def _parsed_effect(template, tooltip: str, source: dict[str, Any]):
    """Parse the *entire* effect from a sourced tooltip; no damage fallback."""
    ref = (source,)
    if isinstance(template, DamageEffect):
        school = re.escape(template.school)
        m = re.search(_NUM + r'\s+to\s+' + _NUM + r'\s+' + school + r'\s+damage', tooltip, re.I)
        if m is None:
            m = re.search(r'(?:causes?|deals?|for)\s+' + _NUM + r'\s+' + school + r'\s+damage(?!\s+over)', tooltip, re.I)
            if m is None:
                return None
            lo = hi = float(m.group(1))
        else:
            lo, hi = float(m.group(1)), float(m.group(2))
        return replace(template, base_min=lo, base_max=hi,
                       spell_power_coefficient=(float(source['spell_power_coefficient'])
                           if source.get('spell_power_coefficient') is not None
                           else template.spell_power_coefficient),
                       field_provenance={**template.field_provenance, 'base_damage': ref,
                           'spell_power_coefficient': ref if source.get('spell_power_coefficient') is not None
                           else template.field_provenance.get('spell_power_coefficient', ())})
    if isinstance(template, PeriodicEffect):
        school = re.escape(template.school)
        # Additional damage in a mixed direct + periodic spell, or a pure DoT.
        m = re.search(r'(?:additional\s+|causes?\s+)' + _NUM + r'\s+' + school +
                      r'\s+damage\s+over\s+' + _NUM + r'\s+sec', tooltip, re.I)
        if m is None:
            return None
        total, duration = float(m.group(1)), float(m.group(2))
        if duration <= 0 or duration % template.tick_interval_s > 1e-7:
            return None
        return replace(template, total_base_damage=total, duration_s=duration,
                       aura_id=template.aura_id, field_provenance={
                           **template.field_provenance, 'total_base_damage': ref,
                           'duration_s': ref})
    if isinstance(template, ControlEffect):
        # A timed immobilize is only executable when the full source tooltip
        # explicitly identifies both the effect and its duration.
        if template.control_id not in ('root', 'frozen'):
            return None
        match = _IMMOBILIZE.search(tooltip)
        if match is None or float(match.group(1)) <= 0:
            return None
        return replace(template, duration_s=float(match.group(1)))
    if isinstance(template, HealEffect):
        m = re.search(r'\bfor\s+' + _NUM + r'\s+to\s+' + _NUM + r'\b', tooltip, re.I)
        if not m:
            return None
        return replace(template, base_min=float(m.group(1)), base_max=float(m.group(2)),
                       field_provenance={**template.field_provenance, 'base_heal': ref})
    if isinstance(template, PeriodicHealEffect):
        m = re.search(r'\b(?:of|for)\s+' + _NUM + r'\s+(?:damage|health)\s+over\s+' + _NUM + r'\s+sec', tooltip, re.I)
        if not m:
            return None
        total, duration = float(m.group(1)), float(m.group(2))
        if duration <= 0 or duration % template.tick_interval_s > 1e-7:
            return None
        return replace(template, total_base_heal=total, duration_s=duration,
                       field_provenance={**template.field_provenance, 'total_base_heal': ref})
    return None


def _parse_rank(action, row):
    spell_id, rank, level, batch_id, url, raw = row
    payload = json.loads(raw)
    change = payload.get('envChange') or {}
    after = change.get('after') or {}
    if not after or not after.get('text'):
        return None, 'rank_tooltip_missing'
    cast = _seconds(str(after.get('cast') or ''), instant=True)
    cooldown = _seconds(str(after.get('cooldown') or ''), instant=False)
    cost_text = str(after.get('cost') or '')
    range_text = str(after.get('range') or '').strip()
    range_match = _source_range_match(range_text)
    if range_text and range_match is None:
        return None, 'rank_range_unverified'
    cost_match = re.fullmatch(r'\s*' + _NUM + r'\s+Mana\s*', cost_text, re.I)
    if cast is None or cooldown is None or not cost_match:
        return None, 'cast_cooldown_or_mana_cost_unverified'
    if len(action.costs) != 1 or action.costs[0].resource_id != 'mana':
        return None, 'unsupported_resource_cost_shape'
    source = {'authority': 'wowhead_forever_index_capture', 'source_url': url,
              'spell_power_coefficient': after.get('spell_power_coefficient'),
              'capture_batch_id': batch_id, 'spell_id': spell_id, 'rank': rank,
              'required_level': level, 'tooltip': after['text']}
    parsed = tuple(_parsed_effect(e, after['text'], source) for e in action.effects)
    if any(e is None for e in parsed):
        return None, 'effect_not_fully_normalized'
    requirements = tuple(req for req in action.requirements if req.get('kind') != 'minimum_level')
    return replace(action, id=f'{action.family_key}:{spell_id}',
                   name=f'{payload.get("name") or action.name} R{rank}',
                   requirements=(*requirements, {'kind': 'minimum_level', 'value': level}),
                   costs=(ResourceCost('mana', float(cost_match.group(1))),),
                   cast_time_s=cast, cooldown_s=cooldown,
                   effects=parsed, provenance=(source,),
                   metadata={**action.metadata, **({'range_yards': float(range_match.group(1))} if range_match else {}),
                       'rank_source': source,
                       'source_spell_power_coefficient_verified':source.get('spell_power_coefficient') is not None}), None


def source_enrich_action_ranks(ir):
    """Source-driven cross-class rank promotion; no class/ability whitelists.

    An action with unsupported effect shapes is left intact, and its rank
    coverage is not falsely marked complete. No default proxy rank is added.
    """
    if ir is None:
        return None
    class_key = str(ir.actor.metadata.get('class_key') or '').lower()
    level = int(ir.actor.metadata.get('level') or 0)
    with sqlite3.connect(active_ability_db(DEFAULT_DB)) as conn:
        verified = {}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_spell_rank_facts'").fetchone():
            verified = {int(r[0]): r for r in conn.execute("SELECT spell_id, cast_time_s, mana_cost, cooldown_s, tooltip_text, source_url, source_build, captured_at, spell_power_coefficient FROM verified_spell_rank_facts WHERE class_key=?", (class_key,))}
        rows = conn.execute('''SELECT spell_id, rank_hint, level_hint, batch_id,
                                    source_url, raw_listview_json, name
            FROM spell_index WHERE class_key=? AND kind='abilities'
            AND rank_hint IS NOT NULL AND level_hint <= ?''', (class_key, level)).fetchall()
    by_family = {}
    by_id = {}
    for spell_id, rank, reqlevel, batch, url, raw, name in rows:
        if rank is None or reqlevel is None:
            continue
        row = (int(spell_id), int(rank), int(reqlevel), batch, url, raw)
        if int(spell_id) in verified:
            vr = verified[int(spell_id)]
            d = json.loads(raw)
            d['envChange'] = {'after': {'cast': f'{vr[1]} sec cast' if vr[1] else 'Instant',
                'cooldown': f'{vr[3]} sec cooldown' if vr[3] else '',
                'cost': f'{vr[2]} Mana', 'text': vr[4],
                'range': (d.get('envChange') or {}).get('after', {}).get('range', ''),
                'spell_power_coefficient':vr[8]}}
            row = (int(spell_id), int(rank), int(reqlevel),
                   f'{vr[6]}:{vr[7]}', vr[5], json.dumps(d))
        by_family.setdefault(_slug(name), []).append(row)
        by_id[int(spell_id)] = row
    upgraded, blockers, mapped = [], [], {}
    for action in ir.actions:
        # Exact source-indexed semantic actions are already bound to their
        # independently verified spell ID and rank. Rank-up promotion here
        # would overwrite a lower-rank action with a different indexed rank,
        # corrupt provenance and duplicate the latest action in the frontier.
        if action.metadata.get('source_semantic_type') is not None:
            upgraded.append(action)
            continue
        if not action.effects or not action.costs:
            upgraded.append(action)
            continue
        candidates = by_family.get(action.family_key, [])
        try:
            original_id = int(action.id.rsplit(':', 1)[-1])
        except ValueError:
            upgraded.append(action)
            continue
        current = by_id.get(original_id)
        if current is None:
            upgraded.append(action)
            continue
        # Only the highest source rank <= player level is relevant to the
        # normal leveling rank-up policy. Never downrank by accident.
        latest_rank = max((row[1] for row in candidates), default=current[1])
        if latest_rank <= current[1]:
            upgraded.append(action)
            continue
        choices = []
        failures = []
        for candidate in candidates:
            if candidate[1] != latest_rank:
                continue
            result, failure = _parse_rank(action, candidate)
            if result is None:
                failures.append((candidate, failure))
            else:
                choices.append((candidate, result))
        # Alternate spell chains with the same family/rank may be NPC or
        # variant spells. The previous rank's cooldown is a source-backed
        # identity discriminator, not a preference for higher damage.
        if len(choices) > 1:
            matched = [(row, parsed) for row, parsed in choices
                       if abs(parsed.cooldown_s - action.cooldown_s) < 1e-9]
            choices = matched if len(matched) == 1 else []
        # Blockers for an executable upgrade must cite the selected source
        # row, never a same-rank alternate that lost the identity match.
        latest = (choices[0][0] if len(choices) == 1 else
                  max((row for row in candidates if row[1] == latest_rank),
                      key=lambda row: (row[2], row[0])))
        parsed, reason = (choices[0][1], None) if len(choices) == 1 else (
            None, 'ambiguous_rank_spell_chain' if len(choices) > 1 else
            ('ambiguous_rank_spell_chain' if not failures else failures[0][1]))
        if parsed is None:
            blockers.append({'code': 'source_rank_not_executable', 'family': action.family_key,
                             'spell_id': latest[0], 'rank': latest[1], 'reason': reason,
                             'source_url': latest[4]})
            upgraded.append(action)
            continue
        mapped[action.id] = parsed.id
        if any(isinstance(e, DamageEffect) for e in parsed.effects) and not parsed.metadata.get('source_spell_power_coefficient_verified'):
            blockers.append({'code':'source_rank_spell_power_coefficient_unverified',
                'family':action.family_key,'spell_id':latest[0],
                'source_url':latest[4]})
        if 'slow' in str(parsed.metadata.get('rank_source',{}).get('tooltip','')).lower() and not any(isinstance(e, ControlEffect) for e in parsed.effects):
            blockers.append({'code':'source_rank_movement_slow_unmodeled',
                'family':action.family_key,'spell_id':latest[0],
                'source_url':latest[4]})
        if any(isinstance(e, PeriodicEffect) for e in parsed.effects):
            blockers.append({'code':'source_rank_periodic_scaling_unverified',
                'family':action.family_key,'spell_id':latest[0],
                'source_url':latest[4]})
        upgraded.append(parsed)
    policies = []
    for policy in ir.policies:
        rules = tuple(replace(rule, action_id=mapped.get(rule.action_id, rule.action_id))
                      for rule in policy.rules)
        policies.append(replace(policy, rules=rules))
    missing_ability_families=sorted(set(by_family)-{a.family_key for a in upgraded})
    if missing_ability_families:
        blockers.append({'code':'source_index_ability_families_not_executable',
            'count':len(missing_ability_families),
            'families':missing_ability_families})
    return replace(ir, actions=tuple(upgraded), policies=tuple(policies),
                   unsupported_semantics=(*ir.unsupported_semantics, *blockers),
                   source_facts=(*ir.source_facts, {'family': 'source_rank_promotion',
                       'rank_upgrades': mapped, 'unverified_upgrades': blockers,
                       'authority': 'canonical_sqlite_spell_index',
                       'source_status': 'indexed_capture_not_live_verified'},))
