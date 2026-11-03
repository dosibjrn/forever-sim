"""Retired source-proof and source-audit CLIs must not return as gates.

MythicSim owns spell/rank acquisition legality and game-source facts.
Obsolete GameIR route products are deleted; active gate entrypoints remain.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RETIRED_TOOLS = (
    "tools/wf332_druid20_acquisition_evidence.py",
    "tests/test_wf_gen03a4c2b2_completeness.py",
    "tests/test_wf_gen03a4c2b2_proof_contract.py",
    "tests/test_wf_gen03a4c2b2_independent_oracle.py",
    "tools/wf288_real_contiguous_route_benchmark.py",
    "tools/wf288_replay_route.py",
    "tools/wf257_run_corridor.py",
    "tests/test_wf257_source_level_corridor.py",
    "tools/wf289_replay_parent_druid_corridor.py",
    "tools/wf293_bounded_nine_class_groups.py",
    "scripts/audit_product_coverage.py",
    "tests/test_product_coverage_v2.py",
    "tests/test_wf288_bounded_route_evidence.py",
    "tests/generic/search/test_wf288_source_bounded_level_routes.py",
    "tests/test_wf289_reference_route_attestation.py",
    "tests/test_wf288_contiguous_source_stateful_route.py",
    "tools/wf291_source_acquisition_route_benchmark.py",
    "tools/audit_forever_source_coverage.py",
    "tools/audit_forever_source_rules.py",
    "tools/wf318_four_level_frontier.py",
    "tools/wf330_druid_l20_queued_swing_evidence.py",
    "tools/wf331_druid20_web_l0_evidence.py",
    "tools/wf332_rune_policy_evidence.py",
    "tools/wf355_p7_preflight.py",
    "tools/wf336_druid_l20_p2_certificate.py",
    "tools/wf336_p2_optimizer_pilot.py",
    "tools/wf349_druid30_p2_diagnostic.py",
    "tools/wf350_druid30_p2_acceptance.py",
    "tools/wf387_atomic_source_talent_probe.py",
    "tools/wf430_p2_gate_report.py",
    "tools/wf362_warrior_l30_p2_acceptance.py",
    "tools/wf_druid_p2_probe.py",
    "tests/test_wf_druid_p2_probe.py",
    "tools/wf338_druid_l20_p3_certificate.py",
    "tools/wf356_legacy_l30_equipment_audit.py",
    "tools/wf344_source_equipment_merged_report.py",
    "tools/wf352_p3_reaudit.py",
    "tools/ingest_source_acquisition_evidence_sqlite.py",
    "tools/ingest_source_acquisition_entities_sqlite.py",
    "tools/wf_gate_p1_live.py",
    "tools/wf_p1_native_effects.py",
    "src/engine_client/native_p1_effect_probe.py",
    "config/gates/p1_scenario_applicability_v1.json",
    ".github/workflows/p1-native-validator-contract.yml",
    "tests/test_wf466_p1_live.py",
    "tests/test_wf469_p1_alignment.py",
    "tests/test_wf470_p1_scope.py",
    "tests/test_wf472_p1_gate_nonimpact.py",
    "tests/gates/test_wf_p1_native_blackbox.py",
    "integrations/mythicsim-rust/tests/test_native_p1_effect_probe.py",
    "tools/wf318_nine_class_composite_batch.py",
    "tests/generic/search/test_wf390_generic_talent_subset_search.py",
    "tools/wf390_generic_talent_search.py",
    "tests/test_wf318_index_composite_batch.py",
    "src/engine_client/native_p2_rank_probe.py",
    "integrations/mythicsim-rust/test_native_p2_rank_probe.py",
    "integrations/mythicsim-rust/tests/test_native_p2_rank_probe.py",
    "tests/maintenance/test_native_p2_client_boundary.py",
    "tests/test_wf_prio_p2_legal_pair.py",
    "tests/test_wf_prio_native_p2_source_receipts.py",
    "tools/wf_gate_p2_live.py",
    "src/game/data/forever/checkpoint_p2_execution_gate.py",
    "src/game/data/forever/source_checkpoint_p2.py",
    "src/game/data/forever/source_checkpoint_p2_optimizer.py",
    "tools/wf351_druid30_p3.py",
    "tools/ingest_talent_tree_rows_sqlite.py",
    "tests/test_wf_feral01c_source_tree_gates.py",
    "data/forever/staged_druid_l30_talents_70338.sqlite",
    "tests/test_wf337_p2_optimizer_integration.py",
    "tests/test_wf349_druid30_p2_source_integrity.py",
    "tests/test_wf350_druid30_staged_talents.py",
    "tests/test_wf362_warrior_l30_p2.py",
    "tests/test_wf381_mage_l30_talent_positions_tdd.py",
    "tests/test_wf387_atomic_rank_promotion.py",
    "tests/test_wf382_mage_l30_build_delta_p1_tdd.py",
    "tests/test_talent_tree_row_ingestion.py",
    "tests/test_wf_feral01c_source_tree_gates.py",
    "data/forever/source_captures/wowhead_druid_tree_rows_2026-10-10.json",
    "tests/generic/search/test_wf_p2_cross_tree_source_witness.py",
    "tests/generic/search/test_wf_p2_source_witness_priority.py",
    "evidence/wf336/druid_l20_talent_rank_observations_70338.json",
    "evidence/wf336/WF336_P2_CHECKPOINT_CERTIFICATE.json",
    "evidence/wf349/WF349_P2_DIAGNOSTIC.json",
    "evidence/wf349/WF349_P2_SOURCE_GAPS.json",
    "evidence/wf350/WF350_P2_ACCEPTANCE.json",
    "evidence/wf362/WF362_WARRIOR_L30_P2_CERTIFICATE.json",
    "evidence/wf430/WF430_P2_GATE_RED_26PT.json",
    "evidence/wf432/WF432_P2_FULL_GATE.json",
    "evidence/wf432/WF432_P2_FULL_GATE_RED.log",
    "evidence/wf433/WF433_P2_GATE.json",
    "evidence/wf433/WF433_P2_GATE.log",
    "evidence/wf434/P2_GATE.json",
    "evidence/wf434/KNOWN_P2_P4_RED.log",
    "evidence/wf436/WF436_P2_GATE.json",
    "evidence/wf436/WF436_P2_GATE_RED.json",
    "evidence/wf436/WF436_P2_GATE_RED.log",
    "evidence/wf436/WF436_WIP_VALIDATION.json",
    "evidence/wf437/WF437_P2_ACCEPTANCE_RED.log",
    "evidence/wf438/WF438_P2_GATE.log",
    "evidence/wf482_druid_tree_rows_20261017.json",
    "gate_evidence/druid/L20/unrestricted/P2.json",
    "gate_evidence/druid/L30/unrestricted/P2.json",
    "gate_sources/druid/WF443_P2_GATE_RED.json",
    "tests/test_wf_prio_p2_source_grant.py",
    "tests/test_p2_source_control_proc_runtime.py",
    "tests/test_wf475_live_p2_gate_alignment.py",
    "tests/test_wf478_p2_effect_runtime.py",
    "tests/test_wf480_p2_mode_entry_runtime.py",
    "tests/test_wf479_p2_crit_cost_runtime.py",
    "tests/test_prio_p2_solo_threat_exclusion.py",
    "tests/test_prio_p2_live_critical_resource_gain.py",
    "tests/test_prio_source_cast_pushback_l60.py",
    "tests/test_wf481_p2_periodic_duration_runtime.py",
    "tests/test_wf482_p2_gcd_and_tree_rows.py",
    "tests/test_wf_prio_p2_exact_rank_fullpoint.py",
    "tests/test_wf35_source_spec_p2_adapter.py",
    "tests/test_wf430_p2_whole_gate_26point_tdd.py",
    "tests/gates/test_wf336_generic_p2_acceptance.py",
    "tests/test_wf428_staged_atomic_fraction_p2_tdd.py",
    "tests/test_wf429_source_cast_pushback_p2_tdd.py",
    "tests/test_wf432_p2_full_26point_red.py",
    "tests/test_wf436_feral_conditional_crit_healing_p2_tdd.py",
    "tests/test_wf_p2_sourced_cast_stun.py",
    "tests/test_wf440_bash_stun_compound_tdd.py",
    "tests/test_wf440_next_cast_instant_p2_tdd.py",
    "tests/test_wf441_source_spatial_charge_p2_tdd.py",
    "tests/test_wf439_channel_healing_compound_p2_tdd.py",
    "tests/test_wf437_blood_frenzy_source_proc_p2_tdd.py",
    "tests/test_wf439_timed_spell_critical_haste_p2_tdd.py",
    "tests/test_wf436_source_natural_instinct_runtime_tdd.py",
    "tests/test_wf441_source_active_periodic_full_heal_p2_tdd.py",
    "tests/test_wf438_source_resource_talent_action_p2_tdd.py",
    "tests/test_wf442_source_dodge_resource_and_heal_crit_p2_tdd.py",
    "tests/test_prio_blood_frenzy_canonical_tooltip.py",
)
RETIRED_SOURCE_PROOF_MODULES = (
    "src/game/data/forever/source_checkpoint_acquisition.py",
    "src/v2/source_sqlite_semantic_proof.py",
    "src/v2/source_sqlite_semantic_audit.py",
    "src/v2/source_sqlite_direct_damage_oracle.py",
    "src/v2/source_budgeted_level_route.py",
    "src/v2/source_stateful_level_route.py",
    "src/v2/source_legal_level_corridor.py",
    "src/v2/source_bounded_route_evidence.py",
    "src/v2/source_reference_route_evidence.py",
    "data/forever/source_bounded_level_routes_v1.json",
    "data/forever/wf289_parent_druid_l1_60_replay.json",
    "src/game/data/forever/source_checkpoint_p7_legacy.py",
    "src/game/data/forever/source_acquisition.py",
    "src/game/data/forever/source_acquisition_entities.py",
    "src/game/data/forever/source_acquisition_events.py",
    "src/game/data/forever/source_world_acquisition.py",
    "tests/test_wf290_source_acquisition_batch.py",
    "tests/test_wf291_source_world_acquisition.py",
    "tests/maintenance/test_source_acquisition_import_boundary.py",
    "src/game/data/forever/source_index_composite_l1.py",
)
RETIRED_IMPORT_NAMES = (
    "wf332_druid20_acquisition_evidence",
    "wf291_source_acquisition_route_benchmark",
    "audit_forever_source_coverage",
    "audit_forever_source_rules",
    "wf318_four_level_frontier",
    "wf330_druid_l20_queued_swing_evidence",
    "wf331_druid20_web_l0_evidence",
    "wf332_rune_policy_evidence",
    "source_checkpoint_acquisition",
    "source_checkpoint_p7_legacy",
    "wf355_p7_preflight",
    "P7_LEGACY_HOLDOUT",
    "wf336_druid_l20_p2_certificate",
    "wf336_p2_optimizer_pilot",
    "wf349_druid30_p2_diagnostic",
    "wf350_druid30_p2_acceptance",
    "wf387_atomic_source_talent_probe",
    "wf430_p2_gate_report",
    "wf362_warrior_l30_p2_acceptance",
    "wf_druid_p2_probe",
    "wf338_druid_l20_p3_certificate",
    "wf356_legacy_l30_equipment_audit",
    "wf344_source_equipment_merged_report",
    "wf352_p3_reaudit",
    "from src.game.data.forever.source_acquisition import",
    "from src.game.data.forever import source_acquisition",
    "import src.game.data.forever.source_acquisition",
    "from src.game.data.forever.source_acquisition_entities import",
    "from src.game.data.forever import source_acquisition_entities",
    "import src.game.data.forever.source_acquisition_entities",
    "from src.game.data.forever.source_acquisition_events import",
    "from src.game.data.forever import source_acquisition_events",
    "import src.game.data.forever.source_acquisition_events",
    "from src.game.data.forever.source_world_acquisition import",
    "from src.game.data.forever import source_world_acquisition",
    "import src.game.data.forever.source_world_acquisition",
    "ingest_source_acquisition_evidence_sqlite",
    "ingest_source_acquisition_entities_sqlite",
    "wf_gate_p1_live",
    "wf_p1_native_effects",
    "native_p1_effect_probe",
    "wf_gate_p2_live",
    "checkpoint_p2_execution_gate",
    "source_checkpoint_p2",
    "source_checkpoint_p2_optimizer",
    "wf351_druid30_p3",
    "ingest_talent_tree_rows_sqlite",
)


def test_retired_source_proof_and_audit_clis_are_not_live_tools():
    for relative in RETIRED_TOOLS:
        assert not (ROOT / relative).exists(), relative
    assert (ROOT / "tools/wf_gate.py").is_file()
    assert not (ROOT / "src/v2/source_budgeted_level_route.py").exists()
    assert not (ROOT / "tools/wf_gate_p2_live.py").exists()

    workflow = (ROOT / ".github/workflows/maintenance-evidence-tests.yml").read_text(encoding="utf-8")
    for relative in RETIRED_TOOLS:
        assert relative not in workflow, relative


def test_no_live_python_imports_retired_source_proof_and_audit_clis():
    # Match actual imports, not incidental metadata keys or historical strings.
    # An import may name the module directly or import its leaf from a package.
    retired_modules = {
        Path(relative).stem
        for relative in (*RETIRED_TOOLS, *RETIRED_SOURCE_PROOF_MODULES)
    }
    retired_modules.update(name for name in RETIRED_IMPORT_NAMES if name.isidentifier())
    for root in (ROOT / "src", ROOT / "tools", ROOT / "tests", ROOT / "integrations"):
        for path in root.rglob("*.py"):
            if path == Path(__file__):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:
                # Non-importable legacy scripts cannot provide live imports.
                # Their syntax is outside this retired-import boundary check.
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = {part for alias in node.names for part in alias.name.split(".")}
                elif isinstance(node, ast.ImportFrom):
                    imported = set((node.module or "").split("."))
                    imported.update(alias.name for alias in node.names)
                else:
                    continue
                assert not (imported & retired_modules), (path, node.lineno, imported & retired_modules)


def test_retired_checkpoint_acquisition_proof_and_l0_verdict_are_gone():
    for relative in RETIRED_SOURCE_PROOF_MODULES:
        assert not (ROOT / relative).exists(), relative
    frontier = (ROOT / "src/game/data/forever/source_checkpoint_l0.py").read_text(encoding="utf-8")
    for obsolete in (
        "source_checkpoint_acquisition",
        "source_acquisition_frontier",
        "source_acquisition_category",
        "source_acquisition_evidence_status",
        "'blocker':",
        "'PASS1':False",
        "legal_combat_spell_proven",
    ):
        assert obsolete not in frontier, obsolete


def test_historical_p1_gameir_admission_toolchain_is_retired():
    """P1's old source/IR acceptance provider is retired; historical artifacts remain."""
    retired = (
        "src/game/data/forever/source_checkpoint_p1_acceptance.py",
        "tools/wf406_druid20_live_p1p2.py",
        "tools/wf335_spellbook_p1.py",
        "tools/wf348_druid30_spellbook_p1.py",
        "tools/wf361_warrior_l30_p1.py",
        "tools/wf377_mage_l30_p1.py",
        "tools/wf333_checkpoint_p1_contract.py",
        "tests/test_wf335_druid20_spellbook_p1.py",
        "tests/test_wf348_druid30_source_spellbook.py",
        "tests/test_wf361_warrior_l30_p1.py",
        "tests/test_wf377_mage_l30_source_p1.py",
        "tests/test_wf377_mage_spellbook_reconciliation.py",
        "tests/gates/test_wf333_checkpoint_p1_contract.py",
    )
    workflow = (ROOT / ".github/workflows/maintenance-evidence-tests.yml").read_text(encoding="utf-8")
    for relative in retired:
        assert not (ROOT / relative).exists(), relative
        assert relative not in workflow, f"retired path remains in maintenance workflow: {relative}"
    # P1/P2 have no live gate provider or retained P2 helper module.
    assert not (ROOT / "tools/wf_gate_p1_live.py").exists()
    assert not (ROOT / "tools/wf_gate_p2_live.py").exists()


