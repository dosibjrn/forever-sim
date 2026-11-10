"""P7.4 native gear-axis contract and P7.5 shared search scheduling regressions."""
import copy
from types import SimpleNamespace
import pytest
from tools import wf_gate_p7_4_live as gate


def test_l30_p74_uses_exact_frozen_reference_without_resampling(monkeypatch, tmp_path):
    """P7.4 must inherit the paid L30 P7.1 request, not the L60 donor."""
    import hashlib
    import json
    from tools import wf_p7_native_reference as frozen

    directory = frozen._reference_directory(tmp_path, "druid", 30, "unrestricted")
    directory.mkdir(parents=True)
    request = {
        "raid": {"parties": [{"players": [{
            "class": "ClassDruid", "talentsString": "0-0-0",
            "equipment": {"items": [{"id": 12345}]},
            "rotation": {"priorityList": [{"action": {"castSpell": {
                "spellId": {"spellId": 5176}}}}]},
        }]}]},
        "encounter": {"targets": [{"level": 30}]},
        "simOptions": {"iterations": 1000},
    }
    raw = json.dumps(request, sort_keys=True).encode()
    (directory / "request.json").write_bytes(raw)
    source_sha = hashlib.sha256(raw).hexdigest()
    binary = tmp_path / "pinned/forever-engine"
    checks = []

    def check_reference(*args):
        checks.append(args)
        return {"status": "PASS", "saved_reference_dps": 8.357414975823593,
                "source_request_raw_sha256": source_sha}

    monkeypatch.setattr(frozen, "run_generated_p71", check_reference)
    monkeypatch.setattr(frozen, "_binary_and_pin",
                        lambda _root: (binary, "41444ee-frozen"))
    selected, meta, scorer = gate._pinned_source_runtime(
        tmp_path, "druid", 30, "unrestricted", "P7.4", require_world=False)
    assert selected == request
    assert scorer == binary
    assert meta["source_request_raw_sha256"] == source_sha
    assert meta["selected_engine_revision"] == "41444ee-frozen"
    assert meta["native_actor_level_context"] == 30
    assert meta["reference_dps"] == 8.357414975823593
    assert checks == [(tmp_path, "druid", 30, "unrestricted")]


def test_l30_p74_preserves_native_reference_refusal(monkeypatch, tmp_path):
    """An incompatible frozen pin must not be scored as a gear challenger."""
    from tools import wf_p7_native_reference as frozen

    monkeypatch.setattr(frozen, "run_generated_p71", lambda *_args: {
        "status": "BLOCKED",
        "reasons": ["P7_1_GENERATED_REFERENCE_ENGINE_CHANGED"]})
    monkeypatch.setattr(
        frozen, "_binary_and_pin",
        lambda *_args: (_ for _ in ()).throw(AssertionError(
            "native scoring cannot run on an incompatible reference")))
    assert gate._pinned_source_runtime(
        tmp_path, "druid", 30, "unrestricted", "P7.4",
        require_world=False) == {
            "status": "BLOCKED",
            "reasons": [
                "P7_4_NATIVE_GENERATED_REFERENCE_NOT_VERIFIED",
                "P7_1_GENERATED_REFERENCE_ENGINE_CHANGED",
            ],
            "native_reference_status": "BLOCKED",
        }


def test_wrong_reference_never_reaches_native(tmp_path):
    report = gate.run_live(tmp_path, "priest", 60, spec="holy")
    assert report["status"] == "BLOCKED"
    assert "P7_4_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT" in report["reasons"]


def test_p74_paid_step_guard_prevents_observed_302s_overrun(monkeypatch):
    """A measured 2.6s balanced candidate may not start at 299s and block holdout.

    Source-native+2D paid screens are indivisible; final 1,000 stochastic
    iterations are a separate stage outside the 300s search clock.
    """
    clock = SimpleNamespace(now=299.0)
    monkeypatch.setattr(gate.time, "monotonic", lambda: clock.now)
    assert not gate._paid_step_has_budget(0.0, 2.6)
    assert not gate._paid_step_has_budget(0.0, 0.9)
    clock.now = 295.0
    assert gate._paid_step_has_budget(0.0, 2.6)
    # Fast 3-fight balanced screens can still run late in the window when
    # their measured duration fits; no finalist-only rerank phase exists.
    clock.now = 299.0
    assert gate._paid_step_has_budget(0.0, 0.10)
    clock.now = 299.95
    assert not gate._paid_step_has_budget(0.0, 0.10)


