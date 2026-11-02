"""Legacy GameIR source-action assembly, separate from provider selection.

This adapter retains the existing gsim/source execution path until its actual
consumers move to the pinned MythicSim Rust backend. It must not become a
second authority for native spell, talent or combat mechanics.
"""
from __future__ import annotations

from src.game.model.ir import GameIRSlice
from .primary_stat_conversions import source_enrich_primary_stats
from .target_combat_source import source_enrich_target_combat
from .source_rank_overlay import source_enrich_action_ranks
from .source_area_overlay import source_enrich_area_actions
from .source_talent_overlay import source_enrich_indexed_talents
from .source_incoming_world import source_enrich_incoming_world


def assemble_source_ir(ir: GameIRSlice, *, class_key: str, level: int,
                       ability_db_path=None) -> GameIRSlice:
    """Apply legacy source overlays in their established order and DB scope.

    The caller owns provider dispatch and the active ability_source_scope.
    Staged canonical-source action replacement occurs before compilation.
    """
    # All nine classes receive the same SQLite-indexed action inventory.  The
    # source compiler remains selective until each effect has executable proof;
    # unseen rows are exposed as typed blockers, not omitted from optimization.
    from .source_ability_semantics import source_ability_actions
    from .source_indexed_action_coverage import attach_indexed_ability_coverage
    key = str(class_key).strip().lower()
    if ability_db_path is not None:
        # The staged source override must replace precompiled default-DB
        # actions before the scoped source compiler adds staged actions.
        from .source_stage_isolation import strip_precompiled_source_actions
        ir = strip_precompiled_source_actions(ir)
    ir = source_ability_actions(ir, class_key=key, level=int(level), db_path=ability_db_path)
    if ability_db_path is not None:
        from pathlib import Path
        from .source_checkpoint_talent_stage import source_enrich_control_target_caps
        ir = source_enrich_control_target_caps(ir,class_key=key,db_path=Path(ability_db_path))
    # Same canonical SQLite scope, same Game IR / executor / joint optimizer.
    # Timed control observations require their own source-verified effect facts;
    # absent observations leave the indexed spell as an explicit blocker.
    from .source_control_action_compiler import source_control_actions
    ir = source_control_actions(ir, class_key=key, level=int(level), db_path=ability_db_path)
    from .source_queued_swing import source_queued_swing_actions
    ir = source_queued_swing_actions(ir, class_key=key, level=int(level), db_path=ability_db_path)
    from .source_enemy_melee_ap_debuff import source_enemy_melee_ap_debuff_actions
    ir = source_enemy_melee_ap_debuff_actions(ir, class_key=key, level=int(level), db_path=ability_db_path)
    from .source_reactive_control import source_reactive_control_actions
    ir = source_reactive_control_actions(ir, class_key=key, level=int(level), db_path=ability_db_path)
    from .source_stealth_actions import source_stealth_actions
    ir = source_stealth_actions(ir, class_key=key, level=int(level), db_path=ability_db_path)
    # Preserve the legacy source-overlay order explicitly. Each step consumes
    # the previous slice; none is an alternative native Rust combat model.
    # Keep the DB override on the same primary-stat enrichment as before.
    ir = source_enrich_action_ranks(ir)
    ir = source_enrich_area_actions(ir)
    ir = source_enrich_indexed_talents(ir)
    ir = source_enrich_primary_stats(ir, db_path=ability_db_path)
    ir = source_enrich_target_combat(ir)
    ir = source_enrich_incoming_world(ir)
    from .source_enemy_melee_ap_debuff import source_enrich_enemy_melee_ap_incoming
    ir = source_enrich_enemy_melee_ap_incoming(ir)
    return attach_indexed_ability_coverage(ir, class_key=key, level=int(level), db_path=ability_db_path)

