"""Work1: Druid L30 P7.2 uses its own frozen native reference and actor level.

These are Forever transport/refusal regressions, not independent Warcraft
spell, talent or APL legality tests. Only selected Rust judges the candidate.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from tools import wf_gate_p7_2_live as p72
from tools import wf_p7_native_reference as reference


def _l30_request():
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassDruid",
            "level": 30,
            "balanceDruid": {"options": {"classOptions": {}}},
            "talentsString": "0-0-0",
            "equipment": {"items": []},
            "rotation": {"type": "TypeAPL", "priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 5176}}}},
            ]},
        }]}]},
        "encounter": {"targets": [{"level": 30}]},
        "simOptions": {"iterations": 1000, "randomSeed": "42"},
    }


def test_l30_p72_selects_frozen_checked_reference_without_repay(
        monkeypatch, tmp_path):
    frozen = reference._reference_directory(
        tmp_path, "druid", 30, "unrestricted")
    frozen.mkdir(parents=True)
    raw = json.dumps(_l30_request(), sort_keys=True).encode()
    (frozen / "request.json").write_bytes(raw)
    binary = tmp_path / "selected/engine/target/release/forever-engine"
    sha = hashlib.sha256(raw).hexdigest()
    checks = []

    def check(_root, class_key, level, spec):
        checks.append((class_key, level, spec))
        return {"status": "PASS", "saved_reference_dps": 8.357414975823593,
                "source_request_raw_sha256": sha}

    monkeypatch.setattr(reference, "run_generated_p71", check)
    monkeypatch.setattr(reference, "_binary_and_pin",
                        lambda _root: (binary, "41444ee"))
    got = p72._pinned_source_runtime(
        tmp_path, "druid", 30, "unrestricted", "P7.2",
        require_world=False)
    source, meta, selected_binary = got
    assert source == _l30_request()
    assert meta["source_request_raw_sha256"] == sha
    assert meta["selected_engine_revision"] == "41444ee"
    assert meta["reference_dps"] == 8.357414975823593
    assert meta["native_actor_level_context"] == 30
    assert selected_binary == binary
    assert checks == [("druid", 30, "unrestricted")]


def test_l30_p72_refuses_unverified_reference_before_native_score(
        monkeypatch, tmp_path):
    monkeypatch.setattr(
        reference, "run_generated_p71",
        lambda *_args: {"status": "BLOCKED",
                        "reasons": ["P7_1_NATIVE_PREPARE_REFUSED"]})
    got = p72._pinned_source_runtime(
        tmp_path, "druid", 30, "unrestricted", "P7.2",
        require_world=False)
    assert got == {
        "status": "BLOCKED",
        "reasons": ["P7_2_NATIVE_GENERATED_REFERENCE_NOT_VERIFIED",
                    "P7_1_NATIVE_PREPARE_REFUSED"],
        "native_reference_status": "BLOCKED",
    }


def _exercise_paid_axis(monkeypatch, *, refused=False):
    base = _l30_request()
    original = copy.deepcopy(base)
    observed = []

    def mutate(_actions, source_actions, _rng, *, cold):
        # For this authentic one-action source, an additional sourced action
        # is a distinct native APL candidate; legality is decided by Rust.
        return copy.deepcopy(source_actions + source_actions)

    class NativeRefusal(RuntimeError):
        def __init__(self):
            self.code = "apl"
            self.reason = "selected native refused candidate"
            super().__init__(self.reason)

    def pay(_binary, path, iterations, *, rng_mode, actor_level):
        request = json.loads(path.read_text())
        observed.append((request, iterations, rng_mode, actor_level))
        if refused:
            raise NativeRefusal()
        return {"iterations": 3, "native_dps": 8.75}

    scorer = SimpleNamespace(native_source_control=pay,
                             NativeSourceRefusal=NativeRefusal)
    mutator = SimpleNamespace(mutate_apl=mutate)
    monkeypatch.setattr(
        p72, "_pinned_source_runtime",
        lambda *_args, **_kwargs: (
            base, {"reference_dps": 8.357414975823593,
                   "selected_engine_revision": "41444ee",
                   "selected_reference_profile": "unrestricted",
                   "source_request_raw_sha256": "frozen-L30-request"},
            Path("/selected/forever-engine")))
    monkeypatch.setattr(
        p72, "_source_module",
        lambda _path, name: mutator if "mutator" in name else scorer)
    monkeypatch.delenv("FOREVER_P7_FULL_SOURCE_SEARCH", raising=False)
    result = p72.run_live(
        Path("/not-needed"), "druid", 30, spec="unrestricted")
    assert base == original
    assert len(observed) == 1
    candidate, iterations, rng_mode, actor_level = observed[0]
    assert (iterations, rng_mode, actor_level) == (3, "balanced", 30)
    proposed = candidate["raid"]["parties"][0]["players"][0]
    baseline = original["raid"]["parties"][0]["players"][0]
    assert proposed["rotation"]["priorityList"] != baseline["rotation"]["priorityList"]
    assert proposed["equipment"] == baseline["equipment"]
    assert proposed["talentsString"] == baseline["talentsString"]
    assert candidate["encounter"] == original["encounter"]
    assert result["native_source_revision"] == "41444ee"
    return result


def test_l30_p72_pays_distinct_apl_with_explicit_native_actor_level(monkeypatch):
    result = _exercise_paid_axis(monkeypatch)
    assert result["status"] == "PASS"
    assert result["source_legal_cold_candidates_paid"] == 1
    assert result["winner_native_dps"] == 8.75
    assert result["checkpoint_spec"] == "unrestricted"
    assert result["source_fixed_gear_and_talents"] is True


def test_l30_p72_native_refusal_is_not_a_paid_pass(monkeypatch):
    result = _exercise_paid_axis(monkeypatch, refused=True)
    assert result["status"] == "BLOCKED"
    assert result["source_legal_cold_candidates_paid"] == 0
    assert result["native_refusals"][0]["code"] == "apl"
