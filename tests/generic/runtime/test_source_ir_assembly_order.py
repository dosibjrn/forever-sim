"""Guard the production legacy GameIR source pipeline while Rust callers migrate.

The stages are replaced only for this order/DB-scope contract test. The
existing source-paid regressions separately exercise real source data.
"""
from importlib import import_module

import pytest

from src.game.data.forever import source_ir_assembly


_TOP_LEVEL_STAGES = (
    "source_enrich_action_ranks",
    "source_enrich_area_actions",
    "source_enrich_indexed_talents",
    "source_enrich_primary_stats",
    "source_enrich_target_combat",
    "source_enrich_incoming_world",
)
_DYNAMIC_STAGES = (
    ("source_stage_isolation", "strip_precompiled_source_actions"),
    ("source_ability_semantics", "source_ability_actions"),
    ("source_checkpoint_talent_stage", "source_enrich_control_target_caps"),
    ("source_control_action_compiler", "source_control_actions"),
    ("source_queued_swing", "source_queued_swing_actions"),
    ("source_enemy_melee_ap_debuff", "source_enemy_melee_ap_debuff_actions"),
    ("source_reactive_control", "source_reactive_control_actions"),
    ("source_stealth_actions", "source_stealth_actions"),
    ("source_enemy_melee_ap_debuff", "source_enrich_enemy_melee_ap_incoming"),
    ("source_indexed_action_coverage", "attach_indexed_ability_coverage"),
)


@pytest.mark.parametrize("use_staged_db", [False, True])
def test_assembly_retains_stage_order_and_primary_stat_db_scope(
    monkeypatch, tmp_path, use_staged_db
):
    calls = []

    def trace(stage):
        def apply(ir, **kwargs):
            calls.append((stage, kwargs))
            return ir + (stage,)
        return apply

    for stage in _TOP_LEVEL_STAGES:
        monkeypatch.setattr(source_ir_assembly, stage, trace(stage))
    for module, stage in _DYNAMIC_STAGES:
        target = import_module(f"src.game.data.forever.{module}")
        monkeypatch.setattr(target, stage, trace(stage))

    staged_db = tmp_path / "staged.sqlite" if use_staged_db else None
    result = source_ir_assembly.assemble_source_ir(
        (), class_key=" DRUID ", level=30, ability_db_path=staged_db
    )

    initial = ["source_ability_actions"]
    if use_staged_db:
        initial = [
            "strip_precompiled_source_actions",
            "source_ability_actions",
            "source_enrich_control_target_caps",
        ]
    expected = initial + [
        "source_control_actions",
        "source_queued_swing_actions",
        "source_enemy_melee_ap_debuff_actions",
        "source_reactive_control_actions",
        "source_stealth_actions",
        "source_enrich_action_ranks",
        "source_enrich_area_actions",
        "source_enrich_indexed_talents",
        "source_enrich_primary_stats",
        "source_enrich_target_combat",
        "source_enrich_incoming_world",
        "source_enrich_enemy_melee_ap_incoming",
        "attach_indexed_ability_coverage",
    ]
    assert result == tuple(expected)
    assert [stage for stage, _ in calls] == expected
    arguments = dict(calls)
    assert arguments["source_enrich_primary_stats"] == {"db_path": staged_db}
    assert arguments["source_enrich_target_combat"] == {}
    assert arguments["source_ability_actions"] == {
        "class_key": "druid", "level": 30, "db_path": staged_db
    }
    assert arguments["attach_indexed_ability_coverage"] == {
        "class_key": "druid", "level": 30, "db_path": staged_db
    }
