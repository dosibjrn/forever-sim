"""P4/P5 short diagnostic on the existing cold, source-paid whole-build search.

Only counted partial unit: a sourced eligible equipment slot for which a
COMPLETE paid production CombatRuntime candidate actually exercised a source
action. This is a narrow, provisional gear-axis subset of P4/P5; it cannot
be mistaken for a full 30/300s+100mob gate acceptance.

No saved report is read; there is no second optimizer or gate-only engine.
"""
from __future__ import annotations

from pathlib import Path


def paid_gear_slot_coverage(search: dict) -> dict:
    """Derive a comparable real paid coverage fraction, not candidate count."""
    slots = search.get("source_slot_proposal_coverage") or {}
    eligible = set(slots.get("eligible_slots") or ())
    attempted = set(slots.get("paid_slots") or ())
    if not eligible:
        return {"verified": 0, "applicable": 0, "executed": 0,
                "reason": "NO_SOURCE_ELIGIBLE_EQUIPMENT_SLOTS"}
    # The paid_slots field is derived from real evaluated build identities
    # by source_bounded_joint_frontier. A paid candidate may still be rejected
    # or non-completing; count ONLY meaningful completed runtime screens.
    completed = [r for r in search.get("rows", ())
                 if r.get("screen_invoked")
                 and r.get("screen_status") == "COMPLETE"
                 and sum(int(n) for n in (r.get("source_action_counts") or {}).values()) > 0]
    verified = set()
    for row in completed:
        label = str(row.get("gear_move") or "")
        slot = label.split(":", 1)[0]
        if slot in eligible and slot in attempted:
            verified.add(slot)
    return {"verified": len(verified), "applicable": len(eligible),
            "executed": len(completed),
            "paid_slots": sorted(verified),
            "eligible_slots": sorted(eligible)}


def paid_source_action_coverage(search: dict, source_actions) -> dict:
    """Actual sourced actions cast in COMPLETE paid production screens.

    Use the production GameIR action universe as the denominator; neither
    candidate count nor explored gear slots contribute. This is a provisional
    source-policy functional slice of P4/P5, not independent search acceptance.
    A single completed source-action cast is useful, no 30/300s holdout required.
    """
    eligible = {str(a.id) for a in source_actions if getattr(a, "id", None)}
    complete = [row for row in search.get("rows", ())
                if row.get("screen_invoked")
                and row.get("screen_status") == "COMPLETE"]
    used = set()
    for row in complete:
        used.update(str(k) for k, n in
                    (row.get("source_action_counts") or {}).items()
                    if type(n) is int and n > 0)
    return {"verified": len(eligible & used), "applicable": len(eligible),
            "executed": len(complete)}


