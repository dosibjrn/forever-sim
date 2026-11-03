"""Fail-closed source fact validation for native P2 rank receipts."""
from tools import wf_gate_p2_live as p2


def test_native_rank_diagnostic_requires_checkpoint_source_l0_before_execution():
    result = p2._native_p2_rank_diagnostic(
        None, "moonkin_form", 1,
        {"source_rank_facts": {"talent_id": "moonkin_form"}},
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "CANONICAL_CHECKPOINT_SOURCE_L0_MISSING"


def test_native_rank_diagnostic_checks_source_prerequisite_on_both_pair_members():
    source_url = "https://example.invalid/druid-talent-source"
    prerequisite = {
        "talent_id": "feral_swiftness",
        "required_rank": 2,
    }
    source = {
        "class_key": "druid",
        "level": 60,
        "talent_id": "predatory_strikes",
        "rank": 1,
        "tree_key": "feral",
        "tree_row": 3,
        "rank_cap": 3,
        "source_build": "1.60.1.70338",
        "source_url": source_url,
        "prerequisite": prerequisite,
        "tree_members": ["ferocity", "feral_swiftness", "predatory_strikes"],
        "points_per_row": 5,
        "checkpoint_source_l0": {
            "source_url": source_url,
            "prerequisite": prerequisite,
            "expected_clause_count": 1,
            "effects": [{
                "domain": "form_melee_attack_power_from_level",
                "target": "attack_power",
                "sourced_value": 0.02,
                "condition": "cat_form",
                "source": source_url,
            }],
        },
    }
    # Independently reject an invalid control and an invalid candidate. A
    # single pair where both sides fail would not prove that both are checked.
    invalid_pairs = (
        (
            {"ferocity": 5, "feral_swiftness": 1},
            {"ferocity": 5, "feral_swiftness": 2, "predatory_strikes": 1},
        ),
        (
            {"ferocity": 5, "feral_swiftness": 2},
            {"ferocity": 5, "feral_swiftness": 1, "predatory_strikes": 1},
        ),
    )
    for control_witness, witness in invalid_pairs:
        result = p2._native_p2_rank_diagnostic(
            None,
            "predatory_strikes",
            1,
            {
                "source_rank_facts": source,
                "control_witness": control_witness,
                "witness": witness,
            },
        )
        assert result["status"] == "BLOCKED"
        assert result["reason"] == "SOURCE_RANK_PAIR_PREREQUISITE_NOT_SATISFIED"


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


def test_native_rank_diagnostic_requires_source_tree_tier_points_in_both_pair_members():
    source_url = "https://example.invalid/druid-talent-source"
    source = {
        "class_key": "druid",
        "level": 60,
        "talent_id": "predatory_strikes",
        "rank": 1,
        "tree_key": "feral",
        "tree_row": 3,
        "rank_cap": 3,
        "tree_members": ["ferocity", "feral_swiftness", "predatory_strikes"],
        "points_per_row": 5,
        "source_build": "1.60.1.70338",
        "source_url": source_url,
        "prerequisite": None,
        "checkpoint_source_l0": {
            "source_url": source_url,
            "expected_clause_count": 1,
            "effects": [{
                "domain": "form_melee_attack_power_from_level",
                "target": "attack_power",
                "sourced_value": 0.02,
                "condition": "cat_form",
                "source": source_url,
            }],
        },
    }
    result = p2._native_p2_rank_diagnostic(
        None,
        "predatory_strikes",
        1,
        {
            "source_rank_facts": source,
            "control_witness": {"ferocity": 5, "feral_swiftness": 9},
            "witness": {"ferocity": 5, "feral_swiftness": 9, "predatory_strikes": 1},
        },
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "SOURCE_RANK_PAIR_TIER_NOT_SATISFIED"


def test_native_rank_diagnostic_preserves_bridge_flags_without_gating(tmp_path, monkeypatch):
    source_url = "https://example.invalid/druid-talent-source"
    control = {
        "ferocity": 5,
        "feral_swiftness": 2,
        "feral_instinct": 3,
        "thick_hide": 5,
    }
    candidate = {**control, "predatory_strikes": 1}
    binary = tmp_path / "engine" / "target" / "debug" / "forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"selected-engine-test-double")

    def fake_run_native_rank_pair(**kwargs):
        assert kwargs["before_selection"] == control
        assert kwargs["after_selection"] == candidate
        return {
            "status": "PROBE_PASS",
            "reason": "NATIVE_DPS_INCREASE_OBSERVED",
            "delta_dps": 1.0,
            "accepted_for_p2": False,
        }

    monkeypatch.setattr(p2, "run_native_rank_pair", fake_run_native_rank_pair)
    result = p2._native_p2_rank_diagnostic(
        str(binary),
        "predatory_strikes",
        1,
        {
            "source_rank_facts": {
                "class_key": "druid",
                "level": 60,
                "talent_id": "predatory_strikes",
                "rank": 1,
                "tree_key": "feral",
                "tree_row": 3,
                "rank_cap": 3,
                "source_build": "1.60.1.70338",
                "source_url": source_url,
                "prerequisite": None,
                "tree_members": [
                    "ferocity", "feral_swiftness", "feral_instinct",
                    "thick_hide", "predatory_strikes",
                ],
                "points_per_row": 5,
                "checkpoint_source_l0": {
                    "source_url": source_url,
                    "expected_clause_count": 1,
                    "prerequisite_rank_build_bridge_unverified": True,
                    "unsupported_prerequisite_rank_bridge_unverified": True,
                    "effects": [{
                        "domain": "form_melee_attack_power_from_level",
                        "target": "attack_power",
                        "sourced_value": 0.02,
                        "condition": "cat_form",
                        "source": source_url,
                    }],
                },
            },
            "control_witness": control,
            "witness": candidate,
        },
    )

    assert result["status"] == "PROBE_PASS"
    assert result["accepted_for_p2"] is False
    assert result["source_rank_facts"]["prerequisite_rank_build_bridge_unverified"] is True
    assert result["source_rank_facts"]["unsupported_prerequisite_rank_bridge_unverified"] is True


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
