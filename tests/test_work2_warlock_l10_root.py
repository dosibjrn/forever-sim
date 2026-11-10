"""New native L10 root must never inherit an L20 paid predecessor."""
import json
import subprocess
import sys

import pytest
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


@pytest.mark.parametrize("failure,expected_status", [
    ("nonzero", "PAID_RECEIPT_MISSING"),
    ("exception", "PAID_DRIVER_ERROR"),
])
def test_paid_driver_failure_without_receipt_keeps_unmeasured_root_and_resumes(
        tmp_path, monkeypatch, failure, expected_status):
    binary, template = _inputs(tmp_path)

    def propose(**kwargs):
        out = kwargs["out"]
        out.mkdir(parents=True)
        source = out / "source_request.json"
        source.write_text(json.dumps({"native": "prepared L10"}))
        receipt = {
            "status": "NATIVE_PREPARED_NOT_YET_PAID",
            "native_binary_sha256": root.next_level.sha256(binary),
            "original_template_sha256": root.next_level.sha256(template),
            "selected_source_sha256": root.next_level.sha256(source),
        }
        root._write(out / "proposal.json", receipt)
        return receipt

    calls = []

    def paid(args):
        calls.append(args)
        if failure == "exception":
            raise RuntimeError("native transport unexpectedly disconnected")
        return 2  # The native caller failed before it could write route.json.

    monkeypatch.setattr(root, "propose_root", propose)
    monkeypatch.setattr(root.guide, "main", paid)
    monkeypatch.setattr(root.paid_range, "run",
                        lambda **kwargs: (_ for _ in ()).throw(
                            AssertionError("must never advance without paid L10")))
    monkeypatch.setattr(root.next_level, "verified_paid_predecessor",
                        lambda **kwargs: (_ for _ in ()).throw(
                            AssertionError("cannot verify a refused L10")))

    out = tmp_path / "paid"
    args = dict(binary=binary, template=template, out=out)
    first = root.run(**args)
    assert first["stopped"]["status"] == expected_status
    assert first["completed_new_levels"] == []
    assert first["next_level"] == 10
    report = json.loads(Path(first["last_paid_route"]).read_text())
    assert report["measured_levels"] == []
    assert report["native_refusals"][0]["status"] == expected_status
    assert report["native_refusals"][0]["level"] == 10
    assert (out / "GUIDE.md").is_file()
    if failure == "exception":
        assert "native transport unexpectedly disconnected" in (
            out / "L10" / next((out / "L10").iterdir()).name / "paid" /
            "driver_error.json").read_text()
    else:
        assert "exit code 2" in report["native_refusals"][0]["error"]

    second = root.run(**args)
    assert second["stopped"]["status"] == expected_status
    assert second["completed_new_levels"] == []
    assert len(calls) == 1  # Resume never pays an equivalent failed attempt.


def test_workflow_root_cli_imports_without_pythonpath():
    # GitHub Actions invokes this file directly, not `python -m tools...`.
    # -I excludes the ambient cwd/PYTHONPATH so the entrypoint must bootstrap
    # its own imports, rather than depending on a developer's environment.
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-I", str(repo / "tools/wf_warlock_l10_root.py"),
         "--help"], cwd=repo, capture_output=True, text=True, timeout=20,
        check=False)
    assert result.returncode == 0, result.stderr
    assert "--end-level" in result.stdout