def _native_cold_options_without_paid_executor(class_key: str, level: int,
                                               spec: str) -> dict:
    """Consult Rust when no legacy gear role exists; never fake a paid screen.

    Item-options enumerates individually eligible gear, not a legal complete
    build or a combat evaluator. Until the native whole-build paid path can
    consume these options, preserve BLOCKED rather than crediting P4/P5.
    """
    import os
    from src.game.native_p3_item_options import (
        NativeItemOptionsError, query_native_p3_item_options)

    component = "src.game.native_p3_item_options.query_native_p3_item_options"
    binary = os.environ.get("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN")
    if not binary:
        return {"status": "BLOCKED", "reasons": [
            "P4_P5_NATIVE_ITEM_OPTIONS_BINARY_REQUIRED"],
            "production_component": component}
    try:
        response = query_native_p3_item_options(
            binary, class_key, level, spec=spec)
    except NativeItemOptionsError as exc:
        return {"status": "BLOCKED", "reasons": [str(exc)],
                "production_component": component}
    options = response["items"]
    report = {
        "status": "BLOCKED",
        "reasons": [("P4_P5_NATIVE_PAID_WHOLE_BUILD_EXECUTOR_NOT_CONNECTED"
                     if options else "P4_P5_NATIVE_ITEM_OPTIONS_EMPTY")],
        "production_component": component,
        "native_source_option_count": len(options),
        "native_source_unverified_candidate_count": response["unverified_candidate_count"],
        "native_source_status": response["status"],
        "paid_candidates": 0,
        "screen_complete_candidates": 0,
        "coverage_scope_complete": False,
    }
    # Only the actual source-supplied Priest L20 request may exercise the
    # selected native whole-build scorer. Never fabricate an L20 request by
    # lowering an existing level-60 actor, or count a native-only fight as
    # a completed 2D/100-mob gate screen.
    request_file = os.environ.get("FOREVER_P4_P5_PRIEST_L20_SOURCE_REQUEST")
    candidate_dir = os.environ.get("FOREVER_P4_P5_PRIEST_L20_SOURCE_REQUEST_DIR")
    if (options and class_key == "priest" and level == 20
            and spec == "unrestricted" and (request_file or candidate_dir)):
        from tools.wf_native_priest_l20_paid import (
            couple_source_priest_l20_world,
            couple_source_priest_l20_persistent_world,
            score_native_priest_l20_item_candidates,
            score_source_priest_l20_candidates)
        try:
            if request_file and candidate_dir:
                raise ValueError("P4_P5_NATIVE_AMBIGUOUS_SOURCE_REQUEST")
            # Opt in on a selected bridge-capable engine. The same paid
            # candidate then flows through the existing real native↔gsim-2D
            # damage/ACK loop; a one-fight ACK is NOT a 100-mob screen.
            live_enabled = os.environ.get(
                "FOREVER_P4_P5_PRIEST_L20_LIVE_WORLD") == "1"
            persistent_targets = (int(os.environ.get(
                "FOREVER_P4_P5_PRIEST_L20_PERSISTENT_TARGETS", "2"))
                if live_enabled else 2)
            live_kwargs = ({"persistent_world": couple_source_priest_l20_persistent_world,
                            # A requested full 100-target screen is already
                            # native↔2D ACKed. Do not spend another independent
                            # one-fight smoke or pre-veto on its outcome.
                            # Keep the smaller two-target CI smoke unchanged.
                            "world_screen": (None if persistent_targets == 100
                                             else couple_source_priest_l20_world),
                            "persistent_target_count": persistent_targets}
                           if live_enabled else {})
            # Explicit opt-in for the real single 300s native/world cold
            # search. Its 30s snapshot and 300s winner share one execution;
            # normal hourly P4/P5 probes remain cheap and unchanged.
            if os.environ.get("FOREVER_P4_P5_PRIEST_L20_COLD_SEARCH") == "1":
                if not request_file or not live_enabled or persistent_targets != 100:
                    raise ValueError("P4_P5_NATIVE_COLD_REQUIRES_SOURCE_LIVE_100MOB")
                from tools.wf_native_priest_l20_cold import run_native_priest_l20_cold
                cold = run_native_priest_l20_cold(binary, request_file, options)
                # Optional ordinary Actions artifact of this *executed* source
                # run, never a second M1 ledger or a replay input authority.
                receipt_out = os.environ.get(
                    "FOREVER_P4_P5_PRIEST_L20_COLD_RECEIPT_OUT")
                if receipt_out:
                    import json
                    receipt_path = Path(receipt_out)
                    receipt_path.parent.mkdir(parents=True, exist_ok=True)
                    receipt_path.write_text(json.dumps(
                        cold, sort_keys=True, ensure_ascii=False) + "\n",
                        encoding="utf-8")
                report.update(cold)
                report["status"] = "FAIL"
                report["paid_candidates"] = (
                    cold["native_cold_native_paid_before_30"]
                    + cold["native_cold_native_paid_after_30"])
                report["screen_complete_candidates"] = cold.get(
                    "native_cold_completed_100mob_finalists",
                    cold["native_cold_completed_routes_before_30"]
                    + cold["native_cold_completed_routes_after_30"])
                if not cold["native_cold_300s_reached"]:
                    reason = "P4_P5_NATIVE_COLD_300S_SEARCH_NOT_COMPLETED"
                # A paid native/world evaluation can cross the exact 300s
                # cutoff after it starts. The producer excludes that entire
                # late result from both finalist windows; elapsed wall over
                # 300s is diagnostic, not grounds for rejecting pre-cutoff
                # real paid winners or the completed cold search.
                elif cold["native_cold_snapshot_30"] is None:
                    reason = "P4_P5_NATIVE_30S_PAID_WINNER_UNAVAILABLE"
                elif cold["native_cold_final_300"] is None:
                    reason = "P4_P5_NATIVE_300S_PAID_WINNER_UNAVAILABLE"
                elif cold["native_cold_native_paid_after_30"] == 0:
                    reason = "P5_NO_NATIVE_PAID_CONTINUATION_AFTER_30S"
                else:
                    # Producer progress is not a gate PASS. Merge must inspect
                    # native source/talent/policy breadth and approved predicates.
                    reason = "P4_P5_NATIVE_COLD_PRODUCER_EXECUTED_GATE_NOT_ACCEPTED"
                report["reasons"] = [reason]
                return report
            if candidate_dir:
                paid = score_source_priest_l20_candidates(
                    binary, candidate_dir, **live_kwargs)
            else:
                paid = score_native_priest_l20_item_candidates(
                    binary, request_file, options, **live_kwargs)
        except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
            report["reasons"] = [
                "P4_P5_NATIVE_PRIEST_L20_PAID_REFUSED:" + str(exc)[-400:]
            ]
            return report
        report.update(paid)
        report["paid_candidates"] = paid["native_paid_whole_builds"]
        if not report["paid_candidates"]:
            report["reasons"] = ["P4_P5_NATIVE_SOURCE_CANDIDATES_NOT_PAID"]
        elif (persistent_targets == 100
              and paid.get("native_2d_persistent_verified") == 1
              and paid.get("native_2d_persistent_targets_killed") == 100):
            # Genuine 100 distinct native/2D ACKed kills are an executable
            # result, not a missing bridge. They are still NOT a completed
            # P4/P5 gate: native-paid recovery and the cold 30/300s search
            # have not been established by this bounded producer.
            recovered = any(
                row.get("status") == "NATIVE_PAID"
                and isinstance(row.get("native_2d_persistent_world"), dict)
                and row["native_2d_persistent_world"].get(
                    "native_2d_persistent_paid_recovery") is True
                for row in paid.get("native_candidate_receipts", ())
            )
            report["reasons"] = [
                "P4_P5_NATIVE_100MOB_PAID_RECOVERY_VERIFIED_COLD_SEARCH_NOT_COMPLETE"
                if recovered else
                "P4_P5_NATIVE_PAID_RECOVERY_AND_COLD_SEARCH_NOT_COMPLETE"]
        else:
            # Keep the *observed* source/native-world failure on the active
            # gate result. Previously this was buried on a candidate row
            # under a generic "not connected" reason, hiding the first
            # reproducible failure even when the actual runner was invoked.
            native_error = next((
                row["native_2d_persistent_error"]
                for row in paid.get("native_candidate_receipts", ())
                if row.get("status") == "NATIVE_PAID"
                and row.get("native_2d_persistent_error")
            ), None)
            report["reasons"] = [
                ("P4_P5_NATIVE_2D_100MOB_FAILED:" + str(native_error)[-400:])
                if native_error and persistent_targets == 100
                else "P4_P5_NATIVE_2D_100MOB_SCREEN_NOT_CONNECTED"]
            if native_error and persistent_targets == 100:
                # A real invoked native/world producer failed. Report FAIL,
                # not the old BLOCKED/"not connected" classification; only
                # an unrun or unavailable producer is BLOCKED.
                report["status"] = "FAIL"
    return report


