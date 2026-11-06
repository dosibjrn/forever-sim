"""P7.5 source-legal cold joint fixed-value mutation, not a fake PASS."""
import copy
import inspect
import random
from types import SimpleNamespace

from tools import wf_gate_p7_5_live as gate


def _base():
    return {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}, {"id": 20}]},
        "talentsString": "reference",
        "rotation": {"priorityList": [1, 2, 3]},
    }]}]}}


def test_cold_joint_changes_all_three_dimensions_and_does_not_seed_winner():
    original = _base()
    prior = copy.deepcopy(original)
    def player(obj):
        return obj["raid"]["parties"][0]["players"][0]
    def create(reference, pools, rng, item_names=None):
        q = copy.deepcopy(reference)
        p = player(q)
        p["equipment"]["items"] = [{"id": 11}, {"id": 21}]
        p["talentsString"] = "new-legal-source"
        p["rotation"]["priorityList"] = [3, 2, 1]
        return q
    v = SimpleNamespace(engine={11: {"name": "One"}, 21: {"name": "Two"}},
                        validate=lambda *args: (_ for _ in ()).throw(
                            AssertionError("duplicate Python gear veto executed")))
    source = SimpleNamespace(make_candidate=create, player=player,
                             RejectedGear=ValueError)
    candidate = gate._cold_joint(original, source, v, {}, random.Random(1))
    assert player(candidate)["talentsString"] != player(original)["talentsString"]
    assert player(candidate)["rotation"] != player(original)["rotation"]
    assert player(candidate)["equipment"] != player(original)["equipment"]
    assert original == prior


def test_source_joint_keeps_same_name_distinct_ids_for_real_legality_check(
        monkeypatch):
    """RED before fix: name equality alone rejected source-admissible pairs.

    The actual joint generator must leave recorded uniqueness/limit-category
    legality to GearValidator.validate, not invent a display-name rule.
    """
    import importlib
    from pathlib import Path

    monkeypatch.syspath_prepend(str(
        Path(__file__).resolve().parents[2] / "integrations/mythicsim-rust"))
    source = importlib.import_module("p75_joint_search")
    base = _base()
    player = source.player(base)
    player["equipment"]["items"] = [{"id": 100 + i} for i in range(16)]
    pools = {i: [100 + i] for i in range(16)}
    names = {100 + i: f"distinct-{i}" for i in range(16)}
    names[110] = names[111] = "same-display-name-not-same-id"
    monkeypatch.setattr(source, "random_build", lambda rng: "legal-ranks")
    # The joint candidate generator must not import or call Python talent
    # legality: the selected Rust prepare/sim gate owns the outcome.
    assert not hasattr(source, "validate")
    monkeypatch.setattr(source, "encode", lambda ranks: "legal")
    monkeypatch.setattr(source, "mutate_apl", lambda *args, **kwargs: [1, 2, 3])

    candidate = source.make_candidate(
        base, pools, random.Random(3), item_names=names)
    items = source.player(candidate)["equipment"]["items"]
    assert [items[10]["id"], items[11]["id"]] == [110, 111]
    assert [items[12]["id"], items[13]["id"]] == [112, 113]
    assert source.player(base)["talentsString"] == "reference"


def test_unrelated_checkpoint_does_not_use_balance_ref(tmp_path):
    report = gate.run_live(tmp_path, "warrior", 40, spec="arms")
    assert report["status"] == "BLOCKED"
    assert "P7_5_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT" in report["reasons"]


