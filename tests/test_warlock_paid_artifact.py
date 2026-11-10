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
