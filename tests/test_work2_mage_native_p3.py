"""Mage L60 selected-native P3 transport, refusals and equipment regressions."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from tools import wf_gate_p3_live as p3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/mythicsim-rust"))

from native_p3_equipped import compare_equipped_native  # noqa: E402


def _mage_reference():
    # The selected Mage Arcane fixture has 15 equipment entries and no level
    # hint. Only native prepare is authoritative for the actual level.
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassMage", "talentsString": "source-profile",
            "equipment": {"items": [{"id": 100 + index} for index in range(15)]},
            "rotation": {"type": "TypeAPL", "priorityList": []},
        }]}]},
        "encounter": {"duration": 30},
        "simOptions": {"iterations": 5, "randomSeed": "42"},
    }


def _unified_payload(*, item_eligible=False):
    rows = [
        {"item_id": 900, "eligibility": "native_eligible",
         "native": {"item_id": 900, "slot": "weapon", "item_level": 60},
         "unverified": None},
        {"item_id": 901, "eligibility": "native_eligible",
         "native": {"item_id": 901, "slot": "head", "item_level": 50},
         "unverified": None},
        {"item_id": 902, "eligibility": "proficiency_unverified",
         "native": None, "unverified": {"item_type": "ItemTypeHead"}},
    ]
    return {
        "schema_version": 1, "source_revision": "selected-rust-source",
        "class": "mage", "level": 60, "spells": [],
        "talents": {"status": "ok", "trees": [{}, {}, {}]},
        "coverage": {
            "spell_learnability_complete": False,
            "item_eligibility_complete": item_eligible,
            "talent_prerequisites_complete": True,
            "native_item_status": "partial_level_unknown",
        },
        "items": rows,
    }


def test_unified_mage_options_only_forward_confirmed_native_slot(monkeypatch):
    seen = []

    def fake_cli(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(_unified_payload()), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_cli)
    result = p3._query_native_unified_p3_items(ROOT, "selected-engine", "mage", 60)
    assert seen[0][0] == ["selected-engine", "options", "--class", "mage", "--level", "60"]
    assert result["source"] == "selected-rust-source"
    assert result["coverage"]["item_eligibility_complete"] is False
    assert result["unverified_candidate_count"] == 1
    assert [item["item_id"] for item in result["items"]] == [900, 901]
    assert result["unverified_item_ids"] == [902]
    proposals = p3._native_p3_equipped_slot_proposals(result)["slots"]
    assert proposals["weapon"]["selected_ids"] == [900, 902]
    assert proposals["head"]["selected_ids"] == [901, 902]
    assert len(proposals) == 17
    assert proposals["feet"]["selected_ids"] == [902]



def test_unknown_proficiency_native_proposals_are_paid_not_pre_vetoed(monkeypatch):
    """Mage and Paladin unknown slot IDs reach Rust, including its refusals."""
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")

    for cls, spec, checkpoint, actor, objective in (
        ("mage", "arcane", "mage_l60", "ClassMage", "DPS"),
        ("paladin", "holy", "paladin_holy_l60", "ClassPaladin", "HPS"),
    ):
        payload = _unified_payload()
        payload["class"] = cls
        payload["items"] = [{
            "item_id": 902, "eligibility": "proficiency_unverified",
            "native": None, "unverified": {"item_type": "ItemTypeUnknown"},
        }]
        def fake_cli(command, **_kwargs):
            assert command[:6] == [
                "selected-engine", "options", "--class", cls, "--level", "60"]
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        monkeypatch.setattr(subprocess, "run", fake_cli)
        paid_calls = []
        def native_paid(_root, binary, selection, budget, *, checkpoint):
            paid_calls.append((binary, selection, budget, checkpoint))
            return {
                "status": "PAID_NATIVE_REFUSAL", "paid_attempts": 2,
                "objective": objective, "actor_checkpoint_verified": True,
                "native_prepared_actor": {
                    "actor_class": actor, "actor_level": 60,
                    "engine_revision": "selected-rust-source",
                },
                "source_occupied_slots": ["head"],
                "evaluations": [{
                    "status": "VALID", "score": 10.0,
                    "request_sha256": "real-native-baseline",
                }],
                "native_slot_evaluations": [{
                    "swap": {"slot": "head", "to_id": 902},
                    "status": "UNSUPPORTED", "reason": "native gear refusal",
                }],
                "native_slots_valid": 0,
            }

        monkeypatch.setattr(p3, "_paid_native_equipped_probe", native_paid)
        result = p3.run_live(ROOT, cls, 60, spec=spec)
        assert len(paid_calls) == 1
        binary, selection, budget, actual_checkpoint = paid_calls[0]
        assert (binary, budget, actual_checkpoint) == (
            "selected-engine", 44, checkpoint)
        assert selection["slots"]["head"]["selected_ids"] == [902]
        assert result["status"] == "FAIL"
        assert result["real_catalogue_legal_items"] == 0
        assert result["native_unverified_candidate_count"] == 1
        assert result["native_equipped_paid_attempts"] == 2
        assert "P3_NATIVE_SLOT_UNSCORED:head:UNSUPPORTED" in result["reasons"]
        assert "runtime_proof" not in result


def test_mage_p3_routes_to_unified_native_without_gameir(monkeypatch):
    import src.game.data.forever.registry as registry
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")

    def no_python_ir(**_kwargs):
        raise AssertionError("Mage L60 P3 must not enter Python GameIR")

    monkeypatch.setattr(registry, "build_game_ir_slice", no_python_ir)
    monkeypatch.setattr(p3, "_query_native_unified_p3_items",
                        lambda _root, binary, cls, level: {
                            "source": "selected-rust-source", "status": "ok",
                            "transport": "MYTHICSIM_NATIVE_GET_OPTIONS",
                            "items": [{"slot": "weapon", "item_id": 900,
                                       "item_level": 60}],
                            "unverified_candidate_count": 4,
                        })
    seen = []

    def paid(root, binary, selection, remaining, *, checkpoint):
        seen.append((binary, selection, remaining, checkpoint))
        return {
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2,
            "actor_checkpoint_verified": True,
            "native_prepared_actor": {"actor_class": "ClassMage", "actor_level": 60,
                                      "engine_revision": "selected-engine-revision"},
            "evaluations": [
                {"status": "VALID", "score": 100.0, "request_sha256": "baseline-sha"},
                {"status": "VALID", "score": 104.0, "request_sha256": "swapped-sha"},
            ],
            "native_slot_evaluations": [{
                "swap": {"slot": "weapon", "to_id": 900},
                "status": "VALID", "score": 104.0, "delta_dps": 4.0,
            }],
            "native_slots_valid": 1,
            "source_occupied_slots": ["weapon"],
        }

    monkeypatch.setattr(p3, "_paid_native_equipped_probe", paid)
    result = p3.run_live(ROOT, "mage", 60, spec="arcane")
    assert seen == [("selected-engine",
                     {"slots": {"weapon": {"selected_ids": [900]}}},
                     44, "mage_l60")]
    assert result["status"] == "PASS"  # Synthetic contract-only receipt, NOT gate evidence.
    assert result["item_options_source"] == "MYTHICSIM_NATIVE_GET_OPTIONS"
    assert result["native_unverified_candidate_count"] == 4


def test_mage_p3_rejects_unknown_native_coverage_before_paid(monkeypatch):
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")
    payload = _unified_payload()
    payload["coverage"]["talent_prerequisites_complete"] = None

    def fake_cli(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_cli)
    monkeypatch.setattr(p3, "_paid_native_equipped_probe", lambda *_a, **_kw: (
        (_ for _ in ()).throw(AssertionError("No paid call on invalid source"))))
    result = p3.run_live(ROOT, "mage", 60, spec="arcane")
    assert result["status"] == "BLOCKED"
    assert any("NATIVE_OPTIONS_INVALID_COVERAGE" in reason for reason in result["reasons"])
    assert result["real_source_search_evaluated"] == 0


def test_mage_l60_fifteen_item_source_is_checked_by_native_prepare_and_paid():
    reference = _mage_reference()
    original = copy.deepcopy(reference)
    evaluations = []

    def evaluator(binary, request, iterations, seed, rng_mode, deadline, **kwargs):
        assert rng_mode == "balanced"
        evaluations.append(copy.deepcopy(request))
        item = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][14]["id"]
        return (110.0 if item == 900 else 100.0), {}, 0.01, f"sha-{len(evaluations)}"

    result = compare_equipped_native(
        "selected-engine", reference, {"weapon": {"selected_ids": [900]}},
        class_key="mage", level=60, evaluator=evaluator,
        preparer=lambda *_a: {
            "status": "PREPARED", "actor_class": "ClassMage",
            "actor_level": 60, "engine_revision": "selected-rust-revision",
        })
    assert result["status"] == "PAID_NATIVE_DIFFERENCE"
    assert result["actor_checkpoint_verified"] is True
    assert result["comparison"]["delta_dps"] == 10.0
    assert result["paid_attempts"] == 2
    assert len(result["source_occupied_slots"]) == 15
    assert "offhand" not in result["source_occupied_slots"]
    assert "ranged" not in result["source_occupied_slots"]
    assert evaluations[0] == reference and reference == original
    assert evaluations[1]["raid"]["parties"][0]["players"][0]["equipment"]["items"][14] == {"id": 900}


def test_mage_l60_refuses_unmatched_native_prepared_actor_without_paid():
    result = compare_equipped_native(
        "selected-engine", _mage_reference(), {"weapon": {"selected_ids": [900]}},
        class_key="mage", level=60,
        preparer=lambda *_a: {
            "status": "PREPARED", "actor_class": "ClassMage",
            "actor_level": 20, "engine_revision": "selected-rust-revision",
        },
        evaluator=lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("Wrong-level actor cannot be paid")),
    )
    assert result["status"] == "NATIVE_ACTOR_CHECKPOINT_MISMATCH"
    assert result["paid_attempts"] == 0
    assert result["actor_checkpoint_verified"] is False


def test_mage_p3_verdict_counts_real_occupied_slots_not_phantom_positions():
    from native_p3_equipped import NATIVE_SLOT_POSITIONS

    occupied = [slot for slot, index in NATIVE_SLOT_POSITIONS if index < 15]
    assert len(occupied) == 15
    options = {
        "status": "ok", "source": "selected-rust",
        "items": [{"slot": slot, "item_id": 2000 + index, "item_level": 50}
                  for index, (slot, _pos) in enumerate(NATIVE_SLOT_POSITIONS)],
    }
    evaluations = [{
        "swap": {"slot": slot, "to_id": 2000 + index},
        "status": "VALID", "score": 505.0 if index == 0 else 500.0,
        "delta_dps": 5.0 if index == 0 else 0.0,
        "request_sha256": f"paid-sha-{index}",
    } for index, slot in enumerate(occupied)]
    receipt = {
        "status": "PAID_NATIVE_DIFFERENCE",
        "paid_attempts": 16, "actor_checkpoint_verified": True,
        "source_occupied_slots": occupied,
        "native_prepared_actor": {
            "actor_class": "ClassMage", "actor_level": 60,
            "engine_revision": "pinned-engine",
        },
        "evaluations": [{"status": "VALID", "score": 500.0,
                         "request_sha256": "native-baseline"}],
        "native_slot_evaluations": evaluations, "native_slots_valid": 15,
    }
    result = p3._native_rogue_p3_verdict(options, receipt, checkpoint="mage_l60")
    assert result["status"] == "PASS", result["reasons"]
    assert result["pass_count"] == result["reachability_count"] == 15
    assert "offhand" in result["real_selected_item_alternatives_by_slot"]
    assert "ranged" in result["real_selected_item_alternatives_by_slot"]

    no_occupancy = copy.deepcopy(receipt)
    no_occupancy.pop("source_occupied_slots")
    missing = p3._native_rogue_p3_verdict(options, no_occupancy, checkpoint="mage_l60")
    assert missing["status"] == "FAIL"
    assert "P3_NATIVE_OCCUPIED_SLOT_RECEIPT_MISSING" in missing["reasons"]

    one_unpaid = copy.deepcopy(receipt)
    one_unpaid["native_slot_evaluations"] = evaluations[:-1]
    not_scored = p3._native_rogue_p3_verdict(options, one_unpaid, checkpoint="mage_l60")
    assert not_scored["status"] == "FAIL"
    assert "P3_NATIVE_SLOT_UNSCORED:trinket2:NOT_ATTEMPTED" in not_scored["reasons"]


def test_mage_fire_l60_routes_source_native_and_scores(monkeypatch):
    """The second L60 Mage spec reuses Arcane's same native paid scorer."""
    import src.game.data.forever.registry as registry

    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **_kw: (
        (_ for _ in ()).throw(AssertionError("No Python GameIR in Mage Fire P3"))))
    seen = []
    def native_options(root, binary, cls, level):
        seen.append(("options", binary, cls, level))
        return {
            "status": "ok", "transport": "MYTHICSIM_NATIVE_GET_OPTIONS",
            "source": "selected-engine-source",
            "items": [{"slot": "weapon", "item_id": 900, "item_level": 60}],
        }
    def native_paid(root, binary, selection, remaining, *, checkpoint):
        seen.append(("paid", binary, selection, remaining, checkpoint))
        return {
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2,
            "actor_checkpoint_verified": True,
            "native_prepared_actor": {
                "actor_class": "ClassMage", "actor_level": 60,
                "engine_revision": "selected-engine",
            },
            "source_occupied_slots": ["weapon"],
            "evaluations": [
                {"status": "VALID", "score": 100.0, "request_sha256": "paid-base"},
                {"status": "VALID", "score": 105.0, "request_sha256": "paid-gear"},
            ],
            "native_slot_evaluations": [{
                "swap": {"slot": "weapon", "to_id": 900}, "status": "VALID",
                "score": 105.0, "delta_dps": 5.0,
            }],
            "native_slots_valid": 1,
        }
    monkeypatch.setattr(p3, "_query_native_unified_p3_items", native_options)
    monkeypatch.setattr(p3, "_paid_native_equipped_probe", native_paid)
    assert p3.native_item_options_required("mage", 60, "fire")
    result = p3.run_live(ROOT, "mage", 60, spec="fire")
    assert result["status"] == "PASS", result["reasons"]
    assert result["reachability_count"] == result["pass_count"] == 1
    assert result["item_options_source"] == "MYTHICSIM_NATIVE_GET_OPTIONS"
    assert seen == [
        ("options", "selected-engine", "mage", 60),
        ("paid", "selected-engine",
         {"slots": {"weapon": {"selected_ids": [900]}}}, 44,
         "mage_fire_l60"),
    ]