def test_native_options_refusal_resumes_after_interrupted_guide_without_requery(
        tmp_path, monkeypatch):
    binary, template = _inputs(tmp_path)
    calls = []

    def refused_options(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 2, stderr="native L10 source refused")

    monkeypatch.setattr(root.subprocess, "run", refused_options)
    write_refusal = root._refusal_report

    def interrupted(*args, **kwargs):
        raise OSError("interrupted between proposal and guide publication")

    monkeypatch.setattr(root, "_refusal_report", interrupted)
    out = tmp_path / "resume"
    with pytest.raises(OSError, match="interrupted"):
        root.run(binary=binary, template=template, out=out)
    assert len(calls) == 1
    assert list(out.glob("L10/*/proposal/proposal.json"))
    monkeypatch.setattr(root, "_refusal_report", write_refusal)
    resumed = root.run(binary=binary, template=template, out=out)
    assert resumed["stopped"]["status"] == "NATIVE_OPTIONS_REFUSED"
    assert resumed["completed_new_levels"] == []
    assert len(calls) == 1  # exact native refusal reused, not retried
    report = json.loads(Path(resumed["last_paid_route"]).read_text())
    assert report["measured_levels"] == []
    assert "native L10 source refused" in report["native_refusals"][0]["error"]


def test_prepared_l10_cache_without_selected_native_source_is_not_repaid(
        tmp_path, monkeypatch):
    binary, template = _inputs(tmp_path)
    out = tmp_path / "orphaned"
    key = root.paid_range._digest({
        "level": 10, "native_binary": root.next_level.sha256(binary),
        "template": root.next_level.sha256(template), "max_proposals": 30,
        "health_threshold": 0.7, "mana_threshold": 0.25,
        "recovery": "decisions", "target_count": 100, "hostile": True,
    })
    receipt = out / "L10" / key / "proposal" / "proposal.json"
    root._write(receipt, {
        "status": "NATIVE_PREPARED_NOT_YET_PAID",
        "native_binary_sha256": root.next_level.sha256(binary),
        "original_template_sha256": root.next_level.sha256(template),
        "selected_source_sha256": "a" * 64,
    })
    monkeypatch.setattr(root, "propose_root",
                        lambda **kwargs: pytest.fail("do not repropose orphaned actor"))
    monkeypatch.setattr(root.guide, "main",
                        lambda args: pytest.fail("do not pay unverified actor"))
    with pytest.raises(ValueError, match="no selected source"):
        root.run(binary=binary, template=template, out=out)


@pytest.mark.parametrize("receipt_text", [
    json.dumps({"class": "warlock", "measured_levels": [10],
                "observations": []}),
    "{incomplete native route",
])
def test_unverified_l10_paid_ack_preserves_original_receipt_and_stops_resume(
        tmp_path, monkeypatch, receipt_text):
    """A zero-exit paid producer is never proof without source-linked 100/100 ACK."""
    binary, template = _inputs(tmp_path)
    paid_calls = []

    def propose(**kwargs):
        p = kwargs["out"]
        p.mkdir(parents=True)
        source = p / "source_request.json"
        source.write_text('{"native":"L10 prepared"}')
        receipt = {
            "status": "NATIVE_PREPARED_NOT_YET_PAID",
            "native_binary_sha256": root.next_level.sha256(binary),
            "original_template_sha256": root.next_level.sha256(template),
            "selected_source_sha256": root.next_level.sha256(source),
        }
        root._write(p / "proposal.json", receipt)
        return receipt

    def paid(args):
        paid_calls.append(args)
        p = Path(args[args.index("--out") + 1])
        p.mkdir(parents=True)
        (p / "route.json").write_text(receipt_text)
        (p / "GUIDE.md").write_text("# Falsely claimed paid L10\n")
        return 0

    monkeypatch.setattr(root, "propose_root", propose)
    monkeypatch.setattr(root.guide, "main", paid)
    monkeypatch.setattr(root.paid_range, "run",
                        lambda **kwargs: pytest.fail("unverified ACK advanced L11"))
    out = tmp_path / "unverified"
    arguments = dict(binary=binary, template=template, out=out,
                     end_level=19, max_new_levels=2)
    first = root.run(**arguments)
    assert first["completed_new_levels"] == []
    assert first["reused_levels"] == []
    assert first["stopped"]["status"] == "PAID_ACK_UNVERIFIED"
    assert first["next_level"] == 10
    assert Path(first["last_paid_route"]).read_text() == receipt_text
    assert "No source-linked native 100/100" in Path(first["latest_guide"]).read_text()
    assert "Falsely claimed" not in Path(first["latest_guide"]).read_text()
    error = next(out.glob("L10/*/paid/ack_verification_error.json"))
    receipt = json.loads(error.read_text())
    assert receipt["status"] == "PAID_ACK_UNVERIFIED"
    assert receipt["selected_source_sha256"] == root.next_level.sha256(
        Path(first["last_paid_source"]))
    assert receipt["native_binary_sha256"] == root.next_level.sha256(binary)
    second = root.run(**arguments)
    assert second["stopped"]["status"] == "PAID_ACK_UNVERIFIED"
    assert second["completed_new_levels"] == second["reused_levels"] == []
    assert len(paid_calls) == 1  # original receipt never silently repaid
    assert Path(second["last_paid_route"]).read_text() == receipt_text