def test_real_p75_provider_rejects_equal_dps_with_wrong_world_duration(monkeypatch, tmp_path):
    """Negative control: a plausible DPS score cannot bypass causal parity."""
    from pathlib import Path
    import json
    from tools import wf_gate_p7_5_live as p75

    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("focused test uses injected production interface")
    for relative in ("data/items.jsonl", "data/enchants.jsonl"):
        path = tmp_path / "upstream" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text("")
    original = _base()
    original["raid"]["parties"][0]["players"][0]["distanceFromTarget"] = 15
    monkeypatch.setattr(p75, "_pinned_source_runtime",
                        lambda *args: (original, {"reference_dps": 728.19}, binary))

    class Validator:
        engine = {11: {"name": "one"}, 21: {"name": "two"}}
        # This parity-negative-control fixture supplies a source validator
        # seam; the real LFS/SQLite check is independently tested above.
        @staticmethod
        def require_sqlite_catalogue(path):
            assert path == catalogue
        def __init__(self, *args): pass
        def validate(self, ids, enchants): assert ids == [11, 21]
        def close(self): pass

    def player(q):
        return q["raid"]["parties"][0]["players"][0]

    def cold(reference, pools, rng, item_names=None):
        candidate = copy.deepcopy(reference)
        p = player(candidate)
        p["equipment"]["items"] = [{"id": 11}, {"id": 21}]
        p["talentsString"] = "source-legal-cold"
        p["rotation"]["priorityList"] = [3, 2, 1]
        return candidate

    source = SimpleNamespace(
        GearValidator=Validator,
        candidate_pool=lambda validator, limit, **kwargs: ({0: [11], 1: [21]}, {}),
        make_candidate=cold, player=player, RejectedGear=ValueError)
    production = SimpleNamespace(
        native_source_control=lambda binary, path, n, *, rng_mode: {
            "iterations": n, "first_duration_s": 120.0, "native_dps": 730.0},
        run=lambda binary, path, distance, iterations, *, rng_mode: {
            "iterations_done": iterations,
            "per_iteration": [
                {"iteration_index": i, "duration_s": 119.0,
                 "world_dps": 730.0, "world_applied_damage": 730.0 * 119.0}
                for i in range(iterations)],
            "sampled_duration_s": 119.0,
            "native_dps": 730.0, "world_mean_dps": 730.0,
            "native_damage_events": 10, "native_world_ticks": 20})
    monkeypatch.setattr(p75, "_source_module",
                        lambda path, name: source if "joint_search" in str(path)
                        else production)
    report = p75.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "FAIL"
    assert report["reasons"] == [
        "P7_5_NO_SOURCE_LEGAL_JOINT_CANDIDATE_REACHED_NATIVE_WORLD"]
    assert any("P7_5_P7_1_NATIVE_WORLD_FIRST_DURATION_DIVERGED" in reason
               for reason in report["cold_candidate_failures"])
    assert "joint_cold_world_dps" not in report


def test_shared_source_preflight_uses_exact_p7_gate_reason(tmp_path):
    from tools.wf_gate_p7_2_live import _pinned_source_runtime
    for gate_name in ("P7.2", "P7.3", "P7.4", "P7.5"):
        report = _pinned_source_runtime(
            tmp_path, "priest", 60, "holy", gate_name)
        assert report["status"] == "BLOCKED"
        assert report["reasons"] == [
            gate_name.replace(".", "_") +
            "_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT"]