def test_pinned_rust_candidate_pool_uses_rust_jsonl_tables(tmp_path):
    import json
    import sys
    from pathlib import Path

    source_dir = Path(gate.__file__).resolve().parents[1] / "integrations/mythicsim-rust"
    sys.path.insert(0, str(source_dir))
    try:
        search = gate._source_module(
            source_dir / "p74_gear_search.py", "p74_pinned_rust_jsonl_search_test")
    finally:
        sys.path.remove(str(source_dir))

    item_types = sorted(set(search.RUST_TYPES[slot] for slot in search.SLOTS))
    item_rows = []
    enchant_rows = []
    for index, item_type in enumerate(item_types):
        item_rows.append({
            "id": 1000 + index,
            "type": item_type,
            "scaling_options": {"0": {"stats": {"5": 10.0 + index}}},
            "hand_type": "HandTypeOneHand",
            "weapon_type": "WeaponTypeSword",
            "ranged_weapon_type": "RangedWeaponTypeIdol",
        })
        enchant_rows.append({
            "effect_id": 2000 + index,
            "type": item_type,
            "enchant_type": "EnchantTypeUnknown",
            "extra_types": [],
        })

    head_type = search.RUST_TYPES["head"]
    item_rows.append({
        "id": 9999, "type": head_type,
        "scaling_options": {"0": {"stats": {"5": 50.0}}},
    })
    weapon_type = search.RUST_TYPES["weapon"]
    item_rows.extend([
        {"id": 9001, "type": weapon_type,
         "scaling_options": {"0": {"stats": {"5": 100.0}}},
         "hand_type": "HandTypeOffHand", "weapon_type": "WeaponTypeDagger"},
        {"id": 9002, "type": weapon_type,
         "scaling_options": {"0": {"stats": {"5": 100.0}}},
         "hand_type": "HandTypeOneHand", "weapon_type": "WeaponTypeShield"},
    ])
    relic_type = search.RUST_TYPES["relic"]
    item_rows.extend([
        {
            "id": 9003, "type": relic_type,
            "scaling_options": {"0": {"stats": {"5": 100.0}}},
            "ranged_weapon_type": "RangedWeaponTypeBow",
        },
        {
            "id": 9004, "type": relic_type,
            "scaling_options": {"0": {"ilvl": 65}},
            "ranged_weapon_type": "RangedWeaponTypeIdol",
            "item_effects": [{"buff_id": 27851, "buff_name": "Reduced Claw and Rake Cost"}],
        },
        {
            # Protobuf JSON omits enum-zero RangedWeaponTypeUnknown.
            "id": 9005, "type": relic_type,
            "scaling_options": {"0": {"stats": {"5": 100.0}}},
        },
    ])

    items_path = tmp_path / "items.jsonl"
    enchants_path = tmp_path / "enchants.jsonl"
    items_path.write_text("".join(json.dumps(row) + "\n" for row in item_rows))
    enchants_path.write_text("".join(json.dumps(row) + "\n" for row in enchant_rows))

    pool, enchant_pools, metadata = search.pinned_rust_candidate_pool(
        items_path, enchants_path)

    assert pool[0][:2] == [9999, 1000 + item_types.index(head_type)]
    assert pool[14] == [1000 + item_types.index(weapon_type)]
    assert pool[15][0] == 9005  # omitted enum zero is proposed; native decides legality
    assert 9003 not in pool[15]  # a known bow is not a druid relic proposal
    assert 9004 in pool[15]  # real relics can have item_effects but no stat map
    assert enchant_pools[6] == [None, 2000 + item_types.index(search.RUST_TYPES["hands"])]
    assert metadata == {
        "unique_item_options": len(item_types) + 3,
        "unique_enchant_options": len(item_types),
    }