def test_mage_fire_p3_uses_exact_fire_fixture_and_talent_preset(monkeypatch):
    """No Arcane gear/talents are accidentally attributed to Fire."""
    seen = []
    def fake_paid(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr="",
                               stdout=json.dumps({"status": "PAID_NATIVE_DIFFERENCE",
                                                  "paid_attempts": 2}))
    monkeypatch.setattr(subprocess, "run", fake_paid)
    selection = {"slots": {"head": {"selected_ids": [345]}}}
    receipt = p3._paid_native_equipped_probe(
        ROOT, "selected-engine", selection, 44, checkpoint="mage_fire_l60")
    assert receipt["paid_attempts"] == 2
    command, kwargs = seen[0]
    assert "--request" in command
    assert command[command.index("--request") + 1].endswith(
        "/fixtures/mage/prepared-v2/fire-reference.request.json")
    assert command[-6:] == ["--class-key", "mage", "--level", "60",
                            "--current-client-profile", "mage/fire"]
    assert json.loads(kwargs["input"]) == selection["slots"]


def test_mage_frost_l60_routes_source_native_and_scores(monkeypatch):
    """The second L60 Mage spec reuses Arcane's same native paid scorer."""
    import src.game.data.forever.registry as registry

    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **_kw: (
        (_ for _ in ()).throw(AssertionError("No Python GameIR in Mage Frost P3"))))
    seen = []
    def native_options(root, binary, cls, level):
        seen.append(("options", binary, cls, level))
        return {
            "status": "ok", "transport": "MYTHICSIM_NATIVE_GET_OPTIONS",
            "source": "selected-engine-source",
            "items": [{"slot": "weapon", "item_id": 900, "item_level": 60}],
        }
    def native_paid(root, binary, selection, remaining, *, checkpoint):
        seen.append(("paid", binary, selection, remaining, checkpoint))
        return {
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2,
            "actor_checkpoint_verified": True,
            "native_prepared_actor": {
                "actor_class": "ClassMage", "actor_level": 60,
                "engine_revision": "selected-engine",
            },
            "source_occupied_slots": ["weapon"],
            "evaluations": [
                {"status": "VALID", "score": 100.0, "request_sha256": "paid-base"},
                {"status": "VALID", "score": 105.0, "request_sha256": "paid-gear"},
            ],
            "native_slot_evaluations": [{
                "swap": {"slot": "weapon", "to_id": 900}, "status": "VALID",
                "score": 105.0, "delta_dps": 5.0,
            }],
            "native_slots_valid": 1,
        }
    monkeypatch.setattr(p3, "_query_native_unified_p3_items", native_options)
    monkeypatch.setattr(p3, "_paid_native_equipped_probe", native_paid)
    assert p3.native_item_options_required("mage", 60, "frost")
    result = p3.run_live(ROOT, "mage", 60, spec="frost")
    assert result["status"] == "PASS", result["reasons"]
    assert result["reachability_count"] == result["pass_count"] == 1
    assert result["item_options_source"] == "MYTHICSIM_NATIVE_GET_OPTIONS"
    assert seen == [
        ("options", "selected-engine", "mage", 60),
        ("paid", "selected-engine",
         {"slots": {"weapon": {"selected_ids": [900]}}}, 44,
         "mage_frost_l60"),
    ]


