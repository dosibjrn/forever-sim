"""Selected-source plumbing regressions for source assembly and its workflow."""

def test_source_assembly_keeps_selected_sqlite_for_shared_scenario_overlays(monkeypatch, tmp_path):
    import importlib
    from src.game.data.forever.source_ir_assembly import assemble_source_ir

    calls = {}
    identity = lambda ir, **kwargs: ir
    no_op_functions = (
        ("source_ability_semantics", "source_ability_actions"),
        ("source_control_action_compiler", "source_control_actions"),
        ("source_queued_swing", "source_queued_swing_actions"),
        ("source_enemy_melee_ap_debuff", "source_enemy_melee_ap_debuff_actions"),
        ("source_reactive_control", "source_reactive_control_actions"),
        ("source_stealth_actions", "source_stealth_actions"),
        ("source_rank_overlay", "source_enrich_action_ranks"),
        ("source_area_overlay", "source_enrich_area_actions"),
        ("source_talent_overlay", "source_enrich_indexed_talents"),
        ("primary_stat_conversions", "source_enrich_primary_stats"),
        ("source_enemy_melee_ap_debuff", "source_enrich_enemy_melee_ap_incoming"),
        ("source_indexed_action_coverage", "attach_indexed_ability_coverage"),
        ("source_stage_isolation", "strip_precompiled_source_actions"),
        ("source_checkpoint_talent_stage", "source_enrich_control_target_caps"),
    )
    for module_name, function_name in no_op_functions:
        module = importlib.import_module(f"src.game.data.forever.{module_name}")
        monkeypatch.setattr(module, function_name, identity)

    def capture(name):
        def apply(ir, **kwargs):
            calls[name] = kwargs.get("db_path")
            return ir
        return apply

    target = importlib.import_module("src.game.data.forever.target_combat_source")
    incoming = importlib.import_module("src.game.data.forever.source_incoming_world")
    monkeypatch.setattr(target, "source_enrich_target_combat", capture("target"))
    monkeypatch.setattr(incoming, "source_enrich_incoming_world", capture("incoming"))

    selected_db = tmp_path / "selected.sqlite"
    selected_db.write_bytes(b"selected-source-fixture")
    ir = object()
    assert assemble_source_ir(
        ir, class_key="druid", level=60, ability_db_path=selected_db
    ) is ir
    assert calls == {"target": selected_db, "incoming": selected_db}

def test_incoming_world_reads_the_explicit_selected_sqlite(tmp_path):
    import sqlite3
    from types import SimpleNamespace
    from src.game.data.forever.source_incoming_world import source_enrich_incoming_world

    selected_db = tmp_path / "selected.sqlite"
    with sqlite3.connect(selected_db) as db:
        db.execute("CREATE TABLE world_incoming_scenario_facts (level INTEGER PRIMARY KEY)")

    ir = SimpleNamespace(
        incoming_attacks=(),
        resources=(SimpleNamespace(id="health"),),
        actor=SimpleNamespace(metadata={"level": 60}),
    )
    assert source_enrich_incoming_world(ir, db_path=selected_db) is ir

def test_druid_talent_overlay_uses_the_selected_source_database(monkeypatch, tmp_path):
    import importlib
    from types import SimpleNamespace

    from src.game.data.forever import druid
    from src.game.model.ir import GameIRSlice

    calls = {}

    mode_resource_facts = importlib.import_module(
        "src.game.data.forever.mode_resource_facts"
    )
    ability_semantics = importlib.import_module(
        "src.game.data.forever.source_ability_semantics"
    )

    def apply_modes(class_key, modes, *, db_path=None):
        calls["mode_resource_facts"] = db_path
        return modes

    def apply_actions(ir, *, class_key, level, db_path=None):
        calls["source_ability_actions"] = db_path
        return ir

    def load_talents(class_key, *, db_path=None, **kwargs):
        calls["load_sqlite_talents"] = db_path
        return SimpleNamespace(
            talents=(),
            tree_rule={"points_per_row": 5},
            captured_count=0,
            expected_count=0,
            batch_id="fixture",
            complete=True,
            blockers=(),
        )

    monkeypatch.setattr(mode_resource_facts, "apply_mode_resource_facts", apply_modes)
    monkeypatch.setattr(ability_semantics, "source_ability_actions", apply_actions)
    monkeypatch.setattr(druid, "load_sqlite_talents", load_talents)

    selected_db = tmp_path / "selected.sqlite"
    ir = GameIRSlice(
        id="test:druid:60",
        ruleset="forever",
        actor=SimpleNamespace(metadata={"class_key": "druid", "level": 60}),
        resources=(),
        actions=(),
    )
    result = druid._with_sqlite_talents(ir, ability_db_path=selected_db)

    assert result is not ir
    assert calls == {
        "mode_resource_facts": selected_db,
        "source_ability_actions": selected_db,
        "load_sqlite_talents": selected_db,
    }

def test_selected_rust_source_workflow_installs_html_parser_dependency():
    from pathlib import Path

    workflow = Path(".github/workflows/rust-upstream-fork.yml").read_text()
    selected_job = workflow.split("  check-selected-rust-source:", 1)[1].split(
        "  sync-fork:", 1
    )[0]
    assert "'beautifulsoup4==4.13.4'" in selected_job
    assert "Install selected-source HTML parser dependency" in selected_job
