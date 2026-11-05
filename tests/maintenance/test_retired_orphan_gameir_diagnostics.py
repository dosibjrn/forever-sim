"""Keep retired one-off GameIR and checkpoint diagnostics out of the live CLI surface.

The retired tool modules had no direct production, test, workflow, or
documentation callers. P1/P2-only source-talent proofs and probes tied to the
removed staged databases are retired; active Forever-owned regressions remain.
Git history retains the implementation archaeology.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RETIRED_TOOLS = (
    # Obsolete independent GameIR bounded gear/talent/policy report, not a native P3–P6 gate.
    "tools/run_source_joint_discovery.py",
    # Duplicate one-off Python Wowhead item-catalogue builder; the live item-refresh service
    # already imports, builds, and publishes the catalogue without this CLI.
    "tools/build_forever_item_catalogue.py",
    # WF420: obsolete Python GameIR-scored 100-mob replay, not selected-native P3/P4-P6.
    "tools/wf420_druid20_independent_full_replay.py",
    # Uncalled fixed-allocation Python talent-rules/scorer CLI; native engine owns game rules.
    "tools/check_cross_class.py",
    # Retired one-shot Python source/SQLite ingesters; native engine owns game facts.
    "tools/ingest_armor_conversions_sqlite.py",
    "tools/ingest_stat_conversions_sqlite.py",
    "tools/ingest_source_ability_semantics_sqlite.py",
    "tools/ingest_source_resource_scaled_periodic.py",
    "tools/ingest_secondary_talent_ranks_sqlite.py",
    "tools/ingest_talent_rank_curves_sqlite.py",
    "tools/ingest_equipped_weapon_mode_sqlite.py",
    "tools/ingest_source_stat_aura_candidates_sqlite.py",
    "tools/ingest_source_talents_sqlite.py",
    "tools/wf470_ingest_available_observations.py",
    # Historical Paladin SQLite/GameIR source mechanics ingesters; active gates use MythicSim.
    "tools/wf253_ingest_seal.py",
    "tools/wf255_ingest_command.py",
    "tools/wf256_ingest_seals.py",
    # One-off Python SQLite unique-equip migration; no runtime or gate callers.
    # Obsolete P3 class-item source-attestation stager; selected native item options own active P3.
    "tools/wf388_stage_class_item_capture.py",
    "tools/wf345_ingest_equipped_group.py",
    # Historical Warrior L30 SQLite/GameIR staging; current P3 uses selected
    # native item options and selected scorer, not staged Python item facts.
    "tools/wf368_warrior_l30_gear_runtime_bridge.py",
    "tools/wf370_warrior_l30_source_bis_stage.py",
    # M47 GameIR-scored baseline/adversarial report CLIs and their exclusive
    # historical report checks; retained M47 mechanics tests are independent.
    "tools/m47_3x3_baseline.py",
    "tools/m47_druid_l60_adversarial.py",
    "tools/m47_mage_l20_adversarial.py",
    "tools/m47_paladin_l40_adversarial.py",
    "tools/m47_paladin_l60_adversarial.py",
    "tests/test_m47_3x3_baseline_v011470.py",
    "tests/test_m47_druid_l60_adversarial_v011475.py",
    "tests/test_m47_mage_l20_adversarial_v0114711.py",
    "tests/test_m47_paladin_selection_v011472.py",
    # Retired M47 Paladin L20 hybrid Python selection/adversarial report drivers;
    # their required root-level baseline and report JSON files are not tracked.
    "tools/m47_paladin_l20_selection.py",
    "tools/m47_paladin_l20_adversarial.py",
    # Standalone legacy GameIR talent/gear/policy bounded search CLI; live gates use wf_gate.py.
    # Retired test-only GameIR/SQLite paid-journal CLI; active cold P4/P5 uses native gate provider.
    "tools/wf400_paid_joint_with_journal.py",
    "scripts/run_staged_joint_search.py",
    # Retired WF442 P2 source-rank ingester (source captures remain historical).
    "tools/wf442_ingest_source_rank_observations.py",
    # Retired P2-only Warrior/Mage talent snapshot builders (historical staged files retained).
    "tools/wf362_stage_warrior30_talents.py",
    "tools/wf381_stage_mage_talent_positions.py",
    # Retired Paladin P2 talent ingestion and uncalled one-shot source rank stagers.
    "tools/wf254_ingest_paladin_talents.py",
    "tools/wf257_ingest_flash_recovery.py",
    "tools/wf257_ingest_paladin_corridor.py",
    # Retired P1-only stealth tooltip ingester; its only caller was a Python GameIR P1 test.
    "tools/wf474_ingest_stealth.py",
    # Retired one-shot GameIR/SQLite observation ingesters; no active native or gate callers.
    "tools/wf437_ingest_critical_resource_source.py",
    "tools/wf438_ingest_resource_actions.py",
    "tools/wf439_ingest_channel_heal.py",
    "tools/wf440_ingest_direct_control.py",
    "tools/wf440_ingest_next_cast_instant.py",
    "tools/wf441_ingest_active_periodic_heal.py",
    "tools/wf441_ingest_spatial_charge.py",
    "tools/wf471_ingest_enemy_ap.py",
    # Historical one-shot Python item/stat source stagers; staged SQLite data and consumers remain.
    "tools/wf346_type_resistance_equipment.py",
    "tools/wf385_stage_mage_stamina.py",
    # P2-era Druid talent SQLite stager: the generated staged database was already retired.
    "tools/wf350_stage_druid30_talents.py",
    # Retired gsim-only 1/2/100-mob historical replay (no active native gate caller).
    "tools/wf61_live_persistent_replay.py",
    # WF260 historical GameIR talent/gear/policy and frozen Mage challenger runner; active gates use native producers.
    "tools/wf260_run_budgeted_joint.py",
    # Orphan WF-COMBAT232/233 GameIR weapon and armor paid-report runners.
    "tools/wf_combat232_weapon_evidence.py",
    "tools/wf_combat233_source_armor_replay.py",
    # PR #912 nonoverlapping orphaned historical frontends, retired after #913.
    "tools/audit_l20_fidelity.py",
    "tools/wf249_ingest_talent_scope.py",
    "tools/wf302_persistent_joint_optimizer.py",
    # Orphaned WF389/WF408/WF410/WF412 Python GameIR P3/100-mob report runners.
    # Historical WF412 P3 recertifier demanded positive Spirit/MP5/etc and
    # pinned obsolete PROCESS hashes; neither is active P3 acceptance.
    "tools/wf412_recertify_druid20_p3.py",
    "tests/test_wf412_p3_same_winner_evidence_tdd.py",
    "tools/wf389_paid_weapon_package_probe.py",
    "tools/wf408_rerun_druid20_p3.py",
    "tools/wf410_druid20_live_p3.py",
    "tools/wf412_druid20_paid_stat_probe.py",
    # Historical WF324 Druid L20 bounded GameIR searches; no active gate/optimizer caller.
    "tools/wf324_druid_l20_talent_screening.py",
    "tools/wf324_persistent_blind_selection.py",
    "tools/wf324_refine_persistent_discovered.py",
    # WF358 frozen GameIR/SQLite contextual Top5 replay and report; no active gate caller.
    "tools/wf358_l30_p3_empirical_report.py",
    "tools/wf358_l30_p3_top5_replay.py",
    # Retired Python GameIR 100-mob continuity challenger; active gates run through wf_gate.
    "tools/wf299_100_mob_continuity_probe.py",
    # Retired GameIR-only cold 30s source benchmark; live cold gates use wf_gate.py.
    "tools/wf299_30s_acceptance.py",
    "tools/wf299_30s_worker.py",
    # Historical Warrior L30 Python GameIR paid-gear runners; frozen reports remain.
    # Retired provisional Python source-membership and heuristic role Top5 probes.
    "tools/wf363_warrior_l30_p3_probe.py",
    "tools/wf365_warrior_l30_p3_role_probe.py",
    "tools/wf368_warrior_l30_p3_paid_swaps.py",
    "tools/wf370_warrior_l30_paid_bis_challenge.py",
    "tools/wf370_warrior_l30_paid_aware_top5.py",
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
    # One-off equal-terms wrapper; its WF299 GameIR probe/test are retired too.
    "tools/wf300_continuous_100_mob_acceptance.py",
    # One-off WF343 report driver had no callers; underlying P3 behavior tests remain.
    "tools/wf343_direct_percent_top5.py",
    # WF431 one-off paid GameIR search runner; retained evidence is diagnostic only.
    "tools/wf431_modified_action_paid_search.py",
    # WF359 one-off P3 rebase depended on the retired staged P2 SQLite database.
    "tools/wf359_druid_l30_p3_rebase.py",
    # WF427 quest-horizon replay was an optional diagnostic, not an active gate objective.
    "tools/wf427_druid_l30_quest_horizon.py",
    # Historical GameIR/SQLite continuity runner; no active callers.
    # WF341 provisional-rating 100-mob probes were used only by retired WF342 reporters.
    "tools/wf341_rating_probe.py",
    "tools/wf341_defense_check.py",
    # Obsolete WF339/341 fixed-Druid GameIR/SQLite paid-report producers; preserve reports.
    # Historical WF340/WF347 Python-GameIR Top-5 and cold P4/P5 report runners.
    # Their one-off outputs survive as frozen evidence; live gates use wf_gate.py.
    "tools/wf340_p4_worker.py",
    "tools/wf340_strict_p4.py",
    "tools/wf346_build_top5.py",
    "tools/wf347_build_top5.py",
    "tools/wf347_p4_worker.py",
    "tools/wf347_strict_p4.py",
    "tools/wf339_build_weighted_top5.py",
    "tools/wf339_weighted_slot_pilot.py",
    "tools/wf341_rating_sensitivity.py",
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
    # Staged Druid L30 P3/GameIR calibration CLIs; the required P2-era SQLite is gone.
    "tools/wf353_l30_p3_direct_swaps.py",
    "tools/wf353_l30_p3_joint_item_swaps.py",
    "tools/wf358_l30_p3_causal_weights.py",
    "tools/wf358_l30_p3_joint_challengers.py",
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
    # Standalone recalibration producer has no callers; retain its completed report.
    "tools/wf357_l30_recovery_p3_recalibrate.py",
    # Legacy v2 challenger exporter has no active P7 consumer; retain reconstruction manifests.
    "tools/wf356_export_legacy_druid30.py",
    # WF322's one-off staged build-parity producer; the input and behavior regressions remain.
    "tools/wf322_druid_l20_build_parity.py",
    # WF328's one-off GameIR/SQLite report producers; keep their historical JSON and prefix regression.
    "tools/wf328_druid_l20_mode_search_evidence.py",
    "tools/wf328_geared_blind_joint_check.py",
    # Historical 100-mob GameIR/SQLite comparison is not active P3-P7.5 acceptance.
    "tools/wf328_geared_comparison.py",
    # Orphaned WF_FERAL01 Druid L20 evidence generator; no retained consumer.
    "tools/run_wf_feral01_evidence.py",
    # Obsolete WF-FERAL01 GameIR probes/replays; independent mechanics tests remain.
    "tools/wf_feral01b_source_damage_probe.py",
    "tools/wf_feral01c2c_replay.py",
    "tools/wf_feral01c2d1_replay.py",
    # WF326/WF327 orphaned Druid L20 GameIR/SQLite evidence generators; retain reports.
    "tools/wf326_druid20_slot_search.py",
    "tools/wf327_druid_l20_action_proxy.py",
    # WF325 scratch-path-only replay drivers and WF347 fixed-policy HP5 probe.
    "tools/wf325_druid_l20_blind_joint.py",
    "tools/wf325_druid_l20_paid_persistent_replay.py",
    "tools/wf347_hp5_persistent_probe.py",
    # Unreferenced 300 s GameIR search driver retained under evidence/ by mistake.
    "evidence/wf438/run300.py",
    # Standalone Hunter/pet partial replay has no consumers; shared companion search stays covered.
    "tools/wf252_companion_replay.py",
    # One-off .242 test aggregator has no callers; its constituent tests remain available.
    "tools/wf242_validate.py",
    # WF243's one-off replay CLI is retired; policy record decoding lives with the optimizer.
    "tools/wf243_joint_multi_pull_replay.py",
    # Retired .251–.256 Python GameIR/SQLite Paladin/Hunter replay chain.
    "tools/wf251_native_replay.py",
    "tools/wf253_paladin_seal_replay.py",
    "tools/wf254_paladin_talent_replay.py",
    "tools/wf255_paladin_command_replay.py",
    "tools/wf256_paladin_seals_replay.py",
    "tools/wf256_run_full_search.py",
    # Retired WF238/239 GameIR talent-sampling scripts; no active gate or optimizer caller.
    "scripts/run_wf_coverage238_sample.py",
    "scripts/run_wf_coverage239_sample.py",
    # P00b/P00c/P01a source-legality and naked-envelope diagnostic entrypoints.
    "scripts/evaluate_source_candidates.py",
    "scripts/prove_p00c_legality.py",
)
RETIRED_SOURCE_MODULES = (
    # Uncalled GameIR-only 2/100-mob policy search; exclusive test retired.
    "src/v2/source_persistent_policy_neighborhood.py",
    # Orphaned WF412 GameIR 100-mob stat/recovery reoptimizer; no native P3 caller.
    "src/v2/source_reoptimized_stat_sensitivity.py",
    # Unused Mage-v2 per-level multiprocessing and path scorer (test-only callers).
    "src/v2/parallel_search.py",
    "src/v2/path_score.py",
    # Orphan Mage analytic projection, route simulation, and v1 stochastic diagnostics.
    "src/v2/mechanics_projection.py",
    "src/v2/latent_search.py",
    "src/v2/path_validation.py",
    "src/v2/stochastic_diagnostics.py",
    "src/v2/stochastic_race.py",
    # WF380 orphan GameIR-only recovery-threshold optimizer (exclusive test retired).
    "src/game/recovery_threshold_search.py",
    # Exclusive Python source/legal empirical P3 proxy and 100-mob causal reporter.
    "src/game/data/forever/source_checkpoint_p3_empirical_weights.py",
    "src/game/data/forever/source_checkpoint_p3_causal_summary.py",
    "src/v2/source_sqlite_spell_facts.py",
    "src/v2/source_sqlite_spell_semantics.py",
    # Historical six-gate/P1/P2 reader; current certification uses m1_progress.
    "src/game/checkpoint_acceptance_status.py",
    # Retired P00b/P00c/P01a GameIR-only legality and naked-envelope chain.
    "src/game/level_legality.py",
    "src/v2/level_evaluation_trace.py",
    "src/v2/legal_candidate_enumeration.py",
)

RETIRED_IMPORT_NAMES = (
    "source_persistent_policy_neighborhood",
    "refine_source_policy_persistent",
    "source_reoptimized_stat_sensitivity",
    "reoptimized_stat_sensitivity",
    "run_source_joint_discovery",
    "build_forever_item_catalogue",
    "wf420_druid20_independent_full_replay",
    "check_cross_class",
    "ingest_armor_conversions_sqlite",
    "ingest_stat_conversions_sqlite",
    "ingest_source_ability_semantics_sqlite",
    "ingest_source_resource_scaled_periodic",
    "ingest_secondary_talent_ranks_sqlite",
    "ingest_talent_rank_curves_sqlite",
    "test_wf_coverage235_secondary_rank_batch",
    "test_wf_feral01c2a_rank_curves",
    "wf253_ingest_seal",
    "wf255_ingest_command",
    "wf256_ingest_seals",
    "wf388_stage_class_item_capture",
    "wf345_ingest_equipped_group",
    "wf368_warrior_l30_gear_runtime_bridge",
    "wf370_warrior_l30_source_bis_stage",
    "m47_paladin_l20_selection",
    "m47_paladin_l20_adversarial",
    "wf442_ingest_source_rank_observations",
    "wf474_ingest_stealth",
    "test_wf474_generic_stealth",
    "test_wf444_joint_critical_proc_tdd",
    "test_wf445_joint_incoming_dodge_resource_tdd",
    "test_wf442_generic_avoidance_resource_red",
    "test_wf442_generic_direct_heal_crit_red",
    "wf254_ingest_paladin_talents",
    "wf257_ingest_flash_recovery",
    "wf257_ingest_paladin_corridor",
    "parallel_search",
    "score_path_levels",
    "path_score",
    "mechanics_projection",
    "latent_search",
    "path_validation",
    "stochastic_diagnostics",
    "stochastic_race",
    "recovery_threshold_search",
    "search_recovery_thresholds",
    "wf260_run_budgeted_joint",
    "wf_combat232_weapon_evidence",
    "wf_combat233_source_armor_replay",
    "audit_l20_fidelity",
    "wf249_ingest_talent_scope",
    "wf302_persistent_joint_optimizer",
    "wf389_paid_weapon_package_probe",
    "wf408_rerun_druid20_p3",
    "wf410_druid20_live_p3",
    "wf412_druid20_paid_stat_probe",
    "wf324_druid_l20_talent_screening",
    "wf324_persistent_blind_selection",
    "wf324_refine_persistent_discovered",
    "wf358_l30_p3_empirical_report",
    "wf358_l30_p3_top5_replay",
    "wf363_warrior_l30_p3_probe",
    "wf365_warrior_l30_p3_role_probe",
    "source_checkpoint_p3_empirical_weights",
    "source_checkpoint_p3_causal_summary",
    "wf261_stateful_benchmark",
    "wf263_l1_value_benchmark",
    "wf276_resource_prefix_benchmark",
    "wf303_source_wide_100mob",
    "wf270_action_source_coverage",
    "wf272_real_source_ranked_finisher",
    "wf279_paid_fixed_marginal_benchmark",
    "wf280_real_mode_path_benchmark",
    "wf319_druid_l20_index_l2_parity",
    "wf299_30s_acceptance",
    "wf299_30s_worker",
    "wf300_two_stage_adversarial_100mob",
    "wf300_continuous_100_mob_acceptance",
    "wf343_direct_percent_top5",
    "wf431_modified_action_paid_search",
    "wf359_druid_l30_p3_rebase",
    "wf427_druid_l30_quest_horizon",
    "wf341_rating_probe",
    "wf341_defense_check",
    "wf340_p4_worker",
    "wf340_strict_p4",
    "wf346_build_top5",
    "wf347_build_top5",
    "wf347_p4_worker",
    "wf347_strict_p4",
    "wf339_build_weighted_top5",
    "wf339_weighted_slot_pilot",
    "wf341_rating_sensitivity",
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
    "wf353_l30_p3_direct_swaps",
    "wf353_l30_p3_joint_item_swaps",
    "wf358_l30_p3_causal_weights",
    "wf358_l30_p3_joint_challengers",
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
    "wf357_l30_recovery_p3_recalibrate",
    "wf356_export_legacy_druid30",
    "export_legacy_winner",
    "wf322_druid_l20_build_parity",
    "wf328_druid_l20_mode_search_evidence",
    "wf328_geared_blind_joint_check",
    "wf328_geared_comparison",
    "run_wf_feral01_evidence",
    "wf_feral01b_source_damage_probe",
    "wf_feral01c2c_replay",
    "wf_feral01c2d1_replay",
    "wf326_druid20_slot_search",
    "wf327_druid_l20_action_proxy",
    "wf325_druid_l20_blind_joint",
    "wf325_druid_l20_paid_persistent_replay",
    "wf347_hp5_persistent_probe",
    "test_held_out_legacy_feral_replay_is_actually_scored_on_same_five_gears",
    "test_held_out_feral_and_wrath_both_replayed_on_source_melee_gear",
    "test_wf357_source_between_pull_recovery",
    "test_wf391_generic_joint_frontier",
    "test_wf424_insect_source_talent_100mob_tdd",
    "test_wf430_source_compound_stun_tdd",
    "source_spell_dependency_observations",
    "source_gap_audit",
    "scope_audit(",
    "checkpoint_acceptance_status",
    "accepted_checkpoint_status",
    "wf252_companion_replay",
    "wf242_validate",
    ".wf243_joint_multi_pull_replay",
    "src.game.level_legality",
    "level_evaluation_trace",
    "legal_candidate_enumeration",
    "evaluate_source_candidates",
    "prove_p00c_legality",
    "evaluate_source_candidate_envelope",
    "enumerate_legal_source_candidates",
    "generate_priority_order_candidates",
    "evaluate_legal_level_continuation",
    "evaluate_mode_auto_attack_trace",
    "compare_level_candidates",
    "LevelState",
    "validate_level_state",
    "validate_level_transition",
    "require_exact_talent_ranks",
    "run_wf_coverage238_sample",
    "run_wf_coverage239_sample",
    "wf251_native_replay",
    "wf253_paladin_seal_replay",
    "wf254_paladin_talent_replay",
    "wf255_paladin_command_replay",
    "wf256_paladin_seals_replay",
    "wf256_run_full_search",
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
    "WF243_INDEPENDENT_JOINT_REPEATED_PULL.json",
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

RETIRED_OUTPUT_PREFIXES = (
    "WF_FERAL01B_SOURCE_DAMAGE_EVIDENCE_",
    "WF_FERAL01C2C_HEART_REPLAY_EVIDENCE_",
    "WF_FERAL01C2D1_STRENGTH_GEAR_REPLAY_",
)


RETIRED_SOURCE_EVIDENCE = (
    "data/forever/source_observations/wf305_druid_l20_engraving_grants.json",
    # P1 source-effect roles only fed the retired P1 proof/ingestion path.
    "evidence/p1_source_effect_roles_v1.json",
)


RETIRED_TESTS = (
    # WF412 Python GameIR stat-positivity witness is not an active P3 requirement.
    "tests/test_wf412_reoptimized_stat_sensitivity_tdd.py",
    "tests/generic/search/test_wf_gen03a1_joint_grid.py",
    # WF420-WF425 exclusively exercised that frozen Python GameIR replay and
    # duplicated Warcraft crit/hit/stat semantics rather than active native gates.
    "tests/test_wf420_paid_full_gear_candidate_tdd.py",
    "tests/test_wf421_source_chance_2d_stat_sensitivity_tdd.py",
    "tests/test_wf422_p3_pack_context_invariance_tdd.py",
    "tests/test_wf423_unified_spell_crit_source_tdd.py",
    "tests/test_wf425_unified_hit_source_paid_100mob_tdd.py",
    # Exclusive retired Python GameIR talent-rank import/legality/runtime tests.
    "tests/test_wf_coverage235_secondary_rank_batch.py",
    "tests/test_wf_feral01c2a_rank_curves.py",
    # Exclusive source-ingest/Paladin GameIR mechanics tests, not native-gate regressions.
    "tests/test_wf253_seal_judgement_vertical.py",
    "tests/test_wf255_paladin_command_weapon.py",
    "tests/test_wf256_paladin_seal_family.py",
    # Exclusive old Warrior staged-SQLite GameIR and item-source checks.
    "tests/test_wf368_warrior_l30_gear_execution.py",
    "tests/test_wf370_warrior_l30_bis_reconciliation.py",
    # Exclusive M47 L20 adversarial test read an absent generated root-level JSON.
    "tests/test_m47_paladin_l20_adversarial_v011471.py",
    # P1-only stealth source-ingest and Python GameIR/runtime assertions are retired.
    "tests/test_wf474_generic_stealth.py",
    # Retired synthetic Python GameIR Warcraft mechanics, not Forever-owned contracts.
    "tests/test_wf442_generic_avoidance_resource_red.py",
    "tests/test_wf442_generic_direct_heal_crit_red.py",
    "tests/test_wf444_joint_critical_proc_tdd.py",
    "tests/test_wf445_joint_incoming_dodge_resource_tdd.py",
    "tests/maintenance/test_wf_coverage_sample_wrappers.py",
    "tests/test_wf254_paladin_rank_batch.py",
    "tests/test_v2_parallel_path.py",
    "tests/generic/search/test_v2_path_score.py",
    "tests/test_v2_projection.py",
    "tests/generic/search/test_v2_path_validation_inputs.py",
    "tests/test_v2_stochastic_diagnostics.py",
    "tests/test_v2_stochastic_race.py",
    "tests/test_wf61_live_persistent_replay.py",
    "tests/generic/search/test_wf260_budgeted_joint_talents.py",
    "tests/test_wf358_p3_contextual_top5.py",
    "tests/test_wf300_continuous_mob.py",
    "tests/gates/test_wf299_30_second_gate.py",
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
    "tests/test_wf427_quest_horizon_paid_tdd.py",
    "tests/test_wf356_export_legacy_druid30.py",
    "tests/test_wf328_geared_reference_replay.py",
    "tests/test_level_evaluation_trace_p00b.py",
    "tests/test_level_legality_p00c.py",
    "tests/test_wf_p01a_legal_candidates.py",
    "tests/test_wf_p01a2_mode_candidate.py",
    "tests/generic/search/test_wf_gen01_priority_search.py",
)

RETIRED_COMMANDS = (
    "python tools/wf_checkpoint_druid_balance_l60.py",
    "python tools/wf_native_session_capability.py",
    "python scripts/evaluate_source_candidates.py",
    "python scripts/prove_p00c_legality.py",
)


RETAINED_BEHAVIOR_TESTS = (
    "tests/test_wf328_mode_joint_prefix_admission.py",
    "tests/test_wf270_index_to_ir_action_frontier.py",
    "tests/test_wf272_source_ranked_periodic_finisher.py",
    "tests/test_wf241_mixed_hot_recovery.py",
    "tests/test_actor_recovery_channel.py",
    "tests/test_wf61_companion_persistence.py",
    "tests/test_work2_persistent_pack_budget.py",
    # Keep the real shared Hunter companion source/search path covered after runner retirement.
    "tests/test_wf252_companion_joint.py",
    # Keep the independently useful Heart and gear-execution regressions after replay retirement.
    "tests/test_wf_feral01c2c_heart_runtime.py",
    "tests/test_wf_feral01c2d1_strength_gear.py",
)


RETAINED_HISTORICAL_EVIDENCE = (
    # Frozen WF408/WF410/WF412 reports remain historical; only generators retire.
    "evidence/wf408/WF408_DRUID20_MERGED_P3_LIVE.json",
    "evidence/wf410/WF410_DRUID20_PROCESS_V2_P3_LIVE.json",
    "evidence/wf412/WF412_DRUID20_PAID_REOPTIMIZED_STAT_PROBES.json",
    # Snapshot of the discontinued WF358 source-IR 100-mob contextual study.
    "evidence/wf358/WF358_L30_P3_TOP5_DIRECT_REPLAYS.json",
    "evidence/wf358/WF358_L30_P3_CONTEXTUAL_TOP5_AND_WEIGHTS.json",
    "evidence/wf358/WF358_L30_CAUSAL_STAT_100MOB.json",
    "evidence/wf358/WF358_L30_CAUSAL_STAT_WEIGHT_TABLE.json",
    "evidence/wf365/WF365_DRUID_L30_REVOCATION.json",
    "evidence/wf363/WF363_WARRIOR_L30_P3_PROBE.json",
    "evidence/wf365/WF365_WARRIOR_L30_P3_ROLE_PROBE.json",
    "evidence/wf343/WF343_SOURCE_DISPLAY_PERCENT_TOP5.json",
    "evidence/wf343/WF343_TOP5_READABLE_REPORT.md",
    "evidence/wf431/WF431_PAID_SOURCE_MODIFIED_APL_DIAGONAL.json",
    "evidence/wf431/WF431_PAID_SOURCE_MODIFIED_APL_MARGINAL_SCREEN.json",
    # WF359 output is retained as historical diagnostic evidence, not re-run.
    "evidence/wf359/WF359_L30_P3_REBASED_DIRECT_100MOB.json",
    "evidence/wf359/WF359_L30_P3_REBASED_TOP5.json",
    "evidence/wf359/WF359_RECONSTRUCTION.json",
    # Retain the WF394 reconstruction manifest that records the archived WF356 source run.
    "evidence/wf394/RECONSTRUCTION.json",
    # Preserve the bounded WF357 recovery-frontier result; retire only its one-off producer.
    "evidence/wf357/WF357_L30_RECOVERY_FRONTIER.json",
    "evidence/wf357/WF357_L30_P3_RECOVERY_RECALIBRATION.json",
    # Preserve original WF326/WF327 reports after deleting their orphaned generators.
    "evidence/wf326/WF326_SLOT_SEARCH_EVIDENCE.json",
    "evidence/wf327/WF327_DRUID20_ACTION_PROXY_AND_L2.json",
    # Preserve the original measured results; retire only the one-off producers.
    "evidence/wf325/WF325_BLIND_JOINT.json",
    "evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json",
    "evidence/wf347/WF347_FIXED_POLICY_HP5_100MOB.json",
    # Retain the measured historical reports, never regenerate via obsolete Python GameIR.
    "evidence/wf340/WF340_P4_STRICT_30S.json",
    "evidence/wf340/WF340_P5_STRICT_300S.json",
    "evidence/wf346/WF346_TOP5.json",
    "evidence/wf346/WF346_TOP5.md",
    "evidence/wf347/WF347_TOP5.json",
    "evidence/wf347/WF347_TOP5.md",
    "evidence/wf347/WF347_P4_STRICT.json",
    "evidence/wf347/WF347_P5_STRICT.json",
    "evidence/wf339/WF339_DRUID_L20_WEIGHTED_TOP5_PER_SLOT.json",
    "evidence/wf339/WF339_WEIGHTED_SLOT_PILOT.json",
    "evidence/wf341/WF341_DRUID_L20_CHANCE_SENSITIVITY_TOP5.json",
    "evidence/wf350/druid_l30_source_talent_catalogue_70338.json",
    "evidence/wf328/WF328_REAL_MODE_PREFIX_30_PAID_AND_100MOB.json",
    "evidence/wf328/WF328_GEARED_BLIND_100MOB_SAME_SOURCE.json",
    "evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json",
    # WF427 inputs and result remain historical evidence; only the producer is retired.
    "evidence/wf427/WF427_L30_COLD_FINALISTS.json",
    "evidence/wf427/DRUID_L30_QUEST_HORIZONS_2_4_8_16.json",
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
    for prefix in RETIRED_OUTPUT_PREFIXES:
        assert not any(path.name.startswith(prefix) for path in ROOT.iterdir()), prefix
    for relative in RETIRED_SOURCE_EVIDENCE:
        assert not (ROOT / relative).exists(), relative

    workflow = (ROOT / ".github/workflows/maintenance-evidence-tests.yml").read_text(
        encoding="utf-8"
    )
    workflow_triggers = workflow.split("permissions:", 1)[0]
    # Live maintenance regression edits still trigger this workflow. Retired
    # one-off generators have been deleted, so requiring their old path filters
    # would keep obsolete CI configuration forever.
    assert "      - 'tests/maintenance/**'" in workflow_triggers
    assert "      - '.github/workflows/maintenance-evidence-tests.yml'" in workflow_triggers
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