@pytest.mark.parametrize("continuation_has_guide", [True, False])
def test_root_publishes_continuation_refusal_guide_not_stale_paid_l10(
        tmp_path, monkeypatch, continuation_has_guide):
    """A stopped L11+ attempt has its own guide, not the last paid L10 guide."""
    binary, template = _inputs(tmp_path)
    out = tmp_path / "range"
    key = root.paid_range._digest({
        "level": 10, "native_binary": root.next_level.sha256(binary),
        "template": root.next_level.sha256(template), "max_proposals": 30,
        "health_threshold": 0.7, "mana_threshold": 0.25,
        "recovery": "decisions", "target_count": 100, "hostile": True,
    })
    folder = out / "L10" / key
    paid_route = folder / "paid" / "route.json"
    paid_source = folder / "proposal" / "source_request.json"
    root._write(paid_route, {"class": "warlock", "measured_levels": [10]})
    root._write(paid_source, {"native": "prepared L10"})
    (paid_route.parent / "GUIDE.md").write_text("# Last paid L10 guide\\n")
    out.mkdir(parents=True, exist_ok=True)
    (out / "GUIDE.md").write_text("# Stale earlier publication\\n")

    verified = []
    def verify(**kwargs):
        verified.append(kwargs["from_level"])
        assert kwargs["route"] == paid_route
        assert kwargs["source"] == paid_source
        return {"level": 10}

    monkeypatch.setattr(root.next_level, "verified_paid_predecessor", verify)

    def refused_continuation(**kwargs):
        assert kwargs["from_level"] == 10
        assert kwargs["predecessor_route"] == paid_route
        child_dir = kwargs["out"]
        child_dir.mkdir(parents=True, exist_ok=True)
        guide_path = child_dir / "GUIDE.md"
        if continuation_has_guide:
            guide_path.write_text("# Native L11 refused\\n")
        return {
            "completed_new_levels": [],
            "reused_levels": [],
            "stopped": {"level": 11, "status": "NATIVE_PAID_REFUSAL"},
            "next_level": 11,
            "last_paid_route": str(paid_route),
            "last_paid_source": str(paid_source),
            "latest_guide": str(guide_path) if continuation_has_guide else None,
        }

    monkeypatch.setattr(root.paid_range, "run", refused_continuation)
    result = root.run(binary=binary, template=template, out=out,
                      end_level=11, max_new_levels=2)
    assert verified == [10]
    assert result["completed_new_levels"] == []
    assert result["reused_levels"] == [10]
    assert result["stopped"]["status"] == "NATIVE_PAID_REFUSAL"
    assert result["last_paid_route"] == str(paid_route)
    assert result["last_paid_source"] == str(paid_source)
    assert result["next_level"] == 11
    assert (paid_route.parent / "GUIDE.md").read_text() == "# Last paid L10 guide\\n"
    if continuation_has_guide:
        assert Path(result["latest_guide"]).read_text() == "# Native L11 refused\\n"
    else:
        assert result["latest_guide"] is None
        assert not (out / "GUIDE.md").exists()