def test_mage_frost_p3_uses_exact_frost_fixture_and_talent_preset(monkeypatch):
    """No Arcane gear/talents are accidentally attributed to Frost."""
    seen = []
    def fake_paid(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr="",
                               stdout=json.dumps({"status": "PAID_NATIVE_DIFFERENCE",
                                                  "paid_attempts": 2}))
    monkeypatch.setattr(subprocess, "run", fake_paid)
    selection = {"slots": {"head": {"selected_ids": [345]}}}
    receipt = p3._paid_native_equipped_probe(
        ROOT, "selected-engine", selection, 44, checkpoint="mage_frost_l60")
    assert receipt["paid_attempts"] == 2
    command, kwargs = seen[0]
    assert "--request" in command
    assert command[command.index("--request") + 1].endswith(
        "/fixtures/mage/prepared-v2/frost-reference.request.json")
    assert command[-6:] == ["--class-key", "mage", "--level", "60",
                            "--current-client-profile", "mage/frost"]
    assert json.loads(kwargs["input"]) == selection["slots"]


def test_m1_dispatch_builds_selected_native_engine_for_frost_p3():
    """Frost's official P3 dispatch must build the same binary as the paid probe."""
    workflow = (ROOT / ".github/workflows/m1-on-demand-record.yml").read_text(
        encoding="utf-8")
    p3_conditions = workflow.split('if [[ "$gate" == P3 ]]; then', 1)[1].split(
        'elif [[ ( "$gate" == P4', 1)[0]
    assert '"$class" == mage && "$level" == 60' in p3_conditions
    assert '"$spec" == arcane' in p3_conditions
    assert '"$spec" == fire' in p3_conditions
    assert '"$spec" == frost' in p3_conditions
    assert "native_options_needed=true" in p3_conditions
