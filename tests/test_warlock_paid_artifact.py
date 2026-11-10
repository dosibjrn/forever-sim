"""Artifact input selection for reusable native-paid Warlock range batches."""
import json

import pytest

from tools.wf_warlock_paid_artifact import stage


def _pair(root, level, key="receipt"):
    folder = root / "warlock-paid-range" / f"L{level}" / key
    source = folder / "proposal" / "source_request.json"
    route = folder / "paid" / "route.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    route.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps({"actor_level": level}))
    route.write_text(json.dumps({"class": "warlock", "measured_levels": [level]}))
    return source, route


def test_stages_only_requested_successor_predecessor(tmp_path):
    archive = tmp_path / "unzip"
    _pair(archive, 43)
    source, route = _pair(archive, 44)
    result = stage(archive, 44, tmp_path / "staged")
    assert result["from_level"] == 44
    assert result["source_original"] == str(source)
    assert result["route_original"] == str(route)
    assert (tmp_path / "staged" / "source_request.json").read_bytes() == source.read_bytes()
    assert (tmp_path / "staged" / "route.json").read_bytes() == route.read_bytes()
    assert json.loads((tmp_path / "staged" / "predecessor_manifest.json").read_text())["route_sha256"]


def test_legacy_l42_artifact_is_accepted_without_replaying(tmp_path):
    archive = tmp_path / "unzip" / "predecessor"
    (archive / "warlock-l42-source").mkdir(parents=True)
    (archive / "warlock-l42-native-route").mkdir()
    (archive / "warlock-l42-source" / "source_request.json").write_text("{}")
    (archive / "warlock-l42-native-route" / "route.json").write_text("{}")
    assert stage(tmp_path / "unzip", 42, tmp_path / "staged")["from_level"] == 42


def test_ambiguous_same_level_paid_pairs_are_refused(tmp_path):
    archive = tmp_path / "unzip"
    _pair(archive, 44, "first")
    _pair(archive, 44, "second")
    with pytest.raises(ValueError, match="exactly one"):
        stage(archive, 44, tmp_path / "staged")


def test_no_paid_route_is_not_accepted_as_predecessor(tmp_path):
    archive = tmp_path / "unzip"
    _pair(archive, 44)
    (archive / "warlock-paid-range" / "L44" / "receipt" / "paid" / "route.json").unlink()
    with pytest.raises(ValueError, match="found 0"):
        stage(archive, 44, tmp_path / "staged")


def test_paid_batch_token_can_download_predecessor_artifacts():
    """The authenticated Actions artifact ZIP endpoint requires actions: read.

    A contents-only GITHUB_TOKEN cannot be assumed to download a prior run's
    paid native receipt. Keep this scope when changing the reusable workflow.
    """
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/work2-warlock-l41-l50-native-batch.yml"
    ).read_text()
    assert "/actions/artifacts/$PREDECESSOR_ARTIFACT_ID/zip" in workflow
    permissions = workflow.split("\npermissions:\n", 1)[1].split("\njobs:\n", 1)[0]
    assert "contents: read" in permissions
    assert "actions: read" in permissions


def test_range_workflow_rejects_stale_cached_progress_after_execution_error():
    """Previous Actions artifacts contain progress; they are not this run's ACK."""
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/work2-warlock-l41-l50-native-batch.yml"
    ).read_text()
    assert "RANGE_STEP_OUTCOME: ${{ steps.range.outcome }}" in workflow
    check = workflow.split(
        "      - name: Check actual newly paid/reused levels", 1)[1]
    guard = 'if [ "$RANGE_STEP_OUTCOME" != "success" ]; then'
    assert guard in check
    assert check.index(guard) < check.index(
        "test -s warlock-paid-range/range_progress.json")


def test_same_origin_range_artifact_restores_paid_cache(tmp_path):
    archive = tmp_path / "unzip"
    predecessor = archive / "predecessor-staged"
    predecessor.mkdir(parents=True)
    (predecessor / "source_request.json").write_text('{"actor_level":44}')
    (predecessor / "route.json").write_text('{"class":"warlock"}')
    (predecessor / "predecessor_manifest.json").write_text(
        json.dumps({"from_level": 44}))
    cache = archive / "warlock-paid-range"
    paid = cache / "L45" / "same-source-key" / "paid"
    paid.mkdir(parents=True)
    (paid / "route.json").write_text('{"paid": true}')
    (cache / "range_progress.json").write_text(json.dumps({
        "kind": "warlock_native_paid_range_v1", "from_level": 44,
        "end_level": 46, "completed_new_levels": [45],
    }))
    restored = tmp_path / "resume"
    result = stage(archive, 44, tmp_path / "staged",
                   resume_cache_out=restored)
    assert result["source_original"] == str(predecessor / "source_request.json")
    assert result["resume_cache"]["restored"] is True
    assert (restored / "L45" / "same-source-key" / "paid" / "route.json").read_text() == '{"paid": true}'
    assert (restored / "range_progress.json").is_file()


def test_different_origin_cache_is_not_restored(tmp_path):
    archive = tmp_path / "unzip"
    _pair(archive, 45)
    cache = archive / "warlock-paid-range"
    (cache / "range_progress.json").write_text(json.dumps({
        "kind": "warlock_native_paid_range_v1", "from_level": 44,
        "completed_new_levels": [45],
    }))
    result = stage(archive, 45, tmp_path / "staged",
                   resume_cache_out=tmp_path / "untouched")
    assert result["resume_cache"] == {"restored": False}
    assert not (tmp_path / "untouched").exists()


