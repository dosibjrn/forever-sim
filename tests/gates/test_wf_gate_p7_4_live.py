"""P7.4 source-legal cold gear mutation contract, never a fake gate PASS."""
import copy
import random
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


def test_cold_gear_requires_nonreference_legal_native_candidate():
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}, {"id": 20}]},
        "talentsString": "source",
        "rotation": {"priorityList": []},
    }]}]}}
    original = copy.deepcopy(base)
    calls = []
    validator = SimpleNamespace(validate=lambda ids: calls.append(ids))
    search = SimpleNamespace(
        candidate_pool=lambda v, limit, **kwargs: ({0: [11], 1: [21]}, {}),
        RejectedGear=ValueError,
        _swap=lambda req, ids: {
            **copy.deepcopy(req),
            "raid": {"parties": [{"players": [{
                **copy.deepcopy(req["raid"]["parties"][0]["players"][0]),
                "equipment": {"items": [{"id": v} for v in ids]}
            }]}]}}
    )
    row = gate._cold_gear(base, validator, search, random.Random(1))
    assert calls == [[11, 21]]
    assert row["raid"]["parties"][0]["players"][0]["equipment"]["items"] == (
        [{"id": 11}, {"id": 21}])
    assert base == original



def test_independently_rediscovered_saved_gear_is_legal_cold_candidate():
    """The gate forbids seeding from the reference, not cold rediscovery.

    A one-build legal source pool must reach the selected engine even when
    its item IDs happen to equal the saved request; otherwise the old
    unconditional reference-equality filter rejects all 60 proposals.
    """
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}, {"id": 20}]},
        "talentsString": "fixed",
        "rotation": {"priorityList": []},
    }]}]}}
    original = copy.deepcopy(base)
    paid_legality_checks = []
    validator = SimpleNamespace(
        validate=lambda ids: paid_legality_checks.append(list(ids)))
    def swap(request, ids):
        result = copy.deepcopy(request)
        items = result["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        for item, iid in zip(items, ids):
            item["id"] = iid
        return result
    source = SimpleNamespace(_swap=swap, RejectedGear=ValueError)
    candidate = gate._cold_gear(
        base, validator, source, random.Random(7),
        pool={0: [10], 1: [20]}, elite=None)
    assert paid_legality_checks == [[10, 20]]
    assert candidate == base
    assert base == original


def test_wrong_reference_never_reaches_native(tmp_path):
    report = gate.run_live(tmp_path, "priest", 60, spec="holy")
    assert report["status"] == "BLOCKED"
    assert "P7_4_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT" in report["reasons"]


def test_full_cold_p74_can_free_enchant_without_changing_fixed_axes():
    """Pre-fix: unchanged reference item IDs could never gain a new enchant."""
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 100+i} for i in range(16)]},
        "talentsString": "fixed-talents",
        "rotation": {"priorityList": [{"action": 1}]},
    }]}]}}
    original = copy.deepcopy(base)
    checked = []
    def validate(ids, enchants=None):
        checked.append((ids, enchants))
        assert ids == [100+i for i in range(16)]
        assert enchants == [411] + [None]*15
    def swap(reference, ids):
        q = copy.deepcopy(reference)
        for item, iid in zip(q["raid"]["parties"][0]["players"][0]["equipment"]["items"], ids):
            item["id"] = iid
        return q
    search = SimpleNamespace(_swap=swap, preflight=lambda *a: True,
                             RejectedGear=ValueError)
    pools = {i: [100+i] for i in range(16)}
    enchants = {i: ([411] if i == 0 else [None]) for i in range(16)}
    winner = gate._cold_gear(
        base, SimpleNamespace(validate=validate), search, random.Random(1),
        pool=pools, enchant_pools=enchants)
    player = winner["raid"]["parties"][0]["players"][0]
    assert player["equipment"]["items"][0] == {"id": 100, "enchant": 411}
    assert player["talentsString"] == "fixed-talents"
    assert player["rotation"] == {"priorityList": [{"action": 1}]}
    assert len(checked) == 1
    assert base == original


