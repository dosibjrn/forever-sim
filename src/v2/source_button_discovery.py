"""Generic, conservative source-IR combat button discovery.

Discovery is not policy evaluation: unsupported effects/requirements are reported,
not silently treated as executable. No class/spell/level identity is hardcoded.
"""
from __future__ import annotations

from src.game.runtime.effect_capabilities import effect_role
from math import isfinite

_SUPPORTED_REQ = {'minimum_level', 'mode_is', 'aura_present', 'aura_any_present'}


def discover_source_combat_buttons(ir, *, level: int, include_resource_actions: bool = False,
                                   mode_id: str | None = None,
                                   attacker_relative_position: str | None = None) -> dict:
    """Discover source actions; resource support is explicit opt-in."""
    initial = [mode for mode in ir.modes if mode.initial]
    if len(initial) > 1 or (ir.modes and not initial):
        raise ValueError('ambiguous initial mode in source IR')
    if mode_id is not None:
        matching = [mode for mode in ir.modes if mode.id == mode_id]
        if len(matching) != 1:
            raise ValueError('requested combat mode is not source-defined')
        active_mode = matching[0]
    else:
        active_mode = initial[0] if initial else None
    enabled = (set(active_mode.enabled_action_ids)
               if active_mode and active_mode.enabled_action_ids is not None else None)
    offensive_roles = {"direct_damage", "periodic_damage", "target_debuff", "combat_enabler", "control"}
    if include_resource_actions:
        offensive_roles.add("resource")
    resource_ids = {r.id for r in ir.resources}
    seen = set()
    available, excluded = [], []
    for action in ir.actions:
        if action.id in seen:
            raise ValueError('duplicate source action id')
        seen.add(action.id)
        reason = None
        if action.owner_actor_id != ir.actor.id:
            reason = 'owned_by_companion_not_primary_actor'
        elif not action.provenance:
            reason = 'missing_provenance'
        elif any(effect_role(e) is None for e in action.effects):
            reason = "unexecutable_effect"
        elif not action.effects or not any(effect_role(e) in offensive_roles for e in action.effects):
            reason = 'not_offensive'
        elif enabled is not None and action.id not in enabled:
            reason = 'unavailable_selected_mode' if mode_id is not None else 'unavailable_initial_mode'
        else:
            for requirement in action.requirements:
                kind = requirement.get('kind')
                if kind not in _SUPPORTED_REQ and kind not in ('resource_min','relative_position_is'):
                    reason = 'unsupported_requirement:' + str(kind)
                    break
                if kind == 'relative_position_is':
                    if attacker_relative_position is None or requirement.get('value') != attacker_relative_position:
                        reason = 'position_not_established'
                        break
                if kind == 'minimum_level':
                    try:
                        minimum = int(requirement['value'])
                    except (KeyError, ValueError, TypeError):
                        reason = 'invalid_minimum_level'
                        break
                    if level < minimum:
                        reason = 'level_locked'
                        break
                if kind == 'mode_is' and (not active_mode or requirement.get('value') != active_mode.id):
                    reason = 'mode_locked'
                    break
                if kind == 'aura_any_present':
                    ids = requirement.get('aura_ids')
                    if not isinstance(ids,(list,tuple)) or not ids or not all(isinstance(i,str) and i for i in ids) or requirement.get('scope','actor') not in ('actor','target'):
                        reason = 'invalid_aura_any_requirement'
                        break
                if kind == 'aura_present':
                    if not requirement.get('aura_id') or requirement.get('scope','actor') not in ('actor','target'):
                        reason = 'invalid_aura_requirement'
                        break
                if kind == 'resource_min':
                    try:
                        value = float(requirement['value'])
                    except (KeyError, ValueError, TypeError):
                        reason = 'invalid_resource_min'
                        break
                    if not isfinite(value) or value < 0 or requirement.get('resource_id') not in resource_ids:
                        reason = 'invalid_resource_min'
                        break
        if reason:
            excluded.append({'id': action.id, 'reason': reason})
        else:
            available.append(action.id)
    return {'action_ids': available, 'excluded': excluded, 'status': 'DISCOVERED_NOT_EVALUATED',
            'source_ir_id': ir.id, 'selected_mode_id': None if active_mode is None else active_mode.id,
            'complete_policy_search': False,
            'attacker_relative_position': attacker_relative_position}