def test_no_live_python_imports_retired_p1_gameir_admission_toolchain():
    retired = (
        "source_checkpoint_p1_acceptance",
        "wf406_druid20_live_p1p2",
        "wf335_spellbook_p1",
        "wf348_druid30_spellbook_p1",
        "wf361_warrior_l30_p1",
        "wf377_mage_l30_p1",
        "wf333_checkpoint_p1_contract",
    )
    for root in (ROOT / "src", ROOT / "tools", ROOT / "integrations", ROOT / "tests"):
        for path in root.rglob("*.py"):
            if path == Path(__file__):
                continue
            source = path.read_text(encoding="utf-8")
            assert not any(name in source for name in retired), path


def test_unapproved_p7_legacy_holdout_preflight_is_retired():
    """The approved P7 contract has five subgates, not a parallel legacy gate."""
    retired = (
        "tools/wf355_p7_preflight.py",
        "src/game/data/forever/source_checkpoint_p7_legacy.py",
        "tests/test_wf355_legacy_holdout_p7.py",
        "evidence/wf355/WF355_P7_LEGACY_PREFLIGHT.json",
    )
    for relative in retired:
        assert not (ROOT / relative).exists(), relative

    workflow = (ROOT / ".github/workflows/maintenance-evidence-tests.yml").read_text(encoding="utf-8")
    for relative in retired:
        assert relative not in workflow, relative

    p7 = (ROOT / "docs/gates/P7.md").read_text(encoding="utf-8")
    for subgate in ("P7.1", "P7.2", "P7.3", "P7.4", "P7.5"):
        assert subgate in p7, subgate
    assert "P7_LEGACY_HOLDOUT" not in p7



