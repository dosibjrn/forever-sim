"""Actual source-legal gear slots must receive paid frontier coordinates.

This tests production candidate scheduling using the real Mage/Druid item
catalogue and valid full-equipment substitutions. It does not claim a P4 gate.
"""
from collections import Counter
from itertools import islice
from pathlib import Path

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.v2.source_bounded_joint_frontier import (
    _SOURCE_GEAR_SAMPLING_VERSION, _source_gear_witness_probes,
    _source_witness_first_coordinates,
    source_cold_start_stage,
)
from src.v2.source_persistent_slot_search import (
    _source_slot_proposals, _source_stat_package_proposals,
)
from src.v2.source_joint_progress import PaidJointProgressJournal, search_context_sha256
from src.v2.source_persistent_joint_finalists import prepare_candidate
from src.v2.source_bounded_joint_frontier import _quick_joint_evaluation


def test_source_legal_slots_get_early_paid_witnesses_before_generic_cross_product():
    for class_key in ("mage", "druid"):
        source_ir = build_game_ir_slice(class_key=class_key, level=30)
        seed = source_cold_start_stage(
            class_key=class_key, level=30, source_ir=source_ir, gear_role=class_key)
        base = seed["gear_policy_result"]["winner"]["gear"]
        moves, _ = _source_slot_proposals(
            class_key=class_key, level=30, base=base,
            per_slot=2, max_proposals=24, slot_offset=0)
        gear_stages = [("incumbent", seed)]
        for slot, item in moves:
            try:
                stage = substituted_multi_stage(
                    stage=seed, class_key=class_key, level=30,
                    swaps={slot: int(item.item_id)})
            except (ValueError, KeyError):
                continue
            gear_stages.append((f"{slot}:{item.item_id}", stage))

        eligible_slots = {label.split(":", 1)[0] for label, _ in gear_stages[1:]}
        assert len(eligible_slots) >= 6, (class_key, eligible_slots)
        witnesses = _source_gear_witness_probes(gear_stages)
        paid_slots = [gear_stages[coords[1]][0].split(":", 1)[0]
                      for coords in witnesses]
        first_pass = paid_slots[:len(eligible_slots)]
        assert len(first_pass) == len(set(first_pass)), (class_key, first_pass)
        assert set(first_pass) == eligible_slots, (class_key, first_pass, eligible_slots)
        assert len(witnesses) == len(set(witnesses))

        # The actual four-axis scheduler must pay for those gear coordinates
        # before consuming its generic policy/talent cross-product suffix.
        # Only the policy labels are inert here: no mock combat or PASS.
        variants = ((("incumbent", None),),)
        dimensions = (1, len(gear_stages), 1, 1)
        scheduled = list(islice(_source_witness_first_coordinates(
            dimensions, variants, "diagonal", [],
            gear_stages=gear_stages), len(witnesses)))
        assert scheduled == list(witnesses), (class_key, scheduled, witnesses)


def test_real_source_depth_three_enters_joint_paid_witness_prefix():
    # The 300s search can admit more gear moves than the 30s search.
    # A hardcoded per-slot top-two cap used to waste that extra paid budget.
    # This is the same catalogue, legality path and scheduler as production;
    # no simulated scores, fake items or gate-acceptance claims.
    for class_key in ("mage", "druid"):
        source_ir = build_game_ir_slice(class_key=class_key, level=30)
        seed = source_cold_start_stage(
            class_key=class_key, level=30, source_ir=source_ir, gear_role=class_key)
        base = seed["gear_policy_result"]["winner"]["gear"]
        deep, source_counts = _source_slot_proposals(
            class_key=class_key, level=30, base=base,
            per_slot=10, max_proposals=64, slot_offset=0)
        shallow, shallow_counts = _source_slot_proposals(
            class_key=class_key, level=30, base=base,
            per_slot=2, max_proposals=64, slot_offset=0)
        assert source_counts == shallow_counts
        assert len(deep) <= 64
        assert len({(slot, item.item_id) for slot, item in deep}) == len(deep)
        shallow_ids = {(slot, item.item_id) for slot, item in shallow}
        assert any((slot, item.item_id) not in shallow_ids for slot, item in deep)

        gear_stages = [("incumbent", seed)]
        for slot, item in deep:
            try:
                stage = substituted_multi_stage(
                    stage=seed, class_key=class_key, level=30,
                    swaps={slot: int(item.item_id)})
            except (ValueError, KeyError):
                continue
            gear_stages.append((f"{slot}:{item.item_id}", stage))

        slots = [label.split(":", 1)[0] for label, _ in gear_stages[1:]]
        counts = Counter(slots)
        assert any(count >= 3 for count in counts.values()), (class_key, counts)
        witnesses = _source_gear_witness_probes(gear_stages)
        paid_slots = [gear_stages[coords[1]][0].split(":", 1)[0]
                      for coords in witnesses]
        assert len(witnesses) <= 32
        assert set(paid_slots[:len(counts)]) == set(counts)
        assert any(count >= 2 for count in Counter(paid_slots).values()), (
            class_key, paid_slots)
        # Larger explicit witness budgets can reach depth three without
        # changing the legal source inventory or the paid evaluation engine.
        deep_witnesses = _source_gear_witness_probes(
            gear_stages, max_probes=64)
        deep_paid_slots = [gear_stages[coords[1]][0].split(":", 1)[0]
                           for coords in deep_witnesses]
        assert any(count >= 3 for count in Counter(deep_paid_slots).values()), (
            class_key, deep_paid_slots)

        variants = ((("incumbent", None),),)
        dimensions = (1, len(gear_stages), 1, 1)
        scheduled = list(islice(_source_witness_first_coordinates(
            dimensions, variants, "diagonal", [],
            gear_stages=gear_stages), len(witnesses)))
        assert scheduled == list(witnesses), (class_key, scheduled, witnesses)



