"""Work2: native-paid range resumption, refusal preservation, and spend budget."""
import json
from pathlib import Path

import pytest

from tools import wf_warlock_paid_range as paid_range


def _inputs(tmp_path):
    binary = tmp_path / "native"
    binary.write_bytes(b"exact native binary")
    source = tmp_path / "source.json"
    source.write_text('{"level":42}')
    route = tmp_path / "route.json"
    route.write_text('{"class":"warlock","observations":[]}')
    return binary, source, route


def _mock_native(monkeypatch):
    calls = {"proposal": [], "paid": [], "verified": []}
    def verify(*, route, source, binary, from_level, predecessor_binary_sha256=None):
        calls["verified"].append(from_level)
        if from_level >= 43:
            assert json.loads(route.read_text())["measured_level"] == from_level
        return {"level": from_level, "observation_id": "paid-" + str(from_level),
                "source_request_sha256": paid_range.next_level.sha256(source),
                "engine_binary_sha256": predecessor_binary_sha256 or paid_range.next_level.sha256(binary),
                "successor_engine_binary_sha256": paid_range.next_level.sha256(binary),
                "cross_engine_source_transition": predecessor_binary_sha256 is not None}
    def propose(**kw):
        calls["proposal"].append(kw["to_level"])
        kw["out"].mkdir(parents=True)
        selected = kw["out"] / "source_request.json"
        selected.write_text(json.dumps({"level": kw["to_level"]}))
        receipt = {
            "status": "NATIVE_PREPARED_NOT_YET_PAID",
            "original_source_sha256": paid_range.next_level.sha256(kw["source"]),
            "native_binary_sha256": paid_range.next_level.sha256(kw["binary"]),
            "selected_source_sha256": paid_range.next_level.sha256(selected),
            "paid_predecessor": verify(route=kw["predecessor_route"],
                    source=kw["source"], binary=kw["binary"],
                    from_level=kw["from_level"],
                    predecessor_binary_sha256=kw["predecessor_binary_sha256"]),
        }
        (kw["out"] / "proposal.json").write_text(json.dumps(receipt))
        return receipt
    def publish(args):
        if "--native-proposal" in args:
            out = Path(args[args.index("--out") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "route.json").write_text('{"native_refusals":["refused"]}')
            (out / "GUIDE.md").write_text("Refused native source\n")
            return 2
        level = int(args[args.index("--actor-level") + 1])
        calls["paid"].append(level)
        out = Path(args[args.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "route.json").write_text(json.dumps({"measured_level": level}))
        (out / "GUIDE.md").write_text(f"Paid native L{level}\n")
        return 0
    monkeypatch.setattr(paid_range.next_level, "verified_paid_predecessor", verify)
    monkeypatch.setattr(paid_range.next_level, "propose", propose)
    monkeypatch.setattr(paid_range.guide, "main", publish)
    return calls


def test_pays_adjacent_levels_once_and_reuses_paid_cache(tmp_path, monkeypatch):
    binary, source, route = _inputs(tmp_path)
    calls = _mock_native(monkeypatch)
    kwargs = dict(binary=binary, source=source, predecessor_route=route,
                  out=tmp_path / "range", from_level=42, end_level=44)
    result = paid_range.run(**kwargs)
    assert result["completed_new_levels"] == [43, 44]
    assert result["reused_levels"] == []
    assert calls["paid"] == [43, 44]
    assert result["full_10_60_native_replay_executed"] is False
    assert Path(result["latest_guide"]).read_text() == "Paid native L44\n"
    again = paid_range.run(**kwargs)
    assert again["completed_new_levels"] == []
    assert again["reused_levels"] == [43, 44]
    assert calls["paid"] == [43, 44]
    assert calls["proposal"] == [43, 44]
    assert Path(again["latest_guide"]).read_text() == "Paid native L44\n"


def test_new_level_budget_preserves_intermediate_paid_checkpoint(tmp_path, monkeypatch):
    binary, source, route = _inputs(tmp_path)
    calls = _mock_native(monkeypatch)
    kwargs = dict(binary=binary, source=source, predecessor_route=route,
                  out=tmp_path / "range", from_level=42, end_level=45)
    first = paid_range.run(**kwargs, max_new_levels=1)
    assert first["completed_new_levels"] == [43]
    assert first["next_level"] == 44
    assert first["stopped"] == {"level": 44, "status": "BOUNDED_NEW_LEVEL_BUDGET"}
    assert Path(first["latest_guide"]).read_text() == "Paid native L43\n"
    second = paid_range.run(**kwargs, max_new_levels=2)
    assert second["reused_levels"] == [43]
    assert second["completed_new_levels"] == [44, 45]
    # The old implementation concatenated completed + reused and reported L44
    # as the next level, even though L45 had just been paid and verified.
    assert second["next_level"] == 46
    assert calls["paid"] == [43, 44, 45]
    third = paid_range.run(**kwargs, max_new_levels=1)
    assert third["completed_new_levels"] == []
    assert third["reused_levels"] == [43, 44, 45]
    assert third["next_level"] == 46
    assert calls["paid"] == [43, 44, 45]  # never repay existing receipts


def test_native_prepare_refusal_is_published_and_stops(tmp_path, monkeypatch):
    binary, source, route = _inputs(tmp_path)
    calls = _mock_native(monkeypatch)
    def native_refuses(**kw):
        kw["out"].mkdir(parents=True)
        receipt = {
            "kind": "adjacent_native_warlock_candidate",
            "status": "NATIVE_ACTOR_LEVEL_UNSUPPORTED",
            "original_source_sha256": paid_range.next_level.sha256(kw["source"]),
            "native_binary_sha256": paid_range.next_level.sha256(kw["binary"]),
            "paid_predecessor": paid_range.next_level.verified_paid_predecessor(
                route=kw["predecessor_route"], source=kw["source"],
                binary=kw["binary"], from_level=kw["from_level"],
                predecessor_binary_sha256=kw["predecessor_binary_sha256"]),
            "native_refusals": [{"reason": "selected native actor source refused"}],
        }
        (kw["out"] / "proposal.json").write_text(json.dumps(receipt))
        return receipt
    monkeypatch.setattr(paid_range.next_level, "propose", native_refuses)
    kwargs = dict(binary=binary, source=source, predecessor_route=route,
                  out=tmp_path / "range", from_level=42, end_level=45)
    result = paid_range.run(**kwargs)
    assert result["completed_new_levels"] == []
    assert result["stopped"]["status"] == "NATIVE_ACTOR_LEVEL_UNSUPPORTED"
    assert calls["paid"] == []
    assert Path(result["stopped"]["route"]).is_file()
    assert Path(result["latest_guide"]).read_text() == "Refused native source\n"
    repeated = paid_range.run(**kwargs)
    assert repeated["stopped"]["status"] == "NATIVE_ACTOR_LEVEL_UNSUPPORTED"
    assert calls["paid"] == []


def test_failed_native_payment_resumes_without_repaying_same_refusal(tmp_path, monkeypatch):
    binary, source, route = _inputs(tmp_path)
    calls = _mock_native(monkeypatch)

    def native_refuses_payment(args):
        level = int(args[args.index("--actor-level") + 1])
        calls["paid"].append(level)
        out = Path(args[args.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        # Real guide publication includes the already measured predecessor
        # but explicitly refuses to score this new-level 100-target attempt.
        (out / "route.json").write_text(json.dumps({
            "class": "warlock", "measured_levels": [42],
            "native_refusals": [{
                "level": level, "variant": "best_apl",
                "status": "NATIVE_EXECUTION_REFUSED",
                "error": "native Rust rejected this hostile candidate",
            }],
        }))
        (out / "GUIDE.md").write_text(f"Refused native L{level}\n")
        return 2

    monkeypatch.setattr(paid_range.guide, "main", native_refuses_payment)
    kwargs = dict(binary=binary, source=source, predecessor_route=route,
                  out=tmp_path / "range", from_level=42, end_level=44)
    first = paid_range.run(**kwargs)
    assert first["stopped"]["status"] == "NATIVE_PAID_REFUSAL"
    assert first["stopped"]["level"] == 43
    assert first["completed_new_levels"] == []
    assert calls["paid"] == [43]

    resumed = paid_range.run(**kwargs)
    assert resumed["stopped"] == first["stopped"]
    assert resumed["completed_new_levels"] == []
    assert resumed["reused_levels"] == []
    assert resumed["last_paid_route"] == str(route)
    assert calls["paid"] == [43]  # no second paid native attempt
    assert calls["proposal"] == [43]  # no duplicate native prepare
    assert Path(resumed["latest_guide"]).read_text() == "Refused native L43\n"



def test_missing_native_guide_never_leaves_an_old_range_guide(tmp_path, monkeypatch):
    binary, source, route = _inputs(tmp_path)
    _mock_native(monkeypatch)
    output = tmp_path / "range"
    output.mkdir()
    (output / "GUIDE.md").write_text("Unrelated previous range guide")

    def refuse_without_guide(args):
        level = int(args[args.index("--actor-level") + 1])
        paid = Path(args[args.index("--out") + 1])
        paid.mkdir(parents=True, exist_ok=True)
        (paid / "route.json").write_text(json.dumps({
            "class": "warlock", "measured_levels": [42],
            "native_refusals": [{"level": level, "status": "NATIVE_EXECUTION_REFUSED"}],
        }))
        return 2

    monkeypatch.setattr(paid_range.guide, "main", refuse_without_guide)
    result = paid_range.run(
        binary=binary, source=source, predecessor_route=route, out=output,
        from_level=42, end_level=43,
    )
    assert result["stopped"]["status"] == "NATIVE_PAID_REFUSAL"
    assert result["latest_guide"] is None
    assert not (output / "GUIDE.md").exists()



def test_cached_refusal_requires_unmeasured_same_level(tmp_path):
    report = tmp_path / "route.json"
    report.write_text(json.dumps({
        "class": "warlock", "measured_levels": [42],
        "native_refusals": [
            {"level": 44, "status": "NATIVE_EXECUTION_REFUSED"},
        ],
    }))
    assert not paid_range._cached_paid_refusal(report, 43)
    assert paid_range._cached_paid_refusal(report, 44)
    # A candidate refusal beside a separate measured candidate cannot mask
    # an invalid or mismatched paid result at the same level.
    report.write_text(json.dumps({
        "class": "warlock", "measured_levels": [43],
        "native_refusals": [
            {"level": 43, "status": "NATIVE_EXECUTION_REFUSED"},
        ],
    }))
    assert not paid_range._cached_paid_refusal(report, 43)
    report.write_text(json.dumps({
        "class": "warlock", "measured_levels": [42],
        "native_refusals": [{"level": 43, "status": None}],
    }))
    assert not paid_range._cached_paid_refusal(report, 43)


def test_newly_paid_level_links_exact_workflow_without_relabeling_cached_receipt(
        tmp_path, monkeypatch):
    binary, source, route = _inputs(tmp_path)
    calls = _mock_native(monkeypatch)
    observed_args = []
    original_publish = paid_range.guide.main

    def record_publish(args):
        observed_args.append(list(args))
        return original_publish(args)

    monkeypatch.setattr(paid_range.guide, "main", record_publish)
    kwargs = dict(binary=binary, source=source, predecessor_route=route,
                  out=tmp_path / "range", from_level=42, end_level=43)
    url = "https://github.com/dosibjrn/forever-sim/actions/runs/42822112684"
    first = paid_range.run(**kwargs, run_url=url)
    assert first["completed_new_levels"] == [43]
    assert calls["paid"] == [43]
    assert len(observed_args) == 1
    assert observed_args[0][observed_args[0].index("--run-url") + 1] == url
    assert paid_range.run(**kwargs, run_url=url)["reused_levels"] == [43]
    assert len(observed_args) == 1  # original paid provenance is immutable

    # Malformed provenance cannot be attached to a native paid receipt.
    import pytest
    with pytest.raises(ValueError, match="actual GitHub Actions run"):
        paid_range.run(**kwargs, run_url="https://example.com/pretend-run")
    assert calls["paid"] == [43]


def test_paid_range_workflow_forwards_its_own_real_actions_run_url():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/work2-warlock-l41-l50-native-batch.yml"
    ).read_text()
    assert ('--run-url "$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/'
            'actions/runs/$GITHUB_RUN_ID"') in workflow


@pytest.mark.parametrize(("failure", "expected_status"), [
    ("exception", "PAID_DRIVER_ERROR"),
    ("missing_failed_receipt", "PAID_RECEIPT_MISSING"),
    ("missing_success_receipt", "PAID_ACK_UNVERIFIED"),
    ("incomplete_success_receipt", "PAID_ACK_UNVERIFIED"),
])
def test_unverified_paid_range_attempt_is_preserved_not_repaid(
        tmp_path, monkeypatch, failure, expected_status):
    binary, source, route = _inputs(tmp_path)
    calls = _mock_native(monkeypatch)

    def unfinished_paid_producer(args):
        level = int(args[args.index("--actor-level") + 1])
        calls["paid"].append(level)
        paid_dir = Path(args[args.index("--out") + 1])
        paid_dir.mkdir(parents=True, exist_ok=True)
        (paid_dir / "GUIDE.md").write_text("Unverified native producer text\n")
        if failure == "exception":
            raise RuntimeError("native transport dropped after attempt")
        if failure == "incomplete_success_receipt":
            (paid_dir / "route.json").write_text(
                '{"class":"warlock","measured_levels":[]}')
        return 2 if failure == "missing_failed_receipt" else 0

    monkeypatch.setattr(paid_range.guide, "main", unfinished_paid_producer)
    kwargs = dict(binary=binary, source=source, predecessor_route=route,
                  out=tmp_path / "range", from_level=42, end_level=44)
    first = paid_range.run(**kwargs)
    assert first["completed_new_levels"] == []
    assert first["reused_levels"] == []
    assert first["next_level"] == 43
    assert first["last_paid_route"] == str(route)
    assert first["stopped"]["level"] == 43
    assert first["stopped"]["status"] == expected_status
    receipt = Path(first["stopped"]["driver_error"])
    report = json.loads(receipt.read_text())
    assert report["status"] == expected_status
    assert report["native_binary_sha256"] == paid_range.next_level.sha256(binary)
    assert len(report["selected_source_sha256"]) == 64
    assert Path(first["latest_guide"]).read_text().startswith(
        f"# Warlock L43: {expected_status}")
    assert (receipt.parent / "GUIDE.md").read_text() == (
        "Unverified native producer text\n")  # original output is immutable

    resumed = paid_range.run(**kwargs)
    assert resumed["stopped"] == first["stopped"]
    assert resumed["completed_new_levels"] == []
    assert resumed["last_paid_route"] == str(route)
    assert calls["paid"] == [43]  # no duplicate native 100-target payment
    assert calls["proposal"] == [43]
    assert Path(resumed["latest_guide"]).read_text() == Path(
        first["latest_guide"]).read_text()


def test_cached_driver_error_rejects_unrelated_selected_source(tmp_path, monkeypatch):
    binary, source, route = _inputs(tmp_path)
    _mock_native(monkeypatch)

    def stopped_paid_producer(args):
        out = Path(args[args.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        return 2

    monkeypatch.setattr(paid_range.guide, "main", stopped_paid_producer)
    kwargs = dict(binary=binary, source=source, predecessor_route=route,
                  out=tmp_path / "range", from_level=42, end_level=43)
    stopped = paid_range.run(**kwargs)["stopped"]
    receipt = Path(stopped["driver_error"])
    report = json.loads(receipt.read_text())
    report["selected_source_sha256"] = "0" * 64
    receipt.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="unverified paid error has mismatched identity"):
        paid_range.run(**kwargs)
