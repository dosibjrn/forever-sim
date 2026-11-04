"""P7.4 source-legal cold gear mutation contract, never a fake gate PASS."""
import copy
import random
from types import SimpleNamespace
from tools import wf_gate_p7_4_live as gate


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


def test_full_p74_freezes_one_paid_source_gear_winner_for_stochastic_holdout(
        monkeypatch, tmp_path):
    """Producer routing regression; mocked backend is NOT a P7.4 acceptance run."""
    import hashlib
    import json
    from pathlib import Path
    from types import SimpleNamespace

    base = {"raid": {"parties": [{"players": [{
        "class": "ClassDruid",
        "distanceFromTarget": 15,
        "equipment": {"items": [{"id": 10}, {"id": 20}]},
        "talentsString": "fixed-talents",
        "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": 1}}}]},
    }]}]}}
    original = copy.deepcopy(base)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("fake executable; never invoked")
    upstream = binary.parents[2]
    (upstream / "data").mkdir()
    (upstream / "data/items.jsonl").write_text("")
    (upstream / "data/enchants.jsonl").write_text("")
    catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text("fake catalogue; validator injected")

    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    # Routing clock: start, two paid candidates, then 300s observation.
    # No per-final-step timestamp calls are required for gate acceptance.
    monkeypatch.setattr(gate, "_paid_step_has_budget", lambda *a: True)
    clock = iter([0.0, 0.0, 0.0, 300.0, 300.0, 300.0])
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(clock, 300.0))
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *a: (base, {"reference_dps": 728.19}, binary))
    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda *a, **kw: None)

    pool_calls = []
    class Validator:
        @staticmethod
        def require_sqlite_catalogue(path):
            assert path == catalogue

        def __init__(self, *args):
            assert args[-1] is base

        def validate(self, ids, enchants=None):
            assert ids == [11, 21]
            if enchants is not None:
                assert len(enchants) == 2

        def close(self):
            pass

    def candidate_pool(validator, limit, **kwargs):
        pool_calls.append(limit)
        return ({0: [11], 1: [21]}, {})

    def swap(request, ids):
        result = copy.deepcopy(request)
        for slot, iid in zip(
                result["raid"]["parties"][0]["players"][0]["equipment"]["items"],
                ids):
            slot["id"] = iid
        return result

    gear = SimpleNamespace(
        GearValidator=Validator, candidate_pool=candidate_pool, _swap=swap,
        preflight=lambda reference, candidate: True,
        source_enchant_pools=lambda validator, pools: {0: [None, 201], 1: [None]},
        RejectedGear=ValueError)
    # Force two actually paid mock candidates. The first wins, the last
    # candidate loses: reporting the final loop SHA would misidentify it.
    candidates = iter([[11, 21], [12, 21]])
    monkeypatch.setattr(gate, "_cold_gear",
                        lambda request, *args, **kwargs: swap(request, next(candidates)))
    calls = []
    def native(binary, path, n, *, rng_mode):
        calls.append(("native", n, rng_mode, path.read_text()))
        return {"native_dps": 730.0}

    def world(binary, path, distance, iterations, *, rng_mode):
        assert distance == 15
        calls.append(("world", iterations, rng_mode, path.read_text()))
        item_id = json.loads(path.read_text())["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"]
        return {"world_mean_dps": 729.0 if item_id == 11 else 700.0,
                "iterations_done": iterations, "native_damage_events": 12,
                "native_world_ticks": 25}

    producer = SimpleNamespace(native_source_control=native, run=world)
    monkeypatch.setattr(gate, "_source_module",
                        lambda path, name: gear if "p74_gear_search" in str(path)
                        else producer)

    from tools.wf_gate import _run_live_gate
    report = _run_live_gate(tmp_path, "druid", 60, "balance", "P7.4", "")
    assert pool_calls == [None], "Full search must keep all admitted source items"
    assert [(kind, n, mode) for kind, n, mode, _ in calls] == [
        ("native", 3, "balanced"), ("world", 3, "balanced"),
        ("native", 3, "balanced"), ("world", 3, "balanced"),
        ("native", 1000, "stochastic"), ("world", 1000, "stochastic")]
    assert json.loads(calls[0][3]) == json.loads(calls[5][3])
    assert json.loads(calls[0][3]) != json.loads(calls[2][3])
    assert report["frozen_request_raw_sha256"] == hashlib.sha256(
        calls[5][3].encode()).hexdigest()
    assert report["cold_winner_request_sha256"] == hashlib.sha256(
        json.dumps(json.loads(calls[5][3]), sort_keys=True).encode()).hexdigest()
    assert report["cold_unique_source_requests"] == 2
    frozen_items = json.loads(calls[5][3])["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    assert report["cold_winner_gear"] == [
        {"slot": slot, "item_id": item["id"], "enchant_id": item.get("enchant")}
        for slot, item in enumerate(frozen_items)]
    assert report["source_legal_cold_candidates_paid"] == 2
    assert report["winner_selection"] == "best_balanced_live_screen"
    assert report["search_rng_mode"] == "balanced"
    assert report["paid_stochastic_finalists"] == 0
    assert report["stochastic_parent_proposals"] == 0
    # The real chosen winner is NOT the last attempted candidate.
    assert report["cold_winner_request_sha256"] != hashlib.sha256(
        json.dumps(json.loads(calls[2][3]), sort_keys=True).encode()).hexdigest()
    assert report["independent_300s_search_completed"] is True
    assert report["frozen_stochastic_iterations"] == 1000
    assert report["frozen_stochastic_reference_floor_met"] is True
    assert report["status"] == "PASS"  # mocked routing, not real source/native proof
    assert report["runtime_proof"]["executed"] is True
    assert report["runtime_proof"]["source_revision"] == report["frozen_request_raw_sha256"]
    assert report["reasons"] == []
    assert base == original