def test_pure_source_stat_witness_survives_bounded_package_prefix():
    # A bounded real paid prefix must not be consumed by mixed-stat and
    # atomic-weapon families before the first legal pure-stat package.
    # The previous scheduler dropped this coordinate at max_probes=32.
    stages = [('incumbent', None)]
    stages += [(f'slot{i}:item', None) for i in range(12)]
    stages += [(f'source_stat_package:spell_power+stat{i}', None)
               for i in range(20)]
    stages += [(f'package:weapon{i}', None) for i in range(10)]
    pure_index = len(stages)
    stages.append(('source_stat_package:spell_power', None))
    witnesses = _source_gear_witness_probes(stages, max_probes=32)
    assert (0, pure_index, 0, 0) in witnesses


def test_pure_source_stat_package_reaches_real_paid_frontier_before_repeated_slot():
    # Production previously generated legal pure-axis full gear packages, but
    # silently omitted them from the witness prefix (only '+' mixed labels
    # survived). Check the actual canonical source catalogue and pay the
    # same real CombatRuntime as ordinary gear coordinates.
    class_key, level = "mage", 30
    ir = build_game_ir_slice(class_key=class_key, level=level)
    seed = source_cold_start_stage(
        class_key=class_key, level=level, source_ir=ir, gear_role=class_key)
    base = seed["gear_policy_result"]["winner"]["gear"]
    moves, _ = _source_slot_proposals(
        class_key=class_key, level=level, base=base,
        per_slot=3, max_proposals=18)
    stat_packages, _ = _source_stat_package_proposals(
        class_key=class_key, level=level, base=base, max_packages=8)

    stages = [("incumbent", seed)]
    for slot, item in moves:
        try:
            variant = substituted_multi_stage(
                stage=seed, class_key=class_key, level=level,
                swaps={slot: int(item.item_id)})
        except (ValueError, KeyError):
            continue
        stages.append((f"{slot}:{item.item_id}", variant))
    for axis, swaps in stat_packages:
        variant = substituted_multi_stage(
            stage=seed, class_key=class_key, level=level, swaps=swaps)
        stages.append(("source_stat_package:" + axis, variant))

    pure = [i for i, (label, _) in enumerate(stages)
            if label.startswith("source_stat_package:") and "+" not in label]
    assert pure, stat_packages
    # Exercise the exact production cap, not a larger test-only prefix.
    witnesses = _source_gear_witness_probes(stages)
    scheduled_indices = [c[1] for c in witnesses]
    assert len(witnesses) <= 32
    assert pure[0] in scheduled_indices
    first_pure = min(scheduled_indices.index(i) for i in pure)
    def slot_key(index):
        label = stages[index][0]
        return label.split(":", 1)[0] if ":" in label and not label.startswith(
            ("source_stat_package:", "package:")) else None
    first_repeat = next((
        j for j, index in enumerate(scheduled_indices)
        if slot_key(index) is not None
        and slot_key(index) in {slot_key(prev) for prev in scheduled_indices[:j]}
        ), len(scheduled_indices))
    assert first_pure < first_repeat, [stages[i][0] for i in scheduled_indices]

    variants = ((("incumbent", None),),)
    scheduled = list(islice(_source_witness_first_coordinates(
        (1, len(stages), 1, 1), variants, "diagonal", [],
        gear_stages=stages), len(witnesses)))
    assert (0, pure[0], 0, 0) in scheduled
    candidate = prepare_candidate(
        class_key=class_key, level=level, stage=stages[pure[0]][1],
        source_ir=ir, allow_partial_gear_stats=True)
    real_paid = _quick_joint_evaluation(
        candidate, level=level, mobs=1, recovery_policy=None,
        timeout_s=8., pack_size=1, backend="direct")
    assert real_paid["status"] == "COMPLETE", real_paid
    assert real_paid["count"] == 1 and real_paid["events"] > 0

