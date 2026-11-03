"""Isolate canonical-default source actions before staged SQLite recompilation.

Provider dispatch selects a class; this module owns the source-snapshot
boundary for legacy GameIR. It does not invent or execute combat effects.
"""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.game.model.ir import GameIRSlice


def strip_precompiled_source_actions(ir: GameIRSlice) -> GameIRSlice:
    """Remove only default-source compiled actions that a staged DB replaces.

    Keep all unrelated provider actions; clear affected mode allowlists and
    obsolete indexed-ability coverage facts exactly as the registry did.
    """
    original_ids = {
        action.id for action in ir.actions
        if action.metadata.get("source_semantic_type") is not None
    }
    if not original_ids:
        return ir
    return replace(
        ir,
        actions=tuple(action for action in ir.actions if action.id not in original_ids),
        modes=tuple(
            replace(mode, enabled_action_ids=(
                None if mode.enabled_action_ids is None
                else tuple(action_id for action_id in mode.enabled_action_ids
                           if action_id not in original_ids)
            ))
            for mode in ir.modes
        ),
        source_facts=tuple(
            fact for fact in ir.source_facts
            if not (isinstance(fact, dict)
                    and fact.get("fact_kind") == "source_indexed_executable_ability")
        ),
    )