def test_retired_one_off_p3_report_writers_keep_historical_evidence():
    """Retiring one-off generators must not delete their retained evidence."""
    retained = (
        "evidence/wf344/WF344_P4_SOURCE_EQUIPMENT_30S.json",
        "evidence/wf344/WF344_P5_SOURCE_EQUIPMENT_300S.json",
        "evidence/wf344/WF344_SOURCE_DISPLAY_PERCENT_EQUIPMENT_TOP5.json",
        "evidence/wf344/WF344_TOP5_READABLE_REPORT.md",
        "evidence/wf352/WF352_L30_P3_TOP5.json",
        "evidence/wf352/WF352_P3_ADVERSARIAL_CURVES.json",
        "evidence/wf352/WF352_P3_REVOCATION.json",
    )
    for relative in retained:
        assert (ROOT / relative).is_file(), relative

def test_retired_p2_gate_and_checkpoint_chain_has_no_code_or_actions():
    """The retired P2 rank-pair adapter must not survive as a hidden workflow."""
    retired = (
        "src/engine_client/native_p2_rank_probe.py",
        "integrations/mythicsim-rust/test_native_p2_rank_probe.py",
        "integrations/mythicsim-rust/tests/test_native_p2_rank_probe.py",
        "tests/maintenance/test_native_p2_client_boundary.py",
    )
    for relative in retired:
        assert not (ROOT / relative).exists(), relative

    assert not (ROOT / "tools/wf_gate_p2_live.py").exists()
    assert not (ROOT / "src/game/data/forever/checkpoint_p2_execution_gate.py").exists()
    assert not (ROOT / "src/game/data/forever/source_checkpoint_p2.py").exists()
    assert not (ROOT / "src/game/data/forever/source_checkpoint_p2_optimizer.py").exists()
    optimizer = (ROOT / "src/v2/source_budgeted_joint_talents.py").read_text(encoding="utf-8")
    assert "talent_l0_certificate" not in optimizer
    assert "source_checkpoint_p2_optimizer" not in optimizer

    gate_cli = (ROOT / "tools/wf_gate.py").read_text(encoding="utf-8")
    assert "native_rank_probe" not in gate_cli
    assert 'VALIDATORS = {"P3": _validate_p3,' in gate_cli

    rust_workflow = (ROOT / ".github/workflows/rust-upstream-fork.yml").read_text(encoding="utf-8")
    assert "native_p2_rank_probe" not in rust_workflow
    assert "test_native_p2_rank_probe" not in rust_workflow
    assert "FOREVER_P2_HYDRATED_SOURCE_DB_PATH" not in rust_workflow
    assert "FOREVER_P2_HYDRATED_SOURCE_DB_SHA256" not in rust_workflow

    submodule_workflow = (ROOT / ".github/workflows/rust-submodule-verify.yml").read_text(encoding="utf-8")
    assert "native_p2_rank_probe" not in submodule_workflow
    assert "test_native_p2_rank_probe" not in submodule_workflow
    assert "submodules: true" in submodule_workflow
    for relative in (".github/workflows/maintenance-evidence-tests.yml",
                     ".github/workflows/generic-source-search-regressions.yml"):
        workflow = (ROOT / relative).read_text(encoding="utf-8")
        assert "wf_gate_p2_live.py" not in workflow
    generic = (ROOT / ".github/workflows/generic-source-search-regressions.yml").read_text(encoding="utf-8")
    assert "test_wf_p2_cross_tree_source_witness.py" not in generic
    assert "test_wf_p2_source_witness_priority.py" not in generic
    assert "cargo build --locked --bin forever-engine" in submodule_workflow


def test_legacy_evidence_reader_rejects_retired_p1_p2(tmp_path):
    from tools.wf_gate import evaluate

    for gate in ("P1", "P2"):
        report = evaluate(tmp_path, "druid", 20, "unrestricted", gate, {})
        assert report["status"] == "FAIL"
        assert report["reasons"] == ["RETIRED_OR_UNKNOWN_GATE:" + gate]