def test_package_families_survive_real_32_coordinate_cap_under_pressure():
    # No fake combat: exercise the production scheduler's fixed 32-coordinate
    # bound with more source-labelled mixed/weapon proposals than can fit.
    # The separate canonical Mage test proves a legal pure-stat stage can
    # actually reach CombatRuntime's paid one-mob evaluation.
    stages = [('incumbent', None)]
    stages.extend((f'slot{n}:item{n}', None) for n in range(16))
    stages.extend((f'source_stat_package:mixed{n}+mixed{n}', None)
                  for n in range(24))
    stages.extend((f'package:weapon{n}', None) for n in range(24))
    stages.append(('source_stat_package:stamina', None))
    indices = [coordinates[1] for coordinates in
               _source_gear_witness_probes(stages)]
    labels = [stages[i][0] for i in indices]
    assert len(indices) == 32
    assert 'source_stat_package:stamina' in labels
    assert any(label.startswith('package:') for label in labels)
    assert any('+' in label for label in labels)
    assert len({label.split(':', 1)[0] for label in labels
                if label.startswith('slot')}) == 16


def test_deeper_source_frontier_cannot_resume_old_paid_search_journal(tmp_path):
    """Older paid journals cannot resume after candidate-order or event schema changes."""
    class_key, level = "mage", 30
    source_ir = build_game_ir_slice(class_key=class_key, level=level)
    seed = source_cold_start_stage(
        class_key=class_key, level=level, source_ir=source_ir, gear_role=class_key)
    assert _SOURCE_GEAR_SAMPLING_VERSION == "stratified_source_slots_v10_pure_stat_paid_witness"
    new_options = {"gear_slot_sampling_version": _SOURCE_GEAR_SAMPLING_VERSION}
    new_hash = search_context_sha256(
        class_key=class_key, level=level, source_ir=source_ir,
        seed_stage=seed, options=new_options)
    for old_version in ("stratified_source_slots_v1", "stratified_source_slots_v2_depth10",
                        "stratified_source_slots_v3_paid_axis_balance",
                        "stratified_source_slots_v4_paid_events_identity",
                        "stratified_source_slots_v5_real_paid_budget",
                        "stratified_source_slots_v6_mandatory_unlock_axis",
                        "stratified_source_slots_v7_all_required_unlocks",
                        "stratified_source_slots_v8_skip_absent_source_apl",
                        "stratified_source_slots_v9_atomic_weapon_paid_witness"):
        old_hash = search_context_sha256(
            class_key=class_key, level=level, source_ir=source_ir,
            seed_stage=seed, options={"gear_slot_sampling_version": old_version})
        assert old_hash != new_hash
        path = tmp_path / (old_version + ".json")
        old_journal = PaidJointProgressJournal(path, context_sha256=old_hash)
        old_journal.write(
            status="IN_PROGRESS_NOT_CERTIFIED", phase="PREPARED",
            attempted=[], completed=[], events=0, full_evaluated_candidates=0,
            elapsed_wall_s=0.)
        with pytest.raises(ValueError, match="mismatched input context"):
            PaidJointProgressJournal(path, context_sha256=new_hash, resume=True)


def test_compound_apl_gets_a_paid_coordinate_before_second_item_in_same_slot():
    # Real Mage/Druid source gear stages, production coordinate scheduler.
    # No combat mocks or checkpoint PASS: this establishes the *order* of
    # candidates that can actually reach the paid evaluator.
    for class_key in ("mage", "druid"):
        ir = build_game_ir_slice(class_key=class_key, level=30)
        seed = source_cold_start_stage(
            class_key=class_key, level=30, source_ir=ir, gear_role=class_key)
        base = seed["gear_policy_result"]["winner"]["gear"]
        moves, _ = _source_slot_proposals(
            class_key=class_key, level=30, base=base,
            per_slot=10, max_proposals=64)
        gear_stages = [("incumbent", seed)]
        for slot, item in moves:
            try:
                stage = substituted_multi_stage(
                    stage=seed, class_key=class_key, level=30,
                    swaps={slot: int(item.item_id)})
            except (ValueError, KeyError):
                continue
            gear_stages.append((f"{slot}:{item.item_id}", stage))
        # Source policy label only, no fake combat scoring.
        variants = ((("incumbent", None), ("multi_dot", None)),)
        dims = (1, len(gear_stages), 2, 1)
        scheduled = list(islice(
            _source_witness_first_coordinates(
                dims, variants, "diagonal", [], gear_stages=gear_stages), 80))
        compound = (0, 0, 1, 0)
        assert compound in scheduled
        def pure_slot(c):
            label = gear_stages[c[1]][0]
            return (c[1] != 0 and c[2] == 0
                    and not label.startswith(("source_stat_package:", "package:")))
        pure_slots = [gear_stages[c[1]][0].split(":", 1)[0]
                      for c in scheduled if pure_slot(c)]
        assert len(pure_slots) > len(set(pure_slots)), (class_key, pure_slots)
        first_repeat = next(
            i for i, c in enumerate(scheduled)
            if pure_slot(c)
            and gear_stages[c[1]][0].split(":", 1)[0] in {
                gear_stages[a[1]][0].split(":", 1)[0]
                for a in scheduled[:i] if pure_slot(a)})
        assert scheduled.index(compound) < first_repeat, (class_key, scheduled[:first_repeat+1])


