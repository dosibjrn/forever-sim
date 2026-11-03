"""Native P2 diagnostic boundary: forward candidates; let MythicSim decide legality."""
from tools import wf_gate_p2_live as p2


def _native_test_binary(tmp_path):
    binary = tmp_path / "engine" / "target" / "debug" / "forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"selected-engine-test-double")
    return binary


def test_native_rank_diagnostic_forwards_pair_without_source_proof(monkeypatch, tmp_path):
    control = {"ferocity": 5, "feral_swiftness": 1}
    candidate = {**control, "predatory_strikes": 1}
    binary = _native_test_binary(tmp_path)
    calls = []
    native_result = {
        "status": "INVALID",
        "reason": "native-owned talent refusal",
        "accepted_for_p2": False,
    }

    def fake_run_native_rank_pair(**kwargs):
        calls.append(kwargs)
        return dict(native_result)

    monkeypatch.setattr(p2, "run_native_rank_pair", fake_run_native_rank_pair)
    result = p2._native_p2_rank_diagnostic(
        str(binary), "predatory_strikes", 1,
        {
            "control_witness": control,
            "witness": candidate,
            # Deliberately contradictory legacy metadata must not veto or
            # rewrite the selected engine's answer.
            "source_rank_facts": {
                "class_key": "mage", "level": 1, "talent_id": "wrong",
                "rank": 99, "rank_cap": 0, "checkpoint_source_l0": None,
            },
        },
        tree_key="feral",
    )

    assert len(calls) == 1
    assert calls[0]["scenario"] == "cat"
    assert calls[0]["before_selection"] == control
    assert calls[0]["after_selection"] == candidate
    assert calls[0]["target_talent_id"] == "predatory_strikes"
    assert calls[0]["target_rank"] == 1
    assert calls[0]["rng_mode"] == p2.NativeRngMode.BALANCED
    assert result == native_result


def test_native_rank_diagnostic_preserves_native_terminal_statuses(monkeypatch, tmp_path):
    binary = _native_test_binary(tmp_path)
    control = {"ferocity": 5}
    candidate = {**control, "predatory_strikes": 1}

    for status in ("INVALID", "UNSUPPORTED", "ERROR", "BLOCKED"):
        native_result = {
            "status": status,
            "reason": "native-owned terminal result",
            "accepted_for_p2": False,
        }
        monkeypatch.setattr(
            p2, "run_native_rank_pair",
            lambda **kwargs: dict(native_result),
        )
        result = p2._native_p2_rank_diagnostic(
            str(binary), "predatory_strikes", 1,
            {"control_witness": control, "witness": candidate},
            tree_key="feral",
        )
        assert result == native_result


def test_native_rank_diagnostic_blocks_only_missing_request_routing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        p2, "run_native_rank_pair",
        lambda **kwargs: calls.append(kwargs) or {"status": "PROBE_PASS"},
    )
    no_pair = p2._native_p2_rank_diagnostic(
        None, "predatory_strikes", 1, {}, tree_key="feral"
    )
    assert no_pair["status"] == "BLOCKED"
    assert no_pair["reason"] == "SOURCE_RANK_PAIR_UNAVAILABLE"

    no_scenario = p2._native_p2_rank_diagnostic(
        None, "predatory_strikes", 1,
        {"control_witness": {}, "witness": {}}, tree_key="unknown",
    )
    assert no_scenario["status"] == "BLOCKED"
    assert no_scenario["reason"] == "NATIVE_P2_TREE_SCENARIO_UNAVAILABLE"
    assert calls == []


def test_druid_l30_plus_defaults_to_the_staged_source_catalogue(tmp_path):
    from src.game.data.forever.sqlite_talents import DEFAULT_DB

    staged = tmp_path / "data" / "forever" / "staged_druid_l30_talents_70338.sqlite"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"sqlite-fixture")
    assert p2._default_p2_source_db(tmp_path, "druid", 60) == staged
    assert p2._default_p2_source_db(tmp_path, "druid", 20) == DEFAULT_DB
    override = tmp_path / "explicit.sqlite"
    assert p2._default_p2_source_db(tmp_path, "druid", 60, override) == override


def test_druid_l30_plus_fails_closed_without_staged_source_catalogue(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="DRUID_P2_STAGED_SOURCE_DB_MISSING"):
        p2._default_p2_source_db(tmp_path, "druid", 60)


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


def test_p2_source_db_diagnostics_report_same_process_file_identity(tmp_path):
    import sqlite3
    from hashlib import sha256
    from pathlib import Path

    from tools.wf_gate_p2_live import _p2_source_db_diagnostics, _sqlite_connection_path

    source_db = tmp_path / "selected.sqlite"
    with sqlite3.connect(source_db) as db:
        db.execute("CREATE TABLE source_fixture (id INTEGER PRIMARY KEY)")
    raw = source_db.read_bytes()
    diagnostics = _p2_source_db_diagnostics(tmp_path, source_db)

    assert diagnostics["cwd"] == str(Path.cwd())
    assert diagnostics["root"] == str(tmp_path.resolve())
    assert diagnostics["source_db_path"] == str(source_db.resolve())
    assert diagnostics["source_db_size_bytes"] == len(raw)
    assert diagnostics["source_db_first_32_bytes_hex"] == raw[:32].hex()
    assert diagnostics["source_db_sha256"] == sha256(raw).hexdigest()
    assert diagnostics["source_db_integrity_check"] == "ok"
    assert _sqlite_connection_path(f"file:{source_db.resolve()}?mode=ro") == str(source_db.resolve())
    assert _sqlite_connection_path(":memory:") is None