def test_full_p75_freezes_executed_joint_winner_and_keeps_prior_fail_closed(
        monkeypatch, tmp_path):
    """Injected producer routing; this is NOT a real 300s or P7.5 PASS."""
    import hashlib
    import json
    from pathlib import Path

    original = _base()
    original["raid"]["parties"][0]["players"][0]["distanceFromTarget"] = 15
    unchanged = copy.deepcopy(original)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("producer stub, never invoked")
    upstream = binary.parents[2]
    (upstream / "data").mkdir()
    (upstream / "data/items.jsonl").write_text("")
    (upstream / "data/enchants.jsonl").write_text("")
    catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text("validator injected")
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    clock = iter([0.0, 0.0, 300.0, 300.0])
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(clock, 300.0))
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *a: (original, {"reference_dps": 728.19}, binary))
    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda *a, **kw: None)

    class Validator:
        engine = {11: {"name": "one"}, 21: {"name": "two"}}
        @staticmethod
        def require_sqlite_catalogue(path):
            assert path == catalogue
        def __init__(self, *args):
            assert args[-1] is original
        def validate(self, ids, enchants):
            assert ids == [11, 21]
        def close(self): pass

    pool_calls = []
    def pool(v, limit, **kwargs):
        pool_calls.append(limit)
        return ({0: [11], 1: [21]}, {})

    def player(q):
        return q["raid"]["parties"][0]["players"][0]

    def make_candidate(base, pools, rng, item_names=None, enchant_pools=None):
        q = copy.deepcopy(base)
        p = player(q)
        p["equipment"]["items"] = [{"id": 11}, {"id": 21}]
        p["talentsString"] = "new-source-legal"
        p["rotation"]["priorityList"] = [3, 2, 1]
        return q

    source = SimpleNamespace(
        GearValidator=Validator, candidate_pool=pool,
        source_enchant_pools=lambda validator, pools: {0: [None, 123], 1: [None]},
        make_candidate=make_candidate,
        player=player, RejectedGear=ValueError)
    calls = []
    def native(binary, path, n, *, rng_mode):
        calls.append(("native", n, rng_mode, path.read_text()))
        return {"native_dps": 730.0}
    def world(binary, path, distance, iterations, *, rng_mode):
        assert distance == 15
        calls.append(("world", iterations, rng_mode, path.read_text()))
        return {"world_mean_dps": 729.0, "iterations_done": iterations,
                "native_damage_events": 20, "native_world_ticks": 30}
    producer = SimpleNamespace(native_source_control=native, run=world)
    monkeypatch.setattr(
        gate, "_source_module",
        lambda path, name: source if "joint_search" in str(path) else producer)

    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert pool_calls == [None]
    assert [(a, b, c) for a, b, c, _ in calls] == [
        ("native", 3, "balanced"), ("world", 3, "balanced"),
        ("native", 1000, "stochastic"), ("world", 1000, "stochastic")]
    assert json.loads(calls[0][3]) == json.loads(calls[-1][3])
    assert report["frozen_request_raw_sha256"] == hashlib.sha256(
        calls[-1][3].encode()).hexdigest()
    assert report["independent_300s_search_completed"] is True
    assert report["cold_unique_source_requests"] == 1
    assert report["source_legal_joint_candidates_paid"] == 1
    assert report["frozen_stochastic_iterations"] == 1000
    assert report["frozen_stochastic_external_only_floor_met"] is True
    assert report["final_required_dps"] == 0.93 * 728.19
    # The absence of an optional compatible prior cannot block an otherwise
    # complete real 300s search and frozen 1000-fight native/world result.
    assert report["strongest_accepted_compatible_prior_dps"] is None
    assert report["status"] == "PASS"  # injected transport; not real M1 evidence
    assert report["reasons"] == []
    assert report["runtime_proof"]["executed"] is True
    assert original == unchanged

    # Same full production gate route with the strongest accepted, compatible
    # stochastic final supplied by the real M1 receipt resolver. This unit
    # seam tests gate routing, not a 300-second/native acceptance result.
    monkeypatch.setattr(gate, "strongest_accepted_prior",
                        lambda *args, **kwargs: {
                            "dps": 725.0,
                            "compatible_gates": ["P7.4"],
                            "run_urls": ["https://github.com/example/actions/runs/1"]})
    clock = iter([0.0, 0.0, 300.0, 300.0])
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(clock, 300.0))
    accepted = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert accepted["status"] == "PASS"
    assert accepted["reasons"] == []
    assert accepted["final_required_dps"] == 0.93 * 728.19
    assert accepted["strongest_accepted_compatible_prior_dps"] == 725.0
    assert accepted["runtime_proof"]["executed"] is True

    # An accepted stronger prior raises the P7.5 holdout floor; the same
    # frozen 729-DPS result must now fail, not use the external-only limit.
    monkeypatch.setattr(gate, "strongest_accepted_prior",
                        lambda *args, **kwargs: {
                            "dps": 800.0,
                            "compatible_gates": ["P7.4"],
                            "run_urls": ["https://github.com/example/actions/runs/1"]})
    clock = iter([0.0, 0.0, 300.0, 300.0])
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(clock, 300.0))
    rejected = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert rejected["status"] == "FAIL"
    assert "P7_5_FROZEN_STOCHASTIC_DPS_BELOW_ACCEPTED_PRIOR_FLOOR" in rejected["reasons"]
    assert rejected["final_required_dps"] == 744.0
    assert "runtime_proof" not in rejected
    assert original == unchanged

    # The bounded light recorder must resolve the same accepted comparator,
    # but it cannot claim a final stochastic result or P7.5 acceptance.
    monkeypatch.delenv("FOREVER_P7_FULL_SOURCE_SEARCH", raising=False)
    pool_calls.clear()
    calls.clear()
    prior_calls = []
    def light_prior(*args, **kwargs):
        prior_calls.append((args, kwargs))
        return {"dps": 750.0, "compatible_gates": ["P7.4"],
                "run_urls": ["https://github.com/example/actions/runs/1"]}
    monkeypatch.setattr(gate, "strongest_accepted_prior", light_prior)
    clock = iter([0.0, 1.0])
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(clock, 1.0))

    light = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert pool_calls == [15]
    assert len(prior_calls) == 1
    assert [(a, b, c) for a, b, c, _ in calls] == [
        ("native", 3, "balanced"), ("world", 3, "balanced")]
    assert light["joint_cold_world_dps"] == 729.0
    assert light["final_required_dps"] == 697.5
    assert light["strongest_accepted_compatible_prior_dps"] == 750.0
    assert light["status"] == "BLOCKED"
    assert light["reasons"] == [
        "P7_5_FULL_300S_COLD_SEARCH_AND_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED",
        "P7_5_1000_STOCHASTIC_HOLDOUT_NOT_VERIFIED",
    ]
    assert "frozen_stochastic_iterations" not in light
    from tools.wf_gate_coverage import measured_p7_dps_proximity
    assert measured_p7_dps_proximity("P7.5", light) is None
    assert original == unchanged


