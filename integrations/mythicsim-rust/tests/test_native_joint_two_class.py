"""Production wrapper contract for balanced native JOINT receipts."""
from __future__ import annotations

import copy
import json
import random
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import p73_talent_search_v2 as p73
import native_executor as native_exec
import native_l60_matrix as l60_matrix
import native_joint_two_class as joint
from apl_mutation import _condition_spell_identity_keys, _corpus, _new_cast, _source_action_templates, mutate_apl
from native_joint_two_class import (
    _ensure_native_damage_action, _native_positive_source_casts,
    _write_native_failure, fingerprint, native_payload, native_score_request,
)
from native_matrix import NativeCandidateRefusal, next_budget, search_native


def request():
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassDruid",
            "equipment": {"items": [{"id": 1001}, {"id": 1002}]},
            "talentsString": "source-build",
            "rotation": {"priorityList": []},
        }]}]},
        "encounter": {"duration": 180, "targets": 1},
        "simOptions": {"iterations": 3, "randomSeed": "47"},
    }


class SourceCastPayloadPreservation(unittest.TestCase):
    def test_cold_and_insert_casts_keep_source_healing_targets(self):
        # Candidate generation must not discard opaque native cast fields.
        # MythicSim, not this test, decides whether each cast is legal.
        source = [
            {"action": {"castSpell": {
                "spellId": {"spellId": 5185},
                "target": {"type": "Self"},
            }}},
            {"action": {"castSpell": {
                "spellId": {"spellId": 774},
                "target": {"type": "CurrentTarget"},
            }}},
        ]
        snapshot = copy.deepcopy(source)
        source_casts = {
            json.dumps(entry["action"]["castSpell"], sort_keys=True)
            for entry in source
        }

        cold = mutate_apl(None, source, random.Random(7), cold=True)
        self.assertTrue(cold)
        self.assertTrue(all(
            json.dumps(entry["action"]["castSpell"], sort_keys=True)
            in source_casts for entry in cold
        ))

        class InsertOnlyRng:
            def choices(self, _modes, weights=None):
                return ["insert_cast"]

            def choice(self, values):
                return values[0]

            def randrange(self, _stop):
                return 0

            def random(self):
                return 0.0

        mutated = mutate_apl(source, source, InsertOnlyRng())
        self.assertEqual(3, len(mutated))
        self.assertTrue(all(
            json.dumps(entry["action"]["castSpell"], sort_keys=True)
            in source_casts for entry in mutated
        ))
        self.assertEqual(snapshot, source)


class NativeJointScoringContracts(unittest.TestCase):
    def test_native_request_records_explicit_balanced_mode_and_raw_receipt(self):
        calls = []
        source = request()
        source["raid"]["parties"][0]["players"][0]["talentsString"] = (
            "native-proposal-without-a-python-point-budget"
        )
        seen_talent_payloads = []
        raw = {"status": "VALID", "result": {"raidMetrics": {"dps": {"avg": 123.5}}}}

        def fake_run(binary, candidate, iterations, seed, rng_mode, deadline, objective="DPS"):
            calls.append((binary, iterations, seed, rng_mode, deadline))
            seen_talent_payloads.append(
                candidate["raid"]["parties"][0]["players"][0]["talentsString"]
            )
            return (123.5, raw, 0.0123,
                    fingerprint(native_payload(candidate, iterations, seed)))

        record, actual_raw = native_score_request(
            Path("forever-engine"), source, 40, 731, "balanced",
            time.monotonic() + 5.0, runner=fake_run,
        )
        self.assertEqual(1, len(calls))
        self.assertEqual(
            ["native-proposal-without-a-python-point-budget"],
            seen_talent_payloads,
        )
        self.assertEqual("balanced", calls[0][3])
        self.assertEqual(40, calls[0][1])
        self.assertEqual(731, calls[0][2])
        self.assertEqual(123.5, record["score"])
        self.assertEqual("VALID", record["native_status"])
        self.assertEqual("balanced", record["rng_mode"])
        self.assertEqual(fingerprint(native_payload(source, 40, 731)),
                         record["effective_request_sha256"])
        self.assertEqual(fingerprint(raw), record["raw_response_sha256"])
        self.assertIs(raw, actual_raw)


    def test_native_objective_is_passed_to_the_executor_and_recorded(self):
        source = request()
        raw = {"status": "VALID", "result": {"raidMetrics": {
            "parties": [{"players": [{"hps": {"avg": 17.5}}]}],
        }}}

        def fake_run(binary, candidate, iterations, seed, rng_mode, deadline,
                     objective="DPS"):
            self.assertEqual("HPS", objective)
            return (
                17.5, raw, 0.0123,
                fingerprint(native_payload(candidate, iterations, seed)),
            )

        record, actual_raw = native_score_request(
            Path("forever-engine"), source, 40, 731, "balanced",
            time.monotonic() + 5.0, objective="HPS", runner=fake_run,
        )
        self.assertEqual(17.5, record["score"])
        self.assertEqual("HPS", record["objective"])
        self.assertEqual(
            "result.raidMetrics.parties[0].players[0].hps.avg",
            record["native_metric_path"],
        )
        self.assertIs(raw, actual_raw)

    def test_native_refusal_is_propagated_for_the_exact_talent_candidate(self):
        source = request()
        source["raid"]["parties"][0]["players"][0]["talentsString"] = (
            "native-refusal-proposal"
        )
        effective = native_payload(source, 40, 731)
        raw = {
            "status": "INVALID",
            "error": "MythicSim rejected this talent proposal",
        }
        refusal = NativeCandidateRefusal(
            "INVALID", raw_response=raw,
            reason=raw["error"], returncode=5,
            request_sha256=fingerprint(effective), elapsed_s=0.012,
        )
        seen_talent_payloads = []

        def fake_run(binary, candidate, iterations, seed, rng_mode, deadline, objective="DPS"):
            seen_talent_payloads.append(
                candidate["raid"]["parties"][0]["players"][0]["talentsString"]
            )
            raise refusal

        with self.assertRaises(NativeCandidateRefusal) as raised:
            native_score_request(
                Path("forever-engine"), source, 40, 731, "balanced",
                time.monotonic() + 5.0, runner=fake_run,
            )

        self.assertEqual(["native-refusal-proposal"], seen_talent_payloads)
        self.assertIs(refusal, raised.exception)
        self.assertEqual(raw, raised.exception.raw_response)
        self.assertEqual(fingerprint(effective), raised.exception.request_sha256)


    def test_missing_talent_string_candidate_reaches_native_and_refusal_is_preserved(self):
        source = request()
        source_player = source["raid"]["parties"][0]["players"][0]
        source_player.pop("talentsString")
        effective = native_payload(source, 40, 731)
        raw = {
            "status": "INVALID",
            "error": "MythicSim rejected the request without talentsString",
        }
        refusal = NativeCandidateRefusal(
            "INVALID",
            raw_response=raw,
            reason=raw["error"],
            returncode=5,
            elapsed_s=0.012,
            request_sha256=fingerprint(effective),
        )
        seen_presence = []

        def fake_run(binary, candidate, iterations, seed, rng_mode, deadline, objective="DPS"):
            candidate_player = candidate["raid"]["parties"][0]["players"][0]
            seen_presence.append("talentsString" in candidate_player)
            raise refusal

        with self.assertRaises(NativeCandidateRefusal) as raised:
            native_score_request(
                Path("forever-engine"), source, 40, 731, "balanced",
                time.monotonic() + 5.0, runner=fake_run,
            )

        self.assertEqual([False], seen_presence)
        self.assertIs(refusal, raised.exception)
        self.assertEqual(raw, raised.exception.raw_response)
        self.assertEqual(fingerprint(effective), raised.exception.request_sha256)

    def test_stochastic_mode_is_rejected_before_the_native_runner(self):
        calls = []

        def fake_run(*args):
            calls.append(args)
            raise AssertionError("stochastic must never reach optimizer scorer")

        with self.assertRaisesRegex(
            ValueError, "JOINT_OPTIMIZER_REQUIRES_EXPLICIT_BALANCED_RNG"
        ):
            native_score_request(
                Path("forever-engine"), request(), 40, 731, "stochastic",
                time.monotonic() + 5.0, runner=fake_run,
            )
        self.assertEqual([], calls)


