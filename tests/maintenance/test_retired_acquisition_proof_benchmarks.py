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
)


def test_retired_source_proof_and_audit_clis_are_not_live_tools():
    for relative in RETIRED_TOOLS:
        assert not (ROOT / relative).exists(), relative
    assert (ROOT / "tools/wf_gate.py").is_file()
    assert not (ROOT / "src/v2/source_budgeted_level_route.py").exists()
    # P2-only compatibility remains outside the deleted bounded-route chain.
    assert (ROOT / "tools/wf_gate_p2_live.py").is_file()
    assert (ROOT / "src/engine_client/native_p2_rank_probe.py").is_file()

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
    # P1 has no separate live provider; the P2 helper remains an optimizer dependency.
    assert not (ROOT / "tools/wf_gate_p1_live.py").exists()
    assert (ROOT / "src/game/data/forever/source_checkpoint_p2.py").is_file()


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
