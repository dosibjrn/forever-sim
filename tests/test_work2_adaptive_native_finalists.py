"""M0.6 adaptive native-paid decision routing, not simulated Warcraft combat."""
import hashlib
import json

from src.v2.native_range_optimizer import optimize


def paid(level, mobs, talents, elapsed, *, variant="base", policy=None):
    return {
        "status": "MEASURED_NATIVE_FULLY_RECOVERED",
        "candidate_id": variant, "level": level, "mob_count": mobs,
        "targets_killed": mobs, "rng_mode": "balanced", "iterations": 1,
        "native_prepared": True, "native_world_ack": True,
        "native_full_recovery_paid": True, "recover_to_full": True,
        "terminal_hp": 100.0, "terminal_max_hp": 100.0,
        "terminal_mana": 200.0, "terminal_max_mana": 200.0,
        "elapsed_seconds": elapsed, "terminal_recovery_seconds": 1.0,
        "source_request_sha256": hashlib.sha256(
            f"{level}/{talents}/{variant}".encode()).hexdigest(),
        "engine_binary_sha256": "b" * 64,
        "talents": talents, "gear": {"source_item_ids": [variant]},
        "pet": "native", "apl": {"source_actions": [variant]},
        "native_world_policy": policy or {
            "rest_when_health_below": 1.0, "rest_when_mana_below": 1.0,
        },
    }


def test_one_call_spends_remaining_budget_on_close_paid_finalists():
    families = {
        20: (("5-0-0", 5.0), ("0-5-0", 5.1)),
        40: (("55-0-0", 10.0), ("0-55-0", 11.0)),
        60: (("555-0-0", 30.0), ("0-555-0", 31.0)),
    }
    requests = []

    def native(*, level, parent, budget, mob_count, rng_mode, iterations,
               recover_to_full, candidate_hints=None,
               excluded_paid_source_policies=None, **kwargs):
        assert parent is None and rng_mode == "balanced" and iterations == 1
        assert recover_to_full is True and mob_count == 2
        requests.append((level, budget, excluded_paid_source_policies))
        if excluded_paid_source_policies is not None:
            survivor = families[level][0][0]
            challenger = paid(
                level, mob_count, survivor, 1.0, variant="new-paid-challenger")
            key = (
                challenger["source_request_sha256"],
                json.dumps(challenger["native_world_policy"], sort_keys=True),
            )
            assert key not in excluded_paid_source_policies
            return [challenger]
        return [paid(level, mob_count, talents, seconds,
                     variant=f"initial-{n}")
                for n, (talents, seconds) in enumerate(families[level])][:budget]

    report = optimize(20, 60, 20, 2, 12, evaluate=native,
                      mode="compatible", beam_width=2, class_name="warlock")
    assert report["sampled_levels_compatible"] == [20, 40, 60]
    assert report["adaptive_selected_levels"][0] == 20  # closest measured margin
    assert report["adaptive_native_attempts"] >= 1
    assert report["native_candidates_examined"] <= 12
    assert [entry[0] for entry in requests[:3]] == [20, 40, 60]
    assert report["ranked_alternatives"][0]["steps"][0][
        "receipt"]["candidate_id"] == "new-paid-challenger"
    assert report["ranked_alternatives"][0]["sampled_cumulative_seconds"] == 3.0
    assert all(
        step["receipt"]["native_full_recovery_paid"] is True
        for step in report["ranked_alternatives"][0]["steps"]
    )


def test_backseed_keeps_separately_paid_world_policy_for_same_source():
    def native(*, level, budget, mob_count, candidate_hints=None, **kwargs):
        if level == 20:
            samples = [paid(level, mob_count, "5-0-0", 2.0)]
        elif level == 40:
            samples = [
                paid(level, mob_count, "55-0-0", 8.0),
                paid(level, mob_count, "0-55-0", 1.0),
            ]
            if candidate_hints and any(
                    hint["from_level"] > level for hint in candidate_hints):
                # The same native source can have a genuinely different
                # rest-policy receipt and recovered elapsed time.
                samples = [paid(
                    level, mob_count, "55-0-0", 4.0,
                    policy={"rest_when_health_below": 0.3,
                            "rest_when_mana_below": 0.3},
                )]
        else:
            samples = [
                paid(level, mob_count, "555-0-0", 20.0),
                paid(level, mob_count, "0-555-0", 1.0),
            ]
        return samples[:budget]

    report = optimize(20, 60, 20, 2, 24, evaluate=native,
                      mode="compatible", beam_width=2)
    assert report["backward_seeded_native_attempts"] > 0
    same_source = [row for row in report["independent_level_rankings"]["40"]
                   if row["talents"] == "55-0-0"]
    assert len(same_source) == 2
    assert len({row["source_request_sha256"] for row in same_source}) == 1
    assert len({json.dumps(row["native_world_policy"], sort_keys=True)
                for row in same_source}) == 2
    assert report["native_candidates_examined"] <= 24


def test_adaptive_pays_undercompared_talent_level_before_tight_apl_margin():
    """Prefer untested native build axes; do not invent their performance."""
    choices = {
        20: [paid(20, 2, "5-0-0", 5.0, variant="l20-gear1"),
             paid(20, 2, "5-0-0", 9.0, variant="l20-gear2")],
        40: [paid(40, 2, "55-0-0", 5.0, variant="l40-family1"),
             paid(40, 2, "54-0-0", 5.01, variant="l40-family2")],
    }

    def native(*, level, parent, budget, mob_count, rng_mode, iterations,
               recover_to_full, candidate_hints=None,
               excluded_paid_source_policies=None, **kwargs):
        if excluded_paid_source_policies is not None:
            return []  # No fictional paid winner: native offers no more.
        return choices[level][:budget]

    report = optimize(20, 40, 20, 2, 10, evaluate=native,
                      mode="compatible", beam_width=2)
    assert report["sampled_levels_compatible"] == [20, 40]
    assert report["adaptive_selected_levels"] == [20, 40]
    assert report["adaptive_native_attempts"] == 0
    assert report["native_candidates_examined"] == 4
    assert report["status"] == "SAMPLED_COMPATIBLE_PATH_RANKED"