def test_paid_p74_gear_neighbor_uses_only_paid_loadout_and_source_pools():
    """Local changes preserve untouched paid slots; not seeded by saved gear."""
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}, {"id": 20}, {"id": 30}]},
        "talentsString": "fixed",
        "rotation": {"priorityList": []},
    }]}]}}
    original = copy.deepcopy(base)
    elite = copy.deepcopy(base)
    items = elite["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    for item, iid, enchant in zip(items, [11, 21, 31], [101, None, None]):
        item["id"] = iid
        if enchant is not None:
            item["enchant"] = enchant
    previous = copy.deepcopy(elite)
    calls = []

    class Deterministic:
        def randint(self, lo, hi):
            assert lo == 1 and hi == 3
            return 1
        def randrange(self, n):
            assert n == 3
            return 1
        def choice(self, options):
            return options[-1]

    def validate(ids, enchants):
        calls.append((list(ids), list(enchants)))
        assert ids == [11, 22, 31]
        assert enchants == [101, 202, None]

    def swap(reference, ids):
        result = copy.deepcopy(reference)
        for item, iid in zip(
            result["raid"]["parties"][0]["players"][0]["equipment"]["items"], ids
        ):
            item["id"] = iid
        return result

    source = SimpleNamespace(_swap=swap, preflight=lambda *a: True,
                             RejectedGear=ValueError)
    candidate = gate._cold_gear(
        base, SimpleNamespace(validate=validate), source, Deterministic(),
        pool={0: [11], 1: [21, 22], 2: [31]},
        enchant_pools={0: [None, 101], 1: [None, 202], 2: [None]},
        elite=elite)
    actual = candidate["raid"]["parties"][0]["players"][0]
    assert [i["id"] for i in actual["equipment"]["items"]] == [11, 22, 31]
    assert actual["equipment"]["items"][0]["enchant"] == 101
    assert actual["equipment"]["items"][1]["enchant"] == 202
    assert actual["talentsString"] == "fixed"
    assert actual["rotation"] == {"priorityList": []}
    assert calls == [([11, 22, 31], [101, 202, None])]
    assert base == original and elite == previous


def test_paid_p74_gear_rejects_elite_with_changed_fixed_dimension():
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}]},
        "talentsString": "saved",
        "rotation": {"priorityList": []},
    }]}]}}
    source = SimpleNamespace(RejectedGear=ValueError)
    for axis, altered in (("talentsString", "not-saved"),
                          ("rotation", {"priorityList": [4]})):
        elite = copy.deepcopy(base)
        elite["raid"]["parties"][0]["players"][0][axis] = altered
        try:
            gate._cold_gear(
                base, SimpleNamespace(), source, random.Random(1),
                pool={0: [10]}, elite=elite)
        except ValueError as exc:
            assert str(exc) == "P74_PAID_ELITE_CHANGED_FIXED_AXES"
        else:
            raise AssertionError("altered fixed axis admitted as a paid elite")

 
def test_source_ranked_p74_samples_high_stat_sources_without_truncating_pool():
    """Actual complete sorted candidate pool stays reachable, unlike top-N."""
    source_items = list(range(1000))  # ascending ids stand for source rank
    rng = random.Random(20261102)
    ranked = [gate._source_ranked_item_choice(
        source_items, rng, ranked=True) for _ in range(6000)]
    assert sum(item < 32 for item in ranked) > 5300
    assert any(item >= 900 for item in ranked), "Tail items remain reachable"
    assert len(source_items) == 1000


def test_source_ranked_p74_uniform_cold_path_still_reaches_non_elite_items():
    source_items = list(range(1000))
    rng = random.Random(20261102)
    uniform = [gate._source_ranked_item_choice(
        source_items, rng, ranked=False) for _ in range(1500)]
    assert any(item >= 900 for item in uniform)
    assert sum(item < 32 for item in uniform) < 120
    assert len(source_items) == 1000