def test_pinned_rust_candidate_pool_accepts_actual_engine_jsonl():
    """Exercise the actual pinned item/enchant rows and all 16 slot pools."""
    import os
    import pytest
    import sys
    from pathlib import Path

    root = Path(gate.__file__).resolve().parents[1]
    engine_data = root / "integrations/mythicsim-rust/engine/data"
    items_path = engine_data / "items.jsonl"
    enchants_path = engine_data / "enchants.jsonl"
    if not items_path.is_file() or not enchants_path.is_file():
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail("Generic source-paid CI must check out the pinned Rust data submodule")
        pytest.skip("pinned MythicSim source data is not checked out")

    source_dir = root / "integrations/mythicsim-rust"
    sys.path.insert(0, str(source_dir))
    try:
        search = gate._source_module(
            source_dir / "p74_gear_search.py", "p74_actual_engine_jsonl_search_test")
    finally:
        sys.path.remove(str(source_dir))

    pool, enchant_pools, metadata = search.pinned_rust_candidate_pool(
        items_path, enchants_path)
    assert set(pool) == set(range(len(search.SLOTS)))
    assert all(pool[index] for index in range(len(search.SLOTS)))
    assert 22397 in pool[15]  # Idol of Ferocity: statless effect-only relic
    assert 833 in pool[12] and 833 in pool[13]  # Lifestone: statless trinket
    assert 754 in pool[14]  # Shortsword of Vengeance: statless weapon
    assert metadata["unique_item_options"] > 0
    assert metadata["unique_enchant_options"] > 0
    assert all(choices and choices[0] is None for choices in enchant_pools.values())



@pytest.mark.parametrize("checkpoint_level", [30, 60])
def test_p74_native_axis_pays_changed_gear_without_world_or_holdout(
        monkeypatch, tmp_path, checkpoint_level):
    """Native owns game legality; P7.4 needs only one changed paid gear axis."""
    import json
    import pytest

    base = {"raid": {"parties": [{"players": [{
        "class": "ClassDruid",
        "equipment": {"items": [{"id": 10}, {"id": 20}]},
        "talentsString": "fixed-talents",
        "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": 1}}}]},
    }]}]}}
    original = copy.deepcopy(base)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("mock binary never executed")
    data = binary.parents[2] / "data"
    data.mkdir()
    (data / "items.jsonl").write_text("{}\n")
    (data / "enchants.jsonl").write_text("{}\n")
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    preflights = []
    def preflight(*args, **kw):
        preflights.append((args, kw))
        return base, {"reference_dps": 728.19,
                      "selected_reference_profile": "balance",
                      "selected_engine_revision": "selected-rust"}, binary
    monkeypatch.setattr(gate, "_pinned_source_runtime", preflight)
    source = SimpleNamespace(pinned_rust_candidate_pool=lambda *a: (
        {0: [10, 11], 1: [20]},
        {0: [None], 1: [None, 222]},
        {"unique_item_options": 3, "unique_enchant_options": 1}))
    calls = []
    def native(binary_arg, request_path, n, *, rng_mode, actor_level=None):
        request = json.loads(request_path.read_text())
        calls.append(request)
        assert n == 3 and rng_mode == "balanced"
        assert actor_level == (checkpoint_level if checkpoint_level != 60 else None)
        original_player = original["raid"]["parties"][0]["players"][0]
        player = request["raid"]["parties"][0]["players"][0]
        assert player["talentsString"] == original_player["talentsString"]
        assert player["rotation"] == original_player["rotation"]
        assert player["equipment"] != original_player["equipment"]
        if len(calls) == 1:
            raise RuntimeError(
                'NATIVE_SOURCE_CONTROL_FAILED exit=5 request_sha256=abc '
                'output={"prepared":false,"refusal":{"code":"gear",'
                '"reason":"native rejected first option"}}')
        return {"iterations": 3, "native_dps": 735.0}
    def world(*a, **kw):
        pytest.fail("P7.4 stationary DPS must not call the 2D world")
    monkeypatch.setattr(gate, "_source_module", lambda path, *a: (
        source if "p74_gear_search" in str(path) else
        SimpleNamespace(native_source_control=native, run=world)))
    report = gate.run_live(tmp_path, "druid", checkpoint_level, spec="unrestricted")
    assert preflights[0][0][-1] == "P7.4"
    assert preflights[0][1] == {"require_world": False}
    assert report["status"] == "PASS"
    assert report["winner_native_dps"] == 735.0
    assert report["source_legal_cold_candidates_paid"] == 1
    assert report["native_invalid_candidates"] == 1
    assert report["cold_unique_source_requests"] == 2
    assert report["reference_profile"] == "balance"
    assert report["checkpoint_spec"] == "unrestricted"
    assert report["source_fixed_rotation_and_talents"] is True
    assert report["independent_300s_search_completed"] is False
    assert "frozen_stochastic_iterations" not in report
    assert report["runtime_proof"]["executed"] is True
    # A rejected proposal is not the retained winner; the exact native-paid
    # candidate survives the temporary request file for a true replay.
    assert report["cold_winner_request"] == calls[-1]
    assert report["cold_winner_request"] != calls[0]
    assert report["cold_winner_request"]["raid"]["parties"][0]["players"][0][
        "talentsString"] == original["raid"]["parties"][0]["players"][0]["talentsString"]
    import hashlib
    assert report["cold_winner_request_sha256"] == hashlib.sha256(
        json.dumps(calls[-1], sort_keys=True).encode()).hexdigest()
    assert base == original


