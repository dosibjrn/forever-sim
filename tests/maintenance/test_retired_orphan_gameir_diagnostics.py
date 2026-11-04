"""Keep retired one-off GameIR and checkpoint diagnostics out of the live CLI surface.

The retired tool modules had no direct production, test, workflow, or
documentation callers. Separate source/runtime regression tests remain.
Their implementation history is retained in Git.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RETIRED_TOOLS = (
    "tools/wf261_stateful_benchmark.py",
    "tools/wf263_l1_value_benchmark.py",
    "tools/wf276_resource_prefix_benchmark.py",
    "tools/wf303_source_wide_100mob.py",
    "tools/wf319_druid_l20_index_l2_parity.py",
    "tools/wf399_qualification_probe.py",
    "tools/wf399_replay_winner.py",
    "tools/wf384_generic_checkpoint_screen.py",
    "tools/wf385_mage_stamina_100mob.py",
    "tools/wf294_l1_partial_nine_class.py",
    "tools/wf241_recovery_e2e.py",
    "tools/wf378_evocation_recovery.py",
    "tools/wf242_multi_pull_replay.py",
    "tools/wf244_effect_batch_replay.py",
    "tools/wf257_l30_full_gear.py",
    "tools/wf258_run_budgeted_prefix.py",
    "tools/wf264_decision_sustained.py",
    "tools/wf269_rake_l27_real_replay.py",
    "tools/wf259_run_budgeted_gear.py",
    "tools/wf262_run_stateful_joint.py",
    "tools/wf_checkpoint_druid_balance_l60.py",
    "tools/wf_native_session_capability.py",
    "tools/wf369_druid_l30_apl_probe.py",
    "tools/wf353_l30_p3_context_replay.py",
)
RETIRED_SOURCE_MODULES = (
    "src/v2/source_sqlite_spell_facts.py",
    "src/v2/source_sqlite_spell_semantics.py",
)

RETIRED_IMPORT_NAMES = (
    "wf261_stateful_benchmark",
    "wf263_l1_value_benchmark",
    "wf276_resource_prefix_benchmark",
    "wf303_source_wide_100mob",
    "wf319_druid_l20_index_l2_parity",
    "wf399_qualification_probe",
    "wf399_replay_winner",
    "wf384_generic_checkpoint_screen",
    "wf385_mage_stamina_100mob",
    "wf294_l1_partial_nine_class",
    "wf241_recovery_e2e",
    "wf378_evocation_recovery",
    "wf242_multi_pull_replay",
    "wf244_effect_batch_replay",
    "wf257_l30_full_gear",
    "wf258_run_budgeted_prefix",
    "wf264_decision_sustained",
    "wf269_rake_l27_real_replay",
    "wf259_run_budgeted_gear",
    "wf262_run_stateful_joint",
    "wf_checkpoint_druid_balance_l60",
    "wf_native_session_capability",
    "wf369_druid_l30_apl_probe",
    "wf353_l30_p3_context_replay",
    "source_sqlite_spell_facts",
    "source_sqlite_spell_semantics",
)


RETIRED_OUTPUTS = (
    "evidence/wf378/WF378_100MOB_DIAGNOSTIC.json",
    "evidence/wf369/WF369_DRUID_L30_APL_PROBE.json",
)


RETIRED_TESTS = (
    "tests/test_wf378_recovery_channel_tdd.py",
    "tests/gates/test_wf_first_checkpoint_vertical.py",
    "tests/test_wf_gen03a4c2_sqlite_materialization.py",
    "tests/test_wf_gen03a4c2b2_semantic.py",
    "tests/test_wf_gen03a4c2b2_coverage.py",
)

RETIRED_COMMANDS = (
    "python tools/wf_checkpoint_druid_balance_l60.py",
    "python tools/wf_native_session_capability.py",
)


RETAINED_BEHAVIOR_TESTS = (
    "tests/test_wf241_mixed_hot_recovery.py",
    "tests/test_actor_recovery_channel.py",
)


RETAINED_SEARCH_TESTS = (
    "tests/generic/search/test_wf259_real_budgeted_gear.py",
    "tests/test_wf262_stateful_joint_integration.py",
)


def test_orphan_gameir_diagnostic_clis_stay_retired():
    for relative in RETIRED_TOOLS:
        assert not (ROOT / relative).exists(), relative
    for relative in RETIRED_SOURCE_MODULES:
        assert not (ROOT / relative).exists(), relative
    for relative in RETIRED_OUTPUTS:
        assert not (ROOT / relative).exists(), relative

    workflow = (ROOT / ".github/workflows/maintenance-evidence-tests.yml").read_text(
        encoding="utf-8"
    )
    for relative in RETIRED_TOOLS:
        assert relative not in workflow, relative
    for relative in RETIRED_TESTS:
        assert not (ROOT / relative).exists(), relative
        assert relative not in workflow, relative
    first_checkpoint_doc = (ROOT / "docs/evidence/druid-l60-balance/first-checkpoint/README.md").read_text(
        encoding="utf-8"
    )
    for command in RETIRED_COMMANDS:
        assert command not in first_checkpoint_doc, command
    assert "python tools/wf_gate.py" in first_checkpoint_doc
    for relative in RETAINED_BEHAVIOR_TESTS:
        assert relative in workflow, f"retained recovery regression is not run: {relative}"
    for relative in RETAINED_SEARCH_TESTS:
        assert (ROOT / relative).is_file(), f"retained search regression was removed: {relative}"

    for workflow_path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow_source = workflow_path.read_text(encoding="utf-8")
        for relative in RETIRED_TOOLS:
            assert relative not in workflow_source, f"retired CLI invoked by {workflow_path}: {relative}"

    this_test = Path(__file__).resolve()
    for root in (ROOT / "src", ROOT / "tools", ROOT / "tests", ROOT / "scripts",
                 ROOT / "integrations"):
        for path in root.rglob("*.py"):
            if path.resolve() == this_test:
                continue
            source = path.read_text(encoding="utf-8")
            for name in RETIRED_IMPORT_NAMES:
                assert name not in source, f"{name} reintroduced by {path}"