def test_source_ranked_p74_gear_proposal_is_independent_of_saved_loadout():
    """Rank bias is source-driven, not reference-seeded or a forced config."""
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 999}]},
        "talentsString": "fixed",
        "rotation": {"priorityList": []},
    }]}]}}
    original = copy.deepcopy(base)
    checked = []
    validator = SimpleNamespace(validate=lambda ids, enchants=None:
                                checked.append(list(ids)))
    source = SimpleNamespace(
        _swap=lambda req, ids: {"raid": {"parties": [{"players": [{
            **copy.deepcopy(req["raid"]["parties"][0]["players"][0]),
            "equipment": {"items": [{"id": ids[0]}]},
        }]}]}},
        RejectedGear=ValueError,
    )
    candidate = gate._cold_gear(
        base, validator, source, random.Random(17),
        pool={0: list(range(1, 501))}, source_ranked=True)
    assert checked and checked[0][0] in range(1, 501)
    assert candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"] != 999
    assert base == original


def test_paid_p74_enchant_only_neighbor_preserves_all_paid_gear():
    """An enchant can be optimized independently of gear item swaps."""
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}, {"id": 20}, {"id": 30}]},
        "talentsString": "fixed",
        "rotation": {"priorityList": []},
    }]}]}}
    elite = copy.deepcopy(base)
    for item, iid in zip(
            elite["raid"]["parties"][0]["players"][0]["equipment"]["items"],
            [11, 21, 31]):
        item["id"] = iid
    before = copy.deepcopy(elite)
    calls = []
    def validate(ids, enchants):
        calls.append((list(ids), list(enchants)))
        assert ids == [11, 21, 31]
        assert enchants == [None, 202, None]
    def swap(reference, ids):
        req = copy.deepcopy(reference)
        for item, iid in zip(
                req["raid"]["parties"][0]["players"][0]["equipment"]["items"],
                ids):
            item["id"] = iid
        return req
    class Choice:
        def randrange(self, count):
            assert count == 3
            return 1
        def choice(self, choices):
            return choices[-1]
    source = SimpleNamespace(
        _swap=swap, preflight=lambda *a: True, RejectedGear=ValueError)
    candidate = gate._cold_gear(
        base, SimpleNamespace(validate=validate), source, Choice(),
        pool={0: [11], 1: [21], 2: [31]},
        enchant_pools={0: [None], 1: [None, 202], 2: [None]},
        elite=elite, neighbor_mode="enchant")
    player = candidate["raid"]["parties"][0]["players"][0]
    assert [i["id"] for i in player["equipment"]["items"]] == [11, 21, 31]
    assert [i.get("enchant") for i in player["equipment"]["items"]] == [None, 202, None]
    assert player["talentsString"] == "fixed"
    assert player["rotation"] == {"priorityList": []}
    assert len(calls) == 1
    assert elite == before


def test_paid_p74_single_slot_neighbor_preserves_other_paid_slots():
    """Source-legal coordinate descent does not alter other paid gear."""
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}, {"id": 20}, {"id": 30}]},
        "talentsString": "fixed",
        "rotation": {"priorityList": []},
    }]}]}}
    elite = copy.deepcopy(base)
    for item, iid in zip(
            elite["raid"]["parties"][0]["players"][0]["equipment"]["items"],
            [11, 21, 31]):
        item["id"] = iid
    old = copy.deepcopy(elite)
    def swap(reference, ids):
        req = copy.deepcopy(reference)
        for item, iid in zip(
                req["raid"]["parties"][0]["players"][0]["equipment"]["items"],
                ids):
            item["id"] = iid
        return req
    class Choice:
        def randrange(self, count):
            assert count == 3
            return 2
        def choice(self, choices):
            return choices[-1]
    checked = []
    source = SimpleNamespace(
        _swap=swap, preflight=lambda *a: True, RejectedGear=ValueError)
    candidate = gate._cold_gear(
        base, SimpleNamespace(validate=lambda ids, enchants:
                              checked.append((list(ids), list(enchants)))),
        source, Choice(), pool={0: [11], 1: [21], 2: [31, 32]},
        enchant_pools={0: [None], 1: [None], 2: [None]},
        elite=elite, neighbor_mode="single")
    player = candidate["raid"]["parties"][0]["players"][0]
    assert [i["id"] for i in player["equipment"]["items"]] == [11, 21, 32]
    assert checked == [([11, 21, 32], [None, None, None])]
    assert player["talentsString"] == "fixed"
    assert player["rotation"] == {"priorityList": []}
    assert elite == old


