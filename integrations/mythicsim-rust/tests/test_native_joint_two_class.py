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
import native_joint_two_class as joint
from apl_mutation import _condition_spell_identity_keys, _corpus, _new_cast
from native_joint_two_class import (
    _ensure_native_damage_action, _native_positive_source_casts,
    _write_native_failure, fingerprint, native_payload, native_score_request,
)


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


class NativeJointScoringContracts(unittest.TestCase):
    def test_native_request_records_explicit_balanced_mode_and_raw_receipt(self):
        calls = []
        source = request()
        raw = {"result": {"raidMetrics": {"dps": {"avg": 123.5}}}}

        def fake_run(binary, candidate, iterations, seed, rng_mode, deadline):
            calls.append((binary, iterations, seed, rng_mode, deadline))
            return (123.5, raw, 0.0123,
                    fingerprint(native_payload(candidate, iterations, seed)))

        record, actual_raw = native_score_request(
            Path("forever-engine"), source, 40, 731, "balanced",
            time.monotonic() + 5.0, runner=fake_run,
        )
        self.assertEqual(1, len(calls))
        self.assertEqual("balanced", calls[0][3])
        self.assertEqual(40, calls[0][1])
        self.assertEqual(731, calls[0][2])
        self.assertEqual(123.5, record["score"])
        self.assertEqual("balanced", record["rng_mode"])
        self.assertEqual(fingerprint(native_payload(source, 40, 731)),
                         record["effective_request_sha256"])
        self.assertEqual(fingerprint(raw), record["raw_response_sha256"])
        self.assertIs(raw, actual_raw)

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
        repaired = _ensure_native_damage_action(candidate, witnesses, random.Random(1))
        self.assertEqual(20, len(repaired))
        self.assertEqual({"spellId": 11713},
                         repaired[0]["action"]["castSpell"]["spellId"])
        self.assertNotIn("condition", repaired[0]["action"])
        self.assertEqual(20, len(_ensure_native_damage_action(
            repaired, witnesses, random.Random(1))))
        self.assertEqual(11689, candidate[0]["action"]["castSpell"]["spellId"]["spellId"])

    def test_rogue_stealth_and_vanish_cannot_be_only_unconditional_casts(self):
        # The real Rogue failed receipt has unconditional Vanish/Stealth/Slice
        # and Dice, but no unconditional spell with positive native damage.
        source = [self.source(1856), self.source(1784),
                  self.source(11281, conditional=True)]
        witnesses = _native_positive_source_casts(source, self.native_response(11281))
        self.assertEqual([{"spellId": 11281}], witnesses)
        candidate = [self.source(1856), self.source(1784)]
        repaired = _ensure_native_damage_action(candidate, witnesses, random.Random(2))
        self.assertEqual(11281, repaired[0]["action"]["castSpell"]["spellId"]["spellId"])

    def test_existing_positive_cast_moves_to_front_without_duplication(self):
        witnesses = [{"spellId": 11713}]
        actions = [self.source(11689), self.source(11713)]
        repaired = _ensure_native_damage_action(actions, witnesses, random.Random(3))
        self.assertEqual([11713, 11689],
                         [a["action"]["castSpell"]["spellId"]["spellId"] for a in repaired])

    def test_real_warlock_zero_dps_alternate_talent_needs_multiple_witnesses(self):
        # Stage-5 #41638113867 exact raw receipt 43a719fd...:
        # 40/40 zero DPS with APL [18932, 11689, 25309].
        # 18932 was native-positive in the baseline, but never cast with the
        # alternate talents; Life Tap 11689 then looped 3280 times.
        witnesses = [{"spellId": spell} for spell in
                     (18871, 17923, 11713, 18932)]
        candidate = [self.source(18932), self.source(11689), self.source(25309)]
        original = json.loads(json.dumps(candidate))
        repaired = _ensure_native_damage_action(
            candidate, witnesses, random.Random(3))
        ids = [entry["action"]["castSpell"]["spellId"]["spellId"]
               for entry in repaired]
        self.assertEqual([18932, 18871, 17923, 11713, 11689, 25309], ids)
        self.assertEqual(original, candidate)
        self.assertEqual(repaired, _ensure_native_damage_action(
            repaired, witnesses, random.Random(3)))

        full = [self.source(18932)] + [self.source(11689) for _ in range(19)]
        bounded = _ensure_native_damage_action(
            full, witnesses, random.Random(3))
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
            candidate, [], random.Random(4)))


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
            actions, [{"spellId": 11713}], random.Random(5)
        )

        self.assertEqual(snapshot, actions)
        self.assertEqual(4, len(repaired))
        self.assertEqual(11713, repaired[0]["action"]["castSpell"]["spellId"]["spellId"])
        self.assertIn("condition", repaired[0]["action"])
        self.assertIn("useItem", repaired[1]["action"])
        self.assertEqual(11713, repaired[2]["action"]["castSpell"]["spellId"]["spellId"])
        self.assertNotIn("condition", repaired[2]["action"])
        self.assertEqual(11689, repaired[3]["action"]["castSpell"]["spellId"]["spellId"])


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

    def test_candidate_casts_and_damage_witness_are_bound_to_talent_string(self):
        baseline = self.source_request(
            "baseline-build", [18932, 11713, 17923, 25309]
        )
        donor_a_talents = "333333-333333-333330"
        donor_b_talents = "333333-333330-333333"
        donor_c_talents = "333330-333333-333333"
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
            def __init__(self, class_key, reference, source_requests, items):
                self.reference = reference
                self.mutable_indices = [0]

            def validate(self, request_value):
                return None

            def mutate_one(self, rng):
                return copy.deepcopy(self.reference), {}

            def mutate_from(self, request_value, rng):
                return copy.deepcopy(request_value), {}

        with patch.object(joint, "NativeGearAdapter", FakeGear), patch.object(
            joint, "legal_apl_only_request", return_value=True
        ):
            adapter, scope = joint.source_bounded_adapter(
                "warlock",
                baseline,
                [baseline],
                {},
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
                    {},
                    donor_fixtures=[
                        fixture("donor-a", donor_a, "a"),
                        fixture("donor-b", donor_b, "b"),
                        fixture("donor-c", donor_c, "c"),
                    ],
                    native_damage_witnesses=[],
                )

        self.assertEqual(sorted([donor_a_talents, donor_b_talents]), scope["talent_builds"])
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

        generated = adapter.adapters["apl"].cold(random.Random(23))
        common_casts = {
            json.dumps(value, sort_keys=True, separators=(",", ":"))
            for value in scope["common_source_casts"]
        }
        generated_casts = {
            json.dumps(entry["action"]["castSpell"], sort_keys=True, separators=(",", ":"))
            for entry in generated
            if isinstance(entry.get("action"), dict)
            and isinstance(entry["action"].get("castSpell"), dict)
        }
        self.assertTrue(generated_casts <= common_casts)
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