def test_p75_rejects_invalid_full_search_mode_before_source_work(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "anything")
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *a: ({}, {"reference_dps": 728.19}, tmp_path / "binary"))
    assert gate.run_live(tmp_path, "druid", 60, spec="balance") == {
        "status": "BLOCKED", "reasons": ["P7_5_INVALID_FULL_SOURCE_SEARCH_MODE"]}


def test_joint_cold_admits_independently_rediscovered_reference_axes():
    """RED on old provider: matching even one reference axis was discarded.

    These are source-generated cold builds; equality is not a saved-build seed.
    The real catalogue/native legality remains a separate paid production check.
    """
    original = _base()
    player = lambda q: q["raid"]["parties"][0]["players"][0]
    for unchanged_axis in ("gear", "talents", "rotation", "all"):
        candidate = copy.deepcopy(original)
        p = player(candidate)
        if unchanged_axis != "gear" and unchanged_axis != "all":
            p["equipment"]["items"] = [{"id": 11}, {"id": 21}]
        if unchanged_axis != "talents" and unchanged_axis != "all":
            p["talentsString"] = "independently-found-legal"
        if unchanged_axis != "rotation" and unchanged_axis != "all":
            p["rotation"]["priorityList"] = [3, 1, 2]
        def generate(reference, pools, rng, elite=None, item_names=None):
            assert elite is None  # never seed candidate with a paid prior winner
            assert reference == original
            return copy.deepcopy(candidate)
        validator = SimpleNamespace(
            validate=lambda *args: (_ for _ in ()).throw(
                AssertionError("native candidate pre-veto must not execute")))
        source = SimpleNamespace(make_candidate=generate, player=player,
                                 RejectedGear=ValueError)
        selected = gate._cold_joint(original, source, validator, {}, random.Random(4))
        assert selected == candidate, unchanged_axis
    assert original == _base()


def test_full_p75_mutates_its_own_paid_winner_without_reference_warm_start(
        monkeypatch, tmp_path):
    """Routing RED on old production: every proposal used elite=None.

    This tests the real provider/candidate routing with injected Rust/world
    interfaces; it is not a native execution or a 300-second gate result.
    """
    import json

    base = _base()
    player = lambda q: q["raid"]["parties"][0]["players"][0]
    player(base)["distanceFromTarget"] = 15
    original = copy.deepcopy(base)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("mock producer: never executed")
    upstream = binary.parents[2]
    (upstream / "data").mkdir()
    (upstream / "data/items.jsonl").write_text("")
    (upstream / "data/enchants.jsonl").write_text("")
    catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text("injected validator")
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    # Two paid proposals, then the genuine 300s wall-window observation.
    # The removed final-step timestamp is not an additional clock read.
    clock = iter([0., 0., 0.1, 300., 300.])
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(clock, 300.))
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *a: (base, {"reference_dps": 728.19}, binary))
    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda *a, **kw: None)

    class Validator:
        engine = {10: {"name": "head"}, 20: {"name": "neck"}}
        @staticmethod
        def require_sqlite_catalogue(path):
            assert path == catalogue
        def __init__(self, *args): pass
        def validate(self, ids, enchants):
            assert ids == [10, 20]
        def close(self): pass

    seen_elites = []
    def source_candidate(reference, pools, rng, elite=None, item_names=None, enchant_pools=None):
        assert reference is base
        seen_elites.append(None if elite is None else
                           player(elite)["talentsString"])
        q = copy.deepcopy(reference if elite is None else elite)
        player(q)["talentsString"] = (
            "independently-found" if elite is None else "paid-elite-improved")
        return q

    def score(path):
        talents = player(json.loads(path.read_text()))["talentsString"]
        return 735.0 if talents == "paid-elite-improved" else 700.0

    source = SimpleNamespace(
        GearValidator=Validator,
        candidate_pool=lambda validator, limit, **kwargs: ({0: [10], 1: [20]}, {}),
        source_enchant_pools=lambda validator, pools: {0: [None, 123], 1: [None]},
        make_candidate=source_candidate, player=player,
        RejectedGear=ValueError)
    producer = SimpleNamespace(
        native_source_control=lambda binary, path, n, *, rng_mode: {
            "native_dps": score(path)},
        run=lambda binary, path, distance, iterations, *, rng_mode: {
            "world_mean_dps": score(path), "iterations_done": iterations,
            "native_damage_events": 10, "native_world_ticks": 20})
    monkeypatch.setattr(
        gate, "_source_module",
        lambda path, name: source if "joint_search" in str(path) else producer)

    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert seen_elites == [None, "independently-found"]
    assert report["source_legal_joint_candidates_paid"] == 2
    assert report["joint_cold_world_dps"] == 735.0
    assert report["frozen_stochastic_world_dps"] == 735.0
    assert report["frozen_stochastic_iterations"] == 1000
    assert report["status"] == "PASS"  # injected full holdout; no optional prior needed
    assert report["final_required_dps"] == 0.93 * 728.19
    assert report["strongest_accepted_compatible_prior_dps"] is None
    assert base == original