class NativeDamageAPLAnchorContracts(unittest.TestCase):
    @staticmethod
    def source(spell_id, *, conditional=False):
        action = {"castSpell": {"spellId": {"spellId": spell_id}}}
        if conditional:
            action["condition"] = {"cmp": {"lhs": {"currentManaPercent": {}},
                                             "op": "OpLt",
                                             "rhs": {"const": {"val": "10%"}}}}
        return {"action": action}

    @staticmethod
    def native_response(damaging_id):
        return {"result": {"raidMetrics": {"parties": [{"players": [{
            "actions": [
                {"id": {"spellId": 11689}, "targets": [{"casts": 80}]},
                {"id": {"spellId": damaging_id},
                 "targets": [{"casts": 10, "damage": 800.0}]},
            ]
        }]}]}}}

    def test_warlock_life_tap_only_policy_gets_source_native_damage_action(self):
        # The real #41632564319 artifact contains six 40/40 zero-DPS
        # Warlock policies; Life Tap 11689 was an unconditional non-damage cast.
        source = [self.source(11689), self.source(11713, conditional=True)]
        receipt = self.native_response(11713)
        witnesses = _native_positive_source_casts(source, receipt)
        self.assertEqual([{"spellId": 11713}], witnesses)
        candidate = [self.source(11689) for _ in range(20)]
        repaired = _ensure_native_damage_action(
            candidate, witnesses, random.Random(1), source_actions=source
        )
        self.assertEqual(20, len(repaired))
        self.assertEqual(source[1]["action"], repaired[0]["action"])
        self.assertEqual(source[1]["action"]["condition"],
                         repaired[0]["action"]["condition"])
        self.assertEqual(20, len(_ensure_native_damage_action(
            repaired, witnesses, random.Random(1), source_actions=source)))
        self.assertEqual(11689, candidate[0]["action"]["castSpell"]["spellId"]["spellId"])

    def test_rogue_stealth_and_vanish_cannot_be_only_unconditional_casts(self):
        # The real Rogue failed receipt has unconditional Vanish/Stealth/Slice
        # and Dice, but no unconditional spell with positive native damage.
        source = [self.source(1856), self.source(1784),
                  self.source(11281, conditional=True)]
        witnesses = _native_positive_source_casts(source, self.native_response(11281))
        self.assertEqual([{"spellId": 11281}], witnesses)
        candidate = [self.source(1856), self.source(1784)]
        repaired = _ensure_native_damage_action(
            candidate, witnesses, random.Random(2), source_actions=source
        )
        self.assertEqual(source[2]["action"], repaired[0]["action"])

    def test_existing_positive_cast_moves_to_front_without_duplication(self):
        witnesses = [{"spellId": 11713}]
        actions = [self.source(11689), self.source(11713)]
        repaired = _ensure_native_damage_action(
            actions, witnesses, random.Random(3), source_actions=actions
        )
        self.assertEqual([11713, 11689],
                         [a["action"]["castSpell"]["spellId"]["spellId"] for a in repaired])

    def test_full_conditional_apl_reserves_room_for_all_native_damage_witnesses(self):
        # A full conditional prefix previously displaced native-positive casts:
        # with 20 entries only one of two witnesses survived; with 22 entries
        # the result could exceed the native 20-action limit entirely.
        witnesses = [{"spellId": 3001}, {"spellId": 3002}]
        for conditional_count in (20, 22):
            source = [self.source(2000 + i, conditional=True)
                      for i in range(conditional_count)]
            snapshot = copy.deepcopy(source)
            source_actions = source + [self.source(3001), self.source(3002)]
            repaired = _ensure_native_damage_action(
                source, witnesses, random.Random(7), source_actions=source_actions
            )
            self.assertEqual(20, len(repaired))
            self.assertEqual(
                list(range(2000, 2018)) + [3001, 3002],
                [entry["action"]["castSpell"]["spellId"]["spellId"]
                 for entry in repaired],
            )
            self.assertTrue(all(
                "condition" not in entry["action"]
                for entry in repaired[-2:]
            ))
            self.assertEqual(snapshot, source)
            self.assertEqual(repaired, _ensure_native_damage_action(
                repaired, witnesses, random.Random(7), source_actions=source_actions))

    def test_present_empty_condition_is_not_an_unconditional_damage_witness(self):
        witnesses = [{"spellId": 11713}]
        source = [{
            "action": {
                "castSpell": {"spellId": {"spellId": 11713}},
                "condition": {},
            }
        }]
        snapshot = copy.deepcopy(source)

        repaired = _ensure_native_damage_action(
            source, witnesses, random.Random(8), source_actions=source
        )

        self.assertEqual([snapshot[0]], repaired)
        self.assertEqual({}, repaired[0]["action"]["condition"])
        self.assertEqual(snapshot, source)
        self.assertEqual(repaired, _ensure_native_damage_action(
            repaired, witnesses, random.Random(8), source_actions=source))

    def test_real_warlock_zero_dps_alternate_talent_needs_multiple_witnesses(self):
        # Stage-5 #41638113867 exact raw receipt 43a719fd...:
        # 40/40 zero DPS with APL [18932, 11689, 25309].
        # 18932 was native-positive in the baseline, but never cast with the
        # alternate talents; Life Tap 11689 then looped 3280 times.
        witnesses = [{"spellId": spell} for spell in
                     (18932, 18871, 17923, 11713)]
        candidate = [self.source(18932), self.source(11689), self.source(25309)]
        source_actions = candidate + [
            self.source(18871), self.source(17923), self.source(11713)
        ]
        original = json.loads(json.dumps(candidate))
        repaired = _ensure_native_damage_action(
            candidate, witnesses, random.Random(3), source_actions=source_actions)
        ids = [entry["action"]["castSpell"]["spellId"]["spellId"]
               for entry in repaired]
        self.assertEqual([18932, 18871, 17923, 11713, 11689, 25309], ids)
        self.assertEqual(original, candidate)
        self.assertEqual(repaired, _ensure_native_damage_action(
            repaired, witnesses, random.Random(3), source_actions=source_actions))

        full = [self.source(18932)] + [self.source(11689) for _ in range(19)]
        bounded = _ensure_native_damage_action(
            full, witnesses, random.Random(3), source_actions=source_actions)
        bounded_ids = [entry["action"]["castSpell"]["spellId"]["spellId"]
                       for entry in bounded]
        self.assertEqual(20, len(bounded))
        self.assertEqual([18932, 18871, 17923, 11713], bounded_ids[:4])
        self.assertEqual(11689, bounded_ids[4])

    def test_no_paid_native_damage_receipt_does_not_invent_witness(self):
        source = [self.source(11689), self.source(11713, conditional=True)]
        zero = {"result": {"raidMetrics": {"parties": [{"players": [{
            "actions": [{"id": {"spellId": 11713},
                         "targets": [{"casts": 40, "damage": 0.0}]}]
        }]}]}}}
        self.assertEqual([], _native_positive_source_casts(source, zero))
        candidate = [self.source(11689), self.source(11689)]
        self.assertIs(candidate, _ensure_native_damage_action(
            candidate, [], random.Random(4), source_actions=source))


    def test_damage_witness_is_fallback_after_conditions_and_before_utility_casts(self):
        conditional_damage = self.source(11713, conditional=True)
        opaque = {
            "action": {
                "useItem": {"itemId": 12662},
                "condition": {"auraIsActive": {"auraId": {"spellId": 12662}}},
            }
        }
        utility = self.source(11689)
        existing_damage_fallback = self.source(11713)
        actions = [utility, conditional_damage, opaque, existing_damage_fallback]
        snapshot = json.loads(json.dumps(actions))

        repaired = _ensure_native_damage_action(
            actions, [{"spellId": 11713}], random.Random(5),
            source_actions=actions,
        )

        self.assertEqual(snapshot, actions)
        self.assertEqual(4, len(repaired))
        self.assertEqual(11713, repaired[0]["action"]["castSpell"]["spellId"]["spellId"])
        self.assertIn("condition", repaired[0]["action"])
        self.assertIn("useItem", repaired[1]["action"])
        self.assertEqual(11713, repaired[2]["action"]["castSpell"]["spellId"]["spellId"])
        self.assertNotIn("condition", repaired[2]["action"])
        self.assertEqual(11689, repaired[3]["action"]["castSpell"]["spellId"]["spellId"])


    def test_exact_warlock_lifetap_zero_dps_receipt_is_sanitized_before_fallback(self):
        # Reduced exact reproducer from stage-5 run #41655733807, artifact
        # #13241065075: the failed non-paid request had Life Tap 11689 guarded
        # by dotRemainingTime(25309) <= spellCastTime(25309); its response was
        # hist={"0": 40}, 3,280 Life Tap casts, and zero damage.
        refresh_25309 = {
            "cmp": {
                "lhs": {"dotRemainingTime": {"spellId": {"spellId": 25309}}},
                "op": "OpLe",
                "rhs": {"spellCastTime": {"spellId": {"spellId": 25309}}},
            }
        }
        refresh_11713 = {
            "cmp": {
                "lhs": {"dotRemainingTime": {"spellId": {"spellId": 11713}}},
                "op": "OpLe",
                "rhs": {"spellCastTime": {"spellId": {"spellId": 11713}}},
            }
        }
        source = [
            {"action": {"castSpell": {"spellId": {"spellId": 11689}},
                        "condition": copy.deepcopy(refresh_25309)}},
            {"action": {"castSpell": {"spellId": {"spellId": 25309}},
                        "condition": copy.deepcopy(refresh_25309)}},
            {"action": {"castSpell": {"spellId": {"spellId": 11689}},
                        "condition": copy.deepcopy(refresh_11713)}},
            {"action": {"castSpell": {"spellId": {"spellId": 11713}},
                        "condition": copy.deepcopy(refresh_11713)}},
            self.source(17923),
        ]
        raw_response = {
            "result": {"raidMetrics": {
                "dps": {"hist": {"0": 40}},
                "parties": [{"players": [{"actions": [{
                    "id": {"spellId": 11689},
                    "targets": [{"casts": 3280, "damage": 0.0}],
                }]}]}],
            }}
        }
        self.assertEqual({"0": 40}, raw_response["result"]["raidMetrics"]["dps"]["hist"])
        life_tap_receipt = raw_response["result"]["raidMetrics"]["parties"][0]["players"][0]["actions"][0]
        self.assertEqual(3280, sum(t["casts"] for t in life_tap_receipt["targets"]))
        self.assertEqual(0.0, sum(t["damage"] for t in life_tap_receipt["targets"]))

        source_snapshot = copy.deepcopy(source)

        mutated = mutate_apl(
            copy.deepcopy(source), source, random.Random(5), cold=False
        )
        self.assertEqual(source_snapshot, source, "source APL must remain immutable")
        source_lifetap_actions = {
            json.dumps(entry["action"], sort_keys=True)
            for entry in source
            if entry["action"].get("castSpell", {}).get("spellId", {}).get("spellId") == 11689
        }
        self.assertTrue(all(
            json.dumps(entry["action"], sort_keys=True) in source_lifetap_actions
            for entry in mutated
            if entry["action"].get("castSpell", {}).get("spellId", {}).get("spellId") == 11689
        ))
        repaired = _ensure_native_damage_action(
            mutated, [{"spellId": 17923}], random.Random(5), source_actions=source
        )
        self.assertTrue(any(
            entry["action"].get("castSpell", {}).get("spellId", {}).get("spellId") == 17923
            and "condition" not in entry["action"]
            for entry in repaired
        ))
        self.assertTrue(all(
            "condition" in entry["action"]
            for entry in repaired
            if entry["action"].get("castSpell", {}).get("spellId", {}).get("spellId") == 11689
        ))

    def test_dot_self_refresh_predicate_is_not_grafted_from_dot_to_life_tap(self):
        condition = {
            "cmp": {
                "lhs": {"dotRemainingTime": {"spellId": {"spellId": 25309}}},
                "op": "OpLe",
                "rhs": {"spellCastTime": {"spellId": {"spellId": 25309}}},
            }
        }
        source = [
            self.source(11689),
            {
                "action": {
                    "castSpell": {"spellId": {"spellId": 25309}},
                    "condition": copy.deepcopy(condition),
                }
            },
        ]
        spells, predicates_by_spell, _allowed, compatible, _auras = _corpus(source)
        self.assertIn(condition, compatible)
        source_action_templates = _source_action_templates(source)
        source_action_templates = _source_action_templates(source)

        class TargetRng:
            def __init__(self, target):
                self.target = target

            def choice(self, values):
                if values is spells:
                    return next(item for item in values
                                if item.get("spellId") == self.target)
                return values[0]

            def random(self):
                return 0.0

        life_tap = _new_cast(
            spells, predicates_by_spell, compatible, TargetRng(11689),
            source_action_templates=source_action_templates,
        )
        dot = _new_cast(
            spells, predicates_by_spell, compatible, TargetRng(25309),
            source_action_templates=source_action_templates,
        )
        self.assertNotIn("condition", life_tap["action"])
        self.assertEqual(condition, dot["action"]["condition"])

    def test_cross_spell_source_condition_remains_bound_to_original_cast(self):
        condition = {
            "and": {"vals": [
                {
                    "cmp": {
                        "lhs": {"dotRemainingTime": {"spellId": {"spellId": 24977}}},
                        "op": "OpLt",
                        "rhs": {"spellCastTime": {"spellId": {"spellId": 25298}}},
                    }
                },
                {
                    "cmp": {
                        "lhs": {"dotRemainingTime": {"spellId": {"spellId": 9835}}},
                        "op": "OpLt",
                        "rhs": {"spellCastTime": {"spellId": {"spellId": 25298}}},
                    }
                },
            ]}
        }
        source = [
            self.source(24977),
            self.source(9835),
            {
                "action": {
                    "castSpell": {"spellId": {"spellId": 9912}},
                    "condition": copy.deepcopy(condition),
                }
            },
            self.source(25298),
        ]
        spells, predicates_by_spell, _allowed, compatible, _auras = _corpus(source)
        self.assertIn(condition, compatible)

        class TargetRng:
            def choice(self, values):
                if values is spells:
                    return next(item for item in values
                                if item.get("spellId") == 9912)
                return values[0]

            def random(self):
                return 0.0

        generated = _new_cast(
            spells, predicates_by_spell, compatible, TargetRng(),
            source_action_templates=source_action_templates,
        )
        self.assertEqual(
            9912, generated["action"]["castSpell"]["spellId"]["spellId"]
        )
        self.assertEqual(condition, generated["action"]["condition"])
        for spell_id in (24977, 9835, 25298):
            self.assertNotIn(
                "condition",
                source_action_templates[
                    json.dumps({"spellId": spell_id}, sort_keys=True, separators=(",", ":"))
                ][0],
            )


