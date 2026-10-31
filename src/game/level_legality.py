"""Scorer-independent, fail-closed legality oracle for source-backed level steps.

This checks a *representative source scenario*, not full playable-race or
item-acquisition coverage. The only currently proven gear scenario is naked.
No event simulator, legacy scorer, or route search is imported here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import validate_talent_selection, available_talent_points, apply_talent_selection


@dataclass(frozen=True)
class LevelState:
    class_key: str
    level: int
    race_key: str
    talents: Mapping[str, int]
    action_ids: tuple[str, ...]
    gear_scenario: str = "source_actor_naked"
    selected_items: tuple[str, ...] = ()
    # Real world states need an independently sourced origin and replayable
    # acquisition transactions. Empty defaults preserve bounded scenarios.
    world_origin_id: str | None = None
    world_acquisition_events: tuple[dict, ...] = ()


def require_exact_talent_ranks(talents: Mapping[str, int]) -> None:
    """Reject coerced fractional/boolean ranks before canonical validator."""
    if any(type(rank) is not int for rank in talents.values()):
        raise ValueError("talent ranks must be exact integers")


def _canonical_state(state: LevelState):
    """Check identity, talent, rank/action and bounded gear independently."""
    if not isinstance(state.level, int) or isinstance(state.level, bool):
        raise ValueError("level must be an integer")
    ir = build_game_ir_slice(class_key=state.class_key, level=state.level)
    if ir is None:
        raise ValueError("no source-backed class/level")
    actor_meta = ir.actor.metadata
    if actor_meta.get("class_key") != state.class_key:
        raise ValueError("class identity mismatch")
    if int(actor_meta.get("level", -1)) != state.level:
        raise ValueError("source level mismatch")
    # This is a source-backed *scenario race*, not a list of playable races.
    if actor_meta.get("race_key") != state.race_key:
        raise ValueError("race not verified for this source scenario")
    require_exact_talent_ranks(state.talents)
    validate_talent_selection(ir, state.talents, level=state.level)
    if not state.action_ids or len(state.action_ids) != len(set(state.action_ids)):
        raise ValueError("action ids must be nonempty and unique")
    # Talent-granted actions must be checked against the SAME fully modified
    # canonical IR as the combat scorer, not the raw untalented provider.
    executable, _ = apply_talent_selection(ir, state.talents, level=state.level)
    known_actions = {action.id: action for action in executable.actions}
    if not set(state.action_ids).issubset(known_actions):
        raise ValueError("action/rank unavailable at level")
    if any(not known_actions[aid].provenance for aid in state.action_ids):
        raise ValueError("action missing source provenance")
    # No named item verifier yet. Refuse to infer item legality from a name or
    # caller-supplied level, even when an item happens to exist in the DB.
    if state.gear_scenario != "source_actor_naked" or state.selected_items:
        raise ValueError("named gear legality not independently verified")
    return ir


def validate_level_state(state: LevelState, *, require_world_acquisition: bool = False, world_db_path=None) -> dict:
    ir = _canonical_state(state)
    if require_world_acquisition:
        # Real route admission must NOT treat indexed ranks as already learned.
        # A verified trainer/quest/rune *event* is required before acceptance.
        from src.game.data.forever.source_acquisition import audit_learned_action_legality
        from src.game.talents import apply_talent_selection
        executable, _ = apply_talent_selection(ir, state.talents, level=state.level)
        report = audit_learned_action_legality(executable, level=state.level,
                                               action_ids=state.action_ids,
                                               world_anchor_id=state.world_origin_id,
                                               world_events=state.world_acquisition_events,db_path=world_db_path)
        if not report['complete']:
            raise ValueError('world acquisition not verified: ' +
                             ', '.join(sorted({r['status'] for r in report['blockers']})))
    return {
        "status": "LEGAL_SOURCE_SCENARIO", "class_key": state.class_key,
        "race_key": state.race_key, "level": state.level,
        "talents": {k: int(v) for k, v in state.talents.items()},
        "action_ids": list(state.action_ids),
        "gear_scenario": state.gear_scenario,
        "gear_verified": "naked_only", "race_verified": "representative_scenario_only",
        "ruleset": ir.ruleset,
    }


def validate_level_transition(parent: LevelState, child: LevelState, *,
                              require_world_acquisition: bool = False) -> dict:
    if parent.class_key != child.class_key:
        raise ValueError("class identity mismatch in level transition")
    if parent.race_key != child.race_key:
        raise ValueError("race change in level transition")
    if child.level != parent.level + 1:
        raise ValueError("nonconsecutive level transition")
    before = validate_level_state(parent, require_world_acquisition=require_world_acquisition)
    after = validate_level_state(child, require_world_acquisition=require_world_acquisition)
    if before["ruleset"] != after["ruleset"]:
        raise ValueError("ruleset change in level transition")
    if parent.gear_scenario != child.gear_scenario or parent.selected_items != child.selected_items:
        raise ValueError("unverified gear acquisition in level transition")
    parent_talents = {str(k): int(v) for k, v in parent.talents.items() if v}
    child_talents = {str(k): int(v) for k, v in child.talents.items() if v}
    for key, rank in parent_talents.items():
        if child_talents.get(key, 0) < rank:
            raise ValueError("talent refund/respec without legal transition")
    changes = {key: child_talents.get(key, 0) - parent_talents.get(key, 0)
               for key in set(parent_talents) | set(child_talents)}
    spent = sum(changes.values())
    # Banked unspent points may be spent later; no points can be conjured.
    if spent < 0 or spent > available_talent_points(child.level) - sum(parent_talents.values()):
        raise ValueError("talent transition exceeds earned unspent points")
    return {
        "status": "LEGAL_SOURCE_TRANSITION", "from_level": parent.level,
        "to_level": child.level, "class_key": parent.class_key,
        "race_key": parent.race_key, "ruleset": before["ruleset"],
        "talent_changes": {k: v for k, v in sorted(changes.items()) if v},
        "spent_new_points": spent,
        "available_unspent_after": available_talent_points(child.level) - sum(child_talents.values()),
        "gear_status": "naked_only", "race_status": "representative_scenario_only",
        "resource_carry_forward_proven": False,
        "route_complete": False, "optimization_ready": False,
    }