def test_p74_invalid_full_search_flag_blocks_before_source_work(
        monkeypatch, tmp_path):
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "invalid")
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *a: ({}, {"reference_dps": 728.19}, tmp_path / "binary"))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report == {"status": "BLOCKED",
                      "reasons": ["P7_4_INVALID_FULL_SOURCE_SEARCH_MODE"]}


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

 
def test_p74_source_paid_elite_archive_preserves_native_diversity_and_cold_restart():
    """Only already paid elites, top 15/24; never the saved reference."""
    paid = [(100.0 - i, {"paid_candidate": i}) for i in range(24)]
    class Select:
        def choice(self, options):
            assert len(options) == 15
            assert options[0][1] == {"paid_candidate": 0}
            assert options[-1][1] == {"paid_candidate": 14}
            return options[-1]
    chooser = Select()
    assert gate._paid_gear_elite_choice(paid, chooser, 1) == {"paid_candidate": 14}
    assert gate._paid_gear_elite_choice(paid, chooser, 4) == {"paid_candidate": 14}
    assert gate._paid_gear_elite_choice(paid, chooser, 5) is None
    assert gate._paid_gear_elite_choice([], chooser, 1) is None
    assert len(paid) == 24  # sampling never mutates the measured archive


def test_p74_paid_multiseed_finalists_guide_later_gear_proposals():
    """After paying for independent Balanced scores, exploit their winners.

    The noisy three-fight leader is still in the paid archive, but must not
    monopolize parent selection once stronger paid finalist evidence exists.
    Cold restarts and the original paid archive remain reachable.
    """
    screens = [(900.0, {"paid_candidate": "lucky-three-fight"})]
    finalists = [
        (710.0, {}, "low", {"paid_candidate": "low"}, 900.0),
        (740.0, {}, "best", {"paid_candidate": "best-multiseed"}, 690.0),
        (720.0, {}, "mid", {"paid_candidate": "mid"}, 730.0),
        (700.0, {}, "bottom", {"paid_candidate": "bottom"}, 710.0),
        (705.0, {}, "fifth", {"paid_candidate": "fifth"}, 720.0),
    ]
    class ChooseFirst:
        def choice(self, rows):
            if len(rows) > 1:
                assert len(rows) == 4  # bounded top paid finalists
            return rows[0]

    rng = ChooseFirst()
    assert gate._paid_gear_elite_choice(
        screens, rng, 2, finalists) == {"paid_candidate": "best-multiseed"}
    assert gate._paid_gear_elite_choice(
        screens, rng, 3, finalists) == {"paid_candidate": "lucky-three-fight"}
    assert gate._paid_gear_elite_choice(screens, rng, 5, finalists) is None
    assert gate._paid_gear_elite_choice(
        screens, rng, 2, ()) == {"paid_candidate": "lucky-three-fight"}
    assert finalists[0][2] == "low"  # parent ranking does not mutate receipts


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
        return {"world_mean_dps": {"321": 700.0, "654": 740.0}[seed],
                "iterations_done": 3, "native_damage_events": 1,
                "native_world_ticks": 2}

    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda native, world, n: None)
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