class NativeObjectiveDonorProbeContracts(unittest.TestCase):
    @staticmethod
    def cast(spell_id):
        return {
            "action": {
                "castSpell": {
                    "spellId": {"spellId": spell_id},
                    "target": {"type": "Self"},
                }
            }
        }

    @staticmethod
    def native_heal_response(spell_id):
        return {
            "result": {
                "raidMetrics": {
                    "parties": [{
                        "players": [{
                            "actions": [{
                                "id": {"spellId": spell_id},
                                "targets": [{"unitIndex": 1, "healing": 125.0}],
                            }]
                        }]
                    }]
                }
            }
        }

    def test_donor_probe_uses_native_hps_receipt_per_talent_build(self):
        baseline = request()
        baseline_player = baseline["raid"]["parties"][0]["players"][0]
        baseline_player["class"] = "ClassDruid"
        baseline_player["talentsString"] = "restoration-build-a"
        baseline_cast = self.cast(5185)
        baseline_player["rotation"]["priorityList"] = [copy.deepcopy(baseline_cast)]

        donor = copy.deepcopy(baseline)
        donor_player = donor["raid"]["parties"][0]["players"][0]
        donor_player["talentsString"] = "restoration-build-b"
        donor_cast = self.cast(774)
        donor_player["rotation"]["priorityList"] = [copy.deepcopy(donor_cast)]
        original = copy.deepcopy(baseline)
        seen = []

        def fake_score_request(
            binary, candidate, iterations, seed, rng_mode, deadline, *, objective
        ):
            candidate_player = candidate["raid"]["parties"][0]["players"][0]
            seen.append(copy.deepcopy(candidate))
            self.assertEqual("HPS", objective)
            self.assertEqual("balanced", rng_mode)
            self.assertEqual("restoration-build-b", candidate_player["talentsString"])
            self.assertEqual(
                baseline["raid"]["parties"][0]["players"][0]["equipment"],
                candidate_player["equipment"],
            )
            self.assertEqual(baseline["encounter"], candidate["encounter"])
            self.assertEqual(baseline["simOptions"], candidate["simOptions"])
            spell_id = candidate_player["rotation"]["priorityList"][0]["action"][
                "castSpell"
            ]["spellId"]["spellId"]
            raw = self.native_heal_response(spell_id)
            effective = native_payload(candidate, iterations, seed)
            return ({
                "score": 42.0,
                "effective_request_sha256": fingerprint(effective),
                "raw_response_sha256": fingerprint(raw),
            }, raw)

        witnesses, receipts, positive_apls = joint._probe_native_objective_donor_witnesses(
            Path("forever-engine"),
            baseline,
            [{"request": donor, "source_path": "fixtures/druid-healer.request.json"}],
            [baseline_cast["action"]["castSpell"]],
            iterations=40,
            seed=731,
            objective="HPS",
            baseline_apl_source_path="profiles/druid/restoration.request.json",
            score_request=fake_score_request,
        )

        self.assertEqual(1, len(seen))
        self.assertEqual(
            [baseline_cast],
            seen[0]["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"],
        )
        self.assertEqual(1, len(receipts))
        self.assertEqual("VALID", receipts[0]["status"])
        self.assertEqual("REFERENCE_APL_CROSS_BUILD", receipts[0]["probe_kind"])
        self.assertEqual("profiles/druid/restoration.request.json", receipts[0]["apl_source_path"])
        self.assertEqual("fixtures/druid-healer.request.json", receipts[0]["source_path"])
        self.assertEqual(42.0, receipts[0]["score"])
        self.assertEqual(
            [baseline_cast["action"]["castSpell"]],
            witnesses["restoration-build-a"],
        )
        self.assertEqual(
            [baseline_cast["action"]["castSpell"]],
            witnesses["restoration-build-b"],
        )
        self.assertEqual(
            {"restoration-build-b": [[baseline_cast]]},
            positive_apls,
        )
        self.assertEqual(original, baseline, "Donor probing mutated the reference request")
        self.assertEqual("restoration-build-b", donor_player["talentsString"])

    def test_donor_apl_remains_fallback_when_reference_apl_has_no_positive_hps(self):
        baseline = request()
        baseline_player = baseline["raid"]["parties"][0]["players"][0]
        baseline_player["class"] = "ClassDruid"
        baseline_player["talentsString"] = "restoration-build-a"
        baseline_cast = self.cast(5185)
        baseline_player["rotation"]["priorityList"] = [copy.deepcopy(baseline_cast)]

        donor = copy.deepcopy(baseline)
        donor_player = donor["raid"]["parties"][0]["players"][0]
        donor_player["talentsString"] = "restoration-build-b"
        donor_cast = self.cast(774)
        donor_player["rotation"]["priorityList"] = [copy.deepcopy(donor_cast)]
        seen = []

        def fake_score_request(
            binary, candidate, iterations, seed, rng_mode, deadline, *, objective
        ):
            candidate_player = candidate["raid"]["parties"][0]["players"][0]
            spell_id = candidate_player["rotation"]["priorityList"][0]["action"][
                "castSpell"
            ]["spellId"]["spellId"]
            seen.append(spell_id)
            raw = (
                {"result": {"raidMetrics": {"parties": [{"players": [{"actions": []}]}]}}}
                if spell_id == 5185 else self.native_heal_response(spell_id)
            )
            effective = native_payload(candidate, iterations, seed)
            return ({
                "score": 42.0,
                "effective_request_sha256": fingerprint(effective),
                "raw_response_sha256": fingerprint(raw),
            }, raw)

        witnesses, receipts, positive_apls = joint._probe_native_objective_donor_witnesses(
            Path("forever-engine"),
            baseline,
            [{"request": donor, "source_path": "fixtures/druid-healer.request.json"}],
            [baseline_cast["action"]["castSpell"]],
            iterations=40,
            seed=731,
            objective="HPS",
            score_request=fake_score_request,
        )

        self.assertEqual([5185, 774], seen)
        self.assertEqual(
            ["REFERENCE_APL_CROSS_BUILD", "SOURCE_DONOR_APL"],
            [receipt["probe_kind"] for receipt in receipts],
        )
        self.assertEqual(
            [donor_cast["action"]["castSpell"]],
            witnesses["restoration-build-b"],
        )
        self.assertEqual(
            {"restoration-build-b": [[donor_cast]]},
            positive_apls,
        )


    def test_hps_fallback_budget_covers_twelve_cross_build_misses(self):
        baseline = request()
        baseline_player = baseline["raid"]["parties"][0]["players"][0]
        baseline_player["class"] = "ClassDruid"
        baseline_player["talentsString"] = "restoration-build-a"
        baseline_cast = self.cast(5185)
        baseline_player["rotation"]["priorityList"] = [copy.deepcopy(baseline_cast)]

        donors = []
        expected_casts = {}
        for index in range(12):
            talent = f"restoration-build-{index + 1:02d}"
            donor = copy.deepcopy(baseline)
            donor_player = donor["raid"]["parties"][0]["players"][0]
            donor_player["talentsString"] = talent
            donor_cast = self.cast(6000 + index)
            donor_player["rotation"]["priorityList"] = [copy.deepcopy(donor_cast)]
            expected_casts[talent] = donor_cast
            donors.append({
                "request": donor,
                "source_path": f"fixtures/druid-healer-{index + 1:02d}.request.json",
            })

        seen = []

        def fake_score_request(
            binary, candidate, iterations, seed, rng_mode, deadline, *, objective
        ):
            candidate_player = candidate["raid"]["parties"][0]["players"][0]
            talent = candidate_player["talentsString"]
            spell_id = candidate_player["rotation"]["priorityList"][0]["action"][
                "castSpell"
            ]["spellId"]["spellId"]
            seen.append((talent, spell_id))
            raw = (
                {"result": {"raidMetrics": {"parties": [{"players": [{"actions": []}]}]}}}
                if spell_id == 5185 else self.native_heal_response(spell_id)
            )
            effective = native_payload(candidate, iterations, seed)
            return ({
                "score": 42.0,
                "effective_request_sha256": fingerprint(effective),
                "raw_response_sha256": fingerprint(raw),
            }, raw)

        witnesses, receipts, positive_apls = joint._probe_native_objective_donor_witnesses(
            Path("forever-engine"),
            baseline,
            donors,
            [baseline_cast["action"]["castSpell"]],
            iterations=40,
            seed=731,
            objective="HPS",
            score_request=fake_score_request,
        )

        self.assertEqual(24, len(seen))
        self.assertEqual(24, len(receipts))
        self.assertEqual(
            12,
            sum(receipt["probe_kind"] == "REFERENCE_APL_CROSS_BUILD" for receipt in receipts),
        )
        self.assertEqual(
            12,
            sum(receipt["probe_kind"] == "SOURCE_DONOR_APL" for receipt in receipts),
        )
        self.assertEqual(12, len(positive_apls))
        for talent, donor_cast in expected_casts.items():
            talent_receipts = [
                receipt for receipt in receipts
                if receipt["talentsString"] == talent
            ]
            self.assertEqual(
                ["REFERENCE_APL_CROSS_BUILD", "SOURCE_DONOR_APL"],
                [receipt["probe_kind"] for receipt in talent_receipts],
            )
            self.assertEqual([[donor_cast]], positive_apls[talent])
            self.assertTrue(witnesses[talent])