def test_paid_p74_enchant_only_skips_immutable_slots_even_with_adversarial_rng():
    """Old code retried the first immutable slot 60 times and raised, despite
    a legal alternative in another paid slot. No simulated DPS is asserted."""
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}, {"id": 20}, {"id": 30}]},
        "talentsString": "fixed", "rotation": {"priorityList": []},
    }]}]}}
    elite = copy.deepcopy(base)
    paid_items = elite["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    for item, item_id in zip(paid_items, [11, 21, 31]):
        item["id"] = item_id
    checked = []
    class AlwaysFirstSlot:
        def randrange(self, length):
            return 0  # Pre-fix this always chose immutable slot zero.
        def choice(self, choices):
            return choices[-1]

    def validate(ids, enchants):
        checked.append((ids[:], enchants[:]))
        assert ids == [11, 21, 31]
        assert enchants == [None, 202, None]

    def swap(request, ids):
        result = copy.deepcopy(request)
        items = result["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        for item, item_id in zip(items, ids):
            item["id"] = item_id
        return result

    source = SimpleNamespace(_swap=swap, preflight=lambda *a: True,
                             RejectedGear=ValueError)
    result = gate._cold_gear(
        base, SimpleNamespace(validate=validate), source, AlwaysFirstSlot(),
        pool={0: [11], 1: [21], 2: [31]},
        enchant_pools={0: [None], 1: [None, 202], 2: [None]},
        elite=elite, neighbor_mode="enchant")
    actual = result["raid"]["parties"][0]["players"][0]
    assert [i.get("enchant") for i in actual["equipment"]["items"]] == (
        [None, 202, None])
    assert checked == [([11, 21, 31], [None, 202, None])]
    assert "enchant" not in paid_items[1]  # The paid parent is immutable.


def test_paid_p74_enchant_neighbor_has_no_alternative_fails_explicitly():
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}]},
        "talentsString": "fixed", "rotation": {"priorityList": []},
    }]}]}}
    elite = copy.deepcopy(base)
    elite["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"] = 11
    source = SimpleNamespace(RejectedGear=ValueError)
    try:
        gate._cold_gear(
            base, SimpleNamespace(), source, random.Random(1),
            pool={0: [11]}, enchant_pools={0: [None]},
            elite=elite, neighbor_mode="enchant")
    except ValueError as error:
        assert str(error) == "P74_NO_SOURCE_ENCHANT_ALTERNATIVE"
    else:
        raise AssertionError("An immutable paid enchant slot was treated as a proposal")


