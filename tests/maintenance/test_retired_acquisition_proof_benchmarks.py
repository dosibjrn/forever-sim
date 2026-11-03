"""Retired source-proof and source-audit CLIs must not return as gates.

MythicSim owns spell/rank acquisition legality and game-source facts.
The real route and stable production gate entrypoints remain separate live code.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RETIRED_TOOLS = (
    "tools/wf332_druid20_acquisition_evidence.py",
    "tools/wf291_source_acquisition_route_benchmark.py",
    "tools/audit_forever_source_coverage.py",
    "tools/audit_forever_source_rules.py",
    "tools/wf318_four_level_frontier.py",
    "tools/wf331_druid20_web_l0_evidence.py",
    "tools/wf332_rune_policy_evidence.py",
)
RETIRED_IMPORT_NAMES = (
    "wf332_druid20_acquisition_evidence",
    "wf291_source_acquisition_route_benchmark",
    "audit_forever_source_coverage",
    "audit_forever_source_rules",
    "wf318_four_level_frontier",
    "wf331_druid20_web_l0_evidence",
    "wf332_rune_policy_evidence",
)


def test_retired_source_proof_and_audit_clis_are_not_live_tools():
    for relative in RETIRED_TOOLS:
        assert not (ROOT / relative).exists(), relative
    assert (ROOT / "tools/wf_gate.py").is_file()
    assert (ROOT / "src/v2/source_budgeted_level_route.py").is_file()

    workflow = (ROOT / ".github/workflows/maintenance-evidence-tests.yml").read_text(encoding="utf-8")
    for relative in RETIRED_TOOLS:
        assert relative not in workflow, relative


def test_no_live_python_imports_retired_source_proof_and_audit_clis():
    for root in (ROOT / "src", ROOT / "tools", ROOT / "tests"):
        for path in root.rglob("*.py"):
            if path == Path(__file__):
                continue
            source = path.read_text(encoding="utf-8")
            assert not any(name in source for name in RETIRED_IMPORT_NAMES), path


def test_historical_p1_gameir_admission_toolchain_is_retired():
    """The current P1 gate is native-facing; old L0 spellbook proof CLIs are not gates."""
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
    for relative in retired:
        assert not (ROOT / relative).exists(), relative
    # Keep the actual production P1 entrypoint and the still-live P2 caller.
    assert (ROOT / "tools/wf_gate_p1_live.py").is_file()
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