class NativeJointPerBuildObjectiveWitnessContracts(unittest.TestCase):
    @staticmethod
    def cast(spell_id):
        return {
            "action": {
                "castSpell": {
                    "spellId": {"spellId": spell_id},
                    "target": {"type": "Self"},
                }
            }
        }

    def test_hps_candidates_keep_their_own_native_positive_source_cast(self):
        baseline = request()
        baseline_player = baseline["raid"]["parties"][0]["players"][0]
        baseline_player["class"] = "ClassDruid"
        baseline_player["talentsString"] = "restoration-build-a"
        baseline_cast = self.cast(5185)
        donor_cast = self.cast(774)
        baseline_player["rotation"]["priorityList"] = [copy.deepcopy(baseline_cast)]
        donor = copy.deepcopy(baseline)
        donor_player = donor["raid"]["parties"][0]["players"][0]
        donor_player["talentsString"] = "restoration-build-b"
        donor_player["rotation"]["priorityList"] = [copy.deepcopy(donor_cast)]

        class FakeGear:
            def __init__(self, class_key, reference, source_requests):
                self.reference = reference
                self.mutable_indices = [0]

            def validate(self, request_value):
                return None

            def mutate_one(self, rng):
                return copy.deepcopy(self.reference), {}

            def mutate_from(self, request_value, rng):
                return copy.deepcopy(request_value), {}

        witness_map = {
            "restoration-build-a": [baseline_cast["action"]["castSpell"]],
            "restoration-build-b": [donor_cast["action"]["castSpell"]],
        }
        with patch.object(joint, "NativeGearAdapter", FakeGear):
            adapter, scope = joint.source_bounded_adapter(
                "druid",
                baseline,
                [baseline, donor],
                native_objective_witnesses=[baseline_cast["action"]["castSpell"]],
                native_objective_witnesses_by_talentsString=witness_map,
                objective="HPS",
            )

        candidate = copy.deepcopy(baseline)
        candidate_player = candidate["raid"]["parties"][0]["players"][0]
        candidate_player["talentsString"] = "restoration-build-b"
        self.assertFalse(adapter.legal(candidate))
        self.assertEqual(
            "SELECTED_TALENT_SOURCE_APL_WITH_PER_BUILD_NATIVE_POSITIVE_OBJECTIVE_WITNESS",
            scope["apl_candidate_source"],
        )
        self.assertEqual([], scope[
            "native_positive_objective_witnesses_common_to_selected_talent_builds"
        ])
        self.assertEqual(
            [donor_cast["action"]["castSpell"]],
            scope["native_positive_objective_witnesses_by_talentsString"][
                "restoration-build-b"
            ],
        )

        with patch.object(joint, "mutate_apl", return_value=[]):
            generated = adapter.adapters["apl"].cold(random.Random(23), candidate)
        self.assertEqual(
            [{"action": {"castSpell": donor_cast["action"]["castSpell"]}}],
            generated,
        )
        candidate_player["rotation"]["priorityList"] = generated
        self.assertTrue(adapter.legal(candidate))

        candidate_player["rotation"]["priorityList"] = [
            copy.deepcopy(baseline_cast)
        ]
        self.assertFalse(adapter.legal(candidate))


    def test_native_verified_cross_build_apl_enters_selected_talent_domain(self):
        baseline = request()
        baseline_player = baseline["raid"]["parties"][0]["players"][0]
        baseline_player["class"] = "ClassDruid"
        baseline_player["talentsString"] = "restoration-build-a"
        baseline_cast = self.cast(5185)
        baseline_player["rotation"]["priorityList"] = [copy.deepcopy(baseline_cast)]

        donor = copy.deepcopy(baseline)
        donor_player = donor["raid"]["parties"][0]["players"][0]
        donor_player["talentsString"] = "restoration-build-b"
        donor_cast = self.cast(774)
        donor_player["rotation"]["priorityList"] = [copy.deepcopy(donor_cast)]

        class FakeGear:
            def __init__(self, class_key, reference, source_requests):
                self.reference = reference
                self.mutable_indices = [0]

            def validate(self, request_value):
                return None

            def mutate_one(self, rng):
                return copy.deepcopy(self.reference), {}

            def mutate_from(self, request_value, rng):
                return copy.deepcopy(request_value), {}

        witness = baseline_cast["action"]["castSpell"]
        with patch.object(joint, "NativeGearAdapter", FakeGear):
            adapter, scope = joint.source_bounded_adapter(
                "druid",
                baseline,
                [baseline, donor],
                native_objective_witnesses=[witness],
                native_objective_witnesses_by_talentsString={
                    "restoration-build-a": [witness],
                    "restoration-build-b": [witness],
                },
                native_objective_source_apls_by_talentsString={
                    "restoration-build-b": [[baseline_cast]],
                },
                objective="HPS",
            )

        candidate = copy.deepcopy(donor)
        self.assertFalse(adapter.legal(candidate))
        with patch.object(joint, "mutate_apl", return_value=[]):
            generated = adapter.adapters["apl"].cold(random.Random(23), candidate)
        self.assertEqual([baseline_cast], generated)
        candidate["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"] = generated
        self.assertTrue(adapter.legal(candidate))
        self.assertEqual(
            2,
            scope["source_apl_action_counts_by_talentsString"]["restoration-build-b"],
        )
        self.assertEqual(
            [fingerprint([baseline_cast])],
            scope["native_positive_objective_source_apl_sha256_by_talentsString"][
                "restoration-build-b"
            ],
        )