def test_paid_p74_single_slot_skips_immutable_slots_even_with_adversarial_rng():
    """Before the fix, repeated slot-zero choices exhausted 60 attempts although
    a distinct source-legal paid candidate existed in slot two."""
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}, {"id": 20}, {"id": 30}]},
        "talentsString": "fixed", "rotation": {"priorityList": []},
    }]}]}}
    elite = copy.deepcopy(base)
    paid_items = elite["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    for item, iid in zip(paid_items, [11, 21, 31]):
        item["id"] = iid
    untouched = copy.deepcopy(elite)
    class AlwaysFirstSlot:
        def randrange(self, length):
            return 0  # Old implementation always chose immutable slot zero.
        def choice(self, options):
            return options[-1]

    checked = []
    def validate(ids, enchants):
        checked.append((ids[:], enchants[:]))
        assert ids == [11, 21, 32]
        assert enchants == [None, None, None]

    def swap(request, ids):
        candidate = copy.deepcopy(request)
        items = candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        for item, iid in zip(items, ids):
            item["id"] = iid
        return candidate

    source = SimpleNamespace(_swap=swap, preflight=lambda *a: True,
                             RejectedGear=ValueError)
    result = gate._cold_gear(
        base, SimpleNamespace(validate=validate), source, AlwaysFirstSlot(),
        pool={0: [11], 1: [21], 2: [31, 32]},
        enchant_pools={0: [None], 1: [None], 2: [None]},
        elite=elite, neighbor_mode="single")
    assert [x["id"] for x in
            result["raid"]["parties"][0]["players"][0]["equipment"]["items"]] == (
        [11, 21, 32])
    assert checked == [([11, 21, 32], [None, None, None])]
    assert elite == untouched


def test_paid_p74_single_slot_can_change_only_an_enchant():
    """Source-legal enchant changes remain possible when every item ID is fixed."""
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}, {"id": 20}]},
        "talentsString": "fixed", "rotation": {"priorityList": []},
    }]}]}}
    elite = copy.deepcopy(base)
    paid_items = elite["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    paid_items[0]["id"] = 11
    paid_items[1]["id"] = 21
    checked = []
    def swap(request, ids):
        candidate = copy.deepcopy(request)
        for item, iid in zip(
                candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"], ids):
            item["id"] = iid
        return candidate
    source = SimpleNamespace(_swap=swap, preflight=lambda *a: True,
                             RejectedGear=ValueError)
    class First:
        def choice(self, values):
            return values[0]
    def validate(ids, enchants):
        checked.append((ids[:], enchants[:]))
        assert ids == [11, 21]
        assert enchants == [None, 202]
    result = gate._cold_gear(
        base, SimpleNamespace(validate=validate), source, First(),
        pool={0: [11], 1: [21]},
        enchant_pools={0: [None], 1: [None, 202]},
        elite=elite, neighbor_mode="single")
    assert [x.get("enchant") for x in
            result["raid"]["parties"][0]["players"][0]["equipment"]["items"]] == (
        [None, 202])
    assert checked == [([11, 21], [None, 202])]


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


def test_p74_balanced_finalist_uses_paid_native_and_2d_with_independent_seeds(
        monkeypatch, tmp_path):
    """The second screen is real balanced native+2D payment, not a holdout."""
    import json

    request = {"simOptions": {"randomSeed": "original"},
               "raid": {"parties": [{"players": [{"equipment": {"items": []}}]}]}}
    original = copy.deepcopy(request)
    observed = []

    def native(binary, path, iterations, *, rng_mode):
        observed.append(("native", json.loads(path.read_text())["simOptions"]["randomSeed"],
                         iterations, rng_mode))
        return {"native_dps": 700}

    def world(binary, path, distance, iterations, *, rng_mode):
        seed = json.loads(path.read_text())["simOptions"]["randomSeed"]
        observed.append(("world", seed, iterations, rng_mode))
        return {"native_dps": {"321": 700.0, "654": 740.0}[seed],
                "world_mean_dps": {"321": 700.0, "654": 740.0}[seed],
                "iterations_done": 3, "native_damage_events": 1,
                "native_world_ticks": 2}

    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda native, world, n, **kwargs: None)
    producer = SimpleNamespace(native_source_control=native, run=world)
    score, live = gate._paid_p74_balanced_finalist(
        producer, tmp_path / "binary", request, 15, seeds=("321", "654"))
    assert score == 720.0
    assert live["world_mean_dps"] == 740.0
    assert observed == [
        ("native", "321", 3, "balanced"), ("world", "321", 3, "balanced"),
        ("native", "654", 3, "balanced"), ("world", "654", 3, "balanced")]
    assert request == original


def test_p74_freeze_prefers_independently_confirmed_balanced_winner():
    """A single lucky three-fight result cannot override confirmed scores."""
    noisy = {"gear": "three-fight-outlier"}
    steady = {"gear": "paid-stable-winner"}
    third = {"gear": "paid-third"}
    best = (760.0, {"label": "noisy-screen"}, "noisy", noisy)
    reranked = [
        (690.0, {"label": "noisy-rerank"}, "noisy", noisy, 760.0),
        (742.0, {"label": "steady-rerank"}, "steady", steady, 755.0),
        (735.0, {"label": "third-rerank"}, "third", third, 740.0),
    ]
    assert gate._freeze_paid_p74_balanced_winner(best, [], set()) == (
        760.0, {"label": "noisy-screen"}, "noisy", noisy,
        760.0, "best_balanced_live_screen")
    winner = gate._freeze_paid_p74_balanced_winner(best, reranked, set())
    assert winner[2:5] == ("steady", steady, 755.0)
    assert winner[5] == "paid_2x3_balanced_native_world_finalist"
    # Select only on comparable confirmed measurements when available.
    confirmed = gate._freeze_paid_p74_balanced_winner(
        best, reranked, {"third"})
    assert confirmed[2] == "third"
    assert confirmed[5] == "paid_4x3_balanced_native_world_confirmed"


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