def test_ambiguous_same_origin_resume_caches_are_refused(tmp_path):
    archive = tmp_path / "unzip"
    _pair(archive, 44)
    for name in ("first", "second"):
        cache = archive / name / "warlock-paid-range"
        cache.mkdir(parents=True)
        (cache / "range_progress.json").write_text(json.dumps({
            "kind": "warlock_native_paid_range_v1", "from_level": 44,
        }))
    with pytest.raises(ValueError, match="ambiguous same-origin"):
        stage(archive, 44, tmp_path / "staged",
              resume_cache_out=tmp_path / "restored")


def test_l10_root_resumes_from_exact_artifact_without_reconstructing_paid_state(tmp_path):
    """An original root artifact can survive a second Actions dispatch intact."""
    from tools.wf_warlock_paid_artifact import restore_l10_root_cache
    import hashlib
    archive = tmp_path / "unzip"
    cache = archive / "warlock-paid-range"
    source = cache / "L10" / "root-key" / "proposal" / "source_request.json"
    route = cache / "L10" / "root-key" / "paid" / "route.json"
    source.parent.mkdir(parents=True)
    route.parent.mkdir(parents=True)
    source.write_bytes(b'{"prepared":"native L10"}')
    route.write_bytes(b'{"class":"warlock","measured_levels":[10]}')
    (cache / "range_progress.json").write_text(json.dumps({
        "kind": "warlock_native_l10_root_range_v1",
        "from_level": 10, "end_level": 10,
        "completed_new_levels": [10], "next_level": 11,
    }))
    restored = tmp_path / "restored"
    receipt = restore_l10_root_cache(archive, restored)
    assert receipt["restored"] is True
    assert (restored / source.relative_to(cache)).read_bytes() == source.read_bytes()
    assert (restored / route.relative_to(cache)).read_bytes() == route.read_bytes()
    assert receipt["l10_route_sha256"] == hashlib.sha256(route.read_bytes()).hexdigest()
    # Native-paid ACK itself is checked by wf_warlock_l10_root.run, not staging.


@pytest.mark.parametrize("kind", [
    "warlock_native_paid_range_v1", "other", None,
])
def test_l10_root_restoration_refuses_wrong_origin(tmp_path, kind):
    from tools.wf_warlock_paid_artifact import restore_l10_root_cache
    cache = tmp_path / "archive" / "warlock-paid-range"
    cache.mkdir(parents=True)
    (cache / "range_progress.json").write_text(json.dumps({
        "kind": kind, "from_level": 10,
    }))
    destination = tmp_path / "resume"
    with pytest.raises(ValueError, match="exactly one L10"):
        restore_l10_root_cache(tmp_path / "archive", destination)
    assert not destination.exists()


@pytest.mark.parametrize("route_count", [0, 2])
def test_l10_root_restoration_never_replays_missing_or_ambiguous_receipt(
        tmp_path, route_count):
    from tools.wf_warlock_paid_artifact import restore_l10_root_cache
    cache = tmp_path / "archive" / "warlock-paid-range"
    cache.mkdir(parents=True)
    (cache / "range_progress.json").write_text(json.dumps({
        "kind": "warlock_native_l10_root_range_v1", "from_level": 10,
    }))
    for i in range(route_count):
        route = cache / "L10" / f"key-{i}" / "paid" / "route.json"
        route.parent.mkdir(parents=True)
        route.write_text("{}")
    with pytest.raises(ValueError, match="one original paid/refusal route"):
        restore_l10_root_cache(tmp_path / "archive", tmp_path / "resume")
    assert not (tmp_path / "resume").exists()


def test_workflow_explicitly_restores_l10_before_paying_world_mobs():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1]
                / ".github/workflows/work2-warlock-l41-l50-native-batch.yml"
                ).read_text()
    assert "resume_root_artifact_id:" in workflow
    assert "inputs.from_level == 10 && inputs.resume_root_artifact_id != ''" in workflow
    assert '[[ "$ROOT_ARTIFACT_ID" =~ ^[0-9]+$ ]]' in workflow
    assert "restore_l10_root_cache(" in workflow
    assert workflow.index("restore_l10_root_cache(") < workflow.index(
        "- name: Bootstrap a genuine L10 Rust actor")


def test_paid_l10_root_artifact_survives_multi_dispatch_continuation():
    """Original L10 ACK/refusal must remain restorable after the next cycles.

    Unlike disposable diagnostics, this archive is the only native provenance
    for L11-L19. A three-day expiry would undermine source-verified resume.
    """
    from pathlib import Path

    workflow = (Path(__file__).resolve().parents[1]
                / ".github/workflows/work2-warlock-l41-l50-native-batch.yml"
                ).read_text()
    upload = workflow.split(
        "      - name: Preserve selected source, native 100-mob receipts, "
        "refusal and route output", 1)[1]
    assert "if: always()" in upload
    assert "warlock-paid-range/" in upload
    assert "          retention-days: 30" in upload
    assert "          retention-days: 3\\n" not in upload