class NativeJointTalentCastCompatibilityContracts(unittest.TestCase):
    @staticmethod
    def cast(spell_id):
        return {"action": {"castSpell": {"spellId": {"spellId": spell_id}}}}

    @classmethod
    def source_request(cls, talents, spell_ids):
        value = request()
        source_player = value["raid"]["parties"][0]["players"][0]
        source_player["class"] = "ClassWarlock"
        source_player["talentsString"] = talents
        source_player["rotation"]["priorityList"] = [
            cls.cast(spell_id) for spell_id in spell_ids
        ]
        return value

    def test_healing_witness_is_shared_by_source_builds_with_target_intact(self):
        baseline = request()
        baseline_player = baseline["raid"]["parties"][0]["players"][0]
        baseline_player["class"] = "ClassDruid"
        baseline_player["talentsString"] = "restoration-build-a"
        heal_cast = {
            "spellId": {"spellId": 5185},
            "target": {"type": "Self"},
        }
        donor_only_heal = {
            "spellId": {"spellId": 774},
            "target": {"type": "Self"},
        }
        baseline_player["rotation"]["priorityList"] = [
            {"action": {"castSpell": copy.deepcopy(heal_cast)}}
        ]
        donor = copy.deepcopy(baseline)
        donor_player = donor["raid"]["parties"][0]["players"][0]
        donor_player["talentsString"] = "restoration-build-b"
        donor_player["rotation"]["priorityList"].append(
            {"action": {"castSpell": copy.deepcopy(donor_only_heal)}}
        )

        class FakeGear:
            def __init__(self, class_key, reference, source_requests):
                self.reference = reference
                self.mutable_indices = [0]

            def validate(self, request_value):
                return None

            def mutate_one(self, rng):
                return copy.deepcopy(self.reference), {}

            def mutate_from(self, request_value, rng):
                return copy.deepcopy(request_value), {}

        with patch.object(joint, "NativeGearAdapter", FakeGear):
            adapter, scope = joint.source_bounded_adapter(
                "druid", baseline, [baseline, donor],
                native_objective_witnesses=[heal_cast], objective="HPS",
            )

        candidate = copy.deepcopy(baseline)
        candidate_player = candidate["raid"]["parties"][0]["players"][0]
        candidate_player["talentsString"] = "restoration-build-b"
        self.assertTrue(adapter.legal(candidate))
        self.assertEqual("HPS", scope["objective"])
        self.assertEqual(
            "result.raidMetrics.parties[0].players[0].hps.avg",
            scope["native_metric_path"],
        )
        self.assertEqual(
            [heal_cast],
            scope["native_positive_objective_witnesses_common_to_selected_talent_builds"],
        )

        captured = {}

        def fake_mutate(_current, source_actions, _rng, cold=False):
            captured["source_actions"] = copy.deepcopy(source_actions)
            self.assertTrue(cold)
            return [
                {"action": {"castSpell": copy.deepcopy(donor_only_heal)}},
                {"action": {"castSpell": copy.deepcopy(heal_cast)}},
            ]

        with patch.object(joint, "mutate_apl", side_effect=fake_mutate):
            generated = adapter.adapters["apl"].cold(random.Random(23), candidate)

        source_casts = {
            json.dumps(entry["action"]["castSpell"], sort_keys=True, separators=(",", ":"))
            for entry in captured["source_actions"]
            if isinstance(entry.get("action"), dict)
            and isinstance(entry["action"].get("castSpell"), dict)
        }
        self.assertIn(
            json.dumps(donor_only_heal, sort_keys=True, separators=(",", ":")),
            source_casts,
        )
        self.assertEqual(
            [
                {"action": {"castSpell": heal_cast}},
                {"action": {"castSpell": donor_only_heal}},
            ],
            generated,
        )
        self.assertEqual(
            donor_only_heal["target"],
            generated[1]["action"]["castSpell"]["target"],
        )
        candidate_player["rotation"]["priorityList"] = generated
        self.assertTrue(adapter.legal(candidate))
        candidate_player["talentsString"] = "restoration-build-a"
        self.assertFalse(adapter.legal(candidate))
        self.assertEqual(
            2,
            scope["source_apl_action_counts_by_talentsString"]["restoration-build-b"],
        )

    def test_candidate_casts_and_damage_witness_are_bound_to_talent_string(self):
        baseline = self.source_request(
            "baseline-build", [18932, 11713, 17923, 25309]
        )
        donor_a_talents = "source-candidate-a"
        donor_b_talents = "source-candidate-b"
        donor_c_talents = "source-candidate-c"
        donor_a = self.source_request(donor_a_talents, [11713, 17923])
        donor_b = self.source_request(donor_b_talents, [11713, 17923, 25309])
        donor_c = self.source_request(donor_c_talents, [18932, 25309])

        def fixture(name, request_value, sha_char):
            return {
                "class_name": "ClassWarlock",
                "request": request_value,
                "source_path": "test/" + name,
                "source_sha256": sha_char * 64,
                "item_count": 2,
            }

        class FakeGear:
            def __init__(self, class_key, reference, source_requests):
                self.reference = reference
                self.mutable_indices = [0]

            def validate(self, request_value):
                return None

            def mutate_one(self, rng):
                return copy.deepcopy(self.reference), {}

            def mutate_from(self, request_value, rng):
                return copy.deepcopy(request_value), {}

        with patch.object(joint, "NativeGearAdapter", FakeGear):
            adapter, scope = joint.source_bounded_adapter(
                "warlock",
                baseline,
                [baseline],
                donor_fixtures=[
                    fixture("donor-a", donor_a, "a"),
                    fixture("donor-b", donor_b, "b"),
                    fixture("donor-c", donor_c, "c"),
                ],
                native_damage_witnesses=[
                    {"spellId": 18932},
                    {"spellId": 11713},
                ],
            )

            with self.assertRaisesRegex(ValueError, "BLOCKED_NATIVE_DAMAGE_WITNESS"):
                joint.source_bounded_adapter(
                    "warlock",
                    baseline,
                    [baseline],
                    donor_fixtures=[
                        fixture("donor-a", donor_a, "a"),
                        fixture("donor-b", donor_b, "b"),
                        fixture("donor-c", donor_c, "c"),
                    ],
                    native_damage_witnesses=[],
                )

        self.assertEqual(
            sorted(["baseline-build", donor_a_talents, donor_b_talents]),
            scope["talent_builds"],
        )
        self.assertEqual(
            [donor_c_talents],
            scope["talent_builds_excluded_for_native_damage_witness"],
        )
        self.assertEqual(
            [{"spellId": 11713}],
            scope["native_positive_damage_witnesses_common_to_selected_talent_builds"],
        )
        donor_a_casts = {
            json.dumps(value, sort_keys=True, separators=(",", ":"))
            for value in scope["source_casts_by_talentsString"][donor_a_talents]
        }
        self.assertEqual(
            {
                json.dumps({"spellId": {"spellId": 11713}}, sort_keys=True, separators=(",", ":")),
                json.dumps({"spellId": {"spellId": 17923}}, sort_keys=True, separators=(",", ":")),
            },
            donor_a_casts,
        )

        candidate = copy.deepcopy(baseline)
        candidate_player = candidate["raid"]["parties"][0]["players"][0]
        candidate_player["talentsString"] = donor_a_talents
        candidate_player["rotation"]["priorityList"] = [
            self.cast(18932), self.cast(11713)
        ]
        self.assertFalse(adapter.legal(candidate), "18932 is not in this talent build's source APL")

        candidate_player["rotation"]["priorityList"] = [
            self.cast(11713), self.cast(17923)
        ]
        self.assertTrue(adapter.legal(candidate), "the common source-positive witness is legal")

        candidate_player["rotation"]["priorityList"] = [self.cast(17923)]
        self.assertFalse(adapter.legal(candidate), "a non-witness-only APL is not promotable")

        candidate_player["talentsString"] = donor_b_talents
        candidate_player["rotation"]["priorityList"] = [
            self.cast(11713), self.cast(25309)
        ]
        self.assertTrue(adapter.legal(candidate), "per-talent source casts are checked, not globally guessed")

        candidate_player["talentsString"] = donor_c_talents
        candidate_player["rotation"]["priorityList"] = [
            self.cast(18932), self.cast(25309)
        ]
        self.assertFalse(adapter.legal(candidate), "a build without a common native witness is excluded")

        cold_context = copy.deepcopy(baseline)
        cold_context["raid"]["parties"][0]["players"][0]["talentsString"] = donor_a_talents
        generated = adapter.adapters["apl"].cold(random.Random(23), cold_context)
        donor_a_casts = {
            json.dumps(value, sort_keys=True, separators=(",", ":"))
            for value in scope["source_casts_by_talentsString"][donor_a_talents]
        }
        generated_casts = {
            json.dumps(entry["action"]["castSpell"], sort_keys=True, separators=(",", ":"))
            for entry in generated
            if isinstance(entry.get("action"), dict)
            and isinstance(entry["action"].get("castSpell"), dict)
        }
        self.assertTrue(generated_casts <= donor_a_casts)
        witness_key = json.dumps(
            {"spellId": {"spellId": 11713}}, sort_keys=True, separators=(",", ":")
        )
        self.assertTrue(any(
            json.dumps(entry["action"]["castSpell"], sort_keys=True, separators=(",", ":"))
            == witness_key and not entry["action"].get("condition")
            for entry in generated
            if isinstance(entry.get("action"), dict)
            and isinstance(entry["action"].get("castSpell"), dict)
        ))




    def test_source_observed_donor_only_cast_reaches_native_candidate_domain(self):
        """A donor cast absent from the baseline is for Rust to accept/refuse."""
        baseline = self.source_request("baseline-build", [11713])
        donor_request = self.source_request("donor-build", [11713, 17923])

        class FakeGear:
            def __init__(self, class_key, reference, source_requests):
                self.mutable_indices = [0]

            def validate(self, candidate):
                return None

        with patch.object(joint, "NativeGearAdapter", FakeGear):
            adapter, _scope = joint.source_bounded_adapter(
                "warlock", baseline, [baseline],
                donor_fixtures=[{
                    "class_name": "ClassWarlock",
                    "request": donor_request,
                    "source_path": "test/donor-only-cast",
                    "source_sha256": "d" * 64,
                    "item_count": 2,
                }],
                native_damage_witnesses=[{"spellId": 11713}],
            )

        candidate = copy.deepcopy(baseline)
        p = candidate["raid"]["parties"][0]["players"][0]
        p["talentsString"] = "donor-build"
        p["rotation"]["priorityList"] = [self.cast(11713), self.cast(17923)]
        self.assertTrue(
            adapter.legal(candidate),
            "A baseline-only Python APL cast proof must not veto a donor-observed cast",
        )

        candidate["simOptions"]["iterations"] += 1
        self.assertFalse(adapter.legal(candidate))