def test_p74_native_axis_never_passes_unchanged_reference(monkeypatch, tmp_path):
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}]},
        "talentsString": "fixed", "rotation": {"priorityList": []},
    }]}]}}
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("mock")
    data = binary.parents[2] / "data"
    data.mkdir()
    (data / "items.jsonl").write_text("{}\n")
    (data / "enchants.jsonl").write_text("{}\n")
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    monkeypatch.setattr(gate, "_pinned_source_runtime", lambda *a, **kw: (
        base, {"reference_dps": 728.19}, binary))
    source = SimpleNamespace(pinned_rust_candidate_pool=lambda *a: (
        {0: [10]}, {0: [None]},
        {"unique_item_options": 1, "unique_enchant_options": 0}))
    monkeypatch.setattr(gate, "_source_module", lambda path, *a: (
        source if "p74_gear_search" in str(path) else
        SimpleNamespace(native_source_control=lambda *a, **kw:
                        (_ for _ in ()).throw(AssertionError(
                            "unchanged reference must not be paid")))))
    report = gate.run_live(tmp_path, "druid", 60, spec="unrestricted")
    assert report["status"] == "FAIL"
    assert report["reasons"] == ["P7_4_NO_NATIVE_PAID_CHANGED_GEAR_CANDIDATE"]
    assert report["cold_unique_source_requests"] == 0
    assert report["source_legal_cold_candidates_paid"] == 0


def test_feral_p74_selects_original_source_and_pays_changed_gear_on_go_rules(
        monkeypatch, tmp_path):
    """Forever transport of an authentic Feral P7.4 request; mocked native scorer."""
    import json
    from pathlib import Path
    from tools import wf_gate_p7_2_live as p72
    from tools.wf_gate_p7_1_live import FERAL_REFERENCE_DPS, SAVED_FERAL_RAW_SHA

    root = Path(__file__).resolve().parents[2]
    reference_path = root / "docs/evidence/druid-l60-feral/p7.1/saved_811_request.json"
    base = json.loads(reference_path.read_text())
    fixed = copy.deepcopy(base)
    original_player = base["raid"]["parties"][0]["players"][0]
    original_items = original_player["equipment"]["items"]
    new_id = original_items[0]["id"] + 1
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("mock executable; real engine never invoked")
    data = binary.parents[2] / "data"
    data.mkdir()
    (data / "items.jsonl").write_text("{}\n")
    (data / "enchants.jsonl").write_text("{}\n")
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(binary))
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    monkeypatch.setattr(
        p72, "_selected_rust_submodule", lambda *a: "selected-feral-rust-pin")

    pool = SimpleNamespace(pinned_rust_candidate_pool=lambda *a: (
        {0: [new_id]}, {0: [original_items[0].get("enchant")]},
        {"unique_item_options": 1, "unique_enchant_options": 0}))
    requests = []

    def native_score(selected_binary, path, iterations, *, rng_mode, go_rules=False):
        assert selected_binary == binary.resolve()
        assert iterations == 3 and rng_mode == "balanced" and go_rules is True
        candidate = json.loads(path.read_text())
        changed = candidate["raid"]["parties"][0]["players"][0]
        assert changed["equipment"]["items"][0]["id"] == new_id
        assert changed["equipment"] != original_player["equipment"]
        assert changed["rotation"] == original_player["rotation"]
        assert changed["talentsString"] == original_player["talentsString"]
        requests.append(candidate)
        return {"iterations": 3, "native_dps": 885.25}

    monkeypatch.setattr(gate, "_source_module", lambda path, *a: (
        pool if "p74_gear_search" in str(path) else
        SimpleNamespace(native_source_control=native_score)))
    report = gate.run_live(root, "druid", 60, spec="feral")
    assert report["status"] == "PASS"  # mock transport, NOT a native gate PASS
    assert report["source_request_raw_sha256"] == SAVED_FERAL_RAW_SHA
    assert report["saved_reference_dps"] == FERAL_REFERENCE_DPS
    assert report["reference_profile"] == report["checkpoint_spec"] == "feral"
    assert report["native_rules"] == "go_reference"
    assert report["native_source_revision"] == "selected-feral-rust-pin"
    assert report["source_fixed_rotation_and_talents"] is True
    assert report["source_legal_cold_candidates_paid"] == len(requests) == 1
    assert report["winner_native_dps"] == 885.25
    assert base == fixed