class NativeExecutionErrorReporting(unittest.TestCase):
    def test_missing_dps_average_preserves_raw_native_response(self):
        source = request()
        raw = {"result": {"raidMetrics": {"dps": {"aggregatorData": {"n": 0}}}}}

        def write_output(args, **kwargs):
            output = Path(args[args.index("--outfile") + 1])
            output.write_text(json.dumps(raw))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with patch.object(p73.subprocess, "run", side_effect=write_output):
            with self.assertRaises(p73.NativeScoreExtractionError) as raised:
                p73.run(
                    Path("native"), source, 40, 731, "balanced",
                    time.monotonic() + 5.0,
                )

        self.assertEqual(raw, raised.exception.raw_response)
        self.assertIn("result.raidMetrics.dps.avg", str(raised.exception))
        self.assertGreaterEqual(raised.exception.elapsed_s, 0.0)
        self.assertTrue(raised.exception.request_sha256)

    def test_failed_score_extraction_writes_request_and_raw_response_receipts(self):
        effective = native_payload(request(), 40, 731)
        key = fingerprint(effective)
        raw = {"result": {"raidMetrics": {"dps": {"aggregatorData": {"n": 0}}}}}
        exc = p73.NativeScoreExtractionError(
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
            self.assertNotIn("score", receipt)

    def test_failed_native_execution_preserves_returncode_stdout_and_stderr(self):
        completed = subprocess.CompletedProcess(
            args=["native"], returncode=7,
            stdout="native stdout detail",
            stderr="native stderr detail",
        )
        with patch.object(p73.subprocess, "run", return_value=completed) as run:
            with self.assertRaises(RuntimeError) as raised:
                p73.run(
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

    def test_same_spell_is_preferred_but_compatible_cross_spell_predicates_remain_eligible(self):
        own = self.aura_condition(11689)
        cross = self.aura_condition(1311680)
        source_actions = [
            self.cast(11689, own),
            self.cast(1311680, cross),
        ]
        _spells, same_spell, _allowed, compatible, _source_aura_keys = _corpus(source_actions)

        same_count = 0
        cross_count = 0
        for seed in range(512):
            generated = _new_cast(
                [{"spellId": 11689}],
                same_spell,
                compatible,
                random.Random(seed),
            )
            condition = generated["action"].get("condition")
            if condition == own:
                same_count += 1
            elif condition == cross:
                cross_count += 1
            elif condition is not None:
                self.fail(f"Generated an unobserved predicate: {condition}")

        self.assertGreater(cross_count, 0, "Compatible cross-spell predicates must remain eligible")
        self.assertGreater(same_count, cross_count, "Same-spell predicates must remain preferred")


if __name__ == "__main__":
    unittest.main()