class NativeObjectiveAPLAnchorContracts(unittest.TestCase):
    def test_shaman_10463_guard_survives_cold_elite_and_native_hps_witness_anchor(self):
        guard = {
            "not": {
                "auraIsActive": {
                    "auraId": {"spellId": 10463},
                },
            },
        }
        heal_cast = {
            "spellId": {"spellId": 10463},
            "target": {"type": "Self"},
        }
        source_actions = [{
            "action": {
                "castSpell": copy.deepcopy(heal_cast),
                "condition": copy.deepcopy(guard),
            }
        }]
        response = {"result": {"raidMetrics": {"parties": [{"players": [{
            "actions": [{
                "id": {"spellId": 10463},
                "targets": [{"healing": 125.0}],
            }],
        }]}]}}}
        witnesses = _native_positive_source_casts(
            source_actions, response, objective="HPS"
        )
        self.assertEqual([heal_cast], witnesses)

        for seed in range(32):
            cold = mutate_apl(
                None, source_actions, random.Random(seed), cold=True
            )
            elite = mutate_apl(
                cold, source_actions, random.Random(seed + 1000), cold=False
            )
            for proposal in (cold, elite):
                for entry in proposal:
                    action = entry["action"]
                    cast = action.get("castSpell", {})
                    if cast.get("spellId", {}).get("spellId") == 10463:
                        self.assertEqual(guard, action.get("condition"))

                anchored = _ensure_native_damage_action(
                    proposal, witnesses, random.Random(seed), objective="HPS",
                    source_actions=source_actions,
                )
                guarded = [
                    entry["action"] for entry in anchored
                    if entry["action"].get("castSpell", {}).get(
                        "spellId", {}
                    ).get("spellId") == 10463
                ]
                self.assertTrue(guarded)
                self.assertTrue(all(action.get("condition") == guard
                                    for action in guarded))

        # Even a stale/tampered candidate is repaired from the exact source
        # action rather than receiving an unconditional witness cast.
        tampered = [{"action": {"castSpell": copy.deepcopy(heal_cast)}}]
        repaired = _ensure_native_damage_action(
            tampered, witnesses, random.Random(77), objective="HPS",
            source_actions=source_actions,
        )
        self.assertEqual([source_actions[0]], repaired)

    def test_hps_witness_uses_healing_or_shielding_and_preserves_target(self):
        heal_cast = {
            "spellId": {"spellId": 5185},
            "target": {"type": "Self"},
        }
        source = [{"action": {"castSpell": copy.deepcopy(heal_cast)}}]
        response = {"result": {"raidMetrics": {"parties": [{"players": [{
            "actions": [{
                "id": {"spellId": 5185},
                "targets": [{"healing": 0.0, "shielding": 450.0}],
            }],
        }]}]}}}

        witnesses = _native_positive_source_casts(source, response, objective="HPS")
        self.assertEqual([heal_cast], witnesses)
        candidate = [{"action": {"autocastOtherCooldowns": {}}}]
        repaired = _ensure_native_damage_action(
            candidate, witnesses, random.Random(1), objective="HPS",
            source_actions=source,
        )
        self.assertEqual(heal_cast, repaired[1]["action"]["castSpell"])
        self.assertEqual({"type": "Self"}, repaired[1]["action"]["castSpell"]["target"])

    def test_tps_witness_uses_native_threat_and_preserves_source_cast(self):
        threat_cast = {"spellId": {"spellId": 23922}}
        source = [{"action": {"castSpell": copy.deepcopy(threat_cast)}}]
        response = {"result": {"raidMetrics": {"parties": [{"players": [{
            "actions": [{
                "id": {"spellId": 23922},
                "targets": [{"threat": 975.0}],
            }],
        }]}]}}}

        witnesses = _native_positive_source_casts(source, response, objective="TPS")
        self.assertEqual([threat_cast], witnesses)
        repaired = _ensure_native_damage_action(
            [], witnesses, random.Random(2), objective="TPS",
            source_actions=source,
        )
        self.assertEqual(threat_cast, repaired[0]["action"]["castSpell"])

    def test_profile_role_selects_the_matching_native_objective(self):
        self.assertEqual("HPS", joint.objective_for_profile("druid/restoration"))
        self.assertEqual("HPS", joint.objective_for_profile("priest/holy"))
        self.assertEqual("TPS", joint.objective_for_profile("warrior/protection"))
        self.assertEqual("DPS", joint.objective_for_profile("mage/fire"))