def test_feral_p74_rejects_modified_original_source_before_native(monkeypatch, tmp_path):
    """A changed pinned Feral request is not a replacement gear search input."""
    root = tmp_path
    request = root / "docs/evidence/druid-l60-feral/p7.1/saved_811_request.json"
    request.parent.mkdir(parents=True)
    request.write_text('{"raid":{}, "encounter":{}}')
    report = gate._pinned_source_runtime(
        root, "druid", 60, "feral", "P7.4", require_world=False)
    assert report == {"status": "BLOCKED",
                      "reasons": ["P7_4_PINNED_SOURCE_REQUEST_CHANGED"]}

def test_p74_full_search_env_cannot_reenable_retired_holdout(monkeypatch, tmp_path):
    """Both legacy switch values still dispatch only to paid native P7.4."""
    calls = []

    def direct_native(root, class_key, level, spec):
        calls.append((root, class_key, level, spec))
        return {"status": "PASS", "reasons": [], "winner_native_dps": 42.0}

    monkeypatch.setattr(gate, "_run_native_gear_axis", direct_native)
    for flag in ("1", "invalid"):
        monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", flag)
        report = gate.run_live(tmp_path, "druid", 30, spec="balance")
        assert report["status"] == "PASS"
        assert report["winner_native_dps"] == 42.0

    assert calls == [(tmp_path, "druid", 30, "balance")] * 2



def test_l30_p74_pays_item_on_actual_naked_frozen_reference(
        monkeypatch, tmp_path):
    """Reproduce the real empty P7.1 gear and require a changed native request."""
    import json
    from pathlib import Path

    source_file = (Path(__file__).resolve().parents[2]
                   / "docs/evidence/native-references/"
                   / "druid-l30-unrestricted/request.json")
    reference = json.loads(source_file.read_text())
    assert reference["raid"]["parties"][0]["players"][0]["equipment"]["items"] == []
    base = copy.deepcopy(reference)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("mock only")
    data = binary.parents[2] / "data"
    data.mkdir()
    (data / "items.jsonl").write_text("{}\\n")
    (data / "enchants.jsonl").write_text("{}\\n")
    monkeypatch.setattr(gate, "_pinned_source_runtime", lambda *args, **kwargs: (
        base, {"reference_dps": 8.357414975823593,
               "selected_engine_revision": "41444ee-frozen"}, binary))

    # Propose a new item in an otherwise unoccupied slot index 2.
    # Native decides whether that item is legal; no Python whitelist is used.
    source = SimpleNamespace(pinned_rust_candidate_pool=lambda *args: (
        {0: [], 1: [], 2: [1234]},
        {0: [None], 1: [None], 2: [None, 456]},
        {"unique_item_options": 1, "unique_enchant_options": 1}))
    observed = []

    def native(bin_arg, request_path, iterations, *, rng_mode, actor_level):
        request = json.loads(request_path.read_text())
        observed.append(request)
        assert iterations == 3 and rng_mode == "balanced" and actor_level == 30
        player = request["raid"]["parties"][0]["players"][0]
        original = reference["raid"]["parties"][0]["players"][0]
        assert player["talentsString"] == original["talentsString"]
        assert player["rotation"] == original["rotation"]
        assert player["equipment"]["items"] == [
            {"id": 0}, {"id": 0}, {"id": 1234}]
        return {"iterations": 3, "native_dps": 8.42}

    monkeypatch.setattr(gate, "_source_module", lambda path, *args: (
        source if "p74_gear_search" in str(path)
        else SimpleNamespace(native_source_control=native)))
    report = gate.run_live(tmp_path, "druid", 30, spec="unrestricted")
    assert report["status"] == "PASS"
    assert report["cold_unique_source_requests"] == 1
    assert report["source_legal_cold_candidates_paid"] == 1
    assert report["cold_winner_request"] == observed[0]
    assert base == reference
