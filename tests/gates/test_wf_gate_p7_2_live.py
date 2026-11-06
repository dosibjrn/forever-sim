"""P7.2 cold APL mutation contract; no fake gate acceptance or saved-run PASS."""
import copy
import random
from types import SimpleNamespace

import pytest
from tools import wf_gate_p7_2_live as gate


def _request():
    return {
        "raid": {"parties": [{"players": [{
            "equipment": {"items": [{"id": 14}]},
            "talentsString": "source-legal",
            "rotation": {"priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 1}}}},
                {"action": {"castSpell": {"spellId": {"spellId": 2}}}},
                {"action": {"castSpell": {"spellId": {"spellId": 3}}}},
            ]},
        }]}]}
    }


def test_cold_apl_keeps_actual_gear_talents_and_saved_request_unmodified():
    base = _request()
    original = copy.deepcopy(base)
    def mutation(actions, source_actions, rng, cold):
        assert actions is None and cold
        return list(reversed(source_actions))
    result = gate._cold_apl(base, random.Random(3),
                            SimpleNamespace(mutate_apl=mutation))
    assert result != base
    assert base == original
    assert result["raid"]["parties"][0]["players"][0]["equipment"] == (
        base["raid"]["parties"][0]["players"][0]["equipment"])
    assert result["raid"]["parties"][0]["players"][0]["talentsString"] == (
        base["raid"]["parties"][0]["players"][0]["talentsString"])


def test_independently_rediscovered_reference_apl_remains_eligible():
    base = _request()
    candidate = gate._cold_apl(base, random.Random(3),
                               SimpleNamespace(mutate_apl=lambda a, s, r, cold: copy.deepcopy(s)))
    assert candidate == base
    assert candidate is not base


def test_wrong_checkpoint_refuses_before_any_native_run(tmp_path):
    report = gate.run_live(tmp_path, "priest", 60, spec="holy")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_2_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT"]


@pytest.mark.parametrize("legacy_env", ["0", "1", "yes"])
def test_unrestricted_p72_reuses_actual_balance_reference_and_pays_native(
        monkeypatch, tmp_path, legacy_env):
    """Unrestricted Druid L60 can use the authentic Balance build, not a fake baseline."""
    import json
    from pathlib import Path
    from types import SimpleNamespace

    root = Path(__file__).resolve().parents[2]
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"test-executable-placeholder")
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(binary))
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", legacy_env)
    # This stubs checkout identity, not mechanics; native forwarding is the
    # unit under test. A real selected-engine gate run is still required.
    monkeypatch.setattr(gate, "_selected_rust_submodule",
                        lambda *_: "selected-fork-commit")
    prepared = gate._pinned_source_runtime(
        root, "druid", 60, "unrestricted", "P7.2", require_world=False)
    assert isinstance(prepared, tuple)
    original, meta, selected_binary = prepared
    assert selected_binary == binary.resolve()
    assert meta["selected_reference_profile"] == "balance"
    assert original["raid"]["parties"][0]["players"][0]["balanceDruid"]
    # The three single-axis producers and P7.5 joint search all reuse the
    # authentic source build without inventing an unrestricted report.
    p73_reference = gate._pinned_source_runtime(
        root, "druid", 60, "unrestricted", "P7.3",
        require_world=False)
    assert isinstance(p73_reference, tuple)
    assert p73_reference[1]["selected_reference_profile"] == "balance"
    p74_reference = gate._pinned_source_runtime(
        root, "druid", 60, "unrestricted", "P7.4", require_world=False)
    assert isinstance(p74_reference, tuple)
    assert p74_reference[1]["selected_reference_profile"] == "balance"
    p75_reference = gate._pinned_source_runtime(
        root, "druid", 60, "unrestricted", "P7.5", require_world=False)
    assert isinstance(p75_reference, tuple)
    assert p75_reference[1]["selected_reference_profile"] == "balance"

    source_player = original["raid"]["parties"][0]["players"][0]
    changed = [{"action": {"castSpell": {"spellId": {"spellId": 8921}}}}]
    paid = []

    def native_score(_binary, path, iterations, *, rng_mode):
        paid.append(json.loads(path.read_text()))
        assert (_binary, iterations, rng_mode) == (
            selected_binary, 3, "balanced")
        return {"iterations": 3, "native_dps": 720.0}

    mutation = SimpleNamespace(mutate_apl=lambda *a, **kw: changed)
    native = SimpleNamespace(native_source_control=native_score)
    monkeypatch.setattr(gate, "_source_module",
                        lambda _path, name:
                        mutation if "mutator" in name else native)

    report = gate.run_live(root, "druid", 60, spec="unrestricted")
    assert report["status"] == "PASS"  # mocked scorer, not acceptance evidence
    assert report["checkpoint_spec"] == "unrestricted"
    assert report["reference_profile"] == "balance"
    assert report["saved_reference_dps"] == meta["reference_dps"]
    assert report["source_request_raw_sha256"] == gate.SAVED_BALANCE_RAW_SHA
    assert report["native_source_revision"] == "selected-fork-commit"
    assert report["source_legal_cold_candidates_paid"] == 1
    assert report["independent_300s_search_requested"] is False
    assert report["independent_300s_search_completed"] is False
    assert len(paid) == 1
    candidate = paid[0]["raid"]["parties"][0]["players"][0]
    assert candidate["rotation"]["priorityList"] == changed
    assert candidate["talentsString"] == source_player["talentsString"]
    assert candidate["equipment"] == source_player["equipment"]


