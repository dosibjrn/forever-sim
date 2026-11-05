"""Forever-owned lower-level P7 reference transport tests; no mock PASS is gate credit."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools import wf_p7_native_reference as reference
from tools import wf_gate_p7_1_live as p71


def _request(root: Path, *, level: int = 20):
    source = root / "candidate.json"
    source.write_text(json.dumps({
        "raid": {"parties": [{"players": [
            {"class": "ClassDruid", **({"level": level} if level != 20 else {}),
             "rotation": {"priorityList": []},
             "equipment": {"items": []}, "talentsString": ""}
        ]}]},
        "encounter": {"targets": [{"level": 22, "stats": [{"key": "health", "value": 4000}]}],
                      "duration": 120},
        "simOptions": {"iterations": 50, "randomSeed": 17},
    }))
    return source


def _native_stubs(monkeypatch, *, paid_dps=75., native_level=20):
    revision = "a" * 40
    binary = Path("/selected/pinned/target/release/forever-engine")
    calls = []

    def pay(_binary, path, iterations, *, rng_mode, actor_level):
        assert _binary == binary
        assert rng_mode == "stochastic"
        assert actor_level == 20
        assert iterations == 1000
        assert "level" not in json.loads(path.read_text())["raid"]["parties"][0]["players"][0]
        calls.append(iterations)
        return {"iterations": iterations, "native_dps": paid_dps,
                "native_rules": "forever", "first_duration_s": 120.0}

    monkeypatch.setattr(reference, "_binary_and_pin", lambda root: (binary, revision))
    monkeypatch.setattr(reference, "_prepare_actor",
                        lambda binary, path, level: {
                            "status": "PREPARED", "class": "ClassDruid",
                            "level": native_level})
    monkeypatch.setattr(reference, "_native",
                        lambda root: SimpleNamespace(native_source_control=pay))
    return calls, revision


def test_native_generated_reference_requires_paid_checkpoint_native_score(
        monkeypatch, tmp_path):
    calls, revision = _native_stubs(monkeypatch)
    source = _request(tmp_path)
    generated = reference.produce_reference(
        tmp_path, "druid", 20, "unrestricted", source)
    assert generated["status"] == "REFERENCE_GENERATED"
    assert generated["selected_engine_revision"] == revision
    assert generated["reference_dps"] == 75.
    assert generated["native_actor_level_context"] == 20
    assert generated["reference_configuration_source"] == "native_generated_msim_reference"
    saved = reference._reference_directory(tmp_path, "druid", 20, "unrestricted")
    assert (saved / "request.json").read_bytes() == source.read_bytes()
    receipt = reference.run_generated_p71(tmp_path, "druid", 20, "unrestricted")
    assert receipt["status"] == "PASS"  # mocked transport; NEVER official M1
    assert receipt["checkpoint_spec"] == "unrestricted"
    assert receipt["reference_configuration_source"] == "native_generated_msim_reference"
    assert receipt["source_request_raw_sha256"] == generated["source_request_raw_sha256"]
    assert receipt["runtime_proof"]["engine_revision"] == revision
    # P7.1 reuses the authentic generator's 1,000 paid stochastic fights.
    assert calls == [1000]
    assert receipt["reused_authentic_native_reference_receipt"] is True
    assert receipt["runtime_proof"]["reference_receipt_reused"] is True
    assert generated["reference_native_sample"]["native_dps"] == receipt["native_dps"]
    assert reference.produce_reference(
        tmp_path, "druid", 20, "unrestricted", source)["reasons"] == [
            "P7_1_FROZEN_REFERENCE_ALREADY_EXISTS"]


def test_reference_refuses_l60_copy_or_incompatible_native_actor(
        monkeypatch, tmp_path):
    calls, _ = _native_stubs(monkeypatch)
    source = _request(tmp_path, level=60)
    wrong = reference.produce_reference(
        tmp_path, "druid", 20, "unrestricted", source)
    assert wrong["status"] == "BLOCKED"
    assert wrong["reasons"] == ["P7_1_REQUEST_ACTOR_CHECKPOINT_MISMATCH"]
    assert not calls

    source = _request(tmp_path, level=20)
    monkeypatch.setattr(reference, "_prepare_actor",
                        lambda binary, path, level: {
                            "status": "PREPARED", "class": "ClassDruid", "level": 60})
    mismatch = reference.produce_reference(
        tmp_path, "druid", 20, "unrestricted", source)
    assert mismatch["reasons"] == ["P7_1_NATIVE_PREPARED_ACTOR_LEVEL_MISMATCH"]
    assert not calls


def test_generated_reference_hash_engine_and_floor_fail_closed(
        monkeypatch, tmp_path):
    calls, revision = _native_stubs(monkeypatch)
    source = _request(tmp_path)
    assert reference.produce_reference(
        tmp_path, "druid", 20, "unrestricted", source)["status"] == "REFERENCE_GENERATED"
    monkeypatch.setattr(reference, "_binary_and_pin",
                        lambda root: (Path("/selected/engine"), "b" * 40))
    assert reference.run_generated_p71(
        tmp_path, "druid", 20, "unrestricted")["reasons"] == [
            "P7_1_GENERATED_REFERENCE_ENGINE_CHANGED"]
    new_calls, _ = _native_stubs(monkeypatch, paid_dps=73.5)
    result = reference.run_generated_p71(tmp_path, "druid", 20, "unrestricted")
    assert result["status"] == "PASS"
    assert result["native_dps"] == 75.0
    assert new_calls == []  # no redundant native stochastic replay

    saved = reference._reference_directory(tmp_path, "druid", 20, "unrestricted")
    manifest = saved / "reference.json"
    document = json.loads(manifest.read_text())
    document["reference_native_sample"]["native_dps"] = 73.5
    manifest.write_text(json.dumps(document))
    assert reference.run_generated_p71(
        tmp_path, "druid", 20, "unrestricted")["reasons"] == [
            "P7_1_GENERATED_REFERENCE_IDENTITY_INVALID"]
    document["reference_native_sample"]["native_dps"] = 75.0
    manifest.write_text(json.dumps(document))
    with (saved / "request.json").open("ab") as stream:
        stream.write(b" ")
    assert reference.run_generated_p71(
        tmp_path, "druid", 20, "unrestricted")["reasons"] == [
            "P7_1_GENERATED_REFERENCE_IDENTITY_INVALID"]


def test_selected_l20_gate_delegates_without_l60_saved_report(monkeypatch, tmp_path):
    calls = []

    def route(root, class_key, level, spec):
        calls.append((class_key, level, spec))
        return {"status": "BLOCKED", "reasons": ["NATIVE_REFERENCE_NOT_YET_PINNED"]}

    monkeypatch.setattr(reference, "run_generated_p71", route)
    actual = p71.run_live(tmp_path, "druid", 20, spec="unrestricted")
    assert actual["status"] == "BLOCKED"
    assert calls == [("druid", 20, "unrestricted")]
    assert p71.run_live(tmp_path, "hunter", 20, spec="unrestricted")["reasons"] == [
        "P7_1_SAVED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT"]


def test_absent_native_reference_is_not_an_automatic_gate_pass(tmp_path):
    report = reference.run_generated_p71(tmp_path, "druid", 20, "unrestricted")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_1_NATIVE_GENERATED_REFERENCE_NOT_PINNED"]
    assert "runtime_proof" not in report


def test_native_prepared_level_is_authority_without_proto_level_hint(
        monkeypatch, tmp_path):
    calls, _ = _native_stubs(monkeypatch)
    source = _request(tmp_path)
    document = json.loads(source.read_text())
    assert "level" not in document["raid"]["parties"][0]["players"][0]
    result = reference.produce_reference(
        tmp_path, "druid", 20, "unrestricted", source)
    assert result["status"] == "REFERENCE_GENERATED"
    assert calls == [1000]

    another = tmp_path / "another"
    another.mkdir()
    other_source = _request(another)
    other_document = json.loads(other_source.read_text())
    assert "level" not in other_document["raid"]["parties"][0]["players"][0]
    _native_stubs(monkeypatch, native_level=60)
    rejected = reference.produce_reference(
        another, "druid", 20, "unrestricted", other_source)
    assert rejected["status"] == "BLOCKED"
    assert rejected["reasons"] == ["P7_1_NATIVE_PREPARED_ACTOR_LEVEL_MISMATCH"]


def test_native_source_control_forwards_actor_level_without_proto_mutation(
        monkeypatch, tmp_path):
    """Forever controls native CLI context; Go request stays schema-faithful."""
    module = reference._native(Path(__file__).resolve().parents[1])
    request = _request(tmp_path)
    original = request.read_bytes()
    commands = []

    def native_run(command, **_kwargs):
        commands.append(command)
        output = Path(command[command.index("--outfile") + 1])
        output.write_text(json.dumps({
            "identity": {"engine": "forever-engine"},
            "result": {"iterationsDone": 2, "raidMetrics": {"dps": {"avg": 17.0}},
                       "firstIterationDuration": 120.0},
        }))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", native_run)
    scored = module.native_source_control(
        Path("/selected/forever-engine"), request, 2,
        rng_mode="stochastic", actor_level=20)
    assert scored["iterations"] == 2
    assert scored["native_dps"] == 17.0
    assert commands[0][-2:] == ["--actor-level", "20"]
    assert "--rng-mode" in commands[0] and "stochastic" in commands[0]
    assert request.read_bytes() == original

    module.native_source_control(Path("/selected/forever-engine"), request, 2,
                                 rng_mode="balanced")
    assert "--actor-level" not in commands[1]
    for invalid in (0, -1, True, "20"):
        try:
            module.native_source_control(Path("/selected/forever-engine"), request, 2,
                                         rng_mode="stochastic", actor_level=invalid)
        except ValueError as exc:
            assert str(exc) == "RUST_NATIVE_CONTROL_ACTOR_LEVEL_INVALID"
        else:
            raise AssertionError("invalid native actor level was forwarded")
    assert len(commands) == 2


def test_default_reference_uses_exact_native_owned_fixture(monkeypatch, tmp_path):
    calls, revision = _native_stubs(monkeypatch)
    source = _request(tmp_path)
    pinned = (tmp_path / "integrations/mythicsim-rust/engine"
              / "fixtures/references/druid-l20-p71.request.json")
    pinned.parent.mkdir(parents=True)
    pinned.write_bytes(source.read_bytes())

    result = reference.produce_reference(tmp_path, "druid", 20, "unrestricted")
    assert result["status"] == "REFERENCE_GENERATED"
    assert result["selected_engine_revision"] == revision
    frozen = reference._reference_directory(tmp_path, "druid", 20, "unrestricted")
    assert (frozen / "request.json").read_bytes() == pinned.read_bytes()
    assert calls == [1000]


def test_absent_native_owned_fixture_fails_closed_before_payment(monkeypatch, tmp_path):
    calls, _ = _native_stubs(monkeypatch)
    result = reference.produce_reference(tmp_path, "druid", 20, "unrestricted")
    assert result == {"status": "BLOCKED",
                      "reasons": ["P7_1_NATIVE_SOURCE_REQUEST_NOT_AVAILABLE"]}
    assert calls == []


def test_selected_submodule_binary_is_default_and_pin_is_enforced(monkeypatch, tmp_path):
    monkeypatch.delenv("FOREVER_MYTHICSIM_RUST_BIN", raising=False)
    engine = tmp_path / "integrations/mythicsim-rust/engine"
    binary = engine / "target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"native-selected-test-executable")
    selected_calls = []

    def selected(root, upstream):
        selected_calls.append((root, upstream))
        return "f" * 40

    monkeypatch.setattr(reference, "_selected_rust_submodule", selected)
    assert reference._binary_and_pin(tmp_path) == (binary.resolve(), "f" * 40)
    assert selected_calls == [(tmp_path, engine.resolve())]

    # Even an explicitly supplied executable cannot bypass the gitlink.
    monkeypatch.setattr(reference, "_selected_rust_submodule",
                        lambda root, upstream: None)
    assert reference._binary_and_pin(tmp_path) is None