def test_p75_crossover_randomness_does_not_advance_candidate_search_rng(
        monkeypatch, tmp_path):
    """Donor-pool random draws must not perturb later cold candidate proposals."""

    base = _base()
    player = lambda q: q["raid"]["parties"][0]["players"][0]
    player(base)["distanceFromTarget"] = 15
    original = copy.deepcopy(base)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("mock producer: never executed")
    upstream = binary.parents[2]
    (upstream / "data").mkdir()
    (upstream / "data/items.jsonl").write_text("")
    (upstream / "data/enchants.jsonl").write_text("")
    catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text("injected validator")

    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    clock = iter([0.0] + [0.1] * 13 + [300.0] * 3)
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(clock, 300.0))
    monkeypatch.setattr(gate.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *a: (base, {"reference_dps": 728.19}, binary))
    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda *a, **kw: None)

    class Validator:
        @staticmethod
        def require_sqlite_catalogue(path):
            assert path == catalogue
        def __init__(self, *args):
            pass
        def close(self):
            pass

    candidate_rngs = []
    candidate_rng_state_at_crossover = []
    candidate_count = 0

    def make_candidate(reference, pools, rng, elite=None, **kwargs):
        nonlocal candidate_count
        candidate_count += 1
        candidate_rngs.append(rng)
        request = copy.deepcopy(reference if elite is None else elite)
        player(request)["talentsString"] = f"paid-candidate-{candidate_count}"
        if candidate_count == 13:
            candidate_rng_state_at_crossover.append(rng.getstate())
        return request

    source = SimpleNamespace(
        GearValidator=Validator,
        candidate_pool=lambda validator, limit, **kwargs: (
            {i: [100 + i] for i in range(16)}, {}),
        source_enchant_pools=lambda validator, pools: {
            i: [None] for i in range(16)},
        make_candidate=make_candidate,
        player=player,
        RejectedGear=ValueError,
    )
    producer = SimpleNamespace(
        native_source_control=lambda binary, path, n, *, rng_mode: {
            "native_dps": 700.0},
        run=lambda binary, path, distance, iterations, *, rng_mode: {
            "world_mean_dps": 700.0, "iterations_done": iterations,
            "native_damage_events": 10, "native_world_ticks": 20},
    )
    monkeypatch.setattr(
        gate, "_source_module",
        lambda path, name: source if "joint_search" in str(path) else producer)

    crossover_rngs = []

    def consume_operator_randomness(candidate, parent, finalists,
                                    balanced_elites, source, rng):
        crossover_rngs.append(rng)
        for _ in range(20):
            rng.random()
        return False

    monkeypatch.setattr(gate, "_paid_p75_crossover",
                        consume_operator_randomness)

    report = gate.run_live(tmp_path, "druid", 60, spec="balance")

    assert report["source_legal_joint_candidates_paid"] == 13
    assert len(candidate_rngs) == 13
    assert len(crossover_rngs) == 1  # proposal 13 is the paid gear/talent/APL crossover
    assert crossover_rngs[0] is not candidate_rngs[0]
    assert candidate_rngs[-1].getstate() == candidate_rng_state_at_crossover[0]
    assert report["status"] == "PASS"  # injected full holdout; no optional prior needed
    assert report["final_required_dps"] == 0.93 * 728.19
    assert base == original