def test_source_legal_atomic_weapon_package_is_paid_before_second_slot_item():
    # The actual Mage L30 SQLite catalogue has source-legal 1H/offhand and
    # 2H alternatives. An atomic switch cannot be scored by a single-slot
    # move, so it must enter the SAME production paid coordinate scheduler.
    from src.v2.source_persistent_slot_search import _source_weapon_package_proposals

    class_key, level = "mage", 30
    ir = build_game_ir_slice(class_key=class_key, level=level)
    seed = source_cold_start_stage(
        class_key=class_key, level=level, source_ir=ir, gear_role=class_key)
    base = seed["gear_policy_result"]["winner"]["gear"]
    packages, counts = _source_weapon_package_proposals(
        class_key=class_key, level=level, base=base, max_packages=4)
    assert packages, counts
    moves, _ = _source_slot_proposals(
        class_key=class_key, level=level, base=base,
        per_slot=10, max_proposals=48)
    stages = [("incumbent", seed)]
    for slot, item in moves:
        try:
            variant = substituted_multi_stage(
                stage=seed, class_key=class_key, level=level,
                swaps={slot: int(item.item_id)})
        except (ValueError, KeyError):
            continue
        stages.append((f"{slot}:{item.item_id}", variant))
    for swaps in packages:
        variant = substituted_multi_stage(
            stage=seed, class_key=class_key, level=level, swaps=swaps)
        stages.append(("package:" + repr(sorted(swaps.items())), variant))

    witnesses = _source_gear_witness_probes(stages)
    labels = [stages[c[1]][0] for c in witnesses]
    assert any(label.startswith("package:") for label in labels), labels
    first_package = next(i for i, label in enumerate(labels)
                         if label.startswith("package:"))
    first_repeated_slot = next(
        (i for i, label in enumerate(labels)
         if ":" in label and not label.startswith(("package:", "source_stat_package:"))
         and label.split(":", 1)[0] in {
             previous.split(":", 1)[0] for previous in labels[:i]
             if ":" in previous and not previous.startswith(("package:", "source_stat_package:"))}),
        len(labels))
    assert first_package < first_repeated_slot, labels

    variants = ((("incumbent", None),),)
    scheduled = list(islice(_source_witness_first_coordinates(
        (1, len(stages), 1, 1), variants, "diagonal", [],
        gear_stages=stages), len(witnesses)))
    assert scheduled == list(witnesses)

    # Actual source candidate preparation, not a mock weapon package.
    paid_candidate = prepare_candidate(
        class_key=class_key, level=level, stage=stages[
            witnesses[first_package][1]][1], source_ir=ir,
        allow_partial_gear_stats=True)
    result = _quick_joint_evaluation(
        paid_candidate, level=level, mobs=1, recovery_policy=None,
        timeout_s=8., pack_size=1, backend="direct")
    assert result["status"] == "COMPLETE", result
    assert result["count"] == 1 and result["events"] > 0


def test_real_source_third_item_executes_through_paid_combat_runtime():
    # Not a candidate count or a fake green evaluator: execute a true
    # third-ranked legal item through the *production* GameIR+CombatRuntime.
    for class_key in ("mage", "druid"):
        ir = build_game_ir_slice(class_key=class_key, level=30)
        seed = source_cold_start_stage(
            class_key=class_key, level=30, source_ir=ir, gear_role=class_key)
        base = seed["gear_policy_result"]["winner"]["gear"]
        moves, _ = _source_slot_proposals(
            class_key=class_key, level=30, base=base,
            per_slot=10, max_proposals=64)
        counts = Counter()
        third = None
        for slot, item in moves:
            try:
                stage = substituted_multi_stage(
                    stage=seed, class_key=class_key, level=30,
                    swaps={slot: int(item.item_id)})
            except (ValueError, KeyError):
                continue
            counts[slot] += 1
            if counts[slot] == 3:
                third = (slot, item, stage)
                break
        assert third is not None, (class_key, counts)
        slot, item, stage = third
        candidate = prepare_candidate(
            class_key=class_key, level=30, stage=stage, source_ir=ir,
            allow_partial_gear_stats=True)
        assert int(candidate.source_stage["gear_policy_result"]["winner"]["gear"]
                   ["slots"][slot]["item_id"]) == int(item.item_id)
        result = _quick_joint_evaluation(
            candidate, level=30, mobs=1, recovery_policy=None,
            timeout_s=8., pack_size=1, backend="direct")
        assert result["status"] == "COMPLETE", (class_key, slot, item.item_id, result)
        assert result["count"] == 1
        assert result["events"] > 0


