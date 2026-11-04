"""Keep retired one-off GameIR and checkpoint diagnostics out of the live CLI surface.

The retired tool modules had no direct production, test, workflow, or
documentation callers. P1/P2-only source-talent proofs and probes tied to the
removed staged databases are retired; active Forever-owned regressions remain.
Git history retains the implementation archaeology.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RETIRED_TOOLS = (
    "tools/wf261_stateful_benchmark.py",
    "tools/wf263_l1_value_benchmark.py",
    "tools/wf276_resource_prefix_benchmark.py",
    "tools/wf303_source_wide_100mob.py",
    "tools/wf270_action_source_coverage.py",
    "tools/wf272_real_source_ranked_finisher.py",
    "tools/wf279_paid_fixed_marginal_benchmark.py",
    "tools/wf280_real_mode_path_benchmark.py",
    "tools/wf319_druid_l20_index_l2_parity.py",
    # One-off WF300 GameIR talent-neighbor diagnostic had no callers; active runtime regressions remain.
    "tools/wf300_two_stage_adversarial_100mob.py",
    # One-off WF343 report driver had no callers; underlying P3 behavior tests remain.
    "tools/wf343_direct_percent_top5.py",
    # WF431 one-off paid GameIR search runner; retained evidence is diagnostic only.
    "tools/wf431_modified_action_paid_search.py",
    # WF359 one-off P3 rebase depended on the retired staged P2 SQLite database.
    "tools/wf359_druid_l30_p3_rebase.py",
    # Historical GameIR/SQLite continuity runner; no active callers.
    # WF341 provisional-rating 100-mob probes were used only by retired WF342 reporters.
    "tools/wf341_rating_probe.py",
    "tools/wf341_defense_check.py",
    "tools/wf300_continuous_source_policy_benchmark.py",
    # One-off Python talent-source transcription; frozen stage retained.
    "tools/wf350_build_source_evidence.py",
    # P2-only Swiftmend 100-mob diagnostic depended on the retired staged Druid database.
    "tools/wf441_100mob_swiftmend_evidence.py",
    "tools/wf399_qualification_probe.py",
    "tools/wf399_replay_winner.py",
    "tools/wf384_generic_checkpoint_screen.py",
    "tools/wf385_mage_stamina_100mob.py",
    "tools/wf294_l1_partial_nine_class.py",
    "tools/wf241_recovery_e2e.py",
    "tools/wf378_evocation_recovery.py",
    "tools/wf240_source_joint_replay.py",
    "tools/wf241_source_joint_replay.py",
    "tools/wf250_non_druid_replay.py",
    "tools/wf244_joint_multi_pull_replay.py",
    "tools/wf245_joint_frontier_replay.py",
    "tools/wf246_primary_stat_replay.py",
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
    "tools/wf365_bear_primal_diagnostic.py",
    "tools/wf365_druid_l30_reaudit.py",
    "tools/wf365_spaced_pull_smoke.py",
    "tools/wf353_l30_p3_context_replay.py",
    "tools/wf303_checkpoint_falsifier.py",
    "tools/wf305_ingest_web_observed_spell_dependencies.py",
    "tools/wf357_l30_fresh_replay.py",
    "tools/wf358_l30_fresh_joint_replay.py",
    # WF373 was an orphaned Druid L30 GameIR/SQLite 100-mob diagnostic; its staged database is retired.
    "tools/wf373_druid_l30_primal_vs_swipe_100mob.py",
    # 2026-11-04: orphaned one-off probes; their staged P2 databases were retired.
    "tools/wf357_recovery_probe.py",
    "tools/wf391_generic_joint_probe.py",
    "tools/wf417_source_root_2d_probe.py",
    "tools/wf424_druid_l30_insect_probe.py",
    "tools/wf429_l30_pushback_100mob.py",
    "tools/wf430_l30_starfire_100mob.py",
    # One-off WF357 staged-SQLite recovery frontier; keep its report as historical evidence.
    "tools/wf357_l30_recovery_frontier.py",
    # Unreferenced 300 s GameIR search driver retained under evidence/ by mistake.
    "evidence/wf438/run300.py",
)
RETIRED_SOURCE_MODULES = (
    "src/v2/source_sqlite_spell_facts.py",
    "src/v2/source_sqlite_spell_semantics.py",
    # Historical six-gate/P1/P2 reader; current certification uses m1_progress.
    "src/game/checkpoint_acceptance_status.py",
)

RETIRED_IMPORT_NAMES = (
    "wf261_stateful_benchmark",
    "wf263_l1_value_benchmark",
    "wf276_resource_prefix_benchmark",
    "wf303_source_wide_100mob",
    "wf270_action_source_coverage",
    "wf272_real_source_ranked_finisher",
    "wf279_paid_fixed_marginal_benchmark",
    "wf280_real_mode_path_benchmark",
    "wf319_druid_l20_index_l2_parity",
    "wf300_two_stage_adversarial_100mob",
    "wf343_direct_percent_top5",
    "wf431_modified_action_paid_search",
    "wf359_druid_l30_p3_rebase",
    "wf341_rating_probe",
    "wf341_defense_check",
    "wf300_continuous_source_policy_benchmark",
    "wf350_build_source_evidence",
    "wf399_qualification_probe",
    "wf399_replay_winner",
    "wf384_generic_checkpoint_screen",
    "wf385_mage_stamina_100mob",
    "wf294_l1_partial_nine_class",
    "wf241_recovery_e2e",
    "wf378_evocation_recovery",
    "wf240_source_joint_replay",
    "wf241_source_joint_replay",
    "wf250_non_druid_replay",
    "wf244_joint_multi_pull_replay",
    "wf245_joint_frontier_replay",
    "wf246_primary_stat_replay",
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
    "wf365_bear_primal_diagnostic",
    "wf365_druid_l30_reaudit",
    "wf365_spaced_pull_smoke",
    "wf353_l30_p3_context_replay",
    "source_sqlite_spell_facts",
    "source_sqlite_spell_semantics",
    "wf303_checkpoint_falsifier",
    "wf305_ingest_web_observed_spell_dependencies",
    "wf357_l30_fresh_replay",
    "wf358_l30_fresh_joint_replay",
    "wf373_druid_l30_primal_vs_swipe_100mob",
    "wf357_recovery_probe",
    "wf391_generic_joint_probe",
    "wf417_source_root_2d_probe",
    "wf424_druid_l30_insect_probe",
    "wf429_l30_pushback_100mob",
    "wf430_l30_starfire_100mob",
    "wf441_100mob_swiftmend_evidence",
    "wf357_l30_recovery_frontier",
    "test_wf357_source_between_pull_recovery",
    "test_wf391_generic_joint_frontier",
    "test_wf424_insect_source_talent_100mob_tdd",
    "test_wf430_source_compound_stun_tdd",
    "source_spell_dependency_observations",
    "source_gap_audit",
    "scope_audit(",
    "checkpoint_acceptance_status",
    "accepted_checkpoint_status",
)


RETIRED_OUTPUTS = (
    "evidence/wf378/WF378_100MOB_DIAGNOSTIC.json",
    "evidence/wf369/WF369_DRUID_L30_APL_PROBE.json",
    "evidence/wf365/WF365_BEAR_PRIMAL_DIAGNOSTIC.json",
    "evidence/wf365/WF365_SPACED_PULL_SMOKE.json",
    "WF240_DRUID_L20_JOINT_REPLAY.json",
    "WF241_DRUID_L20_JOINT_REPLAY.json",
    "WF250_NON_DRUID_JOINT_REPLAY.json",
    "WF244_INDEPENDENT_JOINT_REPEATED_PULL.json",
    "WF245_INDEPENDENT_JOINT_REPLAY.json",
    "WF246_PRIMARY_STATS_JOINT_REPLAY.json",
    "evidence/wf357/WF357_RECOVERY_100MOB.json",
    "evidence/wf424/WF424_DRUID_L30_INSECT_SWARM_100MOB.json",
    "evidence/wf429/WF429_L30_26PT_PUSHBACK_100MOB.json",
    "evidence/wf430/WF430_STARFIRE_100MOB.json",
    "evidence/wf430/WF430_RED_2D_STUN.log",
    "evidence/wf430/WF430_RED_COMPOUND.log",
    "evidence/wf430/WF430_RED_PROC_TELEMETRY.log",
    "evidence/wf430/WF430_RED_MAX_RANK_FRONTIER.log",
    "evidence/wf430/WF430_REFACTOR_2D_PASS.log",
    "evidence/wf430/WF430_REFACTOR_CROSS_PASS.log",
)

RETIRED_SOURCE_EVIDENCE = (
    "data/forever/source_observations/wf305_druid_l20_engraving_grants.json",
)


RETIRED_TESTS = (
    "tests/maintenance/test_historical_joint_replay_compat.py",
    "tests/test_wf378_recovery_channel_tdd.py",
    "tests/test_wf365_druid_l30_holdout.py",
    "tests/test_wf365_primal_bite_talent_unlock.py",
    "tests/gates/test_wf_first_checkpoint_vertical.py",
    "tests/test_wf_gen03a4c2_sqlite_materialization.py",
    "tests/test_wf_gen03a4c2b2_semantic.py",
    "tests/test_wf_gen03a4c2b2_coverage.py",
    "tests/test_wf303_checkpoint_falsifier.py",
    "tests/test_wf357_source_between_pull_recovery.py",
    "tests/generic/search/test_wf391_generic_joint_frontier.py",
    "tests/test_wf424_insect_source_talent_100mob_tdd.py",
    "tests/test_wf430_source_compound_stun_tdd.py",
    "tests/gates/test_wf367_six_port_acceptance.py",
    "tests/test_wf359_druid_l30_p3_rebase.py",
)

RETIRED_COMMANDS = (
    "python tools/wf_checkpoint_druid_balance_l60.py",
    "python tools/wf_native_session_capability.py",
)


RETAINED_BEHAVIOR_TESTS = (
    "tests/test_wf270_index_to_ir_action_frontier.py",
    "tests/test_wf272_source_ranked_periodic_finisher.py",
    "tests/test_wf241_mixed_hot_recovery.py",
    "tests/test_actor_recovery_channel.py",
)


RETAINED_HISTORICAL_EVIDENCE = (
    "evidence/wf365/WF365_DRUID_L30_REVOCATION.json",
    "evidence/wf343/WF343_SOURCE_DISPLAY_PERCENT_TOP5.json",
    "evidence/wf343/WF343_TOP5_READABLE_REPORT.md",
    "evidence/wf431/WF431_PAID_SOURCE_MODIFIED_APL_DIAGONAL.json",
    "evidence/wf431/WF431_PAID_SOURCE_MODIFIED_APL_MARGINAL_SCREEN.json",
    # WF359 output is retained as historical diagnostic evidence, not re-run.
    "evidence/wf359/WF359_L30_P3_REBASED_DIRECT_100MOB.json",
    "evidence/wf359/WF359_L30_P3_REBASED_TOP5.json",
    "evidence/wf359/WF359_RECONSTRUCTION.json",
    # Preserve the bounded WF357 recovery-frontier result; retire only its one-off producer.
    "evidence/wf357/WF357_L30_RECOVERY_FRONTIER.json",
    "evidence/wf350/druid_l30_source_talent_catalogue_70338.json",
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
    workflow_jobs = workflow.split("jobs:", 1)[1] if "jobs:" in workflow else ""
    for relative in RETIRED_TOOLS:
        assert relative not in workflow_jobs, relative
    for relative in RETIRED_TESTS:
        assert not (ROOT / relative).exists(), relative
        assert relative not in workflow_jobs, relative
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
    for relative in RETAINED_HISTORICAL_EVIDENCE:
        assert (ROOT / relative).is_file(), f"historical revocation evidence was removed: {relative}"
    for workflow_path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow_source = workflow_path.read_text(encoding="utf-8")
        workflow_jobs = workflow_source.split("jobs:", 1)[1] if "jobs:" in workflow_source else ""
        for relative in RETIRED_TOOLS:
            assert relative not in workflow_jobs, f"retired CLI invoked by {workflow_path}: {relative}"

    this_test = Path(__file__).resolve()
    for root in (ROOT / "src", ROOT / "tools", ROOT / "tests", ROOT / "scripts",
                 ROOT / "integrations"):
        for path in root.rglob("*.py"):
            if path.resolve() == this_test:
                continue
            source = path.read_text(encoding="utf-8")
            for name in RETIRED_IMPORT_NAMES:
                assert name not in source, f"{name} reintroduced by {path}"