def test_full_search_sources_enchants_outside_reference_without_invented_rules(monkeypatch):
    """Only existing Rust/source item validation admits enchant alternatives."""
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "integrations/mythicsim-rust"
    sys.path.insert(0, str(path))
    try:
        spec = importlib.util.spec_from_file_location("source_p75_enchants", path / "p75_joint_search.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path))

    class Validator:
        enchants = {101: {}, 102: {}, 103: {}}
        def __init__(self):
            self.calls = []
        def item(self, slot, anchor, effect_id):
            self.calls.append((slot, anchor, effect_id))
            if slot == 0 and effect_id in (101, 103):
                return {}
            if slot != 0 and effect_id == 102:
                return {}
            raise module.RejectedGear("enchant_slot", "excluded by source")

    v = Validator()
    gear_pools = {i: [i + 1000] for i in range(16)}
    selected = module.source_enchant_pools(v, gear_pools)
    assert selected[0] == [None, 101, 103]
    assert all(selected[i] == [None, 102] for i in range(1, 16))
    assert (0, 1000, 103) in v.calls
    assert (1, 1001, 101) in v.calls


def test_paid_p75_gear_apl_crossover_uses_distinct_paid_donors():
    """Gear and APL must come from two different paid candidates."""
    def player(request):
        return request["player"]

    def build(ids, rotation, talents):
        return {"player": {
            "equipment": {"items": [{"id": item} for item in ids]},
            "rotation": {"priorityList": list(rotation)},
            "talentsString": talents,
        }}

    parent = build([1, 2, 3, 4], [11, 12], "paid-parent")
    gear_donor = build([5, 6, 7, 8], [11, 12], "paid-gear")
    apl_donor = build([1, 2, 3, 4], [21, 22], "paid-apl")
    candidate = copy.deepcopy(parent)
    source = SimpleNamespace(player=player)
    snapshot = copy.deepcopy((parent, gear_donor, apl_donor))
    # The composite helper has no Python gear validator parameter. The caller
    # sends the complete request to selected Rust sim --gate before 2D scoring.
    assert "validator" not in inspect.signature(
        gate._paid_p75_gear_apl_crossover).parameters
    changed = gate._paid_p75_gear_apl_crossover(
        candidate, parent, [],
        [(720., "gear-donor-sha", gear_donor),
         (710., "apl-donor-sha", apl_donor)],
        source, random.Random(23))
    assert changed is True
    result = player(candidate)
    parent_items = player(parent)["equipment"]["items"]
    gear_items = player(gear_donor)["equipment"]["items"]
    changed_slots = [i for i, (a, b) in enumerate(zip(
        result["equipment"]["items"], parent_items)) if a != b]
    assert len(changed_slots) >= 2
    assert all(result["equipment"]["items"][i] == gear_items[i]
               for i in changed_slots)
    assert result["rotation"] == player(apl_donor)["rotation"]
    assert result["talentsString"] == player(parent)["talentsString"]
    assert (parent, gear_donor, apl_donor) == snapshot, "paid parents must be immutable"


def test_paid_p75_gear_apl_crossover_refuses_to_reuse_one_donor():
    """A candidate that changes both axes cannot serve as both donors."""
    def player(request):
        return request["player"]

    def build(ids, rotation):
        return {"player": {
            "equipment": {"items": [{"id": item} for item in ids]},
            "rotation": {"priorityList": list(rotation)},
            "talentsString": "paid",
        }}

    parent = build([1, 2, 3, 4], [11, 12])
    only_donor = build([5, 6, 7, 8], [21, 22])
    candidate = copy.deepcopy(parent)
    source = SimpleNamespace(player=player)

    assert not gate._paid_p75_gear_apl_crossover(
        candidate, parent, [], [(700., "single-donor-sha", only_donor)],
        source, random.Random(23))
    assert candidate == parent


def test_paid_p75_gear_apl_crossover_rolls_back_when_distinct_apl_donor_is_missing():
    """A gear-only donor must not leave a half-applied composite."""
    def player(request):
        return request["player"]

    def build(ids):
        return {"player": {
            "equipment": {"items": [{"id": item} for item in ids]},
            "rotation": {"priorityList": [1, 2]},
            "talentsString": "paid",
        }}

    parent = build([1, 2, 3, 4])
    gear_donor = build([5, 6, 7, 8])
    candidate = copy.deepcopy(parent)
    source = SimpleNamespace(player=player)

    assert not gate._paid_p75_gear_apl_crossover(
        candidate, parent, [], [(700., "gear-only-sha", gear_donor)],
        source, random.Random(23))
    assert candidate == parent