def test_p5_breadth_uses_real_distinct_paid_builds_not_attempted_coordinates():
    """The P5 N denominator cannot include blocked preparations or alias builds."""
    from copy import deepcopy
    from src.v2.source_bounded_joint_frontier import (
        _unique_paid_full_builds, search_bounded_joint_frontier,
    )

    ir = build_game_ir_slice(class_key="druid", level=20)
    seed = source_cold_start_stage(
        class_key="druid", level=20, source_ir=ir, gear_role="druid_feral")
    result = search_bounded_joint_frontier(
        class_key="druid", level=20, source_ir=ir, seed_stage=seed,
        max_talents=1, max_gear_moves=0, max_policies=1,
        max_recovery_policies=1, max_paid_builds=3, max_cpu_s=6.,
        per_candidate_wall_s=1.5, screen_mobs=1, search_only=True,
        screen_evaluator_backend="direct", refinement_rounds=0)
    paid = [row for row in result["rows"] if row.get("screen_events", 0) > 0]
    assert paid, result["status"]
    assert all(row["equipped_gear"]["slots"] and row["policy_signature"]
               for row in paid)
    assert result["unique_full_builds"] == _unique_paid_full_builds(result["rows"])
    assert result["unique_full_builds"] <= result["paid_candidates"]

    # Negative controls are derived from a genuinely executed source build,
    # not a fake scorer: the same full build reached by another gear label is
    # one build, while a distinct coordinate rejected before combat is zero.
    witness = deepcopy(paid[0])
    duplicate = deepcopy(witness)
    duplicate["gear_move"] = "another_source_path_to_same_items"
    blocked = deepcopy(witness)
    blocked["gear_move"] = "not_a_paid_screen"
    blocked["screen_events"] = 0
    blocked["screen_status"] = "BLOCKED_PREPARATION_OR_EXECUTION"
    assert _unique_paid_full_builds([witness, duplicate, blocked]) == 1
    assert _unique_paid_full_builds([blocked]) == 0