def test_p74_live_reranks_noisy_paid_gear_before_1000_stochastic_holdout(
        monkeypatch, tmp_path):
    """Actual run_live scheduling changes the frozen winner; no M1 recording."""
    import json

    base = {"simOptions": {"randomSeed": "original"},
            "raid": {"parties": [{"players": [{
                "class": "ClassDruid", "distanceFromTarget": 15,
                "equipment": {"items": [{"id": 10}]},
                "talentsString": "fixed",
                "rotation": {"priorityList": []},
            }]}]}}
    original = copy.deepcopy(base)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("fake, never executed")
    (binary.parents[2] / "data").mkdir()
    (binary.parents[2] / "data/items.jsonl").write_text("")
    (binary.parents[2] / "data/enchants.jsonl").write_text("")
    catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text("mock")

    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    # Start, three paid screens, three independent re-screens, confirmation,
    # end of the full 300s window and observed deadline.
    times = iter([0.0, 0.0, 0.0, 0.0, 130.0, 150.0,
                  170.0, 270.0, 300.0, 300.0])
    monkeypatch.setattr(gate.time, "monotonic",
                        lambda: next(times, 300.0))
    monkeypatch.setattr(gate.time, "sleep", lambda s: None)
    monkeypatch.setattr(gate, "_paid_step_has_budget", lambda *args: True)
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *args: (base, {"reference_dps": 728.19}, binary))
    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda *args, **kw: None)

    class Validator:
        @staticmethod
        def require_sqlite_catalogue(path):
            assert path == catalogue

        def __init__(self, *args):
            pass

        def close(self):
            pass

    gear = SimpleNamespace(
        GearValidator=Validator, candidate_pool=lambda *a, **kw: ({0: [11, 12, 13]}, {}),
        source_enchant_pools=lambda *a: {0: [None]},
        RejectedGear=ValueError)
    candidates = iter((11, 12, 13))
    def cold(reference, *args, **kwargs):
        req = copy.deepcopy(reference)
        req["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"] = next(candidates)
        return req
    monkeypatch.setattr(gate, "_cold_gear", cold)

    def item(request):
        return request["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"]

    def native(binary, path, n, *, rng_mode):
        return {"native_dps": 735.0}

    def world(binary, path, distance, iterations, *, rng_mode):
        req = json.loads(path.read_text())
        score = {11: 760.0, 12: 755.0, 13: 740.0}[item(req)]
        return {"world_mean_dps": 740.0 if rng_mode == "stochastic" else score,
                "iterations_done": iterations, "native_damage_events": 2,
                "native_world_ticks": 3}
    production = SimpleNamespace(native_source_control=native, run=world)
    monkeypatch.setattr(
        gate, "_source_module",
        lambda path, name: gear if "p74_gear_search" in str(path) else production)

    paid_reranks = []
    def rerank(production, binary, request, distance, *, seeds=("1955004", "1955047")):
        paid_reranks.append((item(request), seeds))
        scores = {11: 690.0, 12: 742.0, 13: 735.0}
        return (740.0 if seeds[0] == "1955113" else scores[item(request)]), {
            "world_mean_dps": scores[item(request)],
            "native_damage_events": 2, "native_world_ticks": 3}
    monkeypatch.setattr(gate, "_paid_p74_balanced_finalist", rerank)

    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "PASS"  # mocked backend; not real gate evidence
    assert report["winner_screen_dps"] == 755.0
    assert report["winner_selection"] == "paid_4x3_balanced_native_world_confirmed"
    assert report["cold_winner_gear"][0]["item_id"] == 12
    assert report["paid_balanced_finalists"] == 3
    assert report["paid_balanced_confirmed"] == 1
    assert report["frozen_stochastic_iterations"] == 1000
    assert len(paid_reranks) == 4
    assert paid_reranks[-1] == (12, ("1955113", "1955139"))
    assert base == original