def test_feral_p72_preserves_authentic_build_and_forwards_native_go_rules(
        monkeypatch, tmp_path):
    """Only the selected native scorer decides changed-APL legality and DPS."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"selected-native-test-placeholder")
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(binary))
    monkeypatch.delenv("FOREVER_P7_FULL_SOURCE_SEARCH", raising=False)
    monkeypatch.setattr(gate, "_selected_rust_submodule",
                        lambda *_: "selected-feral-rust-sha")

    prepared = gate._pinned_source_runtime(
        root, "druid", 60, "feral", "P7.2", require_world=False)
    assert isinstance(prepared, tuple)
    original, meta, _ = prepared
    assert meta["selected_reference_profile"] == "feral"
    assert meta["reference_dps"] == gate.FERAL_REFERENCE_DPS
    assert meta["source_request_raw_sha256"] == gate.SAVED_FERAL_RAW_SHA
    player = original["raid"]["parties"][0]["players"][0]
    assert "feralCatDruid" in player
    assert player["talentsString"] == "050022-55000032021032212051-053"

    seen = []
    def mutate(actions, source_actions, rng, *, cold,
               preserve_source_conditions=False):
        assert preserve_source_conditions is True
        # Reorder complete source entries; do not synthesize Warcraft facts.
        return copy.deepcopy(list(reversed(source_actions)))

    def native(_binary, path, iterations, *, rng_mode, go_rules=False):
        assert (_binary, iterations, rng_mode, go_rules) == (
            binary.resolve(), 3, "balanced", True)
        request = json.loads(path.read_text())
        changed = request["raid"]["parties"][0]["players"][0]
        assert changed["equipment"] == player["equipment"]
        assert changed["talentsString"] == player["talentsString"]
        assert changed["rotation"]["prepullActions"] == player["rotation"]["prepullActions"]
        assert changed["rotation"]["priorityList"] != player["rotation"]["priorityList"]
        seen.append(request)
        return {"iterations": 3, "native_dps": 801.25}

    mutation = SimpleNamespace(mutate_apl=mutate)
    producer = SimpleNamespace(native_source_control=native)
    monkeypatch.setattr(gate, "_source_module",
                        lambda path, name:
                        mutation if "mutator" in name else producer)
    report = gate.run_live(root, "druid", 60, spec="feral")
    assert report["status"] == "PASS"  # mocked transport, not native gate proof
    assert report["source_request_raw_sha256"] == gate.SAVED_FERAL_RAW_SHA
    assert report["native_rules"] == "go_reference"
    assert report["reference_profile"] == "feral"
    assert report["native_source_revision"] == "selected-feral-rust-sha"
    assert report["source_legal_cold_candidates_paid"] == len(seen) == 1
    assert report["winner_native_dps"] == 801.25
    assert report["cold_winner_request"] == seen[0]


def test_feral_p72_native_refusals_remain_blocked_not_paid(monkeypatch, tmp_path):
    """An authoritative Rust refusal cannot become a successful paid score."""
    class NativeSourceRefusal(RuntimeError):
        def __init__(self):
            self.code = "apl"
            self.reason = "selected native refused changed rotation"
            super().__init__(self.reason)

    base = _request()
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *args, **kwargs: (
            base, {"reference_dps": 811.02,
                   "selected_engine_revision": "pinned-feral"},
            tmp_path / "binary"))
    monkeypatch.delenv("FOREVER_P7_FULL_SOURCE_SEARCH", raising=False)
    def mutate(actions, source_actions, rng, *, cold,
               preserve_source_conditions=False):
        assert preserve_source_conditions
        return list(reversed(source_actions))

    def native(*args, **kwargs):
        assert kwargs["go_rules"] is True
        raise NativeSourceRefusal()

    mutation = SimpleNamespace(mutate_apl=mutate)
    producer = SimpleNamespace(native_source_control=native,
                               NativeSourceRefusal=NativeSourceRefusal)
    monkeypatch.setattr(gate, "_source_module",
                        lambda path, name:
                        mutation if "mutator" in name else producer)
    result = gate.run_live(tmp_path, "druid", 60, spec="feral")
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == [
        "P7_2_NATIVE_REFUSED_ALL_DISTINCT_APL_CANDIDATES"]
    assert result["source_legal_cold_candidates_paid"] == 0
    assert result["native_refusals"][0]["code"] == "apl"


def test_p72_cli_keeps_actual_native_mode_refusals_and_paid_build(
        monkeypatch, capsys):
    """The public no-record receipt must retain Feral's native evidence."""
    import json
    from tools import wf_gate as cli

    winner = _request()
    report = {
        "status": "PASS", "reasons": [],
        "production_engine": "pinned_mythicsim_rust_native",
        "native_rules": "go_reference",
        "source_request_raw_sha256": gate.SAVED_FERAL_RAW_SHA,
        "native_source_revision": "selected-rust",
        "source_legal_cold_candidates_paid": 1,
        "winner_native_dps": 800.0,
        "cold_winner_request": winner,
        "cold_winner_apl": winner["raid"]["parties"][0]["players"][0][
            "rotation"]["priorityList"],
        "native_refusals": [{"code": "apl", "reason": "first candidate refused"}],
    }
    monkeypatch.setattr(cli, "_run_live_gate",
                        lambda *args, **kwargs: report)
    assert cli.main(["--class", "druid", "--level", "60", "--spec", "feral",
                     "--gate", "P7.2"]) == 0
    result = json.loads(capsys.readouterr().out)["results"][0]
    assert result["native_rules"] == "go_reference"
    assert result["native_refusals"] == report["native_refusals"]
    assert result["cold_winner_request"] == winner
    assert result["winner_native_dps"] == 800.0