class NativeExecutionErrorReporting(unittest.TestCase):
    def test_joint_and_legacy_p73_paths_share_one_executor(self):
        self.assertIs(joint.run, native_exec.run)
        self.assertIs(l60_matrix.run, native_exec.run)
        self.assertIs(p73.run, native_exec.run)
        self.assertIs(p73.NativeExecutionError, native_exec.NativeExecutionError)
        self.assertIs(p73.NativeScoreExtractionError, native_exec.NativeScoreExtractionError)

    def test_native_objective_paths_read_per_player_hps_and_threat(self):
        raw = {"result": {"raidMetrics": {
            "parties": [{"players": [{
                "hps": {
                    "avg": 42.5,
                    "aggregatorData": {"n": 40},
                    "hist": {"42": 40},
                },
                "threat": {
                    "avg": 987.25,
                    "aggregatorData": {"n": 40},
                    "hist": {"987": 40},
                },
            }]}],
        }}}
        self.assertEqual(
            "result.raidMetrics.parties[0].players[0].hps.avg",
            native_exec.objective_metric_path("HPS"),
        )
        self.assertEqual(
            "result.raidMetrics.parties[0].players[0].threat.avg",
            native_exec.objective_metric_path("TPS"),
        )
        self.assertEqual(42.5, native_exec.objective_value(raw, "HPS"))
        self.assertEqual(987.25, native_exec.objective_value(raw, "TPS"))
        self.assertTrue(native_exec._has_complete_distribution(raw, 40, "HPS"))
        self.assertTrue(native_exec._has_complete_distribution(raw, 40, "TPS"))

    def test_complete_hps_distribution_without_mean_is_unscored_not_dps(self):
        raw = {"status": "VALID", "result": {"raidMetrics": {
            "parties": [{"players": [{
                "hps": {"aggregatorData": {"n": 40}, "hist": {"0": 40}},
            }]}],
        }}}

        def write_output(args, **kwargs):
            Path(args[args.index("--outfile") + 1]).write_text(json.dumps(raw))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with patch.object(native_exec.subprocess, "run", side_effect=write_output):
            with self.assertRaises(native_exec.NativeScoreExtractionError) as raised:
                native_exec.run(
                    Path("native"), request(), 40, 731, "balanced",
                    time.monotonic() + 5.0, objective="HPS",
                )
        self.assertEqual("HPS", raised.exception.objective)
        self.assertIn(
            "result.raidMetrics.parties[0].players[0].hps.avg",
            str(raised.exception),
        )
        self.assertEqual(raw, raised.exception.raw_response)

    def test_native_cli_scores_hps_and_tps_from_player_metrics(self):
        cases = (
            ("HPS", "hps", 31.25),
            ("TPS", "threat", 812.5),
        )
        for objective, field, expected in cases:
            with self.subTest(objective=objective):
                raw = {"status": "VALID", "result": {"raidMetrics": {
                    "parties": [{"players": [{
                        field: {
                            "avg": expected,
                            "aggregatorData": {"n": 40},
                            "hist": {str(int(expected)): 40},
                        },
                    }]}],
                }}}

                def write_output(args, **kwargs):
                    Path(args[args.index("--outfile") + 1]).write_text(json.dumps(raw))
                    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

                with patch.object(native_exec.subprocess, "run", side_effect=write_output):
                    score, response, _elapsed, request_sha = native_exec.run(
                        Path("native"), request(), 40, 731, "balanced",
                        time.monotonic() + 5.0, objective=objective,
                    )
                self.assertEqual(expected, score)
                self.assertEqual(raw, response)
                self.assertTrue(request_sha)

    def test_incomplete_dps_distribution_is_execution_error_and_preserves_raw_response(self):
        source = request()
        raw = {"result": {"raidMetrics": {"dps": {"aggregatorData": {"n": 0}}}}}

        def write_output(args, **kwargs):
            output = Path(args[args.index("--outfile") + 1])
            output.write_text(json.dumps(raw))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with patch.object(p73.subprocess, "run", side_effect=write_output):
            with self.assertRaises(native_exec.NativeExecutionError) as raised:
                native_exec.run(
                    Path("native"), source, 40, 731, "balanced",
                    time.monotonic() + 5.0,
                )

        self.assertEqual(raw, raised.exception.raw_response)
        self.assertEqual("ERROR", raised.exception.status)
        self.assertEqual(0, raised.exception.returncode)
        self.assertGreaterEqual(raised.exception.elapsed_s, 0.0)
        self.assertTrue(raised.exception.request_sha256)

    def test_failed_score_extraction_writes_request_and_raw_response_receipts(self):
        effective = native_payload(request(), 40, 731)
        key = fingerprint(effective)
        raw = {"result": {"raidMetrics": {"dps": {
            "aggregatorData": {"n": 40}, "hist": {"0": 40},
        }}}}
        exc = native_exec.NativeScoreExtractionError(
            "missing avg", raw_response=raw, elapsed_s=0.012,
            request_sha256=key,
        )

        with tempfile.TemporaryDirectory() as directory:
            outdir = Path(directory)
            receipt = _write_native_failure(outdir, key, effective, exc)
            request_path = outdir / ("failed_" + key + ".json")
            response_path = outdir / ("failed_" + key + ".response.json")

            self.assertEqual(effective, json.loads(request_path.read_text()))
            self.assertEqual(raw, json.loads(response_path.read_text()))
            self.assertEqual(fingerprint(raw), receipt["raw_response_sha256"])
            self.assertEqual(response_path.name, receipt["response_file"])
            self.assertEqual("UNSCORED", receipt["native_status"])
            self.assertNotIn("score", receipt)

    def test_failed_native_execution_preserves_returncode_stdout_and_stderr(self):
        completed = subprocess.CompletedProcess(
            args=["native"], returncode=7,
            stdout="native stdout detail",
            stderr="native stderr detail",
        )
        with patch.object(p73.subprocess, "run", return_value=completed) as run:
            with self.assertRaises(RuntimeError) as raised:
                native_exec.run(
                    Path("native"), {"simOptions": {}}, 40, 731, "balanced",
                    time.monotonic() + 5.0,
                )
        message = str(raised.exception)
        self.assertIn("returncode=7", message)
        self.assertIn("output_exists=False", message)
        self.assertIn("native stdout detail", message)
        self.assertIn("native stderr detail", message)
        self.assertIs(run.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertIs(run.call_args.kwargs["stderr"], subprocess.PIPE)



class NativeCliOutcomeClassificationContracts(unittest.TestCase):
    def test_successful_native_report_is_valid(self):
        source = request()
        raw = {"status": "VALID", "result": {"raidMetrics": {"dps": {"avg": 123.0}}}}

        def write_output(args, **kwargs):
            Path(args[args.index("--outfile") + 1]).write_text(json.dumps(raw))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with patch.object(p73.subprocess, "run", side_effect=write_output):
            score, response, _elapsed, request_sha = native_exec.run(
                Path("native"), source, 40, 731, "balanced",
                time.monotonic() + 5.0,
            )
        self.assertEqual(123.0, score)
        self.assertEqual(raw, response)
        self.assertTrue(request_sha)

    def test_unknown_explicit_native_status_fails_closed(self):
        source = request()
        raw = {
            "status": "MAYBE_VALID",
            "result": {"raidMetrics": {"dps": {"avg": 999.0}}},
        }

        def write_output(args, **kwargs):
            Path(args[args.index("--outfile") + 1]).write_text(json.dumps(raw))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with patch.object(p73.subprocess, "run", side_effect=write_output):
            with self.assertRaises(native_exec.NativeExecutionError) as raised:
                native_exec.run(
                    Path("native"), source, 40, 731, "balanced",
                    time.monotonic() + 5.0,
                )

        self.assertEqual("ERROR", raised.exception.status)
        self.assertEqual(0, raised.exception.returncode)
        self.assertEqual(raw, raised.exception.raw_response)
        self.assertIn("Unknown native status", str(raised.exception))
        self.assertTrue(raised.exception.request_sha256)

    def test_gate_exit_three_is_native_unsupported(self):
        raw = {
            "supported": False,
            "refusals": [{"code": "rotation_unsupported", "reason": "unsupported action"}],
        }
        completed = subprocess.CompletedProcess(
            args=["native"], returncode=3, stdout=json.dumps(raw), stderr="",
        )
        with patch.object(p73.subprocess, "run", return_value=completed):
            with self.assertRaises(NativeCandidateRefusal) as raised:
                native_exec.run(Path("native"), request(), 40, 731, "balanced",
                        time.monotonic() + 5.0)
        self.assertEqual("UNSUPPORTED", raised.exception.status)
        self.assertEqual(raw, raised.exception.raw_response)
        self.assertEqual(3, raised.exception.returncode)

    def test_gate_exit_four_is_native_invalid(self):
        completed = subprocess.CompletedProcess(
            args=["native"], returncode=4, stdout="",
            stderr="invalid prepared request: malformed talent payload",
        )
        with patch.object(p73.subprocess, "run", return_value=completed):
            with self.assertRaises(NativeCandidateRefusal) as raised:
                native_exec.run(Path("native"), request(), 40, 731, "balanced",
                        time.monotonic() + 5.0)
        self.assertEqual("INVALID", raised.exception.status)
        self.assertEqual(4, raised.exception.returncode)
        self.assertIn("malformed talent payload", raised.exception.reason)
        self.assertEqual(completed.stderr,
                         raised.exception.raw_response["stderr"])

    def test_prepare_exit_five_maps_native_refusal_codes(self):
        cases = (
            ("request", "INVALID"),
            ("talents", "INVALID"),
            ("rotation_unsupported", "UNSUPPORTED"),
        )
        for code, expected in cases:
            with self.subTest(code=code):
                raw = {"prepared": False, "refusal": {
                    "code": code, "reason": "native refusal reason",
                }}
                completed = subprocess.CompletedProcess(
                    args=["native"], returncode=5,
                    stdout=json.dumps(raw), stderr="",
                )
                with patch.object(p73.subprocess, "run", return_value=completed):
                    with self.assertRaises(NativeCandidateRefusal) as raised:
                        native_exec.run(Path("native"), request(), 40, 731, "balanced",
                                time.monotonic() + 5.0)
                self.assertEqual(expected, raised.exception.status)
                self.assertEqual(raw, raised.exception.raw_response)
                self.assertEqual(5, raised.exception.returncode)

    def test_prepare_fault_is_execution_error_not_candidate_refusal(self):
        raw = {"prepared": False, "refusal": {
            "code": "prepare_fault", "reason": "native prepare fault",
        }}
        completed = subprocess.CompletedProcess(
            args=["native"], returncode=5, stdout=json.dumps(raw), stderr="",
        )
        with patch.object(p73.subprocess, "run", return_value=completed):
            with self.assertRaises(native_exec.NativeExecutionError) as raised:
                native_exec.run(Path("native"), request(), 40, 731, "balanced",
                        time.monotonic() + 5.0)
        self.assertEqual("ERROR", raised.exception.status)
        self.assertEqual(raw, raised.exception.raw_response)

    def test_exit_seven_remains_execution_error(self):
        completed = subprocess.CompletedProcess(
            args=["native"], returncode=7,
            stdout="native stdout detail", stderr="native stderr detail",
        )
        with patch.object(p73.subprocess, "run", return_value=completed):
            with self.assertRaises(native_exec.NativeExecutionError) as raised:
                native_exec.run(Path("native"), request(), 40, 731, "balanced",
                        time.monotonic() + 5.0)
        self.assertEqual("ERROR", raised.exception.status)
        self.assertEqual(7, raised.exception.returncode)
        self.assertIn("native stderr detail", str(raised.exception))

    def test_native_matrix_counts_refusals_separately_from_execution_errors(self):
        class Clock:
            def __init__(self, step):
                self.value = 0.0
                self.step = step
            def __call__(self):
                value = self.value
                self.value += self.step
                return value

        counter = [0]
        def propose(_rng):
            counter[0] += 1
            return {"candidate": counter[0]}
        def mutate(_elite, _rng):
            counter[0] += 1
            return {"candidate": counter[0]}
        def refuse(_candidate, **_kwargs):
            raise NativeCandidateRefusal(
                "UNSUPPORTED", raw_response={"supported": False},
                reason="native coverage refusal", returncode=3,
            )

        result = search_native(
            profile_id="mage/fire", reference=request(), propose=propose,
            mutate=mutate, legal=lambda _candidate: True, evaluate=refuse,
            seconds=1.0, iterations=1, seed=1, clock=Clock(0.1),
        )
        self.assertEqual("BLOCKED_NATIVE_REFUSALS", result["status"])
        self.assertGreater(result["native_refusals"], 0)
        self.assertEqual(result["native_refusals"], result["native_unsupported"])
        self.assertEqual(0, result["engine_errors"])
        self.assertIsNone(next_budget(5, result))

    def test_native_refusal_does_not_block_promotion_after_paid_native_score(self):
        class Clock:
            def __init__(self, step):
                self.value = 0.0
                self.step = step
            def __call__(self):
                value = self.value
                self.value += self.step
                return value

        counter = [0]
        def propose(_rng):
            counter[0] += 1
            return {"candidate": counter[0]}
        def mutate(_elite, _rng):
            counter[0] += 1
            return {"candidate": counter[0]}
        def evaluate(candidate, **_kwargs):
            if candidate["candidate"] == 1:
                raise NativeCandidateRefusal(
                    "INVALID", raw_response={"status": "INVALID"},
                    reason="native talent refusal", returncode=5,
                )
            return float(candidate["candidate"])

        result = search_native(
            profile_id="mage/fire", reference=request(), propose=propose,
            mutate=mutate, legal=lambda _candidate: True, evaluate=evaluate,
            seconds=0.35, iterations=1, seed=1, clock=Clock(0.05),
        )
        self.assertEqual("RAN", result["status"])
        self.assertEqual(1, result["native_invalid"])
        self.assertGreater(result["paid_candidates"], 0)
        self.assertEqual(0, result["engine_errors"])
        self.assertEqual(30, next_budget(5, result))


class APLPredicateCompatibilityContracts(unittest.TestCase):
    @staticmethod
    def cast(spell_id, condition):
        return {
            "action": {
                "castSpell": {"spellId": {"spellId": spell_id}},
                "condition": condition,
            }
        }

    @staticmethod
    def aura_condition(spell_id):
        return {"auraIsActive": {"auraId": {"spellId": spell_id}}}

    def test_only_compatible_source_cast_predicates_enter_the_shared_pool(self):
        own = self.aura_condition(11689)
        cross = {
            "and": {"vals": [
                self.aura_condition(1311680),
                {"dotIsActive": {"spellId": {"spellId": 11689}}},
            ]}
        }
        unknown = {"dotIsActive": {"spellId": {"spellId": 99999}}}
        item_condition = self.aura_condition(12662)
        opaque_condition = {"dotIsActive": {"spellId": {"spellId": 12662}}}
        source_actions = [
            self.cast(11689, own),
            self.cast(1311680, cross),
            self.cast(25311, unknown),
            {
                "action": {
                    "useItem": {"itemId": 12662},
                    "condition": item_condition,
                }
            },
            {
                "action": {
                    "autocastOtherCooldowns": {},
                    "condition": opaque_condition,
                }
            },
        ]

        spells, same_spell, allowed_casts, compatible, source_aura_keys = _corpus(source_actions)
        spell_11689 = json.dumps({"spellId": 11689}, sort_keys=True, separators=(",", ":"))
        spell_1311680 = json.dumps({"spellId": 1311680}, sort_keys=True, separators=(",", ":"))
        spell_25311 = json.dumps({"spellId": 25311}, sort_keys=True, separators=(",", ":"))

        self.assertEqual(
            {spell_11689, spell_1311680, spell_25311},
            {json.dumps(x, sort_keys=True, separators=(",", ":")) for x in spells},
        )
        self.assertIn(spell_11689, allowed_casts)
        self.assertIn(spell_1311680, allowed_casts)
        self.assertIn(spell_25311, allowed_casts)
        self.assertEqual((own,), same_spell[spell_11689])
        self.assertEqual((cross,), same_spell[spell_1311680])
        self.assertEqual((), same_spell[spell_25311])
        self.assertEqual((own, cross), compatible)
        self.assertNotIn(item_condition, compatible)
        self.assertNotIn(opaque_condition, compatible)
        self.assertNotIn(unknown, compatible)

        source_spell_keys = {spell_11689, spell_1311680, spell_25311}
        self.assertEqual({spell_11689, spell_1311680}, set(source_aura_keys))
        for predicate in compatible:
            spell_refs, aura_refs, valid = _condition_spell_identity_keys(predicate)
            self.assertTrue(valid)
            self.assertTrue(set(spell_refs) <= source_spell_keys)
            self.assertTrue(set(aura_refs) <= source_aura_keys)

    def test_each_cast_uses_only_its_exact_source_action_condition(self):
        own = self.aura_condition(11689)
        cross = self.aura_condition(1311680)
        source_actions = [
            self.cast(11689, own),
            self.cast(1311680, cross),
        ]
        _spells, same_spell, _allowed, compatible, _source_aura_keys = _corpus(source_actions)
        templates = _source_action_templates(source_actions)

        for seed in range(128):
            own_action = _new_cast(
                [{"spellId": 11689}], same_spell, compatible, random.Random(seed),
                source_action_templates=templates,
            )
            cross_action = _new_cast(
                [{"spellId": 1311680}], same_spell, compatible, random.Random(seed),
                source_action_templates=templates,
            )
            self.assertEqual(source_actions[0]["action"], own_action["action"])
            self.assertEqual(source_actions[1]["action"], cross_action["action"])


if __name__ == "__main__":
    unittest.main()