def run_paid_partial(root: Path, class_key: str, level: int, *,
                     spec: str, gate: str, budget_s: float = 6.) -> dict:
    if gate not in ("P4", "P5"):
        raise ValueError("UNSUPPORTED_LEVELING_SEARCH_GATE")
    # Full acceptance budgets are explicit: never run 30/300 s during hourly
    # bounded gate probes or ordinary CI. Both modes reuse WF437 production.
    import os
    if os.environ.get("FOREVER_P4_P5_FULL_SOURCE") == "1":
        return run_full_paid_source_search(root, class_key, level,
                                           spec=spec, gate=gate)
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.data.forever.gear import available_gear_roles
    from src.v2.source_bounded_joint_frontier import (
        source_cold_start_stage, search_bounded_joint_frontier)

    roles = available_gear_roles(class_key)
    if not roles:
        # A missing Forever SQLite role is not evidence of missing native
        # Priest gear. Ask the selected Rust item-options source directly.
        # Never pass those items through the legacy Python legality/runtime.
        return _native_cold_options_without_paid_executor(class_key, level, spec)
    ir = build_game_ir_slice(class_key=class_key, level=level)
    if ir is None:
        return {"status": "BLOCKED", "reasons": [
            "SOURCE_COLD_SEARCH_IR_UNAVAILABLE"]}
    # Named checkpoint specs are explicit product constraints, not inferred
    # Forever mechanics. Reuse P2's validated canonical profile and the
    # existing production joint search's source-legal spec frontier.
    search_spec = {}
    if spec != "unrestricted":
        from hashlib import sha256
        from src.game.data.forever.sqlite_talents import DEFAULT_DB
        from tools.wf_source_profile import _load_product_spec_profile

        source_db = Path(DEFAULT_DB)
        if not source_db.is_file():
            return {"status": "BLOCKED", "reasons": [
                "SOURCE_SPEC_PROFILE_DB_UNAVAILABLE"],
                "production_engine": "gsim_CombatRuntime"}
        profile = _load_product_spec_profile(
            root, class_key, level, spec,
            source_sha256=sha256(source_db.read_bytes()).hexdigest())
        if profile is None:
            return {"status": "BLOCKED", "reasons": [
                "SOURCE_SPEC_PRODUCT_PROFILE_NOT_CONFIGURED"],
                "production_engine": "gsim_CombatRuntime"}
        search_spec = {"spec_tree": profile["tree_key"],
                       "min_spec_points": profile["minimum_points"]}
    # The legal role only seeds equipment. It does not seed a talent, APL,
    # gear optimizer winner or previous run. Current native 2D integration
    # remains a separate gating dependency (gsim result is diagnostic).
    role = roles[0]
    seed = source_cold_start_stage(
        class_key=class_key, level=level, source_ir=ir, gear_role=role)
    search = search_bounded_joint_frontier(
        class_key=class_key, level=level, source_ir=ir, seed_stage=seed,
        bonus_talent_points=None,
        max_talents=8, max_gear_moves=12, max_policies=4,
        max_recovery_policies=2, max_paid_builds=32,
        max_cpu_s=float(budget_s), per_candidate_wall_s=.75,
        screen_mobs=2, finalist_mobs=100, pack_size=2,
        search_only=True, screen_evaluator_backend="direct",
        allow_unallocated_talent_baseline=(
            str(class_key).lower() == "mage" and int(level) == 30
            and spec == "unrestricted"),
        refinement_rounds=0, **search_spec)
    if search.get("status") == "BLOCKED":
        return {
            "status": "BLOCKED",
            "reasons": list(search.get("reasons") or [
                "BLOCKED_NO_EXECUTABLE_FULL_POINT_SOURCE_TALENT_FRONTIER"]),
            "production_component": "src.v2.source_bounded_joint_frontier.search_bounded_joint_frontier",
            "production_engine": "gsim_CombatRuntime",
            "talent_frontier_mode": search.get("talent_frontier_mode"),
            "p4_talent_unlock_coverage_pass": False,
            "p4_talent_unlock_coverage_complete": False,
            "real_talent_unlocked_actions_cast": 0,
            "coverage_scope_complete": False,
            "required_full_search_s": (30 if gate == "P4" else 300),
            "diagnostic_wall_s": search.get("wall_s"),
        }
    counts = paid_gear_slot_coverage(search)
    # Explored gear slots are search BREADTH, not correctly functioning
    # behavioral assertions. They must never be a gate success percentage.
    # P4/P5 do have an actual sourced functional requirement: talent-unlocked
    # actions must be cast in a completed paid CombatRuntime screen.
    unlocked = search.get("p4_talent_unlock_coverage") or {}
    verified_unlocks = sum(
        (row.get("status") == "EXECUTED_IN_COMPLETE_PAID_SCREEN"
         and int(row.get("executed_casts") or 0) > 0
         and int(row.get("complete_paid_screens") or 0) > 0)
        for row in unlocked.values()
    )
    actions = paid_source_action_coverage(search, ir.actions)
    reasons = [
        gate + "_FULL_SEARCH_AND_INDEPENDENT_100MOB_NOT_EXECUTED",
        gate + "_SELECTED_NATIVE_2D_COMPATIBILITY_NOT_VERIFIED"]
    if counts["executed"] == 0:
        reasons.append("NO_COMPLETE_SOURCE_PAID_RUNTIME_SCREENS")
    if actions["verified"] == 0:
        reasons.append("NO_SOURCE_ACTION_CAST_IN_COMPLETE_PAID_SCREEN")
    return {
        "status": "FAIL",
        "reasons": reasons,
        "production_component": "src.v2.source_bounded_joint_frontier.search_bounded_joint_frontier",
        "production_engine": "gsim_CombatRuntime",
        # This is the observed source-legal search BREADTH, never success%.
        "explored_paid_gear_slots": counts["verified"],
        "source_eligible_gear_slot_count": counts["applicable"],
        # Direct runtime contact with the source-legal action universe.
        # This grants the first positive PARTIAL on one genuine completed
        # paid source-action screen, without requiring a talent unlock.
        # It is still only a narrow, provisional part of P4/P5.
        **({
            "reachability_count": actions["applicable"],
            "pass_count": actions["verified"],
            "behavior_probes_executed": actions["executed"],
            "partial_scope": "SOURCE_ACTIONS_CAST_IN_COMPLETE_PAID_SCREEN",
            "coverage_basis": "executed_behavior_assertions",
        } if actions["applicable"] and actions["verified"] else {}),
        "real_talent_unlocked_actions_cast": verified_unlocks,
        "talent_frontier_mode": search.get("talent_frontier_mode"),
        "p4_talent_unlock_coverage_pass": bool(
            search.get("p4_talent_unlock_coverage_pass", False)),
        "p4_talent_unlock_coverage_complete": bool(
            search.get("p4_talent_unlock_coverage_complete", False)),
        "coverage_scope_complete": False,
        "paid_source_gear_slots": counts["paid_slots"],
        "source_eligible_gear_slots": counts["eligible_slots"],
        "real_paid_unique_full_builds": search["unique_full_builds"],
        "real_paid_screen_complete": search["screen_complete_candidates"],
        "real_source_unlock_coverage": search["p4_talent_unlock_coverage"],
        "diagnostic_wall_s": search["wall_s"],
        "required_full_search_s": (30 if gate == "P4" else 300),
        "source_role": role,
        "selected_backend_integration_pending": True,
    }


