"""New native L10 root must never inherit an L20 paid predecessor."""
import json
import subprocess
from pathlib import Path

from tools import wf_warlock_l10_root as root


def _inputs(tmp_path):
    binary = tmp_path / "native"
    binary.write_bytes(b"selected rust binary")
    template = tmp_path / "l20-template.json"
    template.write_text(json.dumps({
        "raid": {"parties": [{"players": [{
            "class": "ClassWarlock", "race": "RaceTroll",
            # Actual Rust L20 template has no explicit player level.
            "talentsString": "0-0-0550001000000000",
            "equipment": {"items": [{"id": 260212}, {"id": 22968}]},
            "rotation": {"type": "TypeAPL", "priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 1088}}}}
            ]},
        }]}]},
        "encounter": {"duration": 30, "targets": [{"level": 20}]},
    }))
    return binary, template


def test_seed_from_l20_shape_asks_exact_l10_native_options_and_prepare(
        tmp_path, monkeypatch):
    binary, template = _inputs(tmp_path)
    calls = []

    def options(cmd, **kwargs):
        assert cmd[1:] == ["options", "--class", "warlock", "--level", "10"]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({
            "class": "warlock", "level": 10,
            "source_revision": "selected-native-source",
            "spells": [{"name": "Shadow Bolt", "spell_id": 686}],
            "talents": {"points_available": 1, "trees": [
                {"talents": [{"index": 0, "max_rank": 5}]},
                {"talents": []}, {"talents": []}
            ]},
        }))

    def prepare(*, binary, source, out, actor_level):
        candidate = json.loads(source.read_text())
        actor = candidate["raid"]["parties"][0]["players"][0]
        calls.append(candidate)
        assert actor_level == 10
        assert candidate["encounter"]["targets"][0]["level"] == 10
        assert actor["level"] == 10
        assert actor["talentsString"] == "0-0-0"
        assert actor["rotation"]["priorityList"][0]["action"]["castSpell"][
            "spellId"]["spellId"] == 686  # actual Rust offered ID
        assert actor["equipment"]["items"] == [{"id": 260212}, {"id": 22968}]
        out.mkdir(parents=True)
        (out / "source_request.json").write_bytes(source.read_bytes())
        return {"status": "NATIVE_PREPARED_NOT_YET_PAID", "native_refusals": []}

    monkeypatch.setattr(root.subprocess, "run", options)
    monkeypatch.setattr(root.same_level, "select_prepared_source", prepare)
    out = tmp_path / "proposal"
    receipt = root.propose_root(binary=binary, template=template, out=out)
    assert len(calls) == 1
    assert receipt["status"] == "NATIVE_PREPARED_NOT_YET_PAID"
    assert receipt["paid_predecessor"] is None
    assert receipt["native_options_source_revision"] == "selected-native-source"
    assert receipt["selected_source_sha256"] == root.next_level.sha256(
        out / "source_request.json")
    assert json.loads(template.read_text())["encounter"]["targets"][0]["level"] == 20


def test_root_paid_once_then_reused_and_extended_from_actual_l10_ack(
        tmp_path, monkeypatch):
    binary, template = _inputs(tmp_path)
    paid_calls, continuation_calls, verifications, proposals = [], [], [], []

    def propose(**kwargs):
        proposals.append(10)
        p = kwargs["out"]
        p.mkdir(parents=True)
        source = p / "source_request.json"
        source.write_text(json.dumps({"native": "L10 prepared"}))
        receipt = {
            "kind": "warlock_native_l10_root",
            "status": "NATIVE_PREPARED_NOT_YET_PAID",
            "native_binary_sha256": root.next_level.sha256(binary),
            "original_template_sha256": root.next_level.sha256(template),
            "selected_source_sha256": root.next_level.sha256(source),
            "paid_predecessor": None,
        }
        root._write(p / "proposal.json", receipt)
        return receipt

    def guide(args):
        assert "--baseline-observations" not in args
        assert args[args.index("--actor-level") + 1] == "10"
        paid_calls.append(10)
        path = Path(args[args.index("--out") + 1])
        path.mkdir(parents=True)
        (path / "route.json").write_text(json.dumps({
            "class": "warlock", "measured_levels": [10],
            "observations": [{"level": 10, "status": "measured_native_chain"}],
        }))
        (path / "GUIDE.md").write_text("Native paid L10\n")
        return 0

    def verify(**kwargs):
        verifications.append(kwargs["from_level"])
        assert kwargs["from_level"] == 10
        assert kwargs["route"].is_file()
        assert kwargs["source"].is_file()
        return {"level": 10}

    def advance(**kwargs):
        continuation_calls.append(kwargs)
        assert kwargs["from_level"] == 10
        assert kwargs["max_new_levels"] == (1 if len(continuation_calls) == 1 else 2)
        assert kwargs["predecessor_route"].is_file()
        return {
            "completed_new_levels": [11] if len(continuation_calls) == 1 else [],
            "reused_levels": [] if len(continuation_calls) == 1 else [11],
            "stopped": {"level": 12, "status": "BOUNDED_NEW_LEVEL_BUDGET"},
            "next_level": 12, "last_paid_route": str(kwargs["predecessor_route"]),
            "last_paid_source": str(kwargs["source"]),
        }

    monkeypatch.setattr(root, "propose_root", propose)
    monkeypatch.setattr(root.guide, "main", guide)
    monkeypatch.setattr(root.next_level, "verified_paid_predecessor", verify)
    monkeypatch.setattr(root.paid_range, "run", advance)
    kwargs = dict(binary=binary, template=template, out=tmp_path / "paid",
                  end_level=19, max_new_levels=2)
    first = root.run(**kwargs)
    assert first["completed_new_levels"] == [10, 11]
    assert first["next_level"] == 12
    assert paid_calls == [10]
    again = root.run(**kwargs)
    assert again["reused_levels"] == [10, 11]
    assert again["completed_new_levels"] == []
    assert paid_calls == [10]  # no duplicate paid L10
    assert proposals == [10]
    assert len(continuation_calls) == 2
    assert verifications == [10, 10]
    assert first["full_10_60_native_replay_executed"] is False


def test_native_options_refusal_never_pays_or_uses_l20_as_predecessor(
        tmp_path, monkeypatch):
    binary, template = _inputs(tmp_path)

    def options(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stderr="L10 source unsupported")

    monkeypatch.setattr(root.subprocess, "run", options)
    monkeypatch.setattr(root.guide, "main",
                        lambda args: (_ for _ in ()).throw(
                            AssertionError("must not pay refused L10")))
    monkeypatch.setattr(root.paid_range, "run",
                        lambda **kw: (_ for _ in ()).throw(
                            AssertionError("must not advance from refused L10")))
    out = tmp_path / "refused"
    result = root.run(binary=binary, template=template, out=out)
    assert result["stopped"]["status"] == "NATIVE_OPTIONS_REFUSED"
    assert result["completed_new_levels"] == []
    assert result["next_level"] == 10
    route = json.loads(Path(result["last_paid_route"]).read_text())
    assert route["measured_levels"] == []
    assert route["native_refusals"][0]["level"] == 10
    assert "L10 source unsupported" in route["native_refusals"][0]["error"]
    assert "L10" in (out / "GUIDE.md").read_text()