def test_rejected_preflight_cannot_spend_the_only_paid_screen(monkeypatch):
    """One malformed source coordinate must not steal a real CombatRuntime slot.

    Only candidate preparation is fault-injected as a negative control; the
    following legal source candidate uses the unmodified production evaluator.
    """
    import src.v2.source_bounded_joint_frontier as joint

    ir = build_game_ir_slice(class_key="druid", level=20)
    seed = source_cold_start_stage(
        class_key="druid", level=20, source_ir=ir, gear_role="druid_feral")
    prepare = joint._prepare_joint_policy_candidate
    calls = 0

    def reject_first_source_preflight(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("SOURCE_PREFLIGHT_INVALID_GEAR_NEGATIVE_CONTROL")
        return prepare(**kwargs)

    monkeypatch.setattr(joint, "_prepare_joint_policy_candidate",
                        reject_first_source_preflight)
    result = joint.search_bounded_joint_frontier(
        class_key="druid", level=20, source_ir=ir, seed_stage=seed,
        max_talents=2, max_gear_moves=0, max_policies=2,
        max_recovery_policies=2, max_paid_builds=1, max_cpu_s=8.,
        per_candidate_wall_s=2., screen_mobs=1, search_only=True,
        screen_evaluator_backend="direct", refinement_rounds=0)

    assert calls >= 2, result["rows"]
    assert result["rows"][0]["status"] == "BLOCKED_PREPARATION_OR_EXECUTION"
    assert not result["rows"][0].get("screen_invoked")
    assert result["paid_candidates"] >= 2  # attempts are journalled for resume
    assert result["initial_frontier_paid_candidates"] == 1
    assert sum(bool(row.get("screen_invoked")) for row in result["rows"]) == 1
    assert any(row.get("screen_events", 0) > 0 for row in result["rows"][1:])
    assert result["unique_full_builds"] >= 1  # real paid, source-legal build
    assert not result["eligible_for_checkpoint_acceptance"]


def test_rejected_source_preflight_resumes_without_repaying_it(monkeypatch, tmp_path):
    """A journalled rejection occupies a coordinate, not a paid slot."""
    from src.v2.source_joint_progress import load_verified_joint_progress
    import src.v2.source_bounded_joint_frontier as joint

    ir = build_game_ir_slice(class_key="druid", level=20)
    seed = source_cold_start_stage(
        class_key="druid", level=20, source_ir=ir, gear_role="druid_feral")
    real_prepare = joint._prepare_joint_policy_candidate
    calls = 0

    def reject_then_interrupt(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("SOURCE_PREFLIGHT_INVALID_GEAR_NEGATIVE_CONTROL")
        if calls == 2:
            raise KeyboardInterrupt("interrupt before next paid screen")
        return real_prepare(**kwargs)

    monkeypatch.setattr(joint, "_prepare_joint_policy_candidate",
                        reject_then_interrupt)
    journal = tmp_path / "real-source-preflight.json"
    options = dict(
        class_key="druid", level=20, source_ir=ir, seed_stage=seed,
        max_talents=2, max_gear_moves=0, max_policies=2,
        max_recovery_policies=2, max_paid_builds=1, max_cpu_s=12.,
        per_candidate_wall_s=3., screen_mobs=1,
        screen_then_finalists=True, max_finalists=1,
        progress_path=journal)
    with pytest.raises(KeyboardInterrupt, match="interrupt before next paid"):
        joint.search_bounded_joint_frontier(**options)
    snapshot = load_verified_joint_progress(journal)
    assert snapshot["paid_candidates"] == 1  # one journalled preflight reject
    assert snapshot["rows"][0]["status"] == "BLOCKED_PREPARATION_OR_EXECUTION"
    assert snapshot["rows"][0]["screen_invoked"] is False

    prepared_on_resume = 0

    def count_real_preparations(**kwargs):
        nonlocal prepared_on_resume
        prepared_on_resume += 1
        return real_prepare(**kwargs)

    monkeypatch.setattr(joint, "_prepare_joint_policy_candidate",
                        count_real_preparations)
    result = joint.search_bounded_joint_frontier(**options, resume_progress=True)
    assert prepared_on_resume == 1, result["rows"]
    assert result["paid_candidates"] >= 2
    assert sum(bool(row.get("screen_invoked")) for row in result["rows"]) == 1
    assert result["initial_frontier_paid_candidates"] == 1
    assert any(row.get("screen_events", 0) > 0 for row in result["rows"][1:])
    assert result["unique_full_builds"] >= 1
    assert not result["eligible_for_checkpoint_acceptance"]


@pytest.mark.parametrize("max_paid_builds,expected_refinement", [(1, 0), (2, 1)])
def test_refinement_never_spends_a_second_real_screen_past_paid_budget(max_paid_builds, expected_refinement):
    # Genuine source-backed Druid L20 cold search, no mocked scorer.
    # Before the fix the first real frontier screen exhausted the one-call
    # budget, but the Top-N refinement still paid another CombatRuntime call.
    from src.v2.source_bounded_joint_frontier import search_bounded_joint_frontier

    source_ir = build_game_ir_slice(class_key="druid", level=20)
    stage = source_cold_start_stage(
        class_key="druid", level=20, source_ir=source_ir,
        gear_role="druid_feral")
    result = search_bounded_joint_frontier(
        class_key="druid", level=20, source_ir=source_ir,
        seed_stage=stage, max_paid_builds=max_paid_builds, max_cpu_s=9.,
        per_candidate_wall_s=3., max_talents=1,
        max_gear_moves=0, max_policies=1, max_recovery_policies=1,
        screen_mobs=1, search_only=True,
        screen_evaluator_backend="direct", refinement_rounds=1,
        refinement_top_n=1, refinement_stat_axes=("strength",),
        refinement_probe_delta=20., refinement_gear_candidates=1,
        refinement_policy_candidates=1, refinement_talent_neighbors=0,
        screen_budget_fraction=.4)
    assert result["screen_complete_candidates"] == 1, result["rows"]
    assert result["events"] > 0
    assert result["first_pass_screen_candidates"] == 1
    assert result["refinement"]["paid_evaluations"] == expected_refinement
    assert result["all_quick_evaluations_including_stat_probes"] == max_paid_builds
    assert result["search_budget_exhausted"] is True


def test_p3_source_weapon_proposals_preserve_complete_equipment_legality():
    """Real Mage 1H+offhand must not spend P4 gear moves on a 2H swap.

    The canonical P3 catalogue includes both weapon families. An atomic
    weapon-package move can still switch them; a single-slot move cannot.
    This exercises the actual source-certified proposal path, not mock items.
    """
    from src.rulesets.forever.items.runtime_selection import select_gear, available_items
    from src.v2.source_bounded_joint_frontier import _cold_source_equipment_payload
    from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
    from src.v2.source_persistent_slot_search import _gear_replace

    from src.rulesets.forever.items.source_equipment_semantics import validate_equipped_item_ids

    class_key, level = "mage", 30
    source_items = available_items(class_key, level, required_level_policy="observed")
    selected = select_gear(class_key, level, "mage", weights={},
        required_level_policy="observed", exclude_unknown_item_effects=False)
    onehand = next(item for item in source_items
        if item.weapon_hands == 1 and item.slot in ("one_hand", "main_hand"))
    offhand = next(item for item in source_items
        if item.slot == "off_hand" and item.weapon_hands != 2
        and item.item_id != onehand.item_id)
    twohand = next(item for item in source_items
        if item.weapon_hands == 2 and item.slot in ("two_hand", "main_hand", "one_hand"))
    selected = {**selected, "weapon": onehand, "offhand": offhand}
    validate_equipped_item_ids(item.item_id for item in selected.values())
    base = _cold_source_equipment_payload(
        class_key=class_key, level=level, gear_role="mage", selected=selected)

    # RED on the old code: the low-level single-slot stage builder accepted
    # an illegal 2H+offhand package because unique-item validation alone
    # cannot validate hand occupancy.
    with pytest.raises(ValueError, match="SOURCE_SLOT_REQUIRES_ATOMIC_WEAPON_PACKAGE"):
        _gear_replace(base, "weapon", twohand)

    # RED on the old P3-certified frontier: a high-priority 2H item could
    # consume a scarce paid slot despite being illegal with the current
    # offhand. The real source catalogue and certificate remain unchanged.
    certificate = checkpoint_item_l0(class_key=class_key, level=level)
    proposals, counts = _source_slot_proposals(
        class_key=class_key, level=level, base=base,
        p3_certificate=certificate, allow_unattested_diagnostic=True,
        per_slot=300, max_proposals=10000)
    assert counts["weapon"] > 0
    assert any(slot == "weapon" for slot, _ in proposals)
    assert all(not (slot == "weapon" and item.weapon_hands == 2)
               for slot, item in proposals)


def test_independent_100mob_replay_pins_talented_budget_from_real_source_search():
    """A 30s +5-point search cannot be replayed with a different point budget.

    This uses actual Forever Mage L30 source/gear preparation. The deliberately
    incomplete saved candidate is enough to prove the budget is validated
    *before* an expensive 100-mob attempt, not to fabricate a 100-mob PASS.
    """
    from src.v2.source_bounded_joint_frontier import replay_joint_shortlist_100mob

    ir = build_game_ir_slice(class_key="mage", level=30)
    stage = source_cold_start_stage(
        class_key="mage", level=30, source_ir=ir, gear_role="mage")
    report = {"search_only": True, "validation_shortlist": [
        {"allocation": stage["allocation"]}],
        "bonus_talent_points": 5, "complete_100mob_candidates": 0}

    with pytest.raises(ValueError, match="INDEPENDENT_100MOB_TALENT_BUDGET_MISMATCH"):
        replay_joint_shortlist_100mob(
            report, source_ir=ir, seed_stage=stage,
            class_key="mage", level=30, bonus_talent_points=0)

    # Without an override the actual saved +5 source budget is authoritative.
    # The next expected error is the intentionally absent gear/APL fields,
    # proving the correct budget was admitted before replay preparation.
    with pytest.raises(ValueError, match="INCOMPLETE_SEARCH_CONFIGURATION"):
        replay_joint_shortlist_100mob(
            report, source_ir=ir, seed_stage=stage,
            class_key="mage", level=30)

    with pytest.raises(ValueError, match="INDEPENDENT_100MOB_TALENT_BUDGET_NOT_PINNED"):
        replay_joint_shortlist_100mob(
            {k: v for k, v in report.items() if k != "bonus_talent_points"},
            source_ir=ir, seed_stage=stage, class_key="mage", level=30)


def test_refinement_identity_does_not_repay_same_source_build_under_different_gear_labels():
    """The short paid budget should fund new legal candidates, not label aliases.

    Build the actual source-backed Mage/Druid L30 candidate with the normal
    production preparation path. A second gear-selection coordinate yielding
    exactly that equipment/rotation/talents/recovery must have the SAME key,
    while independent recovery/APL/opening dimensions stay distinguishable.
    This is a bounded identity regression, not a P6 or checkpoint PASS.
    """
    from src.game.policy_evolution import _identity as policy_identity
    from src.v2.source_bounded_joint_frontier import _refinement_build_identity

    for class_key in ("mage", "druid"):
        source_ir = build_game_ir_slice(class_key=class_key, level=30)
        seed = source_cold_start_stage(
            class_key=class_key, level=30, source_ir=source_ir, gear_role=class_key)
        candidate = prepare_candidate(
            class_key=class_key, level=30, stage=seed, source_ir=source_ir,
            allow_partial_gear_stats=True)
        row = {
            "allocation": dict(candidate.allocation),
            "gear_move": "incumbent",
            "policy_signature": policy_identity(candidate.policy),
            "recovery": "always",
            "opening_action_ids": list(candidate.opening),
            "equipped_gear": candidate.source_stage["gear_policy_result"]["winner"]["gear"],
        }
        original = _refinement_build_identity(row, candidate)
        alias = {**row, "gear_move": "source_stat_package:spell_power"}
        assert _refinement_build_identity(alias, candidate) == original
        # The original key included gear_move even with identical source gear.
        assert alias["gear_move"] != row["gear_move"]
        assert _refinement_build_identity(
            {**alias, "recovery": "never"}, candidate) != original
        assert _refinement_build_identity(
            {**alias, "policy_signature": "different_source_apl"}, candidate) != original
        assert _refinement_build_identity(
            {**alias, "opening_action_ids": ["distinct_source_opening"]}, candidate) != original

def test_nested_paid_candidate_expiry_does_not_arm_stray_alarm(monkeypatch):
    """An exhausted enclosing timer must fail inside the guarded coordinate.

    RED: restoring a 1us SIGALRM after the inner screen exits can interrupt
    the *next* frontier coordinate outside its exception handler.
    """
    import signal
    import pytest
    import src.v2.source_bounded_joint_frontier as frontier

    state = {"handler": signal.SIG_DFL, "timer": (0.0, 0.0)}
    monkeypatch.setattr(frontier.signal, "getsignal", lambda _: state["handler"])
    def set_handler(_sig, handler):
        previous = state["handler"]
        state["handler"] = handler
        return previous
    monkeypatch.setattr(frontier.signal, "signal", set_handler)
    monkeypatch.setattr(frontier.signal, "getitimer", lambda _: state["timer"])
    def set_timer(_kind, seconds, interval=0.0):
        previous = state["timer"]
        state["timer"] = (seconds, interval)
        return previous
    monkeypatch.setattr(frontier.signal, "setitimer", set_timer)
    ticks = iter((0.0, 0.0, 0.02))
    monkeypatch.setattr(frontier, "monotonic", lambda: next(ticks))

    with pytest.raises(frontier._CandidateWallBudgetExpired):
        with frontier._quick_candidate_wall_budget(0.01):
            with frontier._quick_candidate_wall_budget(0.03):
                pass
    assert state["timer"] == (0, 0)
    assert state["handler"] == signal.SIG_DFL


def test_work2_selected_paid_parent_lineage_keeps_real_refinement_ancestry():
    # P6's 300s round-3 candidate may descend from a paid round-2
    # transfer. The source search must retain that actual parent relationship
    # even though the public JSON omits full unselected gear/APL rows.
    from src.v2.source_bounded_joint_frontier import _paid_refinement_lineages
    paid=[
        dict(allocation={"root": 5}, gear_move="incumbent",
             policy_signature="p0", screen_s_per_mob=18.3),
        dict(allocation={"other": 5}, gear_move="incumbent",
             policy_signature="p0", screen_s_per_mob=18.2),
        dict(allocation={"reflection": 3}, gear_move="talent_refined:2",
             policy_signature="p0", screen_s_per_mob=17.824687,
             refinement_round=2, refinement_parent_paid_index=0,
             talent_neighbor_operation="macro_transfer:3"),
        dict(allocation={"reflection": 3, "other": 2},
             gear_move="talent_refined:3", policy_signature="p0",
             screen_s_per_mob=17.825495, refinement_round=3,
             refinement_parent_paid_index=2,
             talent_neighbor_operation="point_transfer"),
    ]
    result=_paid_refinement_lineages(paid, [
        {"paid_candidate_index":3},
        {"paid_candidate_index":1},
    ])
    assert result[0]["shortlist_paid_candidate_index"]==3
    path=result[0]["paid_parent_path"]
    assert [r["paid_candidate_index"] for r in path]==[0,2,3]
    assert [r["refinement_round"] for r in path]==[0,2,3]
    assert [r["talent_neighbor_operation"] for r in path]==[
        None, "macro_transfer:3", "point_transfer"]
    assert path[-1]["screen_s_per_mob"]==17.825495
    assert result[1]["paid_parent_path"][0]["paid_candidate_index"]==1
    assert len(result[1]["paid_parent_path"])==1


def test_work2_paid_parent_lineage_rejects_invalid_or_cyclic_ancestry():
    from src.v2.source_bounded_joint_frontier import _paid_refinement_lineages
    paid=[dict(refinement_parent_paid_index=1),
          dict(refinement_parent_paid_index=0)]
    with pytest.raises(ValueError,match="PAID_REFINEMENT_PARENT_CHAIN_INVALID"):
        _paid_refinement_lineages(paid,[{"paid_candidate_index":1}])
    with pytest.raises(ValueError,match="PAID_REFINEMENT_PARENT_CHAIN_INVALID"):
        _paid_refinement_lineages(paid,[{"paid_candidate_index":7}])



def test_p3_druid_l40_unrestricted_spirit_witness_runs_through_live_cli():
    # A prior production run exhausted its 44-call base budget after proving
    # Intellect, MP5 and Spell Power; Spirit was never attempted. The separate
    # bounded witness budget must now reach and prove Spirit through the same
    # public production CLI, with no M1 write.
    from tools.wf_gate import _run_live_gate, ROOT

    report = _run_live_gate(ROOT, "druid", 40, "unrestricted", "P3", "")
    assert report["status"] == "PASS", report
    assert report["pass_count"] == report["reachability_count"] == 149, report
    assert report["real_source_search_attempts"] <= 44, report
    assert report["behavior_probes_executed"] <= 60, report
    assert report["real_measured_stat_weights"]["spirit"] > 0, report
    assert any(w["stat"] == "spirit"
               and w["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS"
               and w["weight_s_saved_per_mob_per_unit"] > 0
               for w in report["source_policy_stat_witnesses"]), report