def _source_frontier_blocked_result(report, error, prefix):
    blocked_tokens = (
        "BLOCKED_NO_EXECUTABLE_FULL_POINT_SOURCE_TALENT_FRONTIER",
        "BLOCKED_NO_EXECUTABLE_SOURCE_POLICY_FRONTIER",
        "SOURCE_FULL_POINT_TALENT_FRONTIER_EMPTY",
    )
    if isinstance(report, dict) and report.get("status") == "BLOCKED":
        reasons = list(report.get("reasons") or [prefix + "SOURCE_FRONTIER_BLOCKED"])
        return {"status": "BLOCKED", "reasons": reasons,
                "production_engine": "gsim_CombatRuntime"}
    if error and any(token in str(error) for token in blocked_tokens):
        return {"status": "BLOCKED", "reasons": [prefix + str(error)],
                "production_engine": "gsim_CombatRuntime"}
    return None


def run_full_paid_source_search(root: Path, class_key: str, level: int, *,
                                spec: str, gate: str) -> dict:
    """Opt-in REAL 30/300s cold source search plus external paid 100-mob replay.

    The existing WF437 production entrypoint does the search and replay; this
    gate adapter only checks its actual receipt. A gsim-only search cannot
    certify the selected native/world P4/P5 gate, even if every mob dies.
    """
    from math import isfinite
    from tempfile import TemporaryDirectory
    from tools.wf_gate_p6_full_source import _execute

    if gate not in ("P4", "P5"):
        raise ValueError("UNSUPPORTED_LEVELING_SEARCH_GATE")
    # Old L30 CLI defaults remain byte-compatible; other checkpoints use the
    # same WF437 production search with explicit canonical source/spec inputs.
    checkpoint_args = ([] if (class_key, level, spec) ==
                       ("druid", 30, "unrestricted") else [
        "--checkpoint-class", class_key, "--checkpoint-level", str(level),
        "--checkpoint-spec", spec])

    # Both gates use ONE cold 300s search. P4 freezes its actual 30s paid
    # best-so-far; P5 continues the same execution to the 300s frontier.
    # The runner replays the frozen 30s winner only when its build is absent
    # from the later finalist list. Identical winners reuse one real receipt.
    budget, timeout_s = 300, 720
    with TemporaryDirectory(prefix="source-paid-" + gate.lower() + "-") as temp:
        folder = Path(temp)
        output = folder / "cold-300.json"
        report, error = _execute(
            Path(root), ["--budget", "300", *checkpoint_args], output, timeout_s)
        blocked = _source_frontier_blocked_result(report, error, gate + "_")
        if blocked:
            return blocked
        if error:
            return {"status": "FAIL", "reasons": [gate + "_" + error],
                    "production_engine": "gsim_CombatRuntime"}

    snapshot = report.get("snapshot_30")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    snapshot_winner = snapshot.get("winner")
    frozen_index = snapshot.get("validation_shortlist_index")
    if (not isinstance(snapshot_winner, dict)
            or type(frozen_index) is not int
            or snapshot.get("cutoff_elapsed_s") != 30
            or snapshot.get("source") != "PAID_SCREEN_COMPLETION_CLOCK"):
        frozen_index = -1
    # The actual cold run embeds independent 100-mob finalist replay OUTSIDE
    # the 30/300s search budget. A successful subprocess alone proves neither.
    validation = report.get("validation")
    validation = validation if isinstance(validation, dict) else {}
    rows = validation.get("rows") or []
    winner_id = validation.get("validated_winner_id")
    shortlist = report.get("validation_shortlist")
    shortlist = shortlist if isinstance(shortlist, list) else []
    final_index = (int(str(winner_id)) if winner_id is not None
                   and str(winner_id).isdigit() else -1)
    # The frozen 30s winner can be different from the 300s validated
    # winner. Verify that its saved shortlist entry is the actual paid
    # candidate frozen at the cutoff; never alias the later finalist.
    if (not isinstance(snapshot_winner, dict)
            or not 0 <= frozen_index < len(shortlist)
            or not isinstance(shortlist[frozen_index], dict)
            or shortlist[frozen_index].get("paid_candidate_index")
               != snapshot_winner.get("paid_candidate_index")):
        frozen_index = -1
    winner_index = frozen_index if gate == "P4" else final_index

    def receipt_for(index):
        if type(index) is not int or index < 0 or not isinstance(rows, list):
            return {}
        matches = [r for r in rows if isinstance(r, dict)
                   and str(r.get("id")) == str(index)]
        return matches[0] if len(matches) == 1 else {}

    # Always use the 100-mob replay of the *selected* window's own build.
    # Previously P4 used the 300s winner_id row, potentially granting P4
    # completion/time even when the 30s winner had never survived 100 mobs.
    row = receipt_for(winner_index)
    seconds = row.get("full_s_per_mob")
    mobs = row.get("mob_completed", row.get("count"))
    complete = (0 <= winner_index < len(shortlist)
                and row.get("status") == "COMPLETE"
                and type(row.get("count")) is int and row["count"] == 100
                and type(mobs) is int and mobs == 100
                and type(seconds) in (int, float)
                and isfinite(seconds) and seconds > 0)
    wall = report.get("wall_s")
    valid_search = (report.get("class_key") == class_key
                    and report.get("level") == level
                    and report.get("search_only") is True
                    and report.get("requested_wall_budget_s") == 300
                    and type(wall) in (int, float)
                    and isfinite(wall) and 30 <= wall <= 300
                    and isinstance(report.get("source_db_sha256"), str)
                    and len(report["source_db_sha256"]) == 64
                    and isinstance(report.get("validation_shortlist"), list)
                    and bool(report["validation_shortlist"]))
    if not valid_search:
        return {"status": "FAIL", "reasons": [
            gate + "_SOURCE_COLD_SEARCH_RECEIPT_INCOMPLETE"],
            "production_engine": "gsim_CombatRuntime"}

    # The paid 100-mob count is not evidence that the SAVED winner is a
    # source-legal whole build. Reuse the P6 source/catalogue/equipment audit,
    # rather than trusting the shortlist's item IDs or serialized stats.
    required = {"allocation", "equipped_gear", "opening_action_ids",
                "policy_ir", "policy_signature", "recovery"}
    winner = shortlist[winner_index] if 0 <= winner_index < len(shortlist) else None
    full_saved_build = isinstance(winner, dict) and required <= winner.keys()
    pinned_gear_source = False
    gear_legal = False
    gear_effect_gaps = {}
    class_membership_attested = False
    gear_audit_error = None
    if full_saved_build:
        from src.v2 import source_paid_cold_comparison as source_comparison
        try:
            saved_snapshot = report.get("source_gear_catalogue_snapshot")
            pinned_gear_source = (
                isinstance(saved_snapshot, dict)
                and saved_snapshot == source_comparison.source_gear_catalogue_snapshot(
                    class_key, level))
            if pinned_gear_source:
                class_membership_attested = (
                    saved_snapshot.get("class_membership_verified") is True)
                source_comparison._verify_winner_gear_legality(
                    winner, class_key=class_key, level=level)
                gear_effect_gaps = source_comparison._winner_gear_effect_gaps(
                    winner, class_key=class_key, level=level)
                gear_legal = True
            else:
                gear_audit_error = "SOURCE_GEAR_SNAPSHOT_MISSING_OR_CHANGED"
        except Exception as exc:
            # The failed source audit remains a diagnostic, never a gate PASS;
            # retain the first error type without hiding actual paid-kill data.
            gear_audit_error = type(exc).__name__ + ": " + str(exc)[:160]
    else:
        gear_audit_error = "SAVED_SOURCE_WINNER_INCOMPLETE"

    # Approved COMMON and P4-P6 explicitly permit a genuine gsim-only
    # continuous 2D leveling executor. Native hybrid integration is useful
    # migration work, NOT an extra P4/P5 acceptance predicate. Likewise a
    # complete external class-item capture is not required when the actual
    # searched/equipped build has been source-legality audited.
    reasons = []
    if (report.get("spatial_mode") not in (
            "simultaneous_2d_pack", "2d_sequential_not_simultaneous_pack")
            or type(report.get("pack_size")) is not int
            or report["pack_size"] < 1):
        reasons.append(gate + "_REAL_CONTINUOUS_2D_WORLD_NOT_VERIFIED")
    unlocks = report.get("p4_talent_unlock_coverage") or {}
    if unlocks and not any(
            isinstance(entry, dict)
            and entry.get("status") == "EXECUTED_IN_COMPLETE_PAID_SCREEN"
            and type(entry.get("executed_casts")) is int
            and entry["executed_casts"] > 0 for entry in unlocks.values()):
        reasons.append(gate + "_NO_REPRESENTATIVE_PAID_TALENT_UNLOCK")
    space = report.get("source_search_space")
    if (not isinstance(space, dict)
            or space.get("class_key") != class_key
            or space.get("level") != level
            or space.get("checkpoint_spec", "unrestricted") != spec):
        reasons.append(gate + "_ACTUAL_CHECKPOINT_SOURCE_SEARCH_SPACE_MISMATCH")
    if (type(report.get("unique_full_builds")) is not int
            or report["unique_full_builds"] < 1
            or type(report.get("screen_complete_candidates")) is not int
            or report["screen_complete_candidates"] < 1):
        reasons.append(gate + "_NO_REAL_COMPLETED_PAID_WHOLE_BUILDS")
    if not pinned_gear_source:
        reasons.append(gate + "_GEAR_CATALOGUE_SNAPSHOT_NOT_VERIFIED")
    if not gear_legal:
        reasons.append(gate + "_WINNING_GEAR_SOURCE_LEGALITY_NOT_VERIFIED")
    if gear_effect_gaps:
        reasons.append(gate + "_WINNER_ITEM_EFFECTS_UNRESOLVED")
    # Keep class-membership capture status visible as diagnostic provenance,
    # without converting a missing full external scrape into a hidden gate.
    if not complete:
        reasons.append(gate + "_INCOMPLETE_PAID_100MOB_FINALIST")
    # Snapshot and finalist are paid by the same source/config/engine run.
    # The saved validation rows are real 100-mob retained-world executions.
    # When both winners have the same shortlist index, the exact same
    # execution receipt suffices; no second identical 100-mob replay.
    def replay_receipt(index, window):
        entry = receipt_for(index)
        return {"window_s": window, "status": entry.get("status"),
                "count": entry.get("count"),
                "mob_completed": entry.get("mob_completed", entry.get("count")),
                "s_per_mob": entry.get("full_s_per_mob")}

    p5_replays = [replay_receipt(frozen_index, 30),
                  replay_receipt(final_index, 300)]
    p5_replays_complete = (
        all(item["status"] == "COMPLETE"
            and type(item["count"]) is int and item["count"] == 100
            and type(item["mob_completed"]) is int
            and item["mob_completed"] == 100
            and type(item["s_per_mob"]) in (int, float)
            and isfinite(item["s_per_mob"]) and item["s_per_mob"] > 0
            for item in p5_replays))
    continuation_paid = snapshot.get("paid_candidates_after_cutoff")
    n30 = snapshot.get("unique_full_builds_before_cutoff")
    n300 = report.get("unique_full_builds")
    if frozen_index < 0 or frozen_index >= len(shortlist):
        reasons.append(gate + "_REAL_30S_FROZEN_PAID_WINNER_MISSING")
    if gate == "P5":
        if type(continuation_paid) is not int or continuation_paid < 1:
            reasons.append("P5_NO_REAL_PAID_EVALUATION_AFTER_30S")
        if type(n300) is not int or n300 < 2:
            reasons.append("P5_DISTINCT_PAID_WHOLE_BUILDS_MISSING")
        if not p5_replays_complete:
            reasons.append("P5_P4_P5_REAL_100MOB_WINNER_RECEIPTS_INCOMPLETE")
    # A successful live run already has its own paid search and complete
    # source-bound 100-mob replay. Give the shared CLI its ordinary runtime
    # identity (same shape as P3), without imposing a second evidence job.
    proof = {}
    if not reasons:
        from hashlib import sha256
        from json import dumps
        from uuid import uuid4
        from src.version import SOFTWARE_VERSION

        source_identity = dumps({
            "ability_db_sha256": report["source_db_sha256"],
            "gear_catalogue": report["source_gear_catalogue_snapshot"],
        }, sort_keys=True, separators=(",", ":"), default=str)
        proof = {"runtime_proof": {
            "executed": True,
            "engine_revision": "gsim-" + SOFTWARE_VERSION,
            "source_revision": sha256(source_identity.encode()).hexdigest(),
            "run_id": "source-paid-" + gate.lower() + "-" + str(uuid4()),
        }}
    return {
        "status": "FAIL" if reasons else "PASS", "reasons": reasons,
        **proof,
        "production_engine": "gsim_CombatRuntime",
        "production_component": "tools.wf437_direct_budgeted_run",
        "selected_production_backend": "gsim",
        "native_hybrid_diagnostic_pending": True,
        "requested_wall_budget_s": budget,
        "real_search_wall_s": wall,
        "source_db_sha256": report["source_db_sha256"],
        "source_gear_catalogue_snapshot": report.get("source_gear_catalogue_snapshot"),
        "real_paid_unique_full_builds": report.get("unique_full_builds"),
        "snapshot_N30_unique_paid": n30,
        "continuous_N300_unique_paid": n300,
        "continuous_paid_evaluations_after_30s": continuation_paid,
        "single_300s_cold_search": True,
        "same_winner_100mob_receipt_reused": (
            frozen_index >= 0 and frozen_index == final_index),
        "p4_p5_100mob_winner_replays_complete": p5_replays_complete,
        "p4_p5_100mob_winner_replays": p5_replays,
        "real_paid_screen_complete": report.get("screen_complete_candidates"),
        "real_talent_unlocked_actions": report.get("p4_talent_unlock_coverage"),
        "talent_unlock_paid_coverage_pass": (
            report.get("p4_talent_unlock_coverage_pass") is True),
        "saved_full_source_winner_build": full_saved_build,
        "gear_source_snapshot_matches_current": pinned_gear_source,
        "winning_gear_source_legality_verified": gear_legal,
        "winning_gear_unresolved_effects": gear_effect_gaps,
        "source_class_gear_membership_attested": class_membership_attested,
        "winning_gear_audit_error": gear_audit_error,
        "source_legal_gear_universe_verified": (
            report.get("source_legal_gear_universe_verified") is True),
        "real_100mob_complete": complete,
        "real_100mob_count": row.get("count") if complete else 0,
        "real_100mob_s_per_mob": seconds if complete else None,
        # Other engines are still being integrated, but gsim is a valid
        # selected production backend when ALL actual gate predicates pass.
        "selected_backend_integration_pending": True,
        "coverage_scope_complete": not reasons,
    }
